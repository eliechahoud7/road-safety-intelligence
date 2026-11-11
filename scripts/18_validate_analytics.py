"""Phase 3 Step 5 — essential validation of the analytics layer (results -> meta.dq_check, layer 'analytics').

A1 accident_fact = 361 593 metropolitan accidents          A5 location summaries do not inflate accident counts
A2 exactly one row per accident                            A6 department / commune aggregates reconcile with accident_fact
A3 casualty totals = clean.road_user                       A7 no unintended NULL / duplicate identifiers
A4 vehicle totals = clean.vehicle                          A8 all seven years represented
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import psycopg

from db_config import conninfo

results = []


def check(code, entity, expected, observed, ok):
    results.append((code, entity, str(expected), str(observed), "pass" if ok else "fail"))


def one(cur, sql):
    cur.execute(sql)
    return cur.fetchone()


def main() -> int:
    with psycopg.connect(**conninfo()) as conn, conn.cursor() as cur:
        # A1 / A2
        n, nd, metro = one(cur, """select count(*), count(distinct num_acc),
                                   (select count(*) from clean.accident where is_metro) from analytics.accident_fact""")
        check("A1_METRO_ACCIDENTS", "accident_fact", 361593, n, n == 361593 == metro)
        check("A2_ONE_ROW_PER_ACCIDENT", "accident_fact", n, nd, n == nd)
        for v in ("accident_casualty_summary", "accident_vehicle_summary", "accident_location_summary"):
            r, d = one(cur, f"select count(*), count(distinct num_acc) from analytics.{v}")
            check("A2_SUMMARY_ONE_ROW_PER_ACCIDENT", v, "382721 = distinct", (r, d), r == d == 382721)

        # A3 casualties (metro accidents)
        f = one(cur, "select sum(n_users), sum(n_killed), sum(n_hospitalised), sum(n_light), sum(n_unhurt), sum(n_grav_unknown), "
                     "sum(n_fugitive_like) from analytics.accident_fact")
        c = one(cur, """select count(*), count(*) filter (where grav=2), count(*) filter (where grav=3), count(*) filter (where grav=4),
                        count(*) filter (where grav=1), count(*) filter (where grav is null), count(*) filter (where is_fugitive_like)
                        from clean.road_user u join clean.accident a using (num_acc) where a.is_metro""")
        check("A3_CASUALTY_TOTALS_EQ_CLEAN", "accident_fact", c, f, tuple(map(int, f)) == tuple(c))
        (ruf,) = one(cur, "select count(*) from analytics.road_user_fact")
        check("A3_ROAD_USER_FACT_EQ_CLEAN_METRO", "road_user_fact", c[0], ruf, ruf == c[0])
        all_users = one(cur, "select (select sum(n_users) from analytics.accident_casualty_summary), (select count(*) from clean.road_user)")
        check("A3_SUMMARY_ALL_USERS", "accident_casualty_summary", all_users[1], all_users[0], int(all_users[0]) == all_users[1] == 871534)

        # A4 vehicles
        fv, cv = one(cur, """select (select sum(n_vehicles) from analytics.accident_fact),
                             (select count(*) from clean.vehicle v join clean.accident a using (num_acc) where a.is_metro)""")
        check("A4_VEHICLE_TOTALS_EQ_CLEAN", "accident_fact", cv, fv, int(fv) == cv)
        (vf,) = one(cur, "select count(*) from analytics.vehicle_fact")
        check("A4_VEHICLE_FACT_EQ_CLEAN_METRO", "vehicle_fact", cv, vf, vf == cv)
        av = one(cur, "select (select sum(n_vehicles) from analytics.accident_vehicle_summary), (select count(*) from clean.vehicle)")
        check("A4_SUMMARY_ALL_VEHICLES", "accident_vehicle_summary", av[1], av[0], int(av[0]) == av[1] == 653712)

        # A5 locations
        seg, cl = one(cur, """select (select sum(n_segments) from analytics.accident_fact),
                              (select count(*) from clean.accident_location l join clean.accident a using (num_acc) where a.is_metro)""")
        check("A5_SEGMENTS_AGGREGATED_NOT_JOINED", "accident_fact", f"{cl} segments over 361593 accidents", f"sum(n_segments)={seg}, rows={n}",
              int(seg) == cl and n == 361593)
        conf = one(cur, """select count(*) filter (where n_segments > 1), count(*) filter (where catr_conflict),
                           count(*) filter (where vma_conflict), count(*) filter (where surf_conflict),
                           count(*) filter (where n_segments = 1 and (catr_conflict or vma_conflict or surf_conflict or circ_conflict))
                           from analytics.accident_fact""")
        check("A5_CONFLICTS_ONLY_IN_MULTI_SEGMENT", "accident_fact",
              "no conflict flag on single-segment accidents", f"multi={conf[0]} catr_conf={conf[1]} vma_conf={conf[2]} surf_conf={conf[3]}",
              conf[4] == 0)

        # A6 aggregates
        dep = one(cur, "select sum(n_accidents), sum(n_killed), sum(n_vehicles), sum(n_users) from analytics.agg_year_department")
        fac = one(cur, "select count(*), sum(n_killed), sum(n_vehicles), sum(n_users) from analytics.accident_fact")
        check("A6_DEPARTMENT_AGG_RECONCILES", "agg_year_department", fac, dep, tuple(map(int, dep)) == tuple(map(int, fac)))
        com = one(cur, "select sum(n_accidents), sum(n_killed), sum(n_vehicles), sum(n_users) from analytics.agg_year_commune")
        check("A6_COMMUNE_AGG_RECONCILES", "agg_year_commune", fac, com, tuple(map(int, com)) == tuple(map(int, fac)))
        nd_dep, n_dup = one(cur, """select (select count(distinct dep_code) from analytics.agg_year_department),
                                   (select count(*) from (select year, dep_code from analytics.agg_year_department group by 1, 2 having count(*) > 1) t)""")
        check("A6_96_DEPARTMENTS", "agg_year_department", 96, nd_dep, nd_dep == 96 and n_dup == 0)

        # A7 identifiers
        nulls = one(cur, """select count(*) filter (where num_acc is null), count(*) filter (where year is null),
                            count(*) filter (where dep_code is null), count(*) filter (where com_cog_2026 is null),
                            count(*) filter (where geom is null), count(*) filter (where spatial_eligibility is null),
                            count(*) filter (where accident_severity is null) from analytics.accident_fact""")
        check("A7_NULL_IDENTIFIERS", "accident_fact", "0,0,0, com_cog_2026=1 (N/C), 0,0,0", nulls, nulls == (0, 0, 0, 1, 0, 0, 0))
        dup_u, dup_v = one(cur, """select (select count(*) - count(distinct road_user_id) from analytics.road_user_fact),
                                  (select count(*) - count(distinct id_vehicule) from analytics.vehicle_fact)""")
        check("A7_NO_DUPLICATE_IDS_IN_FACT_VIEWS", "road_user_fact/vehicle_fact", (0, 0), (dup_u, dup_v), (dup_u, dup_v) == (0, 0))

        # A8 years
        cur.execute("select year, count(*) from analytics.accident_fact group by 1 order by 1")
        years = dict(cur.fetchall())
        exp = {2019: 56016, 2020: 45121, 2021: 53540, 2022: 52380, 2023: 51641, 2024: 51058, 2025: 51837}
        check("A8_ALL_YEARS", "accident_fact", exp, years, years == exp)

        # informative (not pass/fail): eligibility and severity distributions for the report
        cur.execute("select spatial_eligibility, count(*) from analytics.accident_fact group by 1 order by 2 desc")
        elig = cur.fetchall()
        cur.execute("select accident_severity, count(*) from analytics.accident_fact group by 1 order by 2 desc")
        sev = cur.fetchall()
        cur.execute("select count(*) from analytics.hotspot_point")
        hp = cur.fetchone()[0]

        cur.execute("insert into meta.load_run (step, code_fingerprint, parameters) values ('validate_analytics', %s, %s) returning load_run_id",
                    (hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), json.dumps({"checks": len(results)})))
        vid = cur.fetchone()[0]
        cur.executemany("insert into meta.dq_check (load_run_id, layer, check_code, entity, expected, observed, status) "
                        "values (%s, 'analytics', %s, %s, %s, %s, %s)", [(vid, *r) for r in results])
        failed = [r for r in results if r[4] == "fail"]
        cur.execute("update meta.load_run set status=%s, finished_at=now() where load_run_id=%s", ("failed" if failed else "succeeded", vid))
        conn.commit()

    print("validation load_run_id =", vid)
    for r in results:
        print(f"  {r[4].upper():<4} {r[0]:<36} {r[1]:<28} expected={r[2]} | observed={r[3]}")
    print("\nspatial_eligibility:", elig)
    print("accident_severity:", sev)
    print("hotspot_point rows:", hp)
    print(f"\n{len(results) - len(failed)}/{len(results)} pass, {len(failed)} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
