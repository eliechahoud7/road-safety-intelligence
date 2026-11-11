"""Map obsolete BAAC commune codes to successor communes using INSEE COG history (millésime 2026).

Input : reports/geography/tables/geo_validation_accidents.csv.gz (category commune_code_unresolved)
        data/raw/geography/insee_cog/2026/v_mvt_commune_2026.csv, v_commune_depuis_1943.csv
        data/raw/baac/<year>/caract*.csv (accident date only; read-only)
Output: reports/geography/tables/10_* .. 13_*  (original codes are never altered; derived codes in separate fields)

Rules
- A code's validity as a commune (TYPECOM = COM) comes from v_commune_depuis_1943 (DATE_DEBUT/DATE_FIN).
- Successor(s) of a code that ceased to be a COM on date D = COM_AP of the v_mvt events with
  COM_AV = code, TYPECOM_AV = COM, TYPECOM_AP = COM, COM_AP != code and DATE_EFF = D.
- Chains are followed (a successor may itself disappear later).
- Exactly one successor at each step -> deterministic mapping. More than one -> ambiguous (no mapping invented).
- Transformation type taken from the INSEE MOD code of the first step.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COG = ROOT / "data" / "raw" / "geography" / "insee_cog" / "2026"
TAB = ROOT / "reports" / "geography" / "tables"
RAW = ROOT / "data" / "raw" / "baac"

MOD_LABEL = {"10": "Changement de nom", "20": "Création", "21": "Rétablissement", "30": "Suppression",
             "31": "Fusion simple", "32": "Création de commune nouvelle", "33": "Fusion association",
             "34": "Transformation de fusion association en fusion simple", "35": "Suppression de commune déléguée",
             "41": "Changement de code dû à un changement de département",
             "50": "Changement de code dû à un transfert de chef-lieu",
             "70": "Transformation de commune associée en commune déléguée",
             "71": "Rétablissement de commune déléguée", "72": "Création de commune déléguée"}
MOD_CLASS = {"31": "merger", "32": "merger", "33": "merger", "34": "merger",
             "41": "code_change_one_to_one", "50": "code_change_one_to_one",
             "21": "split_or_restoration", "20": "split_or_restoration"}

mvt = pd.read_csv(COG / "v_mvt_commune_2026.csv", dtype=str, keep_default_na=False)
hist = pd.read_csv(COG / "v_commune_depuis_1943.csv", dtype=str, keep_default_na=False)
hist["DATE_FIN"] = hist["DATE_FIN"].replace("", "9999-12-31")


def periods(code: str, typecom: str = "COM") -> pd.DataFrame:
    return hist[(hist["COM"] == code) & (hist["TYPECOM"] == typecom)]


def valid_on(code: str, date: str, typecom: str = "COM") -> bool:
    p = periods(code, typecom)
    return bool(((p["DATE_DEBUT"] <= date) & (date < p["DATE_FIN"])).any())


def end_date(code: str) -> str | None:
    p = periods(code)
    return None if p.empty else p["DATE_FIN"].max()


def step(code: str):
    """Return (end_date, successors, mods) for the event that ended `code` as a COM."""
    d = end_date(code)
    if d is None or d == "9999-12-31":
        return d, [], []
    ev = mvt[(mvt["COM_AV"] == code) & (mvt["TYPECOM_AV"] == "COM") & (mvt["TYPECOM_AP"] == "COM")
             & (mvt["COM_AP"] != code) & (mvt["DATE_EFF"] == d)]
    if ev.empty:   # tolerate DATE_FIN convention (day before effect)
        nxt = (pd.Timestamp(d) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        ev = mvt[(mvt["COM_AV"] == code) & (mvt["TYPECOM_AV"] == "COM") & (mvt["TYPECOM_AP"] == "COM")
                 & (mvt["COM_AP"] != code) & (mvt["DATE_EFF"] == nxt)]
    return d, sorted(set(ev["COM_AP"])), sorted(set(ev["MOD"]))


def resolve(code: str, until: str):
    """Follow successors until a code valid on `until` (YYYY-MM-DD) is reached."""
    path, cur, mods = [code], code, []
    for _ in range(10):
        if valid_on(cur, until):
            return cur, path, mods, "resolved"
        d, succ, m = step(cur)
        mods.append("+".join(m) or "none")
        if d is None:
            return None, path, mods, "code_unknown_to_insee"
        if d == "9999-12-31":
            return None, path, mods, "code_active_but_not_valid_on_date"
        if len(succ) == 0:
            return None, path, mods, "no_successor_event"
        if len(succ) > 1:
            return None, path + ["{" + ",".join(succ) + "}"], mods, "ambiguous_multiple_successors"
        cur = succ[0]
        path.append(cur)
    return None, path, mods, "chain_too_long"


# ---------------------------------------------------------------- accidents
geo = pd.read_csv(TAB / "geo_validation_accidents.csv.gz", dtype=str, keep_default_na=False)
acc = geo[geo["category"] == "commune_code_unresolved"][["year", "Num_Acc", "dep", "com_raw", "com", "com_point", "lat_raw", "long_raw"]].copy()
dates = []
for y in sorted(acc["year"].unique()):
    f = next(p for p in (RAW / y).glob("*.csv") if p.name.lower().startswith(("caract", "carct")))
    c = pd.read_csv(f, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    c.columns = [re.sub(r"\s+", "", x) for x in c.columns]
    c = c.rename(columns={"Accident_Id": "Num_Acc"})
    c["Num_Acc"] = c["Num_Acc"].str.replace(r"\s", "", regex=True)
    c["acc_date"] = c["an"].str.strip() + "-" + c["mois"].str.strip().str.zfill(2) + "-" + c["jour"].str.strip().str.zfill(2)
    dates.append(c[["Num_Acc", "acc_date"]])
acc = acc.merge(pd.concat(dates), on="Num_Acc", how="left")

# ---------------------------------------------------------------- per code
rows = []
for code in sorted(acc["com"].unique()):
    a = acc[acc["com"] == code]
    first_date = a["acc_date"].min()
    p = periods(code)
    d_end, succ1, mods1 = step(code) if not p.empty else (None, [], [])
    at_date, path_d, mods_d, st_d = resolve(code, first_date)
    now, path_n, mods_n, st_n = resolve(code, "2026-01-01")
    # v_commune_depuis_1943 only lists COM/ARM -> delegated/associated status taken from v_mvt events:
    # code became COMD/COMA (same code) at an event, and that status was not suppressed (MOD 34/35)
    # on or before the first accident date.
    became = mvt[(mvt["COM_AV"] == code) & (mvt["COM_AP"] == code) & mvt["TYPECOM_AP"].isin(["COMD", "COMA"])]
    supp = mvt[(mvt["COM_AV"] == code) & mvt["TYPECOM_AV"].isin(["COMD", "COMA"]) & mvt["MOD"].isin(["34", "35"])]
    deleg_type = "/".join(sorted(set(became["TYPECOM_AP"])))
    supp_date = supp["DATE_EFF"].min() if not supp.empty else ""
    deleg_on_acc = (not became.empty) and (became["DATE_EFF"].min() <= first_date) and (supp_date == "" or supp_date > first_date)
    first_mod = mods1[0] if mods1 else ""
    if p.empty:
        cls = "unresolvable_not_in_insee_history"
    elif len(succ1) > 1:
        cls = "split_or_complex"
    elif len(succ1) == 0:
        cls = "unresolvable_no_successor"
    else:
        cls = MOD_CLASS.get(first_mod, f"other_mod_{first_mod}")
    rows.append({
        "com_original": code, "accidents": len(a), "years": "|".join(sorted(a["year"].unique())),
        "insee_name_last": p.sort_values("DATE_FIN")["LIBELLE"].iloc[-1] if not p.empty else "",
        "com_valid_as_COM_until": d_end or "",
        "first_accident_date": first_date,
        "years_obsolete_at_first_accident": round((pd.Timestamp(first_date) - pd.Timestamp(d_end)).days / 365.25, 2) if d_end and d_end != "9999-12-31" else "",
        "insee_mod": "+".join(mods1), "insee_mod_label": " + ".join(MOD_LABEL.get(m, m) for m in mods1),
        "transformation_class": cls,
        "became_delegated_or_associated": deleg_type,
        "delegated_status_suppressed_on": supp_date,
        "is_COMD_or_COMA_on_accident_date": deleg_on_acc,
        "successor_at_accident_date": at_date or "", "status_at_accident_date": st_d,
        "successor_2026": now or "", "status_2026": st_n,
        "chain": " -> ".join(path_n), "chain_mods": " -> ".join(mods_n),
    })
codes = pd.DataFrame(rows)
codes.to_csv(TAB / "10_obsolete_code_mapping.csv", index=False)

# ---------------------------------------------------------------- per accident (original code kept)
m = acc.merge(codes[["com_original", "transformation_class", "successor_at_accident_date", "status_at_accident_date",
                     "successor_2026", "status_2026", "is_COMD_or_COMA_on_accident_date"]],
              left_on="com", right_on="com_original", how="left")
# point-based check of the derived successor (ADMIN EXPRESS edition of the accident year)
m["point_in_successor_at_date"] = (m["successor_at_accident_date"] != "") & (m["com_point"] == m["successor_at_accident_date"])
m["mapping_confidence"] = "none"
det = m["status_at_accident_date"] == "resolved"
m.loc[det & m["point_in_successor_at_date"], "mapping_confidence"] = "high (INSEE deterministic + point agrees)"
m.loc[det & ~m["point_in_successor_at_date"], "mapping_confidence"] = "medium (INSEE deterministic, point disagrees)"
out = m[["year", "Num_Acc", "acc_date", "dep", "com_raw", "com_original", "transformation_class",
         "is_COMD_or_COMA_on_accident_date", "successor_at_accident_date", "successor_2026",
         "status_at_accident_date", "com_point", "point_in_successor_at_date", "mapping_confidence"]]
out = out.rename(columns={"com_point": "com_from_point_admin_express"})
out.to_csv(TAB / "11_obsolete_code_accidents_mapped.csv", index=False)

# ---------------------------------------------------------------- summaries
s1 = out.groupby("transformation_class").agg(accidents=("Num_Acc", "size"))
s1["codes"] = codes.groupby("transformation_class").size()
s2 = pd.crosstab(out["year"], out["transformation_class"], margins=True)
s3 = pd.crosstab(out["transformation_class"], out["mapping_confidence"], margins=True)
s1.to_csv(TAB / "12_mapping_summary_by_class.csv")
s2.to_csv(TAB / "12b_mapping_by_year.csv")
s3.to_csv(TAB / "12c_mapping_confidence.csv")

# disagreement detail: distance from the accident point to the successor polygon (edition of the year)
import geopandas as gpd
from shapely import points as _pts
geo_xy = geo[["Num_Acc", "lat", "lon"]]
dis = out[out["mapping_confidence"].str.startswith("medium")].merge(geo_xy, on="Num_Acc").copy()
dis["dist_point_to_successor_m"] = float("nan")
for y, grp in dis.groupby("year"):
    d = ROOT / "data" / "raw" / "geography" / "admin_express_cog" / "extracted" / y
    if int(y) == 2025:
        com = gpd.read_file(next(d.glob("*.gpkg")), layer="commune", columns=["code_insee"]).rename(columns={"code_insee": "INSEE_COM"})
    else:
        com = gpd.read_file(d / "COMMUNE.shp", columns=["INSEE_COM"])
    com = com.to_crs(2154).set_index("INSEE_COM")
    pts = gpd.GeoSeries(_pts(grp["lon"].astype(float), grp["lat"].astype(float)), index=grp.index, crs=4326).to_crs(2154)
    dis.loc[grp.index, "dist_point_to_successor_m"] = [round(p.distance(com.loc[s].geometry), 1)
                                                      for p, s in zip(pts, grp["successor_at_accident_date"])]
dis.drop(columns=["lat", "lon"]).to_csv(TAB / "13_mapping_point_disagreements.csv", index=False)
print("distance point -> successor (disagreements, m):", dis["dist_point_to_successor_m"].describe(percentiles=[.5, .9]).round(0).to_dict())

pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 70)
print("codes:", len(codes), "| accidents:", len(out))
print(s1.to_string()); print(s2.to_string()); print(s3.to_string())
print("\nMOD distribution (codes):", codes["insee_mod"].value_counts().to_dict())
print("COMD/COMA on accident date (codes):", codes["is_COMD_or_COMA_on_accident_date"].value_counts().to_dict())
print("years obsolete at first accident:", pd.to_numeric(codes["years_obsolete_at_first_accident"], errors="coerce").describe().round(2).to_dict())
print("valid-until years:", codes["com_valid_as_COM_until"].str[:4].value_counts().sort_index().to_dict())
print("status_2026:", codes["status_2026"].value_counts().to_dict())
print("successor at date != successor 2026:", int((codes["successor_at_accident_date"] != codes["successor_2026"]).sum()))
print("\nnon-deterministic codes:\n", codes[codes["status_at_accident_date"] != "resolved"].to_string(index=False))
print("\npoint disagreements:\n", dis.head(25).to_string(index=False))
