"""Phase 3 Step 3 — validation of the reference data (results -> meta.dq_check, layer 'ref').

R1 IGN counts       : DB communes/departements per edition = source layer (re-read) = Phase 1C reference table
R2 geometry         : all valid, MULTIPOLYGON, non-empty; invalid inputs flagged; area consistency
R3 SRS              : SRID 2154 everywhere; known points fall in the right commune (Paris, Ajaccio, Bastia)
R4 INSEE            : staging = file rows; typed = staging; domains; successors exist
R5 harmonisation    : every distinct BAAC code covered; class counts; every metro accident harmonised except N/C;
                      com_cog_2026 exists in IGN 2025 (= COG 2026); agreement with Phase 1D for the 598 accidents
R6 geo validation   : 382 721 records = staging accidents; category counts by year = Phase 1C; 11 proposals 'proposed'
R7 integrity        : Phase 1C num_acc set = staging set; original codes & coordinate strings identical to staging;
                      FK lineage; proposals / Phase 1D rows consistent with categories
R8 staging intact   : staging fingerprints unchanged since before Step 3 (argument: fingerprint file)
Usage: python 14_validate_reference_data.py [staging_fingerprint.txt]
       (default baseline: reports/phase3/staging_fingerprint.txt — see staging_fingerprint.py)
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pyogrio
import psycopg

import staging_fingerprint
from db_config import conninfo

ROOT = Path(__file__).resolve().parents[1]
EXTR = ROOT / "data" / "raw" / "geography" / "admin_express_cog" / "extracted"
GTAB = ROOT / "reports" / "geography" / "tables"
METRO = {f"{i:02d}" for i in range(1, 96) if i != 20} | {"2A", "2B"}
METRO_SQL = "(dep_n ~ '^(0[1-9]|[1-8][0-9]|9[0-5])$' or dep_n in ('2A','2B'))"
results = []


def check(code, entity, year, expected, observed, ok, status_if_not_ok="fail"):
    results.append((code, entity, year, str(expected), str(observed), "pass" if ok else status_if_not_ok))


def q(cur, sql, *args):
    cur.execute(sql, args or None)
    return cur.fetchall()


def q1(cur, sql, *args):
    """single scalar value"""
    return q(cur, sql, *args)[0][0]


def source_counts(year: int):
    d = EXTR / str(year)
    if year == 2025:
        p = next(d.glob("*.gpkg"))
        c = pyogrio.read_dataframe(p, layer="commune", columns=["code_insee_du_departement"], read_geometry=False)
        dd = pyogrio.read_dataframe(p, layer="departement", columns=["code_insee"], read_geometry=False)
        return int(c.iloc[:, 0].isin(METRO).sum()), int(dd.iloc[:, 0].isin(METRO).sum())
    c = pyogrio.read_dataframe(d / "COMMUNE.shp", columns=["INSEE_DEP"], read_geometry=False)
    dd = pyogrio.read_dataframe(d / "DEPARTEMENT.shp", columns=["INSEE_DEP"], read_geometry=False)
    return int(c.INSEE_DEP.isin(METRO).sum()), int(dd.INSEE_DEP.isin(METRO).sum())


def main() -> int:
    fp_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    ref_layers = {int(r["year"]): r for r in csv.DictReader((GTAB / "00_reference_layers.csv").open(encoding="utf-8"))}
    p1c_year = pd.read_csv(GTAB / "02_results_by_year.csv", index_col="year")

    with psycopg.connect(**conninfo()) as conn, conn.cursor() as cur:
        # R1 ------------------------------------------------------------------
        db_c = dict(q(cur, "select edition_year, count(*) from ref.ign_commune group by 1"))
        db_d = dict(q(cur, "select edition_year, count(*) from ref.ign_departement group by 1"))
        for y in range(2019, 2026):
            sc, sd = source_counts(y)
            check("R1_COMMUNE_COUNT", "ign_commune", y, f"source={sc} phase1c={ref_layers[y]['metro_communes']}", db_c.get(y),
                  db_c.get(y) == sc == int(ref_layers[y]["metro_communes"]))
            check("R1_DEPARTEMENT_COUNT", "ign_departement", y, f"source={sd} expected=96", db_d.get(y), db_d.get(y) == sd == 96)

        # R2 ------------------------------------------------------------------
        for t, key in (("ign_commune", "insee_com"), ("ign_departement", "insee_dep")):
            for y, n, valid, mp, empty, was_inv in q(cur, f"""
                    select edition_year, count(*), count(*) filter (where st_isvalid(geom)),
                           count(*) filter (where geometrytype(geom) = 'MULTIPOLYGON'),
                           count(*) filter (where st_isempty(geom)), count(*) filter (where geom_was_invalid)
                    from ref.{t} group by 1 order by 1"""):
                check("R2_GEOM_VALID_MULTIPOLYGON", t, y, n, f"valid={valid} multipolygon={mp} empty={empty}",
                      n == valid == mp and empty == 0)
                exp_inv = int(ref_layers[y]["invalid_commune_geoms" if t == "ign_commune" else "invalid_dep_geoms"])
                check("R2_INPUT_INVALID_FLAGGED", t, y, f"phase1c={exp_inv}", was_inv, was_inv == exp_inv, "warn")
        areas = q(cur, """select c.edition_year, round(sum(st_area(c.geom))/1e6), d.a
                          from ref.ign_commune c join (select edition_year, round(sum(st_area(geom))/1e6) a
                          from ref.ign_departement group by 1) d using (edition_year) group by 1, 3 order by 1""")
        for y, ca, da in areas:
            check("R2_AREA_COMMUNES_VS_DEPTS_km2", "ign", y, f"depts={da}", f"communes={ca}", abs(float(ca) - float(da)) / float(da) < 0.001)
        das = [float(a[2]) for a in areas]
        check("R2_AREA_STABLE_ACROSS_EDITIONS_km2", "ign_departement", None, "spread < 0.5 %",
              f"min={min(das)} max={max(das)}", (max(das) - min(das)) / min(das) < 0.005)

        # R3 ------------------------------------------------------------------
        srids = q(cur, """select 'ign_commune', find_srid('ref','ign_commune','geom') union all
                          select 'ign_departement', find_srid('ref','ign_departement','geom')""")
        for t, s in srids:
            check("R3_SRID_DECLARED", t, None, 2154, s, s == 2154)
        for t in ("ign_commune", "ign_departement"):
            s = q(cur, f"select array_agg(distinct st_srid(geom)) from ref.{t}")[0][0]
            check("R3_SRID_ROWS", t, None, [2154], s, s == [2154])
        for label, lon, lat, exp in (("Paris Notre-Dame", 2.3499, 48.8530, "75056"), ("Ajaccio", 8.7369, 41.9192, "2A004"),
                                     ("Bastia", 9.4500, 42.7000, "2B033")):
            got = dict(q(cur, """select edition_year, insee_com from ref.ign_commune where commune_type = 'COM'
                                 and st_within(st_transform(st_setsrid(st_makepoint(%s,%s),4326),2154), geom)""", lon, lat))
            check("R3_KNOWN_POINT", label, None, exp, got, len(got) == 7 and set(got.values()) == {exp})
        arm = q(cur, """select edition_year, count(*), count(*) filter (where insee_com ~ '^(751|6938|132)')
                        from ref.ign_commune where commune_type = 'ARM' group by 1""")
        check("R2_ARM_POLYGONS_FLAGGED", "ign_commune", None, "[(2019, 45, 45)] (source TYPE='ARM')", arm, arm == [(2019, 45, 45)])
        com_cnt = q(cur, "select edition_year, count(*) from ref.ign_commune where commune_type='COM' group by 1 order by 1")
        check("R2_COMMUNE_POLYGONS_EXCL_ARM", "ign_commune", None, "2019: 34886-45 = 34841", com_cnt,
              dict(com_cnt)[2019] == 34841)
        (overlap,) = q(cur, """select count(*) from ref.ign_commune a join ref.ign_commune b
                               on a.edition_year = b.edition_year and a.insee_com < b.insee_com
                               and a.commune_type = 'COM' and b.commune_type = 'COM' and a.geom && b.geom
                               and st_relate(a.geom, b.geom, '2********')""")[0]
        check("R2_NO_COM_POLYGON_OVERLAP", "ign_commune", None, 0, overlap, overlap == 0, "warn")

        # R4 ------------------------------------------------------------------
        n_file_mvt = sum(1 for _ in open(ROOT / "data/raw/geography/insee_cog/2026/v_mvt_commune_2026.csv", encoding="utf-8")) - 1
        n_file_per = sum(1 for _ in open(ROOT / "data/raw/geography/insee_cog/2026/v_commune_depuis_1943.csv", encoding="utf-8")) - 1
        s_mvt, s_per = q1(cur, "select count(*) from staging.stg_insee_mvt_commune"), q1(cur, "select count(*) from staging.stg_insee_commune_period")
        r_mvt, r_per = q1(cur, "select count(*) from ref.insee_cog_event"), q1(cur, "select count(*) from ref.insee_commune_period")
        check("R4_INSEE_EVENTS", "insee_cog_event", 2026, f"file={n_file_mvt} staging={s_mvt}", r_mvt, n_file_mvt == s_mvt == r_mvt == 13734)
        check("R4_INSEE_PERIODS", "insee_commune_period", 2026, f"file={n_file_per} staging={s_per}", r_per, n_file_per == s_per == r_per == 42333)
        (n_empty_av,) = q(cur, "select count(*) from ref.insee_cog_event where typecom_av is null")[0]
        check("R4_INSEE_EMPTY_TYPECOM_AV", "insee_cog_event", 2026, "127 (source)", n_empty_av, n_empty_av == 127, "warn")
        (bad_succ,) = q(cur, """select count(*) from ref.commune_code_harmonisation h where com_cog_2026 is not null
                                and not exists (select 1 from ref.insee_commune_period p where p.typecom='COM'
                                and p.com=h.com_cog_2026 and p.date_fin is null)""")[0]
        check("R4_SUCCESSORS_ACTIVE_IN_COG2026", "commune_code_harmonisation", None, 0, bad_succ, bad_succ == 0)

        # R5 ------------------------------------------------------------------
        (n_codes,) = q(cur, "select count(distinct btrim(com)) from staging.stg_baac_caracteristiques")[0]
        (n_h,) = q(cur, "select count(*) from ref.commune_code_harmonisation")[0]
        check("R5_ALL_BAAC_CODES_COVERED", "commune_code_harmonisation", None, n_codes, n_h, n_codes == n_h)
        per_class = q(cur, f"""
            with a as (select source_year, btrim(com) com,
                       case when btrim(dep) ~ '^[0-9]$' then '0'||btrim(dep) else btrim(dep) end dep_n
                       from staging.stg_baac_caracteristiques)
            select h.status_2026, h.transformation_class, count(distinct a.com), count(*)
            from a join ref.commune_code_harmonisation h on h.com_original = a.com
            where {METRO_SQL} group by 1, 2 order by 1, 2""")
        cls = {(s, c): (nc, na) for s, c, nc, na in per_class}
        exp = {("active_com", "identity"): (25042, 313631), ("active_arm", "arrondissement_to_commune"): (45, 46883),
               ("unresolved", "unresolved"): (1, 1)}
        for k, v in exp.items():
            check("R5_METRO_CLASS", k[1], None, v, cls.get(k), cls.get(k) == v)
        resolved = [(k, v) for k, v in cls.items() if k[0] == "obsolete_resolved"]
        rc, ra = sum(v[0] for _, v in resolved), sum(v[1] for _, v in resolved)
        check("R5_METRO_OBSOLETE_RESOLVED", "obsolete_resolved", None, "(306 codes, 1078 accidents)", (rc, ra, dict(resolved)),
              (rc, ra) == (306, 1078))
        by_year = q(cur, f"""
            with a as (select source_year, btrim(com) com,
                       case when btrim(dep) ~ '^[0-9]$' then '0'||btrim(dep) else btrim(dep) end dep_n
                       from staging.stg_baac_caracteristiques)
            select source_year, count(*), count(h.com_cog_2026),
                   count(*) filter (where h.status_2026 = 'obsolete_resolved')
            from a left join ref.commune_code_harmonisation h on h.com_original = a.com
            where {METRO_SQL} group by 1 order by 1""")
        for y, n, harmonised, obs in by_year:
            exp_missing = 1 if y == 2022 else 0
            check("R5_METRO_ACCIDENTS_HARMONISED", "accidents", y, f"{n} - {exp_missing} (N/C)", f"{harmonised} (obsolete codes: {obs})",
                  harmonised == n - exp_missing)
        (not_in_ign,) = q(cur, """select count(*) from ref.commune_code_harmonisation h where com_cog_2026 is not null
                                  and com_cog_2026 !~ '^9[78]' and not exists (select 1 from ref.ign_commune c
                                  where c.edition_year = 2025 and c.insee_com = h.com_cog_2026)""")[0]
        check("R5_COG2026_IN_IGN2025", "commune_code_harmonisation", None, 0, not_in_ign, not_in_ign == 0)
        (dis,) = q(cur, """select count(*) from ref.obsolete_code_mapping_phase1d m
                           join ref.commune_code_harmonisation h on h.com_original = m.com_original
                           where m.successor_2026 is distinct from h.com_cog_2026""")[0]
        check("R5_AGREES_WITH_PHASE1D", "obsolete_code_mapping_phase1d", None, 0, dis, dis == 0)

        # R6 ------------------------------------------------------------------
        n_val, n_stg = q1(cur, "select count(*) from ref.geo_validation_phase1c"), q1(cur, "select count(*) from staging.stg_baac_caracteristiques")
        check("R6_GEO_VALIDATION_RECORDS", "geo_validation_phase1c", None, f"staging={n_stg}", n_val, n_val == n_stg == 382721)
        db_cat = q(cur, "select year, category, count(*) from ref.geo_validation_phase1c group by 1, 2")
        dbm = {(y, c): n for y, c, n in db_cat}
        for y in p1c_year.index:
            for c in [c for c in p1c_year.columns if c not in ("total", "pct_valid", "pct_valid_or_nearby")]:
                e = int(p1c_year.loc[y, c])
                check("R6_CATEGORY_COUNT", c, int(y), e, dbm.get((int(y), c), 0), dbm.get((int(y), c), 0) == e)
        corr = q(cur, "select method, correction_status, count(*) from ref.coordinate_correction_proposal group by 1, 2 order by 1")
        check("R6_CORRECTIONS_PROPOSED_ONLY", "coordinate_correction_proposal", None,
              [("flip_longitude_sign", "proposed", 7), ("swap_lat_long", "proposed", 4)], corr,
              corr == [("flip_longitude_sign", "proposed", 7), ("swap_lat_long", "proposed", 4)])
        n1d, n_unres = q1(cur, "select count(*) from ref.obsolete_code_mapping_phase1d"), \
            q1(cur, "select count(*) from ref.geo_validation_phase1c where category = 'commune_code_unresolved'")
        conf = q(cur, "select mapping_confidence, count(*) from ref.obsolete_code_mapping_phase1d group by 1 order by 1")
        check("R6_PHASE1D_RECORDS", "obsolete_code_mapping_phase1d", None, f"unresolved category={n_unres}", (n1d, conf), n1d == n_unres == 598)

        # R7 ------------------------------------------------------------------
        (mismatch,) = q(cur, """select count(*) from ref.geo_validation_phase1c g full join
                                (select regexp_replace(num_acc, '\\s', '', 'g')::bigint num_acc, com, lat, long, dep
                                 from staging.stg_baac_caracteristiques) s using (num_acc)
                                where g.num_acc is null or s.num_acc is null or g.lat_raw <> s.lat or g.long_raw <> s.long
                                   or g.com_raw <> s.com or g.dep_raw <> s.dep""")[0]
        check("R7_PHASE1C_MATCHES_STAGING_ORIGINALS", "geo_validation_phase1c", None,
              "same accidents, identical dep/com/lat/long strings", f"{mismatch} mismatches", mismatch == 0)
        (bad_corr,) = q(cur, """select count(*) from ref.coordinate_correction_proposal c join ref.geo_validation_phase1c g using (num_acc)
                                where c.lat_original <> g.lat_raw or c.long_original <> g.long_raw
                                   or (c.method = 'swap_lat_long' and g.category <> 'swapped')
                                   or (c.method = 'flip_longitude_sign' and g.category not in ('wrong_commune_same_dep','wrong_department'))""")[0]
        check("R7_CORRECTIONS_CONSISTENT", "coordinate_correction_proposal", None, 0, bad_corr, bad_corr == 0)
        (bad_1d,) = q(cur, """select count(*) from ref.obsolete_code_mapping_phase1d m join ref.geo_validation_phase1c g using (num_acc)
                              where g.category <> 'commune_code_unresolved' or m.com_original <> btrim(g.com_raw)""")[0]
        check("R7_PHASE1D_CONSISTENT", "obsolete_code_mapping_phase1d", None, 0, bad_1d, bad_1d == 0)
        for t in ("ign_commune", "ign_departement", "insee_cog_event", "insee_commune_period", "geo_validation_phase1c",
                  "coordinate_correction_proposal", "obsolete_code_mapping_phase1d"):
            (orph,) = q(cur, f"select count(*) from ref.{t} x left join meta.source_file f using (source_file_id) where f.source_file_id is null")[0]
            check("R7_LINEAGE_FK", t, None, 0, orph, orph == 0)

        # R8 ------------------------------------------------------------------
        before, created = staging_fingerprint.baseline(cur, fp_path)
        now = staging_fingerprint.compute(cur)
        for name, t in staging_fingerprint.TABLES:
            check("R8_STAGING_UNCHANGED", f"stg_baac_{t}", None, before[name] if not created else "baseline created now",
                  now[name], before[name] == now[name] and not created, "warn" if created else "fail")

        cur.execute("insert into meta.load_run (step, code_fingerprint, parameters) values ('validate_reference_data', %s, %s) "
                    "returning load_run_id", (hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), json.dumps({"checks": len(results)})))
        vid = cur.fetchone()[0]
        cur.executemany("insert into meta.dq_check (load_run_id, layer, check_code, entity, reference_year, expected, observed, status) "
                        "values (%s, 'ref', %s, %s, %s, %s, %s, %s)", [(vid, *r) for r in results])
        failed = [r for r in results if r[5] == "fail"]
        cur.execute("update meta.load_run set status=%s, finished_at=now() where load_run_id=%s",
                    ("failed" if failed else "succeeded", vid))
        conn.commit()

    s = Counter((r[0], r[5]) for r in results)
    print("validation load_run_id =", vid)
    for code in dict.fromkeys(r[0] for r in results):
        print(f"  {code:<38} pass={s[(code,'pass')]:>3} warn={s[(code,'warn')]} fail={s[(code,'fail')]}")
    for r in results:
        if r[5] != "pass" or r[0] in ("R5_METRO_OBSOLETE_RESOLVED", "R2_AREA_STABLE_ACROSS_EDITIONS_km2", "R6_PHASE1D_RECORDS",
                                      "R6_CORRECTIONS_PROPOSED_ONLY", "R3_KNOWN_POINT"):
            print("  ", r[5].upper(), r[0], r[1], r[2], "| expected:", r[3], "| observed:", r[4])
    print(f"\n{sum(r[5] == 'pass' for r in results)}/{len(results)} pass, {sum(r[5] == 'warn' for r in results)} warn, {len(failed)} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
