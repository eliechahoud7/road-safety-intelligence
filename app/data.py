"""Read-only data access for the dashboard.

* Reuses scripts/db_config.py (credentials from environment / .env — never hard-coded).
* Every connection is opened with default_transaction_read_only=on and conn.read_only = True.
* Queries return small aggregated frames (aggregation happens in PostgreSQL); results are cached by Streamlit.
* Sources: analytics.accident_fact / road_user_fact / agg_year_* / hotspot_point, ref.ign_* (edition 2025),
  ref.methodological_break, and the Phase 5 hotspot CSV.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import psycopg
import streamlit as st
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db_config import conninfo  # noqa: E402

PHASE5 = ROOT / "reports" / "phase5" / "tables"
TO_WGS84 = Transformer.from_crs(2154, 4326, always_xy=True)


def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run one read-only query and return a DataFrame."""
    with psycopg.connect(**conninfo(), options="-c default_transaction_read_only=on", connect_timeout=10) as conn:
        conn.read_only = True
        cur = conn.execute(sql, params or {})
        return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])


def _where(years: tuple, dep: str | None, alias: str = "") -> str:
    a = f"{alias}." if alias else ""
    w = f"{a}year = any(%(years)s)"
    return w + (f" and {a}dep_code = %(dep)s" if dep else "")


def _p(years, dep) -> dict:
    return {"years": list(years), "dep": dep}


# ------------------------------------------------------------------ reference lists
@st.cache_data(ttl=3600)
def departments() -> pd.DataFrame:
    return query("select insee_dep dep_code, departement_name name from ref.ign_departement "
                 "where edition_year = 2025 order by insee_dep")


@st.cache_data(ttl=3600)
def methodological_breaks() -> pd.DataFrame:
    return query("select break_code, effective_from, effective_to, description, recommended_treatment "
                 "from ref.methodological_break order by effective_from nulls last, break_code")


# ------------------------------------------------------------------ overview / temporal
@st.cache_data(ttl=3600)
def kpis(years: tuple, dep: str | None) -> pd.Series:
    return query(f"""select count(*) accidents, count(*) filter (where accident_severity = 'fatal') fatal_accidents,
                            coalesce(sum(n_killed), 0) killed, coalesce(sum(n_hospitalised), 0) hospitalised,
                            coalesce(sum(n_light), 0) light, coalesce(sum(n_unhurt), 0) unhurt,
                            coalesce(sum(n_vehicles), 0) vehicles
                     from analytics.accident_fact where {_where(years, dep)}""", _p(years, dep)).iloc[0]


@st.cache_data(ttl=3600)
def by_year(years: tuple, dep: str | None) -> pd.DataFrame:
    return query(f"""select year, count(*) accidents, count(*) filter (where accident_severity = 'fatal') fatal_accidents,
                            sum(n_killed) killed, sum(n_hospitalised) hospitalised, sum(n_light) light
                     from analytics.accident_fact where {_where(years, dep)} group by 1 order by 1""", _p(years, dep))


@st.cache_data(ttl=3600)
def by_column(column: str, years: tuple, dep: str | None) -> pd.DataFrame:
    """Accidents and fatal accidents by one accident_fact column (whitelisted)."""
    expr = {"month": "month", "weekday": "weekday", "hour": "hour", "is_weekend": "is_weekend",
            "accident_severity": "accident_severity", "atm": "atm", "lum": "lum", "agg": "agg",
            "catr": "case when catr = 7 then 4 else catr end"}[column]
    return query(f"""select {expr} as value, count(*) accidents, count(*) filter (where accident_severity = 'fatal') fatal,
                            count(distinct acc_date) days
                     from analytics.accident_fact where {_where(years, dep)} group by 1 order by 1""", _p(years, dep))


@st.cache_data(ttl=3600)
def month_by_year(years: tuple, dep: str | None) -> pd.DataFrame:
    return query(f"select year, month, count(*) accidents from analytics.accident_fact where {_where(years, dep)} "
                 "group by 1, 2 order by 1, 2", _p(years, dep))


# ------------------------------------------------------------------ road users
@st.cache_data(ttl=3600)
def users(years: tuple, dep: str | None) -> pd.DataFrame:
    """Road users (fugitive-like and unknown severity excluded) aggregated by category, sex, age group, mode, grav."""
    return query(f"""select catu, sexe, age_group, grav,
                            case when catu = 3 then 'Pedestrian' when catv = 1 then 'Bicycle' when catv = 80 then 'E-bike'
                                 when catv in (50, 60) then 'Personal mobility device'
                                 when catv in (2,30,31,32,33,34,41,42,43) then 'Powered 2/3-wheeler'
                                 when catv = 7 then 'Car' when catv = 10 then 'Light commercial'
                                 when catv between 13 and 17 then 'Heavy goods' when catv in (37, 38) then 'Bus / coach'
                                 else 'Other / unknown' end as mode,
                            count(*) n
                     from analytics.road_user_fact
                     where {_where(years, dep)} and not is_fugitive_like and grav is not null
                     group by 1, 2, 3, 4, 5""", _p(years, dep))


# ------------------------------------------------------------------ geography
@st.cache_data(ttl=3600)
def department_geojson() -> dict:
    df = query("""select insee_dep id, departement_name name,
                         st_asgeojson(st_transform(st_simplifypreservetopology(geom, 500), 4326), 5) g
                  from ref.ign_departement where edition_year = 2025""")
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": r.id, "properties": {"name": r.name}, "geometry": json.loads(r.g)} for r in df.itertuples()]}


@st.cache_data(ttl=3600)
def department_stats(years: tuple) -> pd.DataFrame:
    return query("""select dep_code, sum(n_accidents) accidents, sum(n_fatal_accidents) fatal_accidents,
                           sum(n_killed) killed, sum(n_hospitalised) hospitalised, count(distinct year) n_years
                    from analytics.agg_year_department where year = any(%(years)s) group by 1""", {"years": list(years)})


@st.cache_data(ttl=3600)
def commune_geojson(dep: str) -> dict:
    df = query("""select insee_com id, commune_name name,
                         st_asgeojson(st_transform(st_simplifypreservetopology(geom, 100), 4326), 5) g
                  from ref.ign_commune where edition_year = 2025 and commune_type = 'COM' and insee_dep = %(dep)s""",
               {"dep": dep})
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": r.id, "properties": {"name": r.name}, "geometry": json.loads(r.g)} for r in df.itertuples()]}


@st.cache_data(ttl=3600)
def commune_stats(years: tuple, dep: str) -> pd.DataFrame:
    return query("""select c.insee_com com, c.commune_name name, coalesce(sum(a.n_accidents), 0) accidents,
                           coalesce(sum(a.n_fatal_accidents), 0) fatal_accidents, coalesce(sum(a.n_killed), 0) killed
                    from ref.ign_commune c
                    left join analytics.agg_year_commune a on a.com_cog_2026 = c.insee_com and a.year = any(%(years)s)
                    where c.edition_year = 2025 and c.commune_type = 'COM' and c.insee_dep = %(dep)s
                    group by 1, 2""", {"years": list(years), "dep": dep})


@st.cache_data(ttl=3600)
def grid_cells(years: tuple, dep: str | None, bbox: tuple | None = None) -> pd.DataFrame:
    """1 km Lambert-93 cells of the default hotspot population (Phase 5 method), centre in WGS84 for display."""
    where = "year = any(%(years)s)" + (" and dep_code = %(dep)s" if dep else "")
    params = {"years": list(years), "dep": dep}
    if bbox:
        where += " and st_x(geom) between %(x0)s and %(x1)s and st_y(geom) between %(y0)s and %(y1)s"
        params.update(dict(zip(("x0", "y0", "x1", "y1"), bbox)))
    df = query(f"""select floor(st_x(geom)/1000)::int gx, floor(st_y(geom)/1000)::int gy, count(*) accidents,
                          count(*) filter (where accident_severity = 'fatal') fatal,
                          mode() within group (order by com_cog_2026) com
                   from analytics.hotspot_point where {where} group by 1, 2""", params)
    if df.empty:
        return df.assign(lon=[], lat=[])
    df["lon"], df["lat"] = TO_WGS84.transform(df.gx * 1000 + 500, df.gy * 1000 + 500)
    return df


@st.cache_data(ttl=3600)
def national_top1pct_threshold(years: tuple) -> float:
    return float(query("""select percentile_cont(0.99) within group (order by n) t from (
                            select count(*) n from analytics.hotspot_point where year = any(%(years)s)
                            group by floor(st_x(geom)/1000), floor(st_y(geom)/1000)) c""", {"years": list(years)}).t[0])


@st.cache_data(ttl=3600)
def commune_names() -> pd.Series:
    return query("select insee_com com, commune_name name from ref.ign_commune "
                 "where edition_year = 2025 and commune_type = 'COM'").set_index("com").name


@st.cache_data(ttl=3600)
def phase5_hotspots() -> pd.DataFrame:
    """Top-1 % cells 2019–2025 with persistence (Phase 5 output, reused as is)."""
    df = pd.read_csv(PHASE5 / "03_hotspot_cells_top1pct.csv", dtype={"com": str})
    df["lon"], df["lat"] = TO_WGS84.transform(df.gx * 1000 + 500, df.gy * 1000 + 500)
    return df
