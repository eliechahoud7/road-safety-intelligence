"""Phase 3 Step 2 — load BAAC 2019–2025 into the staging layer (values untouched).

Flow (single transaction — all or nothing):
  E0  verify every manifest file (bytes + SHA-256) before loading; abort on mismatch
  DDL apply db/sql/010_meta.sql and db/sql/020_staging_baac.sql (idempotent)
  E1  register load run, source files (meta.source_file) and exact source columns (meta.source_column)
  E2  for each file: parse with the csv module (UTF-8 strict, ';'), canonicalise header names only,
      delete previous rows of that file, COPY untouched values + lineage into staging.stg_baac_<entity>

Parsing rules (evidence: reports/phase1/tables/01_file_format.csv, 09_row_count_reconciliation.csv)
  * quoting is CSV syntax and is removed by the parser; field contents are never changed
  * completely empty records (trailing blank line present in 25 of 28 files) are skipped and counted
  * any other record whose field count differs from the header aborts the load
Header canonicalisation (the only transformation): remove whitespace/newlines, lower-case,
  'accident_id' -> 'num_acc'. Exact names are stored in meta.source_column.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path

import psycopg

from db_config import conninfo, safe_description

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "raw" / "baac" / "_manifest.csv"
SQL_FILES = [ROOT / "db" / "sql" / "010_meta.sql", ROOT / "db" / "sql" / "020_staging_baac.sql"]
COLUMNS = {
    "caracteristiques": ["num_acc", "jour", "mois", "an", "hrmn", "lum", "dep", "com", "agg", "int",
                         "atm", "col", "adr", "lat", "long"],
    "lieux": ["num_acc", "catr", "voie", "v1", "v2", "circ", "nbv", "vosp", "prof", "pr", "pr1", "plan",
              "lartpc", "larrout", "surf", "infra", "situ", "vma"],
    "vehicules": ["num_acc", "id_vehicule", "num_veh", "senc", "catv", "obs", "obsm", "choc", "manv",
                  "motor", "occutc"],
    "usagers": ["num_acc", "id_usager", "id_vehicule", "num_veh", "place", "catu", "grav", "sexe", "an_nais",
                "trajet", "secu1", "secu2", "secu3", "locp", "actp", "etatp"],
}
OPTIONAL = {"usagers": {"id_usager"}}          # absent from 2019–2020 files
ALIASES = {"accident_id": "num_acc"}           # 2022 Caractéristiques


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(name: str) -> str:
    c = re.sub(r"\s+", "", name).lower()
    return ALIASES.get(c, c)


def parse(path: Path):
    text = path.read_bytes().decode("utf-8")                     # strict: raises on invalid UTF-8
    records = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    header, body = records[0], records[1:]
    data, blank = [], 0
    for i, rec in enumerate(body, start=1):
        if rec == [] or rec == [""] * len(rec) and len(rec) <= 1:
            blank += 1
            continue
        if len(rec) != len(header):
            raise ValueError(f"{path.name}: record {i} has {len(rec)} fields, header has {len(header)}")
        data.append(rec)
    return header, data, blank


def main() -> int:
    manifest = [r for r in csv.DictReader(MANIFEST.open(encoding="utf-8")) if r["kind"] == "data"]
    if len(manifest) != 28:
        sys.exit(f"ABORT: manifest lists {len(manifest)} data files, expected 28")

    # ---- E0: raw integrity gate
    for r in manifest:
        p = ROOT / r["file"]
        if p.stat().st_size != int(r["bytes"]) or sha256(p) != r["sha256"]:
            sys.exit(f"ABORT E0: {r['file']} does not match its manifest (size/SHA-256)")
    print("E0 raw integrity: 28/28 files match manifest SHA-256")

    fingerprint = hashlib.sha256(b"".join(f.read_bytes() for f in [Path(__file__), *SQL_FILES])).hexdigest()
    print("Connecting to", safe_description())
    with psycopg.connect(**conninfo()) as conn:          # one transaction; commit only at the end
        with conn.cursor() as cur:
            for f in SQL_FILES:
                cur.execute(f.read_text(encoding="utf-8"))
            cur.execute("insert into meta.load_run (step, code_fingerprint, parameters) values (%s, %s, %s) "
                        "returning load_run_id, started_at",
                        ("staging_baac", fingerprint, json.dumps({"years": "2019-2025", "files": 28})))
            run_id, started = cur.fetchone()
            print(f"load_run_id={run_id} started_at={started}")

            total = 0
            for r in sorted(manifest, key=lambda x: (x["table"], int(x["year"]))):
                entity, year, rel = r["table"], int(r["year"]), r["file"]
                path = ROOT / rel
                header, rows, blank = parse(path)
                canon = [canonical(h) for h in header]
                expected = COLUMNS[entity]
                unknown = [c for c in canon if c not in expected]
                missing = [c for c in expected if c not in canon and c not in OPTIONAL.get(entity, set())]
                if unknown or missing or len(set(canon)) != len(canon):
                    raise RuntimeError(f"{rel}: header not recognised unknown={unknown} missing={missing}")

                cur.execute("""
                    insert into meta.source_file (source_system, entity, reference_year, file_path, file_name,
                        source_url, bytes, sha256, licence, producer, published_or_edition_date, retrieved_at, raw_header)
                    values ('BAAC', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz::date, %s, %s)
                    on conflict (file_path) do update set
                        source_url = excluded.source_url, bytes = excluded.bytes, sha256 = excluded.sha256,
                        licence = excluded.licence, producer = excluded.producer,
                        published_or_edition_date = excluded.published_or_edition_date,
                        retrieved_at = excluded.retrieved_at, raw_header = excluded.raw_header,
                        registered_at = now()
                    returning source_file_id""",
                    (entity, year, rel, path.name, r["url"], int(r["bytes"]), r["sha256"],
                     f"{r['dataset_licence']} (Licence Ouverte)", r["producer"], r["last_modified"],
                     r["retrieved_at"], ";".join(h.replace("\n", "\\n") for h in header)))
                fid = cur.fetchone()[0]
                cur.execute("delete from meta.source_column where source_file_id = %s", (fid,))
                cur.executemany("insert into meta.source_column values (%s, %s, %s, %s)",
                                [(fid, i + 1, h, c) for i, (h, c) in enumerate(zip(header, canon))])

                table = f"staging.stg_baac_{entity}"
                cur.execute(f"delete from {table} where source_file_id = %s", (fid,))
                cols = ["source_file_id", "source_year", "source_row_number", "load_run_id", *canon]
                with cur.copy(f"copy {table} ({', '.join(chr(34) + c + chr(34) for c in cols)}) from stdin") as cp:
                    for n, rec in enumerate(rows, start=1):
                        cp.write_row((fid, year, n, run_id, *rec))
                cur.execute(f"select count(*) from {table} where source_file_id = %s", (fid,))
                loaded = cur.fetchone()[0]
                if loaded != len(rows):
                    raise RuntimeError(f"{rel}: parsed {len(rows)} records but {loaded} rows in {table}")
                total += loaded
                print(f"  {entity:<17} {year}  {loaded:>7,} rows  (blank records skipped: {blank})  file_id={fid}")

            cur.execute("update meta.load_run set status = 'succeeded', finished_at = now() where load_run_id = %s",
                        (run_id,))
        conn.commit()
    print(f"E2 staging load committed: {total:,} rows from 28 files (load_run_id={run_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
