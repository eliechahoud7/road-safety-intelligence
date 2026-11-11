"""Staging fingerprint — proves that the BAAC staging tables are unchanged between pipeline steps.

The fingerprint hashes every staging row's source values, year and row number, EXCLUDING run-specific ids
(load_run_id, source_file_id), so it is identical on any machine that loads the same raw files.

Baseline file: reports/phase3/staging_fingerprint.txt  (lines "name|row_count|md5")
  * created by:  python scripts/staging_fingerprint.py --write   (run after 12_validate_staging.py)
  * used by:     14_validate_reference_data.py (R8) and 16_validate_clean.py (C11)
If the baseline is missing, the validation scripts create it from the current staging tables and report
a warning (first run) instead of failing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "reports" / "phase3" / "staging_fingerprint.txt"
TABLES = (("caract", "caracteristiques"), ("lieux", "lieux"), ("vehicules", "vehicules"), ("usagers", "usagers"))


def compute(cur) -> dict[str, list[str]]:
    """Current fingerprint of each staging table: [row_count, md5]."""
    out = {}
    for name, t in TABLES:
        cur.execute(f"""select count(*), md5(string_agg(md5((to_jsonb(s) - 'load_run_id' - 'source_file_id')::text), ''
                                                     order by s.source_year, s.source_row_number))
                        from staging.stg_baac_{t} s""")
        out[name] = [str(x) for x in cur.fetchone()]
    return out


def write(fp: dict[str, list[str]], path: Path = BASELINE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}|{'|'.join(v)}\n" for k, v in fp.items()), encoding="utf-8")


def read(path: Path = BASELINE) -> dict[str, list[str]]:
    return {l.split("|")[0]: l.strip().split("|")[1:] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def baseline(cur, path: Path | None = None) -> tuple[dict[str, list[str]], bool]:
    """Return (baseline, created). Creates the baseline from the current tables if the file does not exist."""
    path = Path(path) if path else BASELINE
    if path.exists():
        return read(path), False
    fp = compute(cur)
    write(fp, path)
    return fp, True


if __name__ == "__main__":
    import psycopg

    from db_config import conninfo

    with psycopg.connect(**conninfo(), options="-c default_transaction_read_only=on") as conn, conn.cursor() as cur:
        fp = compute(cur)
    for k, v in fp.items():
        print(f"{k:<10} rows={v[0]:>8}  md5={v[1]}")
    if "--write" in sys.argv:
        write(fp)
        print(f"baseline written: {BASELINE.relative_to(ROOT)}")
