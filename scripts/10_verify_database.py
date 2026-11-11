"""Phase 3 Step 1 — verify the PostgreSQL/PostGIS environment (read-only checks).

Checks: connection, server version, PostGIS extension + version, required schemas,
SRIDs 2154 and 4326 present, a WGS84 -> Lambert-93 transformation, GiST support.
Exit code 1 if any check fails.
"""
from __future__ import annotations

import sys

import psycopg

from db_config import conninfo, safe_description

REQUIRED_SCHEMAS = {"meta", "staging", "ref", "clean", "analytics"}


def main() -> int:
    results = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))

    print("Connecting to", safe_description())
    with psycopg.connect(**conninfo(), connect_timeout=10) as conn, conn.cursor() as cur:
        cur.execute("select current_database(), current_user, inet_server_port()")
        db, user, port = cur.fetchone()
        check("connection", True, f"db={db} user={user} container_port={port}")

        cur.execute("show server_version")
        ver = cur.fetchone()[0]
        check("server_version", ver.startswith("18"), ver)

        cur.execute("select extversion from pg_extension where extname = 'postgis'")
        row = cur.fetchone()
        check("postgis_extension", row is not None, f"extension version {row[0] if row else 'MISSING'}")
        if row:
            cur.execute("select postgis_full_version()")
            full = cur.fetchone()[0]
            check("postgis_full_version", "PROJ" in full and "GEOS" in full, full[:160] + "...")

        cur.execute("select schema_name from information_schema.schemata")
        present = {r[0] for r in cur.fetchall()}
        missing = REQUIRED_SCHEMAS - present
        check("schemas", not missing, f"present={sorted(REQUIRED_SCHEMAS & present)} missing={sorted(missing)}")

        cur.execute("select srid, auth_name, auth_srid from spatial_ref_sys where srid in (2154, 4326) order by srid")
        srids = cur.fetchall()
        check("srid_2154_4326", len(srids) == 2, str(srids))

        # Paris Notre-Dame (WGS84) -> Lambert-93; expected approx. X=652 470, Y=6 861 990 (metres)
        cur.execute("""select round(st_x(g)::numeric, 0), round(st_y(g)::numeric, 0)
                       from (select st_transform(st_setsrid(st_makepoint(2.3499, 48.8530), 4326), 2154) g) t""")
        x, y = cur.fetchone()
        check("transform_4326_to_2154", 650_000 < x < 655_000 and 6_859_000 < y < 6_865_000, f"X={x} Y={y}")

        cur.execute("select count(*) from pg_am where amname = 'gist'")
        check("gist_access_method", cur.fetchone()[0] == 1, "GiST available")

        cur.execute("""select count(*) from information_schema.tables
                       where table_schema in ('meta','staging','ref','clean','analytics')""")
        check("user_tables_in_layers", True, f"{cur.fetchone()[0]} tables (expected 0 at Step 1)")

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
