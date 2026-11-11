"""Phase 3 Step 4 — build the clean layer from staging + existing reference tables (one transaction).

  E0  raw BAAC files still match manifest (SHA-256)
  DDL db/sql/040_clean_layer.sql (helper functions + clean tables, idempotent)
  E6a com_cog_at_date for every distinct (commune code, accident date) — INSEE history (ref tables), no spatial work
  E6b clean.accident, clean.accident_location, clean.vehicle, clean.road_user via INSERT ... SELECT from staging
  E6c clean.dq_issue (undocumented codes, error tokens, negative PR, implausible vma, birth-year placeholders, odd num_veh)

Rules: reports/phase2/data_dictionary.md (G1–G9). No row is dropped; nothing is imputed; coordinates are never
corrected (the 11 proposals stay in ref.coordinate_correction_proposal, only flagged here).
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import psycopg

from db_config import conninfo, safe_description

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "db" / "sql" / "040_clean_layer.sql"
MANIFEST = ROOT / "data" / "raw" / "baac" / "_manifest.csv"
METRO_SQL = "('01','02','03','04','05','06','07','08','09'," + ",".join(f"'{i}'" for i in range(10, 96) if i != 20) + ",'2A','2B')"

# documented code lists (ONISR description 2005–2025) — column -> allowed integer codes
R = lambda a, b: list(range(a, b + 1))
CODES = {
    "accident": {"lum": R(1, 5), "agg": [1, 2], "int": R(1, 9), "atm": R(1, 9), "col": R(1, 7)},
    "accident_location": {"catr": R(1, 7) + [9], "circ": R(1, 4), "nbv": R(0, 12), "vosp": R(0, 3), "prof": R(1, 4),
                          "plan": R(1, 4), "surf": R(1, 9), "infra": R(0, 9), "situ": R(0, 6) + [8]},
    "vehicle": {"senc": R(0, 3), "catv": R(0, 21) + R(30, 43) + [50, 60, 80, 99], "obs": R(0, 17),
                "obsm": [0, 1, 2, 4, 5, 6, 9], "choc": R(0, 9), "manv": R(0, 26), "motor": R(0, 6)},
    "road_user": {"place": R(1, 10), "catu": R(1, 3), "grav": R(1, 4), "sexe": [1, 2], "trajet": R(0, 5) + [9],
                  "secu1": R(0, 9), "secu2": R(0, 9), "secu3": R(0, 9), "locp": R(0, 9), "etatp": R(1, 3)},
}
STAGING = {"accident": "staging.stg_baac_caracteristiques", "accident_location": "staging.stg_baac_lieux",
           "vehicle": "staging.stg_baac_vehicules", "road_user": "staging.stg_baac_usagers"}
KEY = {"accident": "c.num_acc::text", "accident_location": "c.location_id::text",
       "vehicle": "c.id_vehicule::text", "road_user": "c.road_user_id::text"}
ACTP_ALLOWED = ("0", "1", "2", "3", "4", "5", "6", "9", "A", "B")
VMA_STANDARD = "(10,15,20,30,40,45,50,60,70,80,90,100,110,120,130)"


def arr(v):
    return "'{" + ",".join(map(str, v)) + "}'::int[]"


def code(col, entity, alias="s"):
    return f"clean.f_code({alias}.\"{col}\", {arr(CODES[entity][col])})"


def com_at_date(cur) -> pd.DataFrame:
    """INSEE commune valid on the accident date for each distinct (code, date) pair."""
    cur.execute("""select distinct btrim(com), make_date(btrim(an)::int, btrim(mois)::int, btrim(jour)::int)
                   from staging.stg_baac_caracteristiques""")
    pairs = pd.DataFrame(cur.fetchall(), columns=["com", "d"])
    cur.execute("select typecom, com, date_debut, date_fin from ref.insee_commune_period")
    per = pd.DataFrame(cur.fetchall(), columns=["typecom", "com", "deb", "fin"])
    cur.execute("""select date_eff, com_av, com_ap from ref.insee_cog_event
                   where typecom_av = 'COM' and typecom_ap = 'COM' and com_av <> com_ap""")
    ev = pd.DataFrame(cur.fetchall(), columns=["date_eff", "av", "ap"])
    cur.execute("select com_original, status_2026, arm_parent_com from ref.commune_code_harmonisation")
    h = pd.DataFrame(cur.fetchall(), columns=["com", "status", "arm_parent"]).set_index("com")

    com_per = {c: g[["deb", "fin"]].values.tolist() for c, g in per[per.typecom == "COM"].groupby("com")}
    arm_codes = set(per[per.typecom == "ARM"].com)
    succ = {}
    for r in ev.itertuples(index=False):
        succ.setdefault((r.av, r.date_eff), set()).add(r.ap)

    def valid(c, d):
        return any(deb <= d and (fin is None or d < fin) for deb, fin in com_per.get(c, []))

    def resolve(c, d):
        for _ in range(10):
            if valid(c, d):
                return c, "valid_on_date" if _ == 0 else "insee_chain"
            ends = [fin for deb, fin in com_per.get(c, []) if fin is not None and fin <= d]
            if not ends:
                return None, "no_period_before_date"
            e = max(ends)
            nxt = succ.get((c, e), set()) | succ.get((c, e + timedelta(days=1)), set())
            if len(nxt) != 1:
                return None, f"{len(nxt)}_successors"
            c = next(iter(nxt))
        return None, "chain_too_long"

    out = []
    for c, d in pairs.itertuples(index=False):
        if c in arm_codes and h.loc[c, "status"] == "active_arm":
            out.append((c, d, h.loc[c, "arm_parent"], "arrondissement_parent"))
        else:
            r, how = resolve(c, d)
            out.append((c, d, r, how))
    return pd.DataFrame(out, columns=["com", "d", "com_at_date", "how"])


def main() -> int:
    for r in csv.DictReader(MANIFEST.open(encoding="utf-8")):
        if hashlib.sha256((ROOT / r["file"]).read_bytes()).hexdigest() != r["sha256"]:
            sys.exit(f"ABORT E0: {r['file']} changed")
    print("E0 raw BAAC integrity: all manifest files match")
    print("Connecting to", safe_description())
    with psycopg.connect(**conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL.read_text(encoding="utf-8"))
            cur.execute("insert into meta.load_run (step, code_fingerprint, parameters) values ('clean_baac', %s, %s) "
                        "returning load_run_id", (hashlib.sha256(Path(__file__).read_bytes() + SQL.read_bytes()).hexdigest(),
                                                  json.dumps({"years": "2019-2025"})))
            run = cur.fetchone()[0]
            print("load_run_id =", run)
            cur.execute("truncate clean.dq_issue, clean.road_user, clean.vehicle, clean.accident_location, clean.accident "
                        "restart identity")

            # ---- E6a commune valid on accident date
            m = com_at_date(cur)
            cur.execute("create temp table tmp_com_at_date (com text, d date, com_at_date char(5), how text, "
                        "primary key (com, d)) on commit drop")
            with cur.copy("copy tmp_com_at_date from stdin") as cp:
                for r in m.itertuples(index=False):
                    # unresolved -> real NULL (pandas turns None into NaN, which COPY would write as the text 'nan')
                    at_date = r.com_at_date if isinstance(r.com_at_date, str) else None
                    cp.write_row((r.com, r.d, at_date, r.how))
            print("E6a com_cog_at_date:", m["how"].value_counts().to_dict())

            # ---- E6b accident
            cur.execute(f"""
                insert into clean.accident (num_acc, year, acc_date, acc_time, hour, weekday, lum, agg, intersection, atm, col,
                    dep_original, dep_code, is_metro, com_original, com_arm, com_cog_at_date, com_cog_2026, com_mapping_class,
                    com_mapping_confidence, adr_original, lat_original, long_original, lat, lon, geom_original,
                    geo_category, geo_dist_declared_m, has_correction_proposal, correction_method,
                    source_file_id, source_row_number, load_run_id)
                select x.*, %s from (
                  select clean.f_id(s.num_acc), btrim(s.an)::smallint,
                         make_date(btrim(s.an)::int, btrim(s.mois)::int, btrim(s.jour)::int),
                         btrim(s.hrmn)::time, extract(hour from btrim(s.hrmn)::time)::smallint,
                         extract(isodow from make_date(btrim(s.an)::int, btrim(s.mois)::int, btrim(s.jour)::int))::smallint,
                         {code('lum', 'accident')}, {code('agg', 'accident')}, {code('int', 'accident')},
                         {code('atm', 'accident')}, {code('col', 'accident')},
                         s.dep, d.dep_code, d.dep_code in {METRO_SQL},
                         btrim(s.com), case when h.status_2026 = 'active_arm' then btrim(s.com) end,
                         t.com_at_date, h.com_cog_2026, h.transformation_class,
                         case when h.com_cog_2026 is null then 'none'
                              when (h.status_2026 = 'active_com' and t.how = 'valid_on_date') or h.status_2026 = 'active_arm' then 'exact'
                              when p1d.num_acc is not null then case when p1d.mapping_confidence like 'high%%' then 'high' else 'medium' end
                              when g.category = 'valid' then 'high' else 'medium' end,
                         s.adr, s.lat, s.long,
                         replace(btrim(s.lat), ',', '.')::float8, replace(btrim(s.long), ',', '.')::float8,
                         case when d.dep_code in {METRO_SQL} then st_transform(st_setsrid(st_makepoint(
                              replace(btrim(s.long), ',', '.')::float8, replace(btrim(s.lat), ',', '.')::float8), 4326), 2154) end,
                         g.category, g.dist_declared_m, p.num_acc is not null, p.method,
                         s.source_file_id, s.source_row_number
                  from staging.stg_baac_caracteristiques s
                  cross join lateral (select case when btrim(s.dep) ~ '^[0-9]$' then '0' || btrim(s.dep) else btrim(s.dep) end dep_code) d
                  join ref.commune_code_harmonisation h on h.com_original = btrim(s.com)
                  join tmp_com_at_date t on t.com = btrim(s.com)
                       and t.d = make_date(btrim(s.an)::int, btrim(s.mois)::int, btrim(s.jour)::int)
                  join ref.geo_validation_phase1c g on g.num_acc = clean.f_id(s.num_acc)
                  left join ref.coordinate_correction_proposal p on p.num_acc = g.num_acc
                  left join ref.obsolete_code_mapping_phase1d p1d on p1d.num_acc = g.num_acc) x""", (run,))
            print("accident:", cur.rowcount)

            # ---- accident_location
            cur.execute(f"""
                insert into clean.accident_location (num_acc, segment_seq, n_segments_in_accident, catr, voie_original, v1, v2,
                    circ, nbv, vosp, prof, pr, pr1, plan, lartpc, larrout, surf, infra, situ, vma, vma_plausible,
                    source_file_id, source_row_number, load_run_id)
                select clean.f_id(s.num_acc),
                       row_number() over w, count(*) over (partition by clean.f_id(s.num_acc)),
                       {code('catr', 'accident_location')}, s.voie, clean.f_int(s.v1)::smallint, clean.f_txt(s.v2),
                       {code('circ', 'accident_location')}, {code('nbv', 'accident_location')}, {code('vosp', 'accident_location')},
                       {code('prof', 'accident_location')},
                       case when clean.f_int(s.pr) >= 0 then clean.f_int(s.pr) end,
                       case when clean.f_int(s.pr1) >= 0 then clean.f_int(s.pr1) end,
                       {code('plan', 'accident_location')},
                       round(clean.f_num(s.lartpc), 2), round(clean.f_num(s.larrout), 2),
                       {code('surf', 'accident_location')}, {code('infra', 'accident_location')}, {code('situ', 'accident_location')},
                       clean.f_int(s.vma)::smallint,
                       case when clean.f_int(s.vma) is null then null else clean.f_int(s.vma) in {VMA_STANDARD} end,
                       s.source_file_id, s.source_row_number, %s
                from staging.stg_baac_lieux s
                window w as (partition by clean.f_id(s.num_acc) order by s.source_file_id, s.source_row_number)""", (run,))
            print("accident_location:", cur.rowcount)

            # ---- vehicle
            cur.execute(f"""
                insert into clean.vehicle (id_vehicule, num_acc, num_veh, senc, catv, obs, obsm, choc, manv, motor, occutc,
                                           source_file_id, source_row_number, load_run_id)
                select clean.f_id(s.id_vehicule)::integer, clean.f_id(s.num_acc), btrim(s.num_veh),
                       {code('senc', 'vehicle')}, {code('catv', 'vehicle')}, {code('obs', 'vehicle')}, {code('obsm', 'vehicle')},
                       {code('choc', 'vehicle')}, {code('manv', 'vehicle')}, {code('motor', 'vehicle')},
                       clean.f_int(s.occutc)::smallint, s.source_file_id, s.source_row_number, %s
                from staging.stg_baac_vehicules s""", (run,))
            print("vehicle:", cur.rowcount)

            # ---- road_user
            cur.execute(f"""
                insert into clean.road_user (id_usager, num_acc, id_vehicule, num_veh, place, catu, grav, severity_rank, is_victim,
                    sexe, an_nais, age_at_accident, an_nais_placeholder, trajet, secu1, secu2, secu3, locp, actp, etatp,
                    is_fugitive_like, source_file_id, source_row_number, load_run_id)
                select case when s.id_usager is not null then clean.f_id(s.id_usager)::integer end,
                       clean.f_id(s.num_acc), clean.f_id(s.id_vehicule)::integer, btrim(s.num_veh),
                       {code('place', 'road_user')}, {code('catu', 'road_user')}, g.grav,
                       case g.grav when 1 then 0 when 4 then 1 when 3 then 2 when 2 then 3 end,
                       case when g.grav is null then null else g.grav in (2, 3, 4) end,
                       {code('sexe', 'road_user')}, a.an_nais, case when a.an_nais not in (1900, 1901)
                           then (s.source_year - a.an_nais)::smallint end,
                       coalesce(a.an_nais in (1900, 1901), false),
                       nullif({code('trajet', 'road_user')}, 0),                -- G4: trajet 0 = not recorded
                       {code('secu1', 'road_user')}, {code('secu2', 'road_user')}, {code('secu3', 'road_user')},
                       {code('locp', 'road_user')},
                       case when clean.f_txt(s.actp) in {ACTP_ALLOWED} then clean.f_txt(s.actp) end,
                       {code('etatp', 'road_user')},
                       s.source_year >= 2021 and {code('sexe', 'road_user')} is null and a.an_nais is null,
                       s.source_file_id, s.source_row_number, %s
                from staging.stg_baac_usagers s
                cross join lateral (select {code('grav', 'road_user')} grav) g
                cross join lateral (select clean.f_int(s.an_nais)::smallint an_nais) a""", (run,))
            print("road_user:", cur.rowcount)

            cur.execute("""update clean.vehicle v set n_users = u.n, has_no_user = (u.n = 0)
                           from (select v2.id_vehicule, count(r.road_user_id) n from clean.vehicle v2
                                 left join clean.road_user r on r.id_vehicule = v2.id_vehicule group by 1) u
                           where u.id_vehicule = v.id_vehicule""")

            # ---- E6c dq_issue
            n_issue = 0
            for entity, cols in CODES.items():
                for col in cols:
                    stg = STAGING[entity]
                    clean_t = f"clean.{entity}"
                    cur.execute(f"""
                        insert into clean.dq_issue (entity, entity_key, num_acc, column_name, issue_code, original_value,
                                                    treatment, source_file_id, source_row_number, load_run_id)
                        select '{entity}', {KEY[entity]}, c.num_acc, '{col}',
                               case when btrim(s."{col}") like '#%%' then 'ERROR_TOKEN' else 'UNDOCUMENTED_CODE' end,
                               s."{col}", 'set_null', s.source_file_id, s.source_row_number, %s
                        from {stg} s join {clean_t} c using (source_file_id, source_row_number)
                        where clean.f_undocumented(s."{col}", {arr(cols[col])})
                           or (btrim(s."{col}") like '#%%')""", (run,))
                    n_issue += cur.rowcount
            extra = [
                ("road_user", "actp", "UNDOCUMENTED_CODE", "set_null",
                 f"clean.f_txt(s.actp) is not null and clean.f_txt(s.actp) not in {ACTP_ALLOWED}"),
                ("road_user", "an_nais", "AN_NAIS_PLACEHOLDER", "kept_flagged", "clean.f_int(s.an_nais) in (1900, 1901)"),
                ("accident_location", "vma", "IMPLAUSIBLE_VMA", "kept_flagged",
                 f"clean.f_int(s.vma) is not null and clean.f_int(s.vma) not in {VMA_STANDARD}"),
                ("accident_location", "pr", "NEGATIVE_VALUE", "set_null", "clean.f_int(s.pr) < 0"),
                ("accident_location", "pr1", "NEGATIVE_VALUE", "set_null", "clean.f_int(s.pr1) < 0"),
                ("vehicle", "num_veh", "NUM_VEH_ODD", "kept_flagged", "btrim(s.num_veh) !~ '^[A-Z]{1,2}[0-9]{2}$'"),
            ]
            for entity, col, issue, treat, cond in extra:
                cur.execute(f"""
                    insert into clean.dq_issue (entity, entity_key, num_acc, column_name, issue_code, original_value,
                                                treatment, source_file_id, source_row_number, load_run_id)
                    select '{entity}', {KEY[entity]}, c.num_acc, '{col}', '{issue}', s."{col}", '{treat}',
                           s.source_file_id, s.source_row_number, %s
                    from {STAGING[entity]} s join clean.{entity} c using (source_file_id, source_row_number)
                    where {cond}""", (run,))
                n_issue += cur.rowcount
            print("dq_issue:", n_issue)
            cur.execute("update meta.load_run set status='succeeded', finished_at=now() where load_run_id=%s", (run,))
        conn.commit()
    with psycopg.connect(**conninfo(), autocommit=True) as conn:
        conn.execute("analyze clean.accident; analyze clean.accident_location; analyze clean.vehicle; "
                     "analyze clean.road_user; analyze clean.dq_issue")
    print("committed and analysed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
