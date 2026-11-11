"""Phase 3 Step 4 — validation of the clean layer (results -> meta.dq_check, layer 'clean').

Expected values come from earlier, independent measurements (Phase 1 tables, Phase 1B/1C/1D), not from the builder.
C1  row counts staging = clean per entity and year            C7  no fan-out; Lieux segments consistent
C2  PK / FK constraints present and validated; 0 orphans      C8  original values preserved; no coordinate corrected
C3  every accident has location, vehicle, user; vehicles      C9  dq_issue counts = Phase 1 measurements
    without users = Phase 1                                    C10 missing-code conventions (grav -1, fugitive-like)
C4  totals: accidents, locations, vehicles, users, casualties  C11 raw files + staging unchanged
C5  all years 2019–2025 present in every table                C12 lineage: every clean row maps to one staging row
C6  commune harmonisation coverage & agreement with Phase 1D
Usage: python 16_validate_clean.py [staging_fingerprint.txt]
       (default baseline: reports/phase3/staging_fingerprint.txt — see staging_fingerprint.py)
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import psycopg

import staging_fingerprint
from db_config import conninfo

ROOT = Path(__file__).resolve().parents[1]
YEARS = list(range(2019, 2026))
ENT = {"accident": "caracteristiques", "accident_location": "lieux", "vehicle": "vehicules", "road_user": "usagers"}
results = []


def check(code, entity, year, expected, observed, ok, level="fail"):
    results.append((code, entity, year, str(expected), str(observed), "pass" if ok else level))


def q(cur, sql, *a):
    cur.execute(sql, a or None)
    return cur.fetchall()


def q1(cur, sql, *a):
    return q(cur, sql, *a)[0][0]


def main() -> int:
    fp_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    with psycopg.connect(**conninfo()) as conn, conn.cursor() as cur:
        # C1 / C5 ----------------------------------------------------------------
        for ent, stg in ENT.items():
            s = dict(q(cur, f"select source_year, count(*) from staging.stg_baac_{stg} group by 1"))
            c = dict(q(cur, f"select f.reference_year, count(*) from clean.{ent} x join meta.source_file f using (source_file_id) group by 1"))
            for y in YEARS:
                check("C1_ROWCOUNT_STAGING_EQ_CLEAN", ent, y, s.get(y), c.get(y), s.get(y) == c.get(y) and c.get(y, 0) > 0)
            check("C5_ALL_YEARS_PRESENT", ent, None, YEARS, sorted(c), sorted(c) == YEARS)

        # C2 ----------------------------------------------------------------------
        cons = q(cur, """select conrelid::regclass::text, contype, conname, convalidated from pg_constraint
                         where connamespace = 'clean'::regnamespace and contype in ('p','f','u') order by 1, 2, 3""")
        need = {("clean.accident", "p"), ("clean.accident", "f"), ("clean.accident_location", "p"), ("clean.accident_location", "f"),
                ("clean.vehicle", "p"), ("clean.vehicle", "f"), ("clean.road_user", "p"), ("clean.road_user", "f")}
        have = {(t, ty) for t, ty, _, _ in cons}
        check("C2_PK_FK_PRESENT", "clean", None, sorted(need), "all present" if need <= have else sorted(need - have),
              need <= have and all(v for *_, v in cons))
        fk = q1(cur, """select count(*) from pg_constraint where conname = 'road_user_vehicle_fk'
                        and pg_get_constraintdef(oid) like '%(id_vehicule, num_acc)%'""")
        check("C2_USER_VEHICLE_FK_ON_ID_VEHICULE", "road_user", None, 1, fk, fk == 1)
        nv_key = q1(cur, """select count(*) from pg_constraint where connamespace='clean'::regnamespace and contype in ('p','u')
                            and pg_get_constraintdef(oid) ilike '%num_veh%'""")
        check("C2_NUM_VEH_NOT_A_KEY", "vehicle", None, 0, nv_key, nv_key == 0)
        for label, sql in {
            "location_without_accident": "select count(*) from clean.accident_location l left join clean.accident a using (num_acc) where a.num_acc is null",
            "vehicle_without_accident": "select count(*) from clean.vehicle v left join clean.accident a using (num_acc) where a.num_acc is null",
            "user_without_vehicle": "select count(*) from clean.road_user u left join clean.vehicle v using (id_vehicule, num_acc) where v.id_vehicule is null",
            "user_without_accident": "select count(*) from clean.road_user u left join clean.accident a using (num_acc) where a.num_acc is null",
        }.items():
            n = q1(cur, sql)
            check("C2_ORPHANS", label, None, 0, n, n == 0)
        dup_nv = q1(cur, "select count(*) from (select num_acc, num_veh from clean.vehicle group by 1, 2 having count(*) > 1) t")
        check("C2_NUM_VEH_DUPLICATES_PRESERVED", "vehicle", None, "56 (num_acc, num_veh) pairs (53 + 2 + 1, Phase 1)", dup_nv, dup_nv == 56)

        # C3 ----------------------------------------------------------------------
        for child in ("accident_location", "vehicle", "road_user"):
            n = q1(cur, f"select count(*) from clean.accident a where not exists (select 1 from clean.{child} c where c.num_acc = a.num_acc)")
            check("C3_ACCIDENT_HAS_CHILD", child, None, 0, n, n == 0)
        exp_novu = {2019: 2040, 2020: 1899, 2021: 6, 2022: 0, 2023: 40, 2024: 24, 2025: 4}
        got = dict(q(cur, "select a.year, count(*) from clean.vehicle v join clean.accident a using (num_acc) where v.has_no_user group by 1"))
        for y in YEARS:
            check("C3_VEHICLES_WITHOUT_USER", "vehicle", y, exp_novu[y], got.get(y, 0), got.get(y, 0) == exp_novu[y])

        # C4 ----------------------------------------------------------------------
        for ent, exp in (("accident", 382721), ("accident_location", 430628), ("vehicle", 653712), ("road_user", 871534)):
            n = q1(cur, f"select count(*) from clean.{ent}")
            check("C4_TOTAL_ROWS", ent, None, exp, n, n == exp)
        sg = {(y, g): n for y, g, n in q(cur, "select source_year, btrim(grav), count(*) from staging.stg_baac_usagers group by 1, 2")}
        cg = {(y, g): n for y, g, n in q(cur, """select a.year, coalesce(u.grav::text, '-1'), count(*) from clean.road_user u
                                                 join clean.accident a using (num_acc) group by 1, 2""")}
        check("C4_CASUALTIES_BY_GRAV_YEAR", "road_user", None, "staging grav counts", "clean grav counts (-1 -> NULL)", sg == cg)
        killed = dict(q(cur, """select a.year, count(*) from clean.road_user u join clean.accident a using (num_acc)
                                where a.is_metro and u.grav = 2 group by 1"""))
        exp_k = {2019: 3244, 2020: 2541, 2021: 2944, 2022: 3267, 2023: 3167, 2024: 3193, 2025: 3263}
        for y in YEARS:
            check("C4_METRO_KILLED_PHASE1B", "road_user", y, exp_k[y], killed.get(y), killed.get(y) == exp_k[y])
        metro = q1(cur, "select count(*) from clean.accident where is_metro")
        check("C4_METRO_ACCIDENTS", "accident", None, 361593, metro, metro == 361593)

        # C6 ----------------------------------------------------------------------
        r = q(cur, """select count(*) filter (where com_cog_2026 is null), count(*) filter (where com_cog_at_date is null),
                             count(*) filter (where com_arm is not null)
                      from clean.accident where is_metro""")[0]
        check("C6_METRO_COM_COG_2026", "accident", None, "1 NULL (N/C)", r[0], r[0] == 1)
        check("C6_METRO_COM_COG_AT_DATE", "accident", None, "1 NULL (N/C)", r[1], r[1] == 1)
        check("C6_ARRONDISSEMENT_IDS_KEPT", "accident", None, 46883, r[2], r[2] == 46883)
        n = q1(cur, """select count(*) from clean.accident a join ref.obsolete_code_mapping_phase1d m using (num_acc)
                       where a.com_cog_at_date is distinct from m.successor_at_accident_date
                          or a.com_cog_2026 is distinct from m.successor_2026""")
        check("C6_AGREES_WITH_PHASE1D_598", "accident", None, 0, n, n == 0)
        n = q1(cur, """select count(*) from clean.accident a join ref.commune_code_harmonisation h on h.com_original = a.com_original
                       where a.com_cog_2026 is distinct from h.com_cog_2026""")
        check("C6_COG2026_EQ_HARMONISATION", "accident", None, 0, n, n == 0)
        n = q1(cur, """select count(*) from clean.accident a where a.is_metro and a.com_cog_at_date is not null and not exists
                       (select 1 from ref.insee_commune_period p where p.typecom = 'COM' and p.com = a.com_cog_at_date
                        and a.acc_date >= p.date_debut and (p.date_fin is null or a.acc_date < p.date_fin))""")
        check("C6_COM_AT_DATE_VALID_ON_DATE", "accident", None, 0, n, n == 0)
        conf = dict(q(cur, "select com_mapping_confidence, count(*) from clean.accident where is_metro group by 1"))
        p1d = dict(q(cur, """select a.com_mapping_confidence, count(*) from clean.accident a
                             join ref.obsolete_code_mapping_phase1d using (num_acc) group by 1"""))
        check("C6_PHASE1D_CONFIDENCE_KEPT", "accident", None, {"high": 579, "medium": 18, "none": 1}, p1d,
              p1d == {"high": 579, "medium": 18, "none": 1})
        check("C6_CONFIDENCE_DISTRIBUTION_METRO", "accident", None, "informative", conf, True)

        # C7 ----------------------------------------------------------------------
        n_u = q1(cur, "select count(*) from clean.road_user")
        n_j = q1(cur, "select count(*) from clean.road_user u join clean.vehicle v using (id_vehicule, num_acc) join clean.accident a using (num_acc)")
        check("C7_USER_VEHICLE_ACCIDENT_JOIN_NO_FANOUT", "road_user", None, n_u, n_j, n_u == n_j)
        n_v = q1(cur, "select count(*) from clean.vehicle v join clean.accident a using (num_acc)")
        check("C7_VEHICLE_ACCIDENT_JOIN_NO_FANOUT", "vehicle", None, 653712, n_v, n_v == 653712)
        bad = q1(cur, """select count(*) from (select num_acc, max(segment_seq) mx, count(*) n, min(n_segments_in_accident) a,
                         max(n_segments_in_accident) b from clean.accident_location group by 1) t where mx <> n or a <> n or b <> n""")
        check("C7_SEGMENT_SEQ_CONSISTENT", "accident_location", None, 0, bad, bad == 0)
        multi = dict(q(cur, """select a.year, count(*) from clean.accident a where exists
                               (select 1 from clean.accident_location l where l.num_acc = a.num_acc and l.n_segments_in_accident > 1) group by 1"""))
        exp_m = {2019: 0, 2020: 0, 2021: 0, 2022: 0, 2023: 15870, 2024: 15645, 2025: 15831}
        for y in YEARS:
            check("C7_MULTI_SEGMENT_ACCIDENTS", "accident_location", y, exp_m[y], multi.get(y, 0), multi.get(y, 0) == exp_m[y])
        naive = q1(cur, "select count(*) from clean.road_user u join clean.accident_location l using (num_acc)")
        check("C7_NAIVE_LIEUX_JOIN_WOULD_INFLATE_USERS", "informative", None, n_u, naive, True)

        # C8 ----------------------------------------------------------------------
        n = q1(cur, """select count(*) from clean.accident a join staging.stg_baac_caracteristiques s using (source_file_id, source_row_number)
                       where a.lat_original <> s.lat or a.long_original <> s.long or a.dep_original <> s.dep
                          or a.adr_original <> s.adr or a.com_original <> btrim(s.com)""")
        check("C8_ORIGINAL_VALUES_PRESERVED", "accident", None, 0, n, n == 0)
        n = q1(cur, """select count(*) from clean.accident a join ref.geo_validation_phase1c g using (num_acc)
                       where a.geo_category <> g.category or a.lat is distinct from g.lat or a.lon is distinct from g.lon""")
        check("C8_COORDS_AND_GEO_CATEGORY_EQ_PHASE1C", "accident", None, 0, n, n == 0)
        r = q(cur, """select count(*), count(*) filter (where a.lat = replace(btrim(a.lat_original), ',', '.')::float8
                                                        and a.lon = replace(btrim(a.long_original), ',', '.')::float8)
                      from clean.accident a where a.has_correction_proposal""")[0]
        check("C8_CORRECTIONS_FLAGGED_NOT_APPLIED", "accident", None, "11 flagged, 11 unchanged", r, r == (11, 11))
        n = q1(cur, """select count(*) from clean.accident where is_metro and (geom_original is null or st_srid(geom_original) <> 2154)""")
        check("C8_METRO_GEOM_2154", "accident", None, 0, n, n == 0)

        # C9 ----------------------------------------------------------------------
        iss = {(e, c, i, y): n for e, c, i, y, n in q(cur, """select d.entity, d.column_name, d.issue_code, f.reference_year, count(*)
                 from clean.dq_issue d join meta.source_file f using (source_file_id) group by 1, 2, 3, 4""")}
        exp_issue = {("accident_location", "nbv", "ERROR_TOKEN"): {2022: 1, 2023: 54, 2024: 50, 2025: 24},
                     ("road_user", "actp", "UNDOCUMENTED_CODE"): {2019: 31, 2020: 19, 2021: 29, 2022: 33, 2023: 33, 2024: 37, 2025: 35},
                     ("road_user", "an_nais", "AN_NAIS_PLACEHOLDER"): {2019: 176, 2020: 15}}
        for (e, c, i), per in exp_issue.items():
            got = {y: iss.get((e, c, i, y), 0) for y in YEARS}
            check("C9_DQ_ISSUE_EQ_PHASE1", f"{e}.{c}", None, {y: per.get(y, 0) for y in YEARS}, got,
                  got == {y: per.get(y, 0) for y in YEARS})
        odd = q(cur, "select count(distinct original_value), count(*) from clean.dq_issue where issue_code = 'NUM_VEH_ODD'")[0]
        check("C9_NUM_VEH_ODD", "vehicle.num_veh", None, "4 distinct values (Phase 1: [01 \\01 ]01 _01)", f"{odd[0]} values / {odd[1]} rows",
              odd[0] == 4)
        nan = q1(cur, "select count(*) from clean.accident where com_cog_at_date = 'nan' or com_cog_2026 = 'nan' or com_arm = 'nan'")
        check("C6_NO_TEXT_NAN_IN_CODES", "accident", None, 0, nan, nan == 0)
        other = Counter()
        for (e, c, i, y), v in iss.items():
            other[(e, c, i)] += v
        check("C9_DQ_ISSUE_SUMMARY", "dq_issue", None, "informative", dict(other), True)

        # C10 ---------------------------------------------------------------------
        g = dict(q(cur, """select a.year, count(*) from clean.road_user u join clean.accident a using (num_acc)
                           join staging.stg_baac_usagers s on s.source_file_id = u.source_file_id and s.source_row_number = u.source_row_number
                           where btrim(s.grav) = '-1' and u.grav is null group by 1"""))
        check("C10_GRAV_MINUS1_TO_NULL", "road_user", None, {2021: 60, 2022: 241, 2023: 118}, g, g == {2021: 60, 2022: 241, 2023: 118})
        f = dict(q(cur, """select a.year, count(*) from clean.road_user u join clean.accident a using (num_acc)
                           where a.is_metro and u.is_fugitive_like group by 1"""))
        exp_f = {2021: 2908, 2022: 2610, 2023: 2278, 2024: 2240, 2025: 2071}
        check("C10_FUGITIVE_LIKE_METRO_PHASE1B", "road_user", None, exp_f, f, f == exp_f)

        # C11 ---------------------------------------------------------------------
        bad = [r["file"] for r in csv.DictReader((ROOT / "data/raw/baac/_manifest.csv").open(encoding="utf-8"))
               if hashlib.sha256((ROOT / r["file"]).read_bytes()).hexdigest() != r["sha256"]]
        check("C11_RAW_UNCHANGED", "raw_baac", None, 0, len(bad), not bad)
        before, created = staging_fingerprint.baseline(cur, fp_path)
        now = staging_fingerprint.compute(cur)
        for name, t in staging_fingerprint.TABLES:
            check("C11_STAGING_UNCHANGED", f"stg_baac_{t}", None, before[name] if not created else "baseline created now",
                  now[name], before[name] == now[name] and not created, "warn" if created else "fail")

        # C12 ---------------------------------------------------------------------
        for ent, stg in ENT.items():
            n = q1(cur, f"""select count(*) from clean.{ent} c left join staging.stg_baac_{stg} s using (source_file_id, source_row_number)
                            where s.source_file_id is null""")
            check("C12_LINEAGE_TO_STAGING", ent, None, 0, n, n == 0)

        cur.execute("insert into meta.load_run (step, code_fingerprint, parameters) values ('validate_clean', %s, %s) returning load_run_id",
                    (hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), json.dumps({"checks": len(results)})))
        vid = cur.fetchone()[0]
        cur.executemany("insert into meta.dq_check (load_run_id, layer, check_code, entity, reference_year, expected, observed, status) "
                        "values (%s, 'clean', %s, %s, %s, %s, %s, %s)", [(vid, *r) for r in results])
        failed = [r for r in results if r[5] == "fail"]
        cur.execute("update meta.load_run set status=%s, finished_at=now() where load_run_id=%s", ("failed" if failed else "succeeded", vid))
        conn.commit()

    s = Counter((r[0], r[5]) for r in results)
    print("validation load_run_id =", vid)
    for code in dict.fromkeys(r[0] for r in results):
        print(f"  {code:<42} pass={s[(code, 'pass')]:>3} fail={s[(code, 'fail')]}")
    for r in results:
        if r[5] != "pass" or r[0] in ("C6_CONFIDENCE_DISTRIBUTION_METRO", "C9_DQ_ISSUE_SUMMARY", "C7_NAIVE_LIEUX_JOIN_WOULD_INFLATE_USERS"):
            print("  ", r[5].upper(), r[0], r[1], r[2], "| expected:", r[3], "| observed:", r[4])
    print(f"\n{sum(r[5] == 'pass' for r in results)}/{len(results)} pass, {len(failed)} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
