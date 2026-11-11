"""Phase 5 — geospatial analysis & accident hotspots (metropolitan France, 2019–2025). Read-only.

Inputs : analytics.accident_fact, analytics.hotspot_point, analytics.agg_year_department / agg_year_commune,
         ref.ign_departement / ref.ign_commune (edition 2025 = COG 2026, commune_type = 'COM').
         Legal population per commune is read (context only, never as a denominator) from the IGN 2025
         GeoPackage already in data/raw (no new dataset).
Method : one spatial method — a regular 1 km x 1 km grid in Lambert-93 (EPSG:2154) over the default hotspot
         population; high-concentration cells = top 1 % of non-empty cells (2019–2025 total); persistence =
         number of normal years (2019, 2021–2025) in which a cell is in that year's top 1 %.
         Departments and communes are aggregated by code (all metropolitan accidents).
Outputs: reports/phase5/tables/*.csv, reports/phase5/figures/*.png (4 maps).
Concentration of recorded injury accidents only — NOT risk (no traffic-volume data).
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
import pyogrio
import shapely
from matplotlib.colors import LogNorm
from matplotlib.patches import Rectangle
from scipy.stats import spearmanr

from db_config import conninfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "phase5"
FIG, TAB = OUT / "figures", OUT / "tables"
FIG.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)
CELL = 1000                       # metres (EPSG:2154)
NORMAL_YEARS = [2019, 2021, 2022, 2023, 2024, 2025]
ZOOMS = {"Paris & inner suburbs": (652_000, 6_862_000), "Lyon": (842_000, 6_519_000), "Marseille": (893_000, 6_247_000)}
HALF = 25_000                     # zoom window half-width (m)


def wilson(k, n, z=1.96):
    k, n = np.asarray(k, float), np.asarray(n, float)
    p = k / n
    d = 1 + z ** 2 / n
    c = (p + z ** 2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / d
    return p, c - h, c + h


def main() -> int:
    with psycopg.connect(**conninfo()) as conn:
        conn.read_only = True

        def query(sql):
            cur = conn.execute(sql)
            return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])

        def geoquery(sql):
            df = query(sql)
            return gpd.GeoDataFrame(df.drop(columns="wkb"), geometry=shapely.from_wkb(df["wkb"].map(bytes)), crs=2154)

        dep = query("""select dep_code, sum(n_accidents) acc, sum(n_fatal_accidents) fatal, sum(n_killed) killed,
                              sum(n_hospitalised) hosp, sum(n_users) users, sum(n_vehicles) veh
                       from analytics.agg_year_department group by 1""").astype({c: int for c in ("acc", "fatal", "killed", "hosp", "users", "veh")})
        dep_year = query("select year, dep_code, n_accidents from analytics.agg_year_department")
        com_year = query("select year, com_cog_2026, n_accidents, n_fatal_accidents, n_killed from analytics.agg_year_commune")
        grid = query(f"""select floor(st_x(geom)/{CELL})::int gx, floor(st_y(geom)/{CELL})::int gy, year,
                                count(*) n, count(*) filter (where accident_severity = 'fatal') fatal,
                                mode() within group (order by com_cog_2026) com
                         from analytics.hotspot_point group by 1, 2, 3""")
        checks = query("""select (select count(*) from analytics.accident_fact) acc_fact,
                                 (select sum(n_killed) from analytics.accident_fact) killed_fact,
                                 (select count(*) from analytics.accident_fact where in_default_hotspot_population) eligible,
                                 (select count(*) from analytics.hotspot_point) hp,
                                 (select count(*) from analytics.hotspot_point where spatial_eligibility not in
                                    ('eligible_exact','eligible_tolerance','eligible_after_code_harmonisation')) hp_not_eligible,
                                 (select count(*) from analytics.hotspot_point h join analytics.accident_fact f using (num_acc)
                                    where f.spatial_eligibility = 'review_wrong_commune') hp_wrong_commune,
                                 (select count(*) from analytics.hotspot_point where st_srid(geom) <> 2154) hp_bad_srid,
                                 (select count(*) - count(distinct num_acc) from analytics.hotspot_point) hp_dup,
                                 (select count(*) from analytics.accident_fact where has_correction_proposal
                                    and in_default_hotspot_population) corrected_in_default""").iloc[0]
        dep_geo = geoquery("""select insee_dep dep_code, departement_name name,
                                     st_asbinary(st_simplifypreservetopology(geom, 500)) wkb
                              from ref.ign_departement where edition_year = 2025""")
        com_geo = geoquery("""select insee_com com, commune_name name, insee_dep dep, round((st_area(geom)/1e6)::numeric, 2) area_km2,
                                     st_asbinary(st_simplifypreservetopology(geom, 250)) wkb
                              from ref.ign_commune where edition_year = 2025 and commune_type = 'COM'""")
    gpkg = next((ROOT / "data/raw/geography/admin_express_cog/extracted/2025").glob("*.gpkg"))
    pop = pyogrio.read_dataframe(gpkg, layer="commune", columns=["code_insee", "population"], read_geometry=False) \
                 .rename(columns={"code_insee": "com"}).set_index("com").population

    # ------------------------------------------------------------ A. departments
    dep["acc_per_year"] = (dep.acc / 7).round(0)
    dep["fatal_share"], dep["fatal_ci_low"], dep["fatal_ci_high"] = wilson(dep.fatal, dep.acc)
    dep["killed_per_100_acc"] = (100 * dep.killed / dep.acc).round(2)
    dep = dep.merge(dep_geo[["dep_code", "name"]], on="dep_code", how="left")
    dep.sort_values("acc", ascending=False).drop(columns=[]).to_csv(TAB / "01_departments.csv", index=False)
    top_dep = dep.nlargest(10, "acc")
    top_dep_fatal_share = dep[dep.acc >= 1000].nlargest(10, "fatal_share")
    share_top10 = top_dep.acc.sum() / dep.acc.sum()

    # ------------------------------------------------------------ B. communes
    cy = com_year.pivot_table(index="com_cog_2026", columns="year", values="n_accidents", aggfunc="sum", fill_value=0)
    cy["total"] = cy.sum(axis=1)
    ranks = cy[list(range(2019, 2026))].rank(ascending=False, method="min")
    cy["years_in_top20"] = (ranks <= 20).sum(axis=1)
    fat = com_year.groupby("com_cog_2026")[["n_fatal_accidents", "n_killed"]].sum()
    com = cy.join(fat).join(com_geo.set_index("com")[["name", "dep", "area_km2"]]).join(pop)
    com = com.reset_index().rename(columns={"com_cog_2026": "com"}).sort_values("total", ascending=False)
    com.to_csv(TAB / "02_communes.csv", index=False)
    top_com = com.head(20)
    consistent = com[com.years_in_top20 == 7]
    # distribution comparison across years
    years_cmp = {}
    for y in (2019, 2022, 2025):
        s = cy[y].sort_values(ascending=False)
        years_cmp[y] = {"communes_with_accident": int((s > 0).sum()),
                        "share_in_top_1pct_communes": round(float(s.head(int(len(com_geo) * 0.01)).sum() / s.sum()), 3)}
    rho_com = spearmanr(cy[2019], cy[2025]).statistic
    dpy = dep_year.pivot(index="dep_code", columns="year", values="n_accidents")
    rho_dep = spearmanr(dpy[2019], dpy[2025]).statistic
    dep_change = ((dpy[2025] / dpy[2019] - 1) * 100).round(1)

    # ------------------------------------------------------------ C. hotspots (1 km grid, default population)
    tot = grid.groupby(["gx", "gy"]).agg(n=("n", "sum"), fatal=("fatal", "sum")).reset_index()
    com_mode = grid.sort_values("n", ascending=False).drop_duplicates(["gx", "gy"]).set_index(["gx", "gy"]).com
    tot = tot.join(com_mode, on=["gx", "gy"])
    thr = tot.n.quantile(0.99)
    tot["hot"] = tot.n >= thr
    per_year = grid.pivot_table(index=["gx", "gy"], columns="year", values="n", aggfunc="sum", fill_value=0)
    year_thr = {y: per_year.loc[per_year[y] > 0, y].quantile(0.99) for y in NORMAL_YEARS}
    persist = sum((per_year[y] >= year_thr[y]).astype(int) for y in NORMAL_YEARS).rename("years_top1pct")
    tot = tot.join(persist, on=["gx", "gy"])
    names = com_geo.set_index("com").name
    tot["commune"] = tot.com.map(names)
    tot["x_km"], tot["y_km"] = tot.gx, tot.gy
    hot = tot[tot.hot].sort_values("n", ascending=False)
    hot.to_csv(TAB / "03_hotspot_cells_top1pct.csv", index=False)
    hot_by_com = hot.groupby(["com", "commune"]).agg(cells=("n", "size"), accidents=("n", "sum")).reset_index() \
                    .sort_values("accidents", ascending=False)
    hot_by_com.to_csv(TAB / "04_hotspot_cells_by_commune.csv", index=False)
    fatal_cells = tot.nlargest(15, "fatal")
    fatal_cells.to_csv(TAB / "05_fatal_concentration_cells.csv", index=False)

    # ------------------------------------------------------------ figures
    dep_map = dep_geo.merge(dep, on="dep_code")
    xmin, ymin, xmax, ymax = dep_geo.total_bounds

    # F1 national distribution (1 km grid raster) + department boundaries
    gx0, gy0 = int(xmin // CELL), int(ymin // CELL)
    W, H = int(xmax // CELL) - gx0 + 1, int(ymax // CELL) - gy0 + 1
    R = np.full((H, W), np.nan)
    R[tot.gy - gy0, tot.gx - gx0] = tot.n
    fig, ax = plt.subplots(figsize=(9, 9))
    im = ax.imshow(R, origin="lower", extent=(gx0 * CELL, (gx0 + W) * CELL, gy0 * CELL, (gy0 + H) * CELL),
                   cmap="inferno_r", norm=LogNorm(vmin=1, vmax=tot.n.max()), interpolation="nearest")
    dep_geo.boundary.plot(ax=ax, color="#777", lw=.3)
    ax.set_axis_off(); fig.colorbar(im, ax=ax, shrink=.6, label="accidents per 1 km² cell, 2019–2025 (log scale)")
    n_hp = f"{int(checks.hp):,}".replace(",", " ")
    ax.set_title(f"Injury accidents per 1 km cell, metropolitan France 2019–2025\n"
                 f"default hotspot population: {n_hp} accidents · EPSG:2154 · concentration, not risk", fontsize=11)
    fig.tight_layout(); fig.savefig(FIG / "fig1_national_distribution_1km.png", dpi=170); plt.close(fig)

    # F2 departments: counts vs fatal share
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 7.5))
    dep_map.plot(column="acc_per_year", ax=a1, cmap="Blues", legend=True, edgecolor="#555", lw=.3,
                 norm=LogNorm(vmin=dep_map.acc_per_year.min(), vmax=dep_map.acc_per_year.max()),
                 legend_kwds={"label": "accidents per year (2019–2025 mean, log scale)", "shrink": .6})
    a1.set_title("Accident concentration (count)", fontsize=11); a1.set_axis_off()
    dep_map.assign(fs=100 * dep_map.fatal_share).plot(column="fs", ax=a2, cmap="OrRd", legend=True, edgecolor="#555", lw=.3,
                                                      legend_kwds={"label": "fatal accidents (% of accidents)", "shrink": .6})
    a2.set_title("Severity (share of accidents that are fatal)", fontsize=11); a2.set_axis_off()
    fig.suptitle("Departments, 2019–2025: where accidents are numerous is not where they are most often fatal", fontsize=12)
    fig.tight_layout(); fig.savefig(FIG / "fig2_departments_count_vs_severity.png", dpi=150); plt.close(fig)

    # F3 communes: total accidents (COG 2026)
    cm = com_geo.merge(com[["com", "total"]], on="com", how="left")
    fig, ax = plt.subplots(figsize=(9, 9))
    cm[cm.total.isna() | (cm.total == 0)].plot(ax=ax, color="#f2f2f2", lw=0)
    cm[cm.total > 0].plot(column="total", ax=ax, cmap="viridis_r", norm=LogNorm(vmin=1, vmax=cm.total.max()), lw=0, legend=True,
                          legend_kwds={"label": "accidents 2019–2025 per commune (log scale)", "shrink": .6})
    dep_geo.boundary.plot(ax=ax, color="#555", lw=.3)
    ax.set_axis_off()
    ax.set_title("Injury accidents per commune (COG 2026), 2019–2025\ngrey: no recorded accident · large communes accumulate more accidents", fontsize=11)
    fig.tight_layout(); fig.savefig(FIG / "fig3_communes.png", dpi=170); plt.close(fig)

    # F4 hotspot zooms: 1 km cells, top-1 % cells outlined
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.8))
    for ax, (label, (cx, cy0)) in zip(axes, ZOOMS.items()):
        sub = tot[(tot.gx * CELL).between(cx - HALF, cx + HALF) & (tot.gy * CELL).between(cy0 - HALF, cy0 + HALF)]
        sc = ax.scatter(sub.gx * CELL + CELL / 2, sub.gy * CELL + CELL / 2, c=sub.n, cmap="inferno_r", marker="s", s=14,
                        norm=LogNorm(vmin=1, vmax=tot.n.max()), linewidths=0)
        for r in sub[sub.hot].itertuples():
            ax.add_patch(Rectangle((r.gx * CELL, r.gy * CELL), CELL, CELL, fill=False, ec="#00a3a3", lw=.5))
        com_geo.cx[cx - HALF:cx + HALF, cy0 - HALF:cy0 + HALF].boundary.plot(ax=ax, color="#bbb", lw=.25)
        ax.set_xlim(cx - HALF, cx + HALF); ax.set_ylim(cy0 - HALF, cy0 + HALF); ax.set_aspect("equal"); ax.set_axis_off()
        ax.set_title(f"{label}: {int(sub.hot.sum())} top-1 % cells", fontsize=11)
    fig.colorbar(sc, ax=axes, shrink=.7, label="accidents per 1 km cell 2019–2025 (log)")
    fig.suptitle(f"Hotspots: 1 km cells in the national top 1 % (≥ {int(thr)} accidents, teal outline), 50 km windows", fontsize=12)
    fig.savefig(FIG / "fig4_hotspot_zooms.png", dpi=150, bbox_inches="tight"); plt.close(fig)

    # ------------------------------------------------------------ validation
    recon = {
        "departments: Σ accidents = accident_fact": (int(dep.acc.sum()), int(checks.acc_fact)),
        "departments: Σ killed = accident_fact": (int(dep.killed.sum()), int(checks.killed_fact)),
        "communes: Σ accidents (incl. N/C group) = accident_fact": (int(cy.total.sum() + com_year[com_year.com_cog_2026.isna()].n_accidents.sum()), int(checks.acc_fact)),
        "communes: Σ accidents = departments Σ": (int(com_year.n_accidents.sum()), int(dep.acc.sum())),
        "grid: Σ accidents = hotspot_point = eligible in accident_fact": (int(tot.n.sum()), int(checks.hp), int(checks.eligible)),
        "hotspot_point: non-eligible / wrong-commune / corrected rows": (int(checks.hp_not_eligible), int(checks.hp_wrong_commune), int(checks.corrected_in_default), 0),
        "hotspot_point: SRID != 2154 / duplicate num_acc": (int(checks.hp_bad_srid), int(checks.hp_dup), 0),
        "96 departments mapped": (len(dep_map), 96),
    }
    ok = all(len(set(v)) == 1 for v in recon.values())
    pd.DataFrame([{"check": k, "values": v, "status": "pass" if len(set(v)) == 1 else "FAIL"} for k, v in recon.items()]) \
      .to_csv(TAB / "00_validation.csv", index=False)

    # ------------------------------------------------------------ console summary
    pd.set_option("display.width", 230, "display.max_columns", 30)
    print("VALIDATION:", "PASS" if ok else "FAIL")
    for k, v in recon.items():
        print(f"  {k}: {v}")
    print(f"\nTop-10 departments ({share_top10:.1%} of accidents):\n",
          top_dep.assign(fatal_pct=lambda d: (100 * d.fatal_share).round(2))[["dep_code", "name", "acc", "acc_per_year", "killed",
                                                                              "killed_per_100_acc", "fatal_pct"]].to_string(index=False))
    print("\nTop-10 fatal share (departments with >= 1000 accidents):\n",
          top_dep_fatal_share.assign(fatal_pct=lambda d: (100 * d.fatal_share).round(1), lo=lambda d: (100 * d.fatal_ci_low).round(1),
                                     hi=lambda d: (100 * d.fatal_ci_high).round(1))[["dep_code", "name", "acc", "fatal", "fatal_pct", "lo", "hi"]]
          .to_string(index=False))
    print("\nLowest fatal share:\n", dep.nsmallest(5, "fatal_share").assign(fatal_pct=lambda d: (100 * d.fatal_share).round(2))[
        ["dep_code", "name", "acc", "fatal_pct"]].to_string(index=False))
    print("\nTop-20 communes:\n", top_com[["com", "name", "dep", "population", "area_km2", "total", 2019, 2020, 2025, "years_in_top20", "n_killed"]].to_string(index=False))
    print("\nConsistently top-20 all 7 years:", len(consistent), list(consistent.name))
    print("distribution by year:", years_cmp, "| Spearman 2019 vs 2025: communes", round(rho_com, 3), "departments", round(rho_dep, 3))
    print("department change 2019->2025 %: median", dep_change.median(), "min", dep_change.idxmin(), dep_change.min(), "max", dep_change.idxmax(), dep_change.max())
    print(f"\nGRID: non-empty cells {len(tot):,}; top-1% threshold >= {thr} accidents; hot cells {int(tot.hot.sum())} "
          f"holding {hot.n.sum():,} accidents ({hot.n.sum() / tot.n.sum():.1%}); persistent in all 6 normal years: {(hot.years_top1pct == 6).sum()}")
    print("hot cells by commune (top 12):\n", hot_by_com.head(12).to_string(index=False))
    print("hottest cells:\n", hot.head(10)[["x_km", "y_km", "n", "fatal", "commune", "years_top1pct"]].to_string(index=False))
    print("fatal concentration cells:\n", fatal_cells[["x_km", "y_km", "fatal", "n", "commune", "hot"]].to_string(index=False))
    print("cells with >=1 fatal accident:", int((tot.fatal > 0).sum()), "| share of fatal accidents in hot cells:",
          round(hot.fatal.sum() / tot.fatal.sum(), 3), "| share of all accidents in hot cells:", round(hot.n.sum() / tot.n.sum(), 3))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
