"""Point-in-polygon validation of BAAC accident coordinates (metropolitan France,
2019-2025) against IGN ADMIN EXPRESS COG commune and department boundaries.

- Each BAAC year is validated against the ADMIN EXPRESS COG edition of that year.
- Original BAAC values are never modified; corrections are written to a
  separate table with the original values preserved.
- All distances are computed in Lambert-93 (EPSG:2154).

Categories (evaluated in this order):
  placeholder_invalid     coordinate missing / unparsable / zero / both integral
  valid                   point lies in the declared commune
  nearby_commune          point outside declared commune but <= 500 m from it
  swapped                 lat/long interchanged: swapped point is in (or <= 500 m
                          from) the declared commune
  outside_coverage        point not inside any metropolitan commune polygon
  wrong_commune_same_dep  point in another commune of the declared department
  wrong_department        point in a commune of another department
Out-of-scope (not validated): accidents declared outside metropolitan France.
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import points

warnings.filterwarnings("ignore", category=RuntimeWarning)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "baac"
GEO = ROOT / "data" / "raw" / "geography" / "admin_express_cog" / "extracted"
OUT = ROOT / "reports" / "geography" / "tables"
OUT.mkdir(parents=True, exist_ok=True)
YEARS = range(2019, 2026)
L93 = 2154
NEAR_M = 500
METRO = {f"{i:02d}" for i in range(1, 96) if i != 20} | {"2A", "2B"}


# ------------------------------------------------------------------ loaders
def load_baac(year: int) -> pd.DataFrame:
    f = next(p for p in (RAW / str(year)).glob("*.csv") if p.name.lower().startswith(("caract", "carct")))
    df = pd.read_csv(f, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    df.columns = [re.sub(r"\s+", "", c) for c in df.columns]
    df = df.rename(columns={"Accident_Id": "Num_Acc"})
    out = pd.DataFrame({
        "year": year,
        "Num_Acc": df["Num_Acc"].str.replace(r"\s", "", regex=True),
        "dep_raw": df["dep"], "com_raw": df["com"], "lat_raw": df["lat"], "long_raw": df["long"],
    })
    dep = out["dep_raw"].str.strip()
    out["dep"] = dep.where(~dep.str.fullmatch(r"\d"), "0" + dep)        # 2019: '1' -> '01'
    out["com"] = out["com_raw"].str.strip()
    # Paris / Lyon / Marseille municipal arrondissements -> commune code used by ADMIN EXPRESS COMMUNE
    out["com_norm"] = (out["com"].str.replace(r"^751\d\d$", "75056", regex=True)
                       .str.replace(r"^6938\d$", "69123", regex=True)
                       .str.replace(r"^132\d\d$", "13055", regex=True))
    out["lat"] = pd.to_numeric(out["lat_raw"].str.strip().str.replace(",", "."), errors="coerce")
    out["lon"] = pd.to_numeric(out["long_raw"].str.strip().str.replace(",", "."), errors="coerce")
    return out


def load_layers(year: int):
    d = GEO / str(year)
    if year == 2025:
        g = next(d.glob("*.gpkg"))
        com = gpd.read_file(g, layer="commune", columns=["code_insee", "code_insee_du_departement"])
        com = com.rename(columns={"code_insee": "com_code", "code_insee_du_departement": "com_dep"})
        dep = gpd.read_file(g, layer="departement", columns=["code_insee"]).rename(columns={"code_insee": "dep_code"})
    else:
        com = gpd.read_file(d / "COMMUNE.shp", columns=["INSEE_COM", "INSEE_DEP"])
        com = com.rename(columns={"INSEE_COM": "com_code", "INSEE_DEP": "com_dep"})
        dep = gpd.read_file(d / "DEPARTEMENT.shp", columns=["INSEE_DEP"]).rename(columns={"INSEE_DEP": "dep_code"})
    com, dep = com.to_crs(L93), dep.to_crs(L93)
    meta = {"year": year, "communes_total": len(com), "departements_total": len(dep),
            "invalid_commune_geoms": int((~com.is_valid).sum()), "invalid_dep_geoms": int((~dep.is_valid).sum())}
    com["geometry"] = com.make_valid()
    dep["geometry"] = dep.make_valid()
    com = com[com["com_dep"].isin(METRO)].reset_index(drop=True)
    dep = dep[dep["dep_code"].isin(METRO)].reset_index(drop=True)
    meta.update({"metro_communes": len(com), "metro_departements": len(dep),
                 "duplicate_commune_codes": int(com["com_code"].duplicated().sum())})
    return com, dep, meta


def to_l93(lon: pd.Series, lat: pd.Series, index) -> gpd.GeoSeries:
    return gpd.GeoSeries(points(lon.to_numpy(), lat.to_numpy()), index=index, crs=4326).to_crs(L93)


def locate(pts: gpd.GeoSeries, com: gpd.GeoDataFrame, dep: gpd.GeoDataFrame) -> pd.DataFrame:
    g = gpd.GeoDataFrame(geometry=pts)
    jc = gpd.sjoin(g, com[["com_code", "com_dep", "geometry"]], how="left", predicate="within")
    jc = jc[~jc.index.duplicated()]
    jd = gpd.sjoin(g, dep[["dep_code", "geometry"]], how="left", predicate="within")
    jd = jd[~jd.index.duplicated()]
    return pd.DataFrame({"com_point": jc["com_code"], "com_point_dep": jc["com_dep"], "dep_point": jd["dep_code"]})


# ------------------------------------------------------------------ main
all_rows, metas, code_checks = [], [], []
layers = {y: load_layers(y) for y in YEARS}
# code -> geometry lookup across all editions (latest edition wins) for codes absent from the year's edition
any_edition = {}
for y in YEARS:
    c = layers[y][0]
    any_edition.update(dict(zip(c["com_code"], c.geometry)))

for year in YEARS:
    com, dep, meta = layers[year]
    metas.append(meta)
    a = load_baac(year)
    a["in_scope"] = a["dep"].isin(METRO)
    m = a[a["in_scope"]].copy()

    # ---- placeholder / invalid
    has = m["lat"].notna() & m["lon"].notna()
    zero = (m["lat"] == 0) | (m["lon"] == 0)
    out_range = ~(m["lat"].between(-90, 90) & m["lon"].between(-180, 180))
    integral = has & (m["lat"] % 1 == 0) & (m["lon"] % 1 == 0)
    m["placeholder_reason"] = np.select(
        [~has, zero, out_range, integral], ["missing_or_unparsable", "zero", "out_of_range", "both_integral"], "")
    ok = m["placeholder_reason"] == ""

    # ---- locate original point
    pts = to_l93(m.loc[ok, "lon"], m.loc[ok, "lat"], m.index[ok])
    loc = locate(pts, com, dep)
    m = m.join(loc)

    # ---- declared commune geometry (edition of the year, else any edition)
    edition = dict(zip(com["com_code"], com.geometry))
    m["declared_in_edition"] = m["com_norm"].isin(edition.keys())
    m["declared_in_any_edition"] = m["com_norm"].isin(any_edition.keys())
    decl_geom = gpd.GeoSeries([edition.get(c, any_edition.get(c)) for c in m["com_norm"]], index=m.index, crs=L93)
    m["dist_declared_m"] = np.nan
    has_decl = ok & decl_geom.notna()
    m.loc[has_decl, "dist_declared_m"] = pts[has_decl[has_decl].index].distance(decl_geom[has_decl]).round(1)

    # ---- alternative hypotheses (swap, longitude sign) for non-matching points
    m["swap_dist_declared_m"] = np.nan
    m["lonsign_dist_declared_m"] = np.nan
    cand = has & decl_geom.notna() & ~(m["placeholder_reason"].isin(["missing_or_unparsable"]))
    cand &= ~(m["com_point"] == m["com_norm"])
    if cand.any():
        sw = to_l93(m.loc[cand, "lat"], m.loc[cand, "lon"], m.index[cand])          # lon<-lat, lat<-lon
        m.loc[cand, "swap_dist_declared_m"] = sw.distance(decl_geom[cand]).round(1)
        sg = to_l93(-m.loc[cand, "lon"], m.loc[cand, "lat"], m.index[cand])
        m.loc[cand, "lonsign_dist_declared_m"] = sg.distance(decl_geom[cand]).round(1)

    # ---- classification
    cat = np.select(
        [~ok,
         m["com_point"] == m["com_norm"],
         ~m["declared_in_any_edition"] & (m["com_point_dep"] == m["dep"]),
         m["dist_declared_m"] <= NEAR_M,
         m["swap_dist_declared_m"] <= NEAR_M,
         m["com_point"].isna(),
         m["com_point_dep"] == m["dep"]],
        ["placeholder_invalid", "valid", "commune_code_unresolved", "nearby_commune", "swapped",
         "outside_coverage", "wrong_commune_same_dep"],
        "wrong_department")
    m["category"] = cat
    # a 'valid' via an older/newer edition polygon (code absent from year edition) is still recorded
    m.loc[(m["category"] != "valid") & ~m["declared_in_edition"] & (m["dist_declared_m"] == 0), "category"] = "valid"
    m["dep_layer_vs_commune_dep_mismatch"] = m["dep_point"].notna() & m["com_point_dep"].notna() & (m["dep_point"] != m["com_point_dep"])
    m["lonsign_would_match"] = m["lonsign_dist_declared_m"] <= NEAR_M
    all_rows.append(pd.concat([m, a[~a["in_scope"]].assign(category="out_of_scope_non_metro")]))

    code_checks.append({"year": year, "metro_accidents": len(m),
                        "declared_com_not_in_year_edition": int((~m["declared_in_edition"]).sum()),
                        "declared_com_not_in_any_edition": int((~m["declared_in_any_edition"]).sum()),
                        "examples_not_in_edition": "; ".join(m.loc[~m["declared_in_edition"], "com"].value_counts().head(8).index)})
    print(f"{year}: {m['category'].value_counts().to_dict()}", flush=True)

R = pd.concat(all_rows, ignore_index=True)
cols = ["year", "Num_Acc", "dep_raw", "com_raw", "dep", "com", "com_norm", "lat_raw", "long_raw", "lat", "lon",
        "category", "placeholder_reason", "com_point", "com_point_dep", "dep_point", "dist_declared_m",
        "swap_dist_declared_m", "lonsign_dist_declared_m", "lonsign_would_match",
        "declared_in_edition", "declared_in_any_edition", "dep_layer_vs_commune_dep_mismatch"]
R[cols].to_csv(OUT / "geo_validation_accidents.csv.gz", index=False, compression="gzip")
pd.DataFrame(metas).to_csv(OUT / "00_reference_layers.csv", index=False)
pd.DataFrame(code_checks).to_csv(OUT / "01_commune_code_vintage.csv", index=False)

CATS = ["valid", "nearby_commune", "wrong_commune_same_dep", "wrong_department", "swapped",
        "placeholder_invalid", "outside_coverage", "commune_code_unresolved"]
M = R[R["category"] != "out_of_scope_non_metro"]
by_year = pd.crosstab(M["year"], M["category"]).reindex(columns=CATS, fill_value=0)
by_year["total"] = by_year.sum(axis=1)
by_year["pct_valid"] = (100 * by_year["valid"] / by_year["total"]).round(3)
by_year["pct_valid_or_nearby"] = (100 * (by_year["valid"] + by_year["nearby_commune"]) / by_year["total"]).round(3)
by_year["out_of_scope_non_metro"] = R[R["category"] == "out_of_scope_non_metro"].groupby("year").size()
by_year.to_csv(OUT / "02_results_by_year.csv")

by_dep = pd.crosstab(M["dep"], M["category"]).reindex(columns=CATS, fill_value=0)
by_dep["total"] = by_dep.sum(axis=1)
by_dep["pct_valid"] = (100 * by_dep["valid"] / by_dep["total"]).round(2)
by_dep["pct_problem"] = (100 * by_dep[CATS[2:7]].sum(axis=1) / by_dep["total"]).round(3)
by_dep.sort_values("pct_valid").to_csv(OUT / "03_results_by_department.csv")
pd.crosstab([M["year"], M["dep"]], M["category"]).reindex(columns=CATS, fill_value=0).to_csv(OUT / "03b_results_by_year_department.csv")

anom = M[M["category"].isin(CATS[2:])].sort_values(["category", "year", "Num_Acc"])
anom[cols].to_csv(OUT / "04_anomalies.csv", index=False)

# distance distribution for mismatches
dist = M[M["category"].isin(["nearby_commune", "wrong_commune_same_dep", "wrong_department"])]
dd = dist.groupby("category")["dist_declared_m"].describe(percentiles=[.5, .9, .99]).round(0)
dd.to_csv(OUT / "05_mismatch_distance_m.csv")
bins = [0, 500, 1000, 2000, 5000, 10000, 50000, np.inf]
wc = M[M["category"].isin(["wrong_commune_same_dep", "wrong_department"])]
pd.cut(wc["dist_declared_m"], bins).value_counts().sort_index().to_csv(OUT / "05b_wrong_commune_distance_bins.csv")

# documented corrections (swapped only) - originals preserved
sw = M[M["category"] == "swapped"]
corr_sw = pd.DataFrame({"year": sw["year"], "Num_Acc": sw["Num_Acc"], "dep": sw["dep"], "com": sw["com"],
                        "category": sw["category"],
                        "lat_original": sw["lat_raw"], "long_original": sw["long_raw"],
                        "lat_corrected": sw["lon"], "long_corrected": sw["lat"],
                        "method": "swap_lat_long",
                        "evidence_distance_to_declared_commune_m": sw["swap_dist_declared_m"]})
# longitude sign error: only for points classified as errors (not valid/nearby) whose sign-flipped
# point falls inside the declared commune (distance 0 m)
ls = M[M["category"].isin(["wrong_commune_same_dep", "wrong_department", "outside_coverage"])
       & (M["lonsign_dist_declared_m"] == 0)]
corr_ls = pd.DataFrame({"year": ls["year"], "Num_Acc": ls["Num_Acc"], "dep": ls["dep"], "com": ls["com"],
                        "category": ls["category"],
                        "lat_original": ls["lat_raw"], "long_original": ls["long_raw"],
                        "lat_corrected": ls["lat"], "long_corrected": -ls["lon"],
                        "method": "flip_longitude_sign",
                        "evidence_distance_to_declared_commune_m": ls["lonsign_dist_declared_m"]})
corr = pd.concat([corr_sw, corr_ls], ignore_index=True)
corr["status"] = "proposed - not applied to any data"
corr.to_csv(OUT / "06_coordinate_corrections.csv", index=False)

# previously identified cases
known = ["201900033874", "202400008235", "202400011273", "202400013466", "202500038525", "202400025734",
         "202400005348", "202400018639", "202400037079", "201900008746", "201900033236", "202000008466"]
R[R["Num_Acc"].isin(known)][cols].to_csv(OUT / "07_known_cases.csv", index=False)

pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 80)
print("\nREFERENCE\n", pd.DataFrame(metas).to_string(index=False))
print("\nCODES\n", pd.DataFrame(code_checks).to_string(index=False))
print("\nBY YEAR\n", by_year.to_string())
print("\nWORST DEPARTMENTS (pct_problem)\n", by_dep.sort_values("pct_problem", ascending=False).head(12).to_string())
print("\nDISTANCES\n", dd.to_string())
print("\nKNOWN CASES\n", R[R["Num_Acc"].isin(known)][["Num_Acc", "dep", "com", "lat_raw", "long_raw", "category",
                                                       "com_point", "dist_declared_m", "swap_dist_declared_m", "lonsign_dist_declared_m"]].to_string(index=False))
print("\nCORRECTIONS\n", corr.to_string(index=False))
dupc = M[M["category"].isin(CATS[2:7])].groupby(["lat_raw", "long_raw"]).size()
print("\nanomalous points sharing identical raw coordinates:", int(dupc[dupc > 1].sum()))
wcd = M[M["category"] == "wrong_department"]["dist_declared_m"]
print("wrong_department within 3 km of declared commune:", int((wcd <= 3000).sum()), "/", len(wcd))
print("\nOTHER FLAGS: dep layer vs commune dep mismatch =", int(M["dep_layer_vs_commune_dep_mismatch"].sum()),
      "| lonsign_would_match among anomalies =", int(anom["lonsign_would_match"].sum()),
      "| placeholder reasons:", M["placeholder_reason"].value_counts().to_dict())
