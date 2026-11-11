"""Phase 3 Step 2 — independent validation of the BAAC staging import.

Re-reads every raw CSV (independently of the loader) and compares with the database:
  V1 files      : 28 files registered = 7 years x 4 entities; SHA-256 in meta = manifest = file on disk
  V2 rows       : DB rows per file = raw records (csv module) = Phase 1 pandas count (01_file_format.csv)
  V3 numbering  : source_row_number is exactly 1..n per file (no gap, no duplicate)
  V4 fidelity   : MD5 fingerprint of all values in file order, computed in Python and in PostgreSQL, must match
  V5 duplicates : fully identical value rows per file — DB count = raw CSV count (import adds none)
  V6 columns    : meta.source_column raw names = exact file header, in order; annual differences listed
  V7 nulls      : value columns contain no NULL except usagers.id_usager for 2019–2020
  V8 lineage    : every staging row resolves to meta.source_file + meta.load_run
  V9 reconcile  : accidents total vs metropolitan, by department code, from staging values
Results are written to meta.dq_check (new load_run step 'validate_staging') and printed.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from collections import Counter
from pathlib import Path

import psycopg

from db_config import conninfo

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "raw" / "baac" / "_manifest.csv"
PHASE1 = ROOT / "reports" / "phase1" / "tables" / "01_file_format.csv"
COLS = {
    "caracteristiques": ["num_acc", "jour", "mois", "an", "hrmn", "lum", "dep", "com", "agg", "int", "atm", "col", "adr", "lat", "long"],
    "lieux": ["num_acc", "catr", "voie", "v1", "v2", "circ", "nbv", "vosp", "prof", "pr", "pr1", "plan", "lartpc", "larrout", "surf", "infra", "situ", "vma"],
    "vehicules": ["num_acc", "id_vehicule", "num_veh", "senc", "catv", "obs", "obsm", "choc", "manv", "motor", "occutc"],
    "usagers": ["num_acc", "id_usager", "id_vehicule", "num_veh", "place", "catu", "grav", "sexe", "an_nais", "trajet", "secu1", "secu2", "secu3", "locp", "actp", "etatp"],
}
ABSENT = "<ABSENT>"          # marker for a column missing from a file (NULL in staging)
US, RS = "\x1f", "\x1e"      # unit / record separators for fingerprints
results = []


def check(code, entity, year, expected, observed, ok, details=None):
    results.append((code, entity, year, str(expected), str(observed), "pass" if ok else "fail", details))


def raw_records(path: Path):
    text = path.read_bytes().decode("utf-8")
    recs = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    return recs[0], [r for r in recs[1:] if r != []]


def main() -> int:
    manifest = [r for r in csv.DictReader(MANIFEST.open(encoding="utf-8")) if r["kind"] == "data"]
    phase1 = {(int(r["year"]), r["table"]): int(r["pandas_rows"]) for r in csv.DictReader(PHASE1.open(encoding="utf-8"))}
    with psycopg.connect(**conninfo()) as conn, conn.cursor() as cur:
        cur.execute("select source_file_id, entity, reference_year, file_path, sha256, raw_header "
                    "from meta.source_file where source_system = 'BAAC'")
        files = {r[3]: r for r in cur.fetchall()}

        # V1 ---------------------------------------------------------------
        combos = {(r[1], r[2]) for r in files.values()}
        check("V1_FILES_REGISTERED", None, None, 28, len(files), len(files) == 28 and len(combos) == 28)
        for m in manifest:
            disk = hashlib.sha256((ROOT / m["file"]).read_bytes()).hexdigest()
            db = files.get(m["file"], (None,) * 6)[4]
            check("V1_SHA256", m["table"], int(m["year"]), m["sha256"][:12], f"db={str(db)[:12]} disk={disk[:12]}",
                  db == m["sha256"] == disk)

        null_exceptions = []
        for m in sorted(manifest, key=lambda x: (x["table"], int(x["year"]))):
            entity, year = m["table"], int(m["year"])
            fid = files[m["file"]][0]
            header, recs = raw_records(ROOT / m["file"])
            canon = ["num_acc" if h.strip().lower() == "accident_id" else "".join(h.split()).lower() for h in header]
            table = f"staging.stg_baac_{entity}"
            cols = COLS[entity]

            # V2 rows
            cur.execute(f"select count(*), min(source_row_number), max(source_row_number), "
                        f"count(distinct source_row_number) from {table} where source_file_id = %s", (fid,))
            n, mn, mx, nd = cur.fetchone()
            check("V2_ROWCOUNT", entity, year, f"raw={len(recs)} phase1={phase1[(year, entity)]}", n,
                  n == len(recs) == phase1[(year, entity)])
            # V3 numbering
            check("V3_ROW_NUMBERING", entity, year, f"1..{len(recs)}", f"{mn}..{mx} distinct={nd}",
                  mn == 1 and mx == n and nd == n)

            # V4 fidelity fingerprint
            idx = {c: canon.index(c) for c in cols if c in canon}
            py = hashlib.md5()
            rows_as_tuples = []
            for i, rec in enumerate(recs):
                vals = [rec[idx[c]] if c in idx else ABSENT for c in cols]
                rows_as_tuples.append(tuple(vals))
                py.update(((RS if i else "") + US.join(vals)).encode("utf-8"))
            expr = ", ".join(f"coalesce({chr(34)}{c}{chr(34)}, '{ABSENT}')" for c in cols)
            cur.execute(f"select md5(string_agg(concat_ws(E'\\x1f', {expr}), E'\\x1e' order by source_row_number)) "
                        f"from {table} where source_file_id = %s", (fid,))
            dbmd5 = cur.fetchone()[0]
            check("V4_VALUE_FINGERPRINT", entity, year, py.hexdigest(), dbmd5, py.hexdigest() == dbmd5)

            # V5 duplicates (identical value rows)
            raw_dups = sum(c - 1 for c in Counter(rows_as_tuples).values() if c > 1)
            cur.execute(f"select coalesce(sum(c - 1), 0) from (select count(*) c from {table} where source_file_id = %s "
                        f"group by {', '.join(chr(34) + c + chr(34) for c in cols)} having count(*) > 1) t", (fid,))
            db_dups = int(cur.fetchone()[0])
            check("V5_DUPLICATE_VALUE_ROWS", entity, year, raw_dups, db_dups, raw_dups == db_dups)

            # V6 columns
            cur.execute("select raw_name, staging_column from meta.source_column where source_file_id = %s "
                        "order by ordinal_position", (fid,))
            sc = cur.fetchall()
            check("V6_SOURCE_COLUMNS", entity, year, "|".join(header).replace("\n", "\\n"),
                  "|".join(r[0] for r in sc).replace("\n", "\\n"),
                  [r[0] for r in sc] == header and [r[1] for r in sc] == canon)

            # V7 NULLs in value columns
            cur.execute(f"select {', '.join(f'count(*) filter (where {chr(34)}{c}{chr(34)} is null)' for c in cols)} "
                        f"from {table} where source_file_id = %s", (fid,))
            nulls = dict(zip(cols, cur.fetchone()))
            allowed = {c: n for c in cols if c not in canon}           # absent column -> all NULL
            bad = {c: v for c, v in nulls.items() if v and allowed.get(c) != v}
            if allowed:
                null_exceptions.append(f"{entity} {year}: {list(allowed)} absent -> NULL")
            check("V7_NULLS_ONLY_FOR_ABSENT_COLUMNS", entity, year, allowed or "none", {c: v for c, v in nulls.items() if v} or "none",
                  not bad)

        # V8 lineage --------------------------------------------------------
        for e in COLS:
            cur.execute(f"""select count(*), count(sf.source_file_id), count(lr.load_run_id), count(sf.file_name),
                            count(lr.started_at)
                            from staging.stg_baac_{e} s
                            left join meta.source_file sf using (source_file_id)
                            left join meta.load_run lr using (load_run_id)""")
            n, a, b, c, d = cur.fetchone()
            check("V8_LINEAGE", e, None, n, f"file={a} run={b} filename={c} ingested_at={d}", n == a == b == c == d)

        # V9 reconciliation (staging values; dep normalised in-query only for the comparison)
        cur.execute("""
            with a as (
              select source_year, dep,
                     case when dep ~ '^[0-9]$' then '0' || dep else dep end as dep_n
              from staging.stg_baac_caracteristiques)
            select source_year,
                   count(*) total,
                   count(*) filter (where dep_n ~ '^(0[1-9]|[1-8][0-9]|9[0-5])$' or dep_n in ('2A','2B')) metro,
                   count(*) filter (where dep ~ '^[0-9]$') metro_single_digit_raw,
                   count(*) filter (where dep_n in ('971','972','973','974','976')) drom,
                   count(*) filter (where dep_n in ('975','977','978','986','987','988')) com_overseas,
                   count(*) filter (where not (dep_n ~ '^(0[1-9]|[1-8][0-9]|9[0-5])$' or dep_n in ('2A','2B')
                                    or dep_n in ('971','972','973','974','976') or dep_n in ('975','977','978','986','987','988'))) other
            from a group by source_year order by source_year""")
        recon = cur.fetchall()
        cur.execute("""select dep, count(*) from staging.stg_baac_caracteristiques
                       where dep ~ '^9[7-8][0-9]$' group by dep order by dep""")
        by_dep = cur.fetchall()
        tot = sum(r[1] for r in recon); met = sum(r[2] for r in recon)
        check("V9_ACCIDENTS_TOTAL", "caracteristiques", None, 382721, tot, tot == 382721)
        check("V9_ACCIDENTS_METRO", "caracteristiques", None, 361593, met, met == 361593)
        check("V9_RECONCILES", "caracteristiques", None, "total = metro + overseas + other(0)",
              f"{tot} = {met} + {sum(r[4] + r[5] for r in recon)} + {sum(r[6] for r in recon)}",
              tot == met + sum(r[4] + r[5] + r[6] for r in recon) and sum(r[6] for r in recon) == 0)

        # persist
        cur.execute("insert into meta.load_run (step, code_fingerprint, parameters) values ('validate_staging', %s, %s) "
                    "returning load_run_id", (hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                              json.dumps({"checks": len(results)})))
        vid = cur.fetchone()[0]
        cur.executemany("insert into meta.dq_check (load_run_id, layer, check_code, entity, reference_year, expected, "
                        "observed, status, details) values (%s, 'staging', %s, %s, %s, %s, %s, %s, %s)",
                        [(vid, c, e, y, ex, ob, st, json.dumps(d) if d else None) for c, e, y, ex, ob, st, d in results])
        failed = [r for r in results if r[5] == "fail"]
        cur.execute("update meta.load_run set status = %s, finished_at = now() where load_run_id = %s",
                    ("failed" if failed else "succeeded", vid))
        conn.commit()

    summary = Counter((r[0], r[5]) for r in results)
    print(f"validation load_run_id={vid}")
    for code in dict.fromkeys(r[0] for r in results):
        print(f"  {code:<34} pass={summary[(code, 'pass')]:>3} fail={summary[(code, 'fail')]}")
    for r in failed:
        print("  FAIL:", r)
    print("\nReconciliation by year (total, metro, raw single-digit dep, DROM 971-976, COM 975/977/978/986-988, other):")
    for r in recon:
        print("  ", r)
    print("Overseas accidents by department code:", by_dep)
    print("Duplicate value rows (raw = db):", [(r[1], r[2], r[4]) for r in results if r[0] == "V5_DUPLICATE_VALUE_ROWS" and r[4] != "0"])
    print("Absent columns:", null_exceptions)
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
