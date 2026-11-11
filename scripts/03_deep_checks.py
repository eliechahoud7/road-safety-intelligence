"""Phase 1 - Targeted investigation of anomalies found by 02_profile_baac.py.

Read-only on data/raw. Outputs: reports/phase1/tables/09_* ... 16_*.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "baac"
OUT = ROOT / "reports" / "phase1" / "tables"
YEARS = range(2019, 2026)


def path(year: int, table: str) -> Path:
    pref = {"caracteristiques": ("caract", "carct")}.get(table, (table,))
    return next(f for f in (RAW / str(year)).glob("*.csv") if f.name.lower().startswith(pref))


def load(year: int, table: str) -> pd.DataFrame:
    df = pd.read_csv(path(year, table), sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    df.columns = [re.sub(r"\s+", "", c) for c in df.columns]
    df = df.rename(columns={"Accident_Id": "Num_Acc"})
    df = df.apply(lambda s: s.str.strip())
    for c in ("Num_Acc", "id_vehicule", "id_usager"):
        if c in df.columns:
            df[c] = df[c].str.replace(r"\s", "", regex=True)
    return df


D = {(y, t): load(y, t) for y in YEARS for t in ("caracteristiques", "lieux", "vehicules", "usagers")}

# ---- 09. row-count discrepancy between csv module and pandas
rows = []
for y in YEARS:
    for t in ("caracteristiques", "lieux", "vehicules", "usagers"):
        text = path(y, t).read_bytes().decode("utf-8")
        recs = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
        ncol = len(recs[0])
        bad = [(i, r) for i, r in enumerate(recs) if len(r) != ncol]
        rows.append({"year": y, "table": t, "csv_records_incl_header": len(recs),
                     "pandas_rows": len(D[(y, t)]),
                     "bad_records": len(bad),
                     "bad_record_positions": "|".join(str(i) for i, _ in bad[:5]),
                     "bad_record_repr": "|".join(repr(r)[:60] for _, r in bad[:3]),
                     "file_tail_repr": repr(text[-40:])})
pd.DataFrame(rows).to_csv(OUT / "09_row_count_reconciliation.csv", index=False)

# ---- 10. Lieux multi-row accidents (2023+)
rows, examples = [], []
for y in YEARS:
    L = D[(y, "lieux")]
    multi = L[L.duplicated("Num_Acc", keep=False)]
    if multi.empty:
        rows.append({"year": y, "accidents_multi": 0})
        continue
    g = multi.groupby("Num_Acc")
    varying = {c: int((g[c].nunique() > 1).sum()) for c in L.columns if c != "Num_Acc"}
    rec = {"year": y, "accidents_multi": g.ngroups, "rows_in_multi": len(multi),
           "exact_dup_rows_within_multi": int(multi.duplicated().sum())}
    rec.update({f"varies_{c}": v for c, v in varying.items()})
    # does a multi-row accident's set of catr differ? distinct catr combos
    rec["top_catr_combos"] = "; ".join(f"{k}:{v}" for k, v in
                                       g["catr"].agg(lambda s: "+".join(sorted(s))).value_counts().head(5).items())
    rows.append(rec)
    examples.append(multi.sort_values("Num_Acc").head(9).assign(year=y))
pd.DataFrame(rows).to_csv(OUT / "10_lieux_multirow.csv", index=False)
pd.concat(examples).to_csv(OUT / "10b_lieux_multirow_examples.csv", index=False)

# ---- 11. Vehicles without usagers
rows = []
for y in YEARS:
    V, U, C = D[(y, "vehicules")], D[(y, "usagers")], D[(y, "caracteristiques")]
    orphan = V[~V["id_vehicule"].isin(U["id_vehicule"])]
    rec = {"year": y, "vehicules_without_usager": len(orphan),
           "accidents_affected": orphan["Num_Acc"].nunique()}
    for c in ("catv", "obs", "obsm", "manv", "num_veh"):
        rec[f"top_{c}"] = "; ".join(f"{k}:{v}" for k, v in orphan[c].value_counts().head(5).items())
    rec["num_veh_prefix_top"] = "; ".join(f"{k}:{v}" for k, v in orphan["num_veh"].str[0].value_counts().head(5).items())
    rows.append(rec)
pd.DataFrame(rows).to_csv(OUT / "11_vehicles_without_usagers.csv", index=False)

# ---- 12. Usagers exact duplicate rows (2019-2020 have no id_usager)
rows = []
for y in YEARS:
    U = D[(y, "usagers")]
    cols = [c for c in U.columns if c != "id_usager"]
    d = U[U.duplicated(cols, keep=False)]
    rows.append({"year": y, "rows_identical_except_id_usager": len(d),
                 "top_catu": "; ".join(f"{k}:{v}" for k, v in d["catu"].value_counts().items()),
                 "top_place": "; ".join(f"{k}:{v}" for k, v in d["place"].value_counts().head(5).items()),
                 "top_catv_of_vehicle": "; ".join(f"{k}:{v}" for k, v in
                     d.merge(D[(y, 'vehicules')][["id_vehicule", "catv"]], on="id_vehicule")["catv"].value_counts().head(5).items())})
pd.DataFrame(rows).to_csv(OUT / "12_usagers_duplicates.csv", index=False)

# ---- 13. Vehicles: num_veh not unique within accident
rows = []
for y in YEARS:
    V = D[(y, "vehicules")]
    d = V[V.duplicated(["Num_Acc", "num_veh"], keep=False)]
    rows.append({"year": y, "rows": len(d), "accidents": d["Num_Acc"].nunique(),
                 "examples": "; ".join(f"{a}/{n}" for a, n in d[["Num_Acc", "num_veh"]].head(4).values)})
pd.DataFrame(rows).to_csv(OUT / "13_vehicles_num_veh_dups.csv", index=False)

# ---- 14. Odd characters & error tokens anywhere
rows = []
for y in YEARS:
    for t in ("caracteristiques", "lieux", "vehicules", "usagers"):
        df = D[(y, t)]
        for c in df.columns:
            s = df[c]
            err = s[s.str.startswith("#")]
            nonascii = s[s.str.contains(r"[^\x00-\x7F]", regex=True)]
            if c in ("adr", "voie", "v2"):
                nonascii = nonascii[nonascii.str.contains(r"[^\x00-\x7FÀ-ÿŒœ’]", regex=True)]
            if len(err) or len(nonascii):
                chars = sorted({ch for v in nonascii.head(500) for ch in v if ord(ch) > 127})
                rows.append({"year": y, "table": t, "column": c, "error_tokens": len(err),
                             "error_values": "; ".join(f"{k}:{v}" for k, v in err.value_counts().head(3).items()),
                             "rows_with_unusual_non_ascii": len(nonascii),
                             "chars": " ".join(f"U+{ord(ch):04X}({unicodedata.name(ch, '?')})" for ch in chars[:4]),
                             "examples": "; ".join(nonascii.head(3).map(repr))})
pd.DataFrame(rows).to_csv(OUT / "14_error_tokens_and_odd_chars.csv", index=False)

# ---- 15. Coordinate precision & outliers (metropolitan)
METRO = {f"{i:02d}" for i in range(1, 96) if i != 20} | {"2A", "2B"}
rows, outl = [], []
for y in YEARS:
    C = D[(y, "caracteristiques")].copy()
    C["dep_n"] = C["dep"].where(~C["dep"].str.fullmatch(r"\d"), "0" + C["dep"])  # 2019 '1'..'9'
    m = C[C["dep_n"].isin(METRO)].copy()
    lat = pd.to_numeric(m["lat"].str.replace(",", "."), errors="coerce")
    lon = pd.to_numeric(m["long"].str.replace(",", "."), errors="coerce")
    eff = lambda s: s.str.extract(r"[.,](\d+)$")[0].str.rstrip("0").str.len().fillna(0)
    de = np.minimum(eff(m["lat"]), eff(m["long"]))
    med = pd.DataFrame({"dep": m["dep_n"], "lat": lat, "lon": lon}).groupby("dep")[["lat", "lon"]].transform("median")
    p1, p2 = np.radians(lat), np.radians(med["lat"])
    dist = 2 * 6371 * np.arcsin(np.sqrt(np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(med["lon"] - lon) / 2) ** 2))
    rows.append({"year": y, "metro_accidents_dep_normalised": len(m),
                 "eff_decimals_<=2_(~1km)": int((de <= 2).sum()),
                 "eff_decimals_3_(~100m)": int((de == 3).sum()),
                 "eff_decimals_4_(~10m)": int((de == 4).sum()),
                 "eff_decimals_>=5": int((de >= 5).sum()),
                 "coord_missing": int((lat.isna() | lon.isna()).sum()),
                 "coord_outside_metro_bbox": int((~(lat.between(41.3, 51.2) & lon.between(-5.3, 9.7))).sum()),
                 "dist_dep_median_>100km": int((dist > 100).sum()),
                 "dist_dep_median_>150km": int((dist > 150).sum()),
                 "lat_lon_possibly_swapped": int((lat.between(-5.3, 9.7) & lon.between(41.3, 51.2)).sum())})
    sel = m.assign(dist_km=dist.round(1))[dist > 100]
    outl.append(sel[["Num_Acc", "dep", "com", "adr", "lat", "long", "dist_km"]].assign(year=y))
pd.DataFrame(rows).to_csv(OUT / "15_coordinate_precision.csv", index=False)
pd.concat(outl).to_csv(OUT / "15b_coordinate_outliers_gt100km.csv", index=False)

# ---- 16. Context: grav distribution & birth-year oddities & dep code formats
rows = []
for y in YEARS:
    U, C = D[(y, "usagers")], D[(y, "caracteristiques")]
    rec = {"year": y}
    rec.update({f"grav_{k}": v for k, v in U["grav"].value_counts().sort_index().items()})
    an = pd.to_numeric(U["an_nais"], errors="coerce")
    rec["an_nais_min"] = an.min()
    rec["an_nais_<=1920_values"] = "; ".join(f"{int(k)}:{v}" for k, v in an[an <= 1920].value_counts().head(5).items())
    rec["dep_single_digit"] = int(C["dep"].str.fullmatch(r"\d").sum())
    rec["dep_2A_2B"] = int(C["dep"].isin(["2A", "2B"]).sum())
    rec["dep_20_or_201_202"] = int(C["dep"].isin(["20", "201", "202"]).sum())
    rec["com_non_numeric_values"] = "; ".join(C["com"][~C["com"].str.fullmatch(r"\d{5}|2[AB]\d{3}")].value_counts().head(5).index)
    rec["adr_blank_or_NA"] = int(C["adr"].isin(["", "N/A"]).sum())
    rec["agg_in_agglo_adr_missing"] = int(((C["agg"] == "2") & C["adr"].isin(["", "N/A"])).sum())
    rows.append(rec)
pd.DataFrame(rows).to_csv(OUT / "16_context_grav_birth_dep.csv", index=False)

# ---- 17. Missingness summary (blank, -1, N/A, '#...' tokens; plus documented 0='non renseigné' for trajet)
rows = []
for y in YEARS:
    for t in ("caracteristiques", "lieux", "vehicules", "usagers"):
        df = D[(y, t)]
        for c in df.columns:
            s = df[c]
            miss = s.isin(["", "-1", "N/A"]) | s.str.startswith("#")
            if c == "trajet":
                miss |= s == "0"
            rows.append({"year": y, "table": t, "column": c, "pct_missing": round(100 * miss.mean(), 2)})
miss = pd.DataFrame(rows).pivot_table(index=["table", "column"], columns="year", values="pct_missing")
miss.to_csv(OUT / "17_missingness_pct.csv")

# ---- 18. Misc: mojibake in addresses, vma > 130, an_nais placeholders
rows = []
for y in YEARS:
    C, L = D[(y, "caracteristiques")], D[(y, "lieux")]
    vma = pd.to_numeric(L["vma"], errors="coerce")
    rows.append({"year": y,
                 "adr_mojibake_(Ã.)": int(C["adr"].str.contains("Ã", regex=False).sum()),
                 "voie_mojibake_(Ã.)": int(L["voie"].str.contains("Ã", regex=False).sum()),
                 "adr_hash_wrapped": int(C["adr"].str.fullmatch(r"#.*#").sum()),
                 "vma_>130": int((vma > 130).sum()), "vma_0": int((vma == 0).sum()),
                 "vma_-1": int((vma == -1).sum()),
                 "an_nais_1900_1901": int(D[(y, "usagers")]["an_nais"].isin(["1900", "1901"]).sum())})
pd.DataFrame(rows).to_csv(OUT / "18_misc_quality.csv", index=False)

pd.set_option("display.width", 250, "display.max_columns", 60, "display.max_colwidth", 110)
print("\n=== 17_missingness_pct.csv (columns with any year > 1%)")
print(miss[(miss > 1).any(axis=1)].to_string())
print("\n=== 18_misc_quality.csv")
print(pd.read_csv(OUT / "18_misc_quality.csv").to_string(index=False))
for f in sorted(OUT.glob("1[0-6]*.csv")) + [OUT / "09_row_count_reconciliation.csv"]:
    if "examples" in f.name or "15b" in f.name:
        continue
    print(f"\n=== {f.name}")
    print(pd.read_csv(f).T.to_string() if f.name[:2] in ("10", "11", "15", "16") else pd.read_csv(f).to_string(index=False))
