"""Phase 3 Step 3 — load reference data into PostgreSQL/PostGIS (one transaction).

  E0  verify IGN archives + INSEE files against their manifests (SHA-256); hash Phase 1C/1D evidence files
  DDL db/sql/030_ref_reference_data.sql
  E1  register sources in meta.source_file (IGN, INSEE, PROJECT_DERIVED)
  E3  INSEE COG 2026 -> staging (text, untouched) -> ref.insee_cog_event / ref.insee_commune_period (typed)
  E4  IGN ADMIN EXPRESS COG 2019–2025 (metropolitan) -> ref.ign_commune / ref.ign_departement
      geometries sent as EWKB in their native CRS; PostGIS does ST_Transform -> 2154, ST_MakeValid,
      polygon extraction and ST_Multi. Invalid inputs are flagged (geom_was_invalid).
  E5  ref.commune_code_harmonisation for EVERY distinct BAAC commune code (all years, all territories)
  E6  Phase 1C validation, 11 proposed corrections (status 'proposed', NOT applied), Phase 1D accident mapping

Only psycopg is used for database access (no SQLAlchemy / GeoAlchemy2 needed).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import psycopg
import shapely

from db_config import conninfo, safe_description

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "data" / "raw" / "geography"
EXTR = GEO / "admin_express_cog" / "extracted"
SQL = ROOT / "db" / "sql" / "030_ref_reference_data.sql"
TAB = ROOT / "reports" / "geography" / "tables"
DERIVED = {
    "geo_validation_phase1c": (TAB / "geo_validation_accidents.csv.gz", "scripts/05_validate_geography.py"),
    "coordinate_correction_proposal": (TAB / "06_coordinate_corrections.csv", "scripts/05_validate_geography.py"),
    "obsolete_code_mapping_phase1d": (TAB / "11_obsolete_code_accidents_mapped.csv", "scripts/07_map_obsolete_communes.py"),
}
METRO = {f"{i:02d}" for i in range(1, 96) if i != 20} | {"2A", "2B"}
OVERSEAS_COLLECTIVITY_PREFIXES = ("975", "977", "978", "986", "987", "988")
ARM_PARENT = (("751", "75056"), ("6938", "69123"), ("132", "13055"))
CLASS_BY_MOD = {31: "merger", 32: "merger", 33: "merger", 34: "merger", 41: "code_change_one_to_one",
                50: "code_change_one_to_one"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def nz(v):
    """'' -> None (typed reference columns only; staging keeps '')."""
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or v == "" else v


def to_bool(v):
    v = nz(v)
    return None if v is None else {"True": True, "False": False}[v]


def register(cur, system, entity, year, path: Path, url, size, digest, licence, producer, published, retrieved):
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    cur.execute("""
        insert into meta.source_file (source_system, entity, reference_year, file_path, file_name, source_url, bytes,
            sha256, licence, producer, published_or_edition_date, retrieved_at)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (file_path) do update set source_url=excluded.source_url, bytes=excluded.bytes,
            sha256=excluded.sha256, licence=excluded.licence, producer=excluded.producer,
            published_or_edition_date=excluded.published_or_edition_date, retrieved_at=excluded.retrieved_at,
            registered_at=now()
        returning source_file_id""",
        (system, entity, year, rel, path.name, url, size, digest, licence, producer, published, retrieved))
    return cur.fetchone()[0]


# ------------------------------------------------------------------ IGN
def read_layer(year: int, layer: str) -> gpd.GeoDataFrame:
    d = EXTR / str(year)
    if year == 2025:
        g = gpd.read_file(next(d.glob("*.gpkg")), layer=layer.lower())
        if layer == "COMMUNE":
            g = g.rename(columns={"code_insee": "code", "code_insee_du_departement": "dep", "nom_officiel": "name"})
        else:
            g = g.rename(columns={"code_insee": "code", "nom_officiel": "name"})
            g["dep"] = g["code"]
        srid = 2154
    else:
        g = gpd.read_file(d / f"{layer}.shp")
        if layer == "COMMUNE":
            g = g.rename(columns={"INSEE_COM": "code", "INSEE_DEP": "dep", "NOM_COM": "name", "NOM": "name"})
        else:
            g = g.rename(columns={"INSEE_DEP": "code", "NOM_DEP": "name", "NOM": "name"})
            g["dep"] = g["code"]
        crs = g.crs.to_string()
        if g.crs.to_epsg() == 4326:
            srid = 4326
        elif "Lambert 93" in g.crs.name or "LAMB93" in crs:          # IGNF:LAMB93 == EPSG:2154 definition
            srid = 2154
        else:
            raise RuntimeError(f"{year} {layer}: unexpected CRS {crs}")
    # source TYPE field (2019/2020 editions only): 'COM' or 'ARM' (municipal arrondissement)
    g["ctype"] = g["TYPE"] if "TYPE" in g.columns else "COM"
    g = g[g["dep"].isin(METRO)][["code", "dep", "name", "ctype", "geometry"]].copy()
    g.attrs["srid"] = srid
    return g


def load_ign(cur, year: int, layer: str, source_file_id: int) -> int:
    g = read_layer(year, layer)
    srid = g.attrs["srid"]
    geoms = shapely.set_srid(g.geometry.values, srid)
    ewkb = shapely.to_wkb(geoms, hex=True, include_srid=True)
    cur.execute("create temp table if not exists tmp_ign (code text, dep text, name text, ctype text, g geometry) on commit drop")
    cur.execute("truncate tmp_ign")
    with cur.copy("copy tmp_ign (code, dep, name, ctype, g) from stdin") as cp:
        for code, dep, name, ctype, wkb in zip(g["code"], g["dep"], g["name"], g["ctype"], ewkb):
            cp.write_row((code, dep, name, ctype, wkb))
    table = "ref.ign_commune" if layer == "COMMUNE" else "ref.ign_departement"
    cur.execute(f"delete from {table} where edition_year = %s", (year,))
    if layer == "COMMUNE":
        cur.execute("""
            insert into ref.ign_commune (edition_year, insee_com, insee_dep, commune_name, commune_type, geom,
                                         geom_was_invalid, source_file_id)
            select %s, code, dep, name, ctype,
                   st_multi(st_collectionextract(st_makevalid(t2154), 3)), not st_isvalid(t2154), %s
            from (select code, dep, name, ctype, st_transform(g, 2154) t2154 from tmp_ign) s""", (year, source_file_id))
    else:
        cur.execute("""
            insert into ref.ign_departement (edition_year, insee_dep, departement_name, geom, geom_was_invalid, source_file_id)
            select %s, code, name,
                   st_multi(st_collectionextract(st_makevalid(t2154), 3)), not st_isvalid(t2154), %s
            from (select code, name, st_transform(g, 2154) t2154 from tmp_ign) s""", (year, source_file_id))
    return len(g)


# ------------------------------------------------------------------ INSEE
def load_insee_staging(cur, path: Path, table: str, fid: int, run_id: int) -> int:
    recs = list(csv.reader(io.StringIO(path.read_bytes().decode("utf-8"), newline="")))
    header, body = recs[0], [r for r in recs[1:] if r != []]
    cols = [h.strip().lower() for h in header]
    cur.execute(f"delete from {table} where source_file_id = %s", (fid,))
    with cur.copy(f"copy {table} (source_file_id, source_row_number, load_run_id, {', '.join(cols)}) from stdin") as cp:
        for n, r in enumerate(body, start=1):
            cp.write_row((fid, n, run_id, *r))
    return len(body)


# ------------------------------------------------------------------ harmonisation
def build_harmonisation(cur) -> list[tuple]:
    cur.execute("select typecom, com, date_debut, date_fin from ref.insee_commune_period")
    periods = pd.DataFrame(cur.fetchall(), columns=["typecom", "com", "debut", "fin"])
    com_p = periods[periods.typecom == "COM"]
    end = com_p.assign(fin=com_p.fin.fillna(pd.Timestamp("9999-12-31").date())).groupby("com").fin.max()
    active_com = set(com_p[com_p.fin.isna()].com)
    active_arm = set(periods[(periods.typecom == "ARM") & periods.fin.isna()].com)
    cur.execute("select mod, date_eff, typecom_av, com_av, typecom_ap, com_ap from ref.insee_cog_event")
    ev = pd.DataFrame(cur.fetchall(), columns=["mod", "date_eff", "tav", "cav", "tap", "cap"])
    succ = ev[(ev.tav == "COM") & (ev.tap == "COM") & (ev.cav != ev.cap)]
    deleg = ev[(ev.cav == ev.cap) & ev.tap.isin(["COMD", "COMA"])].groupby("cav").tap.agg(lambda s: "/".join(sorted(set(s))))

    cur.execute("""select btrim(com), count(*), string_agg(distinct source_year::text, '|' order by source_year::text)
                   from staging.stg_baac_caracteristiques group by btrim(com)""")
    rows = []
    for code, n_acc, years in cur.fetchall():
        rec = dict(com_original=code, arm_parent_com=None, com_cog_2026=None, first_mod=None, n_steps=0, chain=None,
                   obsolete_since=None, became=deleg.get(code), n=n_acc, years=years)
        if code in active_com:
            rec.update(status="active_com", cls="identity", com_cog_2026=code)
        elif code in active_arm:
            parent = next(p for pre, p in ARM_PARENT if code.startswith(pre))
            assert parent in active_com, (code, parent)
            rec.update(status="active_arm", cls="arrondissement_to_commune", arm_parent_com=parent, com_cog_2026=parent)
        elif code in end.index:
            path, mods, cur_code = [code], [], code
            rec["obsolete_since"] = end[code]
            status = None
            for _ in range(10):
                e = end.get(cur_code)
                if e is None:
                    status = "unresolved"; break
                if cur_code in active_com:
                    status = "obsolete_resolved"; break
                nxt = e + pd.Timedelta(days=1)
                s = succ[(succ.cav == cur_code) & succ.date_eff.isin([e, nxt.date() if hasattr(nxt, "date") else nxt])]
                targets = sorted(set(s.cap))
                if len(targets) != 1:
                    status = "unresolved"; break           # none or ambiguous: never guessed
                mods.append(int(s["mod"].iloc[0]))
                cur_code = targets[0]
                path.append(cur_code)
            if status == "obsolete_resolved":
                cls = "merger_chain" if len(mods) > 1 else CLASS_BY_MOD.get(mods[0], f"mod_{mods[0]}")
                rec.update(status=status, cls=cls, com_cog_2026=cur_code, first_mod=mods[0], n_steps=len(mods),
                           chain=" -> ".join(path))
            else:
                rec.update(status="unresolved", cls="unresolved", chain=" -> ".join(path), n_steps=len(mods))
        elif code.startswith(OVERSEAS_COLLECTIVITY_PREFIXES):
            rec.update(status="out_of_cog_scope", cls="out_of_scope")
        else:
            rec.update(status="unresolved", cls="unresolved")
        if rec["cls"].startswith("mod_"):
            raise RuntimeError(f"unexpected INSEE MOD for {code}: {rec}")
        rows.append((rec["com_original"], rec["status"], rec["arm_parent_com"], rec["com_cog_2026"], rec["cls"],
                     rec["first_mod"], rec["n_steps"], rec["chain"], rec["obsolete_since"], rec["became"],
                     rec["n"], rec["years"]))
    return rows


# ------------------------------------------------------------------ main
def main() -> int:
    ign_man = list(csv.DictReader((GEO / "_manifest.csv").open(encoding="utf-8")))
    insee_man = list(csv.DictReader((GEO / "insee_cog" / "_manifest.csv").open(encoding="utf-8")))
    for r in ign_man:
        if sha256(ROOT / r["archive"]) != r["sha256"]:
            sys.exit(f"ABORT E0: {r['archive']} SHA-256 mismatch")
    for r in insee_man:
        if sha256(ROOT / r["file"]) != r["sha256"]:
            sys.exit(f"ABORT E0: {r['file']} SHA-256 mismatch")
    print(f"E0 raw integrity: {len(ign_man)} IGN archives + {len(insee_man)} INSEE files match manifests")

    fp = hashlib.sha256(Path(__file__).read_bytes() + SQL.read_bytes()).hexdigest()
    print("Connecting to", safe_description())
    with psycopg.connect(**conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL.read_text(encoding="utf-8"))
            cur.execute("insert into meta.load_run (step, code_fingerprint, parameters) values ('reference_data', %s, %s) "
                        "returning load_run_id", (fp, json.dumps({"ign_editions": "2019-2025", "insee": "COG 2026"})))
            run_id = cur.fetchone()[0]
            print("load_run_id =", run_id)

            # ---- E1 sources
            ign_fid = {}
            for r in ign_man:
                ign_fid[int(r["baac_year"])] = register(
                    cur, "IGN", "admin_express_cog", int(r["baac_year"]), ROOT / r["archive"], r["url"], int(r["bytes"]),
                    r["sha256"], r["licence"], r["producer"], r["edition_date"], r["retrieved_at"])
            insee_fid = {}
            for r in insee_man:
                p = ROOT / r["file"]
                insee_fid[p.name] = register(cur, "INSEE", p.stem, 2026, p, r["url"], int(r["bytes"]), r["sha256"],
                                             r["licence"], r["producer"], r["data_gouv_last_modified"], r["retrieved_at"])
            der_fid = {}
            for name, (p, producer_script) in DERIVED.items():
                der_fid[name] = register(
                    cur, "PROJECT_DERIVED", name, None, p, f"project://{producer_script}", p.stat().st_size, sha256(p),
                    "derived from Licence Ouverte sources (BAAC, IGN, INSEE)", f"Road Safety Intelligence project ({producer_script})",
                    None, datetime.fromtimestamp(p.stat().st_mtime, timezone.utc))

            # ---- E3 INSEE
            mvt = GEO / "insee_cog" / "2026" / "v_mvt_commune_2026.csv"
            per = GEO / "insee_cog" / "2026" / "v_commune_depuis_1943.csv"
            n_mvt = load_insee_staging(cur, mvt, "staging.stg_insee_mvt_commune", insee_fid[mvt.name], run_id)
            n_per = load_insee_staging(cur, per, "staging.stg_insee_commune_period", insee_fid[per.name], run_id)
            cur.execute("delete from ref.insee_cog_event; delete from ref.insee_commune_period;")
            cur.execute("""
                insert into ref.insee_cog_event (mod, date_eff, typecom_av, com_av, libelle_av, typecom_ap, com_ap,
                                                 libelle_ap, source_file_id, source_row_number)
                select mod::smallint, date_eff::date, nullif(typecom_av, ''), com_av, nullif(libelle_av, ''),
                       nullif(typecom_ap, ''), com_ap, nullif(libelle_ap, ''), source_file_id, source_row_number
                from staging.stg_insee_mvt_commune order by source_row_number""")
            cur.execute("""
                insert into ref.insee_commune_period (typecom, com, libelle, date_debut, date_fin, source_file_id, source_row_number)
                select typecom, com, libelle, date_debut::date, nullif(date_fin, '')::date, source_file_id, source_row_number
                from staging.stg_insee_commune_period""")
            print(f"E3 INSEE: {n_mvt:,} events, {n_per:,} commune periods")

            # ---- E4 IGN
            for year in range(2019, 2026):
                nc = load_ign(cur, year, "COMMUNE", ign_fid[year])
                nd = load_ign(cur, year, "DEPARTEMENT", ign_fid[year])
                print(f"E4 IGN {year}: {nc:,} communes, {nd} departements (metropolitan)", flush=True)

            # ---- E5 harmonisation
            rows = build_harmonisation(cur)
            cur.execute("delete from ref.commune_code_harmonisation")
            with cur.copy("""copy ref.commune_code_harmonisation (com_original, status_2026, arm_parent_com, com_cog_2026,
                             transformation_class, first_mod, n_steps, chain, obsolete_since,
                             became_delegated_or_associated, accidents_2019_2025, years_seen) from stdin""") as cp:
                for r in rows:
                    cp.write_row(r)
            print(f"E5 harmonisation: {len(rows):,} distinct BAAC commune codes")

            # ---- E6 Phase 1C / 1D results
            for t in ("obsolete_code_mapping_phase1d", "coordinate_correction_proposal", "geo_validation_phase1c"):
                cur.execute(f"delete from ref.{t}")
            g = pd.read_csv(DERIVED["geo_validation_phase1c"][0], dtype=str, keep_default_na=False)
            with cur.copy("""copy ref.geo_validation_phase1c (num_acc, year, dep_raw, com_raw, dep, com, com_norm, lat_raw,
                             long_raw, lat, lon, category, placeholder_reason, com_point, com_point_dep, dep_point,
                             dist_declared_m, swap_dist_declared_m, lonsign_dist_declared_m, lonsign_would_match,
                             declared_in_edition, declared_in_any_edition, dep_layer_vs_commune_dep_mismatch,
                             source_file_id) from stdin""") as cp:
                for r in g.itertuples(index=False):
                    cp.write_row((int(r.Num_Acc), int(r.year), r.dep_raw, r.com_raw, r.dep, r.com, nz(r.com_norm),
                                  r.lat_raw, r.long_raw, nz(r.lat), nz(r.lon), r.category, nz(r.placeholder_reason),
                                  nz(r.com_point), nz(r.com_point_dep), nz(r.dep_point), nz(r.dist_declared_m),
                                  nz(r.swap_dist_declared_m), nz(r.lonsign_dist_declared_m), to_bool(r.lonsign_would_match),
                                  to_bool(r.declared_in_edition), to_bool(r.declared_in_any_edition),
                                  to_bool(r.dep_layer_vs_commune_dep_mismatch), der_fid["geo_validation_phase1c"]))
            c = pd.read_csv(DERIVED["coordinate_correction_proposal"][0], dtype=str, keep_default_na=False)
            with cur.copy("""copy ref.coordinate_correction_proposal (num_acc, method, lat_original, long_original,
                             lat_corrected, lon_corrected, evidence_distance_to_declared_commune_m, correction_status,
                             source_file_id) from stdin""") as cp:
                for r in c.itertuples(index=False):
                    cp.write_row((int(r.Num_Acc), r.method, r.lat_original, r.long_original, r.lat_corrected,
                                  r.long_corrected, r.evidence_distance_to_declared_commune_m, "proposed",
                                  der_fid["coordinate_correction_proposal"]))
            m = pd.read_csv(DERIVED["obsolete_code_mapping_phase1d"][0], dtype=str, keep_default_na=False)
            with cur.copy("""copy ref.obsolete_code_mapping_phase1d (num_acc, year, acc_date, com_original,
                             transformation_class, is_comd_or_coma_on_accident_date, successor_at_accident_date,
                             successor_2026, status_at_accident_date, com_from_point_admin_express,
                             point_in_successor_at_date, mapping_confidence, source_file_id) from stdin""") as cp:
                for r in m.itertuples(index=False):
                    cp.write_row((int(r.Num_Acc), int(r.year), r.acc_date, r.com_original, r.transformation_class,
                                  to_bool(r.is_COMD_or_COMA_on_accident_date), nz(r.successor_at_accident_date),
                                  nz(r.successor_2026), r.status_at_accident_date, nz(r.com_from_point_admin_express),
                                  to_bool(r.point_in_successor_at_date), r.mapping_confidence,
                                  der_fid["obsolete_code_mapping_phase1d"]))
            print(f"E6 Phase 1C: {len(g):,} accidents | corrections (proposed, not applied): {len(c)} | Phase 1D: {len(m)}")
            cur.execute("update meta.load_run set status='succeeded', finished_at=now() where load_run_id=%s", (run_id,))
        conn.commit()
    with psycopg.connect(**conninfo(), autocommit=True) as conn:
        conn.execute("analyze ref.ign_commune; analyze ref.ign_departement; analyze ref.insee_cog_event; "
                     "analyze ref.insee_commune_period; analyze ref.commune_code_harmonisation; analyze ref.geo_validation_phase1c")
    print("committed and analysed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
