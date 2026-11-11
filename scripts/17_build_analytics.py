"""Phase 3 Step 5 — build the analytics layer (db/sql/050_analytics_layer.sql) in one transaction."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import psycopg

from db_config import conninfo, safe_description

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "db" / "sql" / "050_analytics_layer.sql"


def main() -> int:
    print("Connecting to", safe_description())
    with psycopg.connect(**conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute("insert into meta.load_run (step, code_fingerprint, parameters) values ('analytics', %s, %s) "
                        "returning load_run_id", (hashlib.sha256(Path(__file__).read_bytes() + SQL.read_bytes()).hexdigest(),
                                                  json.dumps({"materialised": ["analytics.accident_fact"]})))
            run = cur.fetchone()[0]
            cur.execute(SQL.read_text(encoding="utf-8"))
            cur.execute("select count(*) from analytics.accident_fact")
            print(f"load_run_id={run}  analytics.accident_fact rows: {cur.fetchone()[0]:,}")
            cur.execute("update meta.load_run set status='succeeded', finished_at=now() where load_run_id=%s", (run,))
        conn.commit()
    with psycopg.connect(**conninfo(), autocommit=True) as conn:
        conn.execute("analyze analytics.accident_fact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
