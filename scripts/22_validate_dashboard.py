"""Phase 6 — essential dashboard validation (no database writes).

D1 every section renders without exception (Streamlit AppTest), default filters and with filters (2020 only; dep 75)
D2 dashboard totals = analytical layer (accidents, killed, injured, fatal accidents)
D3 filters change the totals consistently (2020 only; department 75)
D4 maps: 96 department polygons; commune totals for a department = department total; grid = eligible hotspot points
D5 read-only: a write attempt through the dashboard connection is rejected
D6 no database modification: insert/update/delete counters unchanged before vs after
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
warnings.filterwarnings("ignore")
import logging
logging.getLogger("streamlit").setLevel(logging.ERROR)

from streamlit.testing.v1 import AppTest  # noqa: E402

import data  # noqa: E402
from db_config import conninfo  # noqa: E402

results = []


def check(name, ok, detail):
    results.append((name, ok, detail))


def write_counters():
    with psycopg.connect(**conninfo()) as c:
        return c.execute("select sum(n_tup_ins + n_tup_upd + n_tup_del) from pg_stat_user_tables").fetchone()[0]


def main() -> int:
    before = write_counters()
    ALL = tuple(range(2019, 2026))

    # D1 ------------------------------------------------------------------
    pages = ["National overview", "Temporal analysis", "Severity & road users", "Environmental conditions",
             "Geospatial analysis", "Hotspot explorer"]
    for scenario, years, dep in (("default", None, None), ("year 2020 only", [2020], None), ("department 75", None, "75 – Paris")):
        at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=300).run()
        if years:
            at.sidebar.multiselect[0].set_value(years).run()
        if dep:
            at.sidebar.selectbox[0].set_value(dep).run()
        errors = []
        for p in pages:
            at.sidebar.radio[0].set_value(p).run()
            if at.exception:
                errors.append(f"{p}: {at.exception[0].message[:120]}")
        check(f"D1_SECTIONS_RENDER [{scenario}]", not errors, errors or f"{len(pages)} sections OK")
        if scenario == "default":
            at.sidebar.radio[0].set_value("National overview").run()
            shown = {m.label: m.value for m in at.metric}
            check("D2_KPI_WIDGETS_PRESENT", len(shown) == 4, shown)

    # D2 / D3 ---------------------------------------------------------------
    ref = data.query("""select count(*) acc, sum(n_killed) killed, sum(n_hospitalised + n_light) injured,
                               count(*) filter (where accident_severity = 'fatal') fatal from analytics.accident_fact""").iloc[0]
    k = data.kpis(ALL, None)
    check("D2_TOTALS_MATCH_ANALYTICS", (k.accidents, k.killed, k.hospitalised + k.light, k.fatal_accidents) ==
          (ref.acc, ref.killed, ref.injured, ref.fatal) == (361593, 21619, 453388, 20384),
          f"accidents {k.accidents}, killed {k.killed}, injured {k.hospitalised + k.light}, fatal {k.fatal_accidents}")
    y = data.by_year(ALL, None)
    check("D2_ANNUAL_SUM", int(y.accidents.sum()) == 361593 and int(y.killed.sum()) == 21619, f"{int(y.accidents.sum())} / {int(y.killed.sum())}")
    k20, k75 = data.kpis((2020,), None), data.kpis(ALL, "75")
    check("D3_YEAR_FILTER", (k20.accidents, k20.killed) == (45121, 2541), f"2020: {k20.accidents} accidents, {k20.killed} killed")
    check("D3_DEPARTMENT_FILTER", (k75.accidents, k75.killed) == (33111, 258), f"Paris: {k75.accidents} accidents, {k75.killed} killed")
    u = data.users(ALL, None)
    exp_u = data.query("select count(*) n from analytics.road_user_fact where not is_fugitive_like and grav is not null").n[0]
    check("D2_USER_CHART_POPULATION", int(u.n.sum()) == exp_u == 809407, f"{int(u.n.sum())} users (fugitive-like / unknown excluded)")
    for col in ("month", "weekday", "hour", "atm", "lum", "agg", "catr", "accident_severity"):
        s = int(data.by_column(col, ALL, None).accidents.sum())
        check(f"D2_NO_DOUBLE_COUNT[{col}]", s == 361593, s)

    # D4 ------------------------------------------------------------------
    gj = data.department_geojson()
    check("D4_DEPARTMENT_POLYGONS", len(gj["features"]) == 96, len(gj["features"]))
    ds = data.department_stats(ALL)
    check("D4_DEPARTMENT_MAP_TOTAL", int(ds.accidents.sum()) == 361593, int(ds.accidents.sum()))
    c13 = int(data.commune_stats(ALL, "13").accidents.sum())
    d13 = int(ds.set_index("dep_code").accidents["13"])
    check("D4_COMMUNE_VS_DEPARTMENT[13]", c13 == d13, f"communes {c13} vs department {d13}")
    g = data.grid_cells(ALL, None)
    check("D4_GRID_ELIGIBLE_ONLY", int(g.accidents.sum()) == 360934, f"{int(g.accidents.sum())} accidents in 1 km cells (eligible population)")
    check("D4_GRID_WGS84_IN_FRANCE", g.lon.between(-5.5, 9.8).all() and g.lat.between(41.2, 51.2).all(), "cell centres within metropolitan bbox")
    hp = data.phase5_hotspots()
    check("D4_PHASE5_HOTSPOTS", len(hp) == 897 and int((hp.years_top1pct == 6).sum()) == 132, f"{len(hp)} cells, {(hp.years_top1pct == 6).sum()} persistent")

    # D5 ------------------------------------------------------------------
    try:
        data.query("create table analytics.should_not_exist (x int)")
        check("D5_READ_ONLY", False, "write accepted!")
    except psycopg.errors.ReadOnlySqlTransaction as e:
        check("D5_READ_ONLY", True, f"rejected: {type(e).__name__}")

    # D6 ------------------------------------------------------------------
    after = write_counters()
    check("D6_NO_DB_MODIFICATION", before == after, f"tuple write counter before={before} after={after}")

    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<38} {detail}")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
