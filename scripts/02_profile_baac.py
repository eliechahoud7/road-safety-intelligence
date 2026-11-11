"""Phase 1 - Profile raw BAAC CSVs (2019-2025). Read-only on data/raw.

Every value is read as text (no type coercion). Normalisation used ONLY for
measurement: strip surrounding whitespace; header names stripped of
whitespace/newlines. Outputs go to reports/phase1/tables/.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "baac"
OUT = ROOT / "reports" / "phase1" / "tables"
OUT.mkdir(parents=True, exist_ok=True)

TABLES = ["caracteristiques", "lieux", "vehicules", "usagers"]
MISSING_TOKENS = {"": "blank", "-1": "minus1", "0": "zero", ".": "dot", "N/A": "na_text"}

# Official code lists - ONISR "Description des bases de données annuelles 2005-2025" (21/10/2026)
def rng(a, b):
    return {str(i) for i in range(a, b + 1)}

CODES = {
    "lum": rng(1, 5), "agg": rng(1, 2), "int": rng(1, 9), "atm": {"-1"} | rng(1, 9),
    "col": {"-1"} | rng(1, 7), "catr": rng(1, 7) | {"9"}, "circ": {"-1"} | rng(1, 4),
    "vosp": {"-1"} | rng(0, 3), "prof": {"-1"} | rng(1, 4), "plan": {"-1"} | rng(1, 4),
    "surf": {"-1"} | rng(1, 9), "infra": {"-1"} | rng(0, 9), "situ": {"-1"} | rng(0, 6) | {"8"},
    "senc": {"-1"} | rng(0, 3),
    "catv": rng(0, 21) | rng(30, 43) | {"50", "60", "80", "99"},
    "obs": {"-1"} | rng(0, 17), "obsm": {"-1", "0", "1", "2", "4", "5", "6", "9"},
    "choc": {"-1"} | rng(0, 9), "manv": {"-1"} | rng(0, 26), "motor": {"-1"} | rng(0, 6),
    "place": rng(1, 10), "catu": rng(1, 3), "grav": rng(1, 4), "sexe": rng(1, 2),
    "trajet": {"-1", "0"} | rng(1, 5) | {"9"},
    "secu1": {"-1"} | rng(0, 9), "secu2": {"-1"} | rng(0, 9), "secu3": {"-1"} | rng(0, 9),
    "locp": {"-1"} | rng(0, 9), "actp": {"-1"} | rng(0, 6) | {"9", "A", "B"},
    "etatp": {"-1"} | rng(1, 3),
}
METRO_DEPS = {f"{i:02d}" for i in range(1, 96) if i != 20} | {"2A", "2B"}
METRO_BBOX = (41.3, 51.2, -5.3, 9.7)  # lat_min, lat_max, lon_min, lon_max


# ---------------------------------------------------------------- helpers
def table_of(name: str) -> str:
    n = name.lower()
    if n.startswith(("caract", "carct")):
        return "caracteristiques"
    for t in ("lieux", "vehicules", "usagers"):
        if n.startswith(t):
            return t
    raise ValueError(name)


def norm_code(v: str) -> str:
    """Strip; drop leading zeros of integer-like codes ('07'->'7', '00'->'0')."""
    v = v.strip()
    if re.fullmatch(r"-?\d+", v):
        return str(int(v))
    return v


def files():
    for ydir in sorted(p for p in RAW.iterdir() if p.is_dir() and p.name.isdigit()):
        for f in sorted(ydir.glob("*.csv")):
            yield int(ydir.name), table_of(f.name), f


def infer_type(s: pd.Series) -> str:
    v = s.str.strip()
    v = v[~v.isin(["", "N/A", "."])]
    if v.empty:
        return "empty"
    checks = [
        ("int", r"-?\d+"), ("int_with_spaces", r"-?\d{1,3}( \d{3})+|-?\d+"),
        ("decimal_comma", r"-?\d+(,\d+)?"), ("decimal_point", r"-?\d+(\.\d+)?"),
        ("time_hh:mm", r"\d{1,2}:\d{2}"),
    ]
    for name, pat in checks:
        if v.str.fullmatch(pat).all():
            return name
    share = v.str.fullmatch(r"-?\d+").mean()
    return f"text (int-like {share:.1%})"


# ---------------------------------------------------------------- 1. formats
fmt_rows, frames = [], {}
for year, table, f in files():
    raw = f.read_bytes()
    try:
        text = raw.decode("utf-8")
        enc = "utf-8"
    except UnicodeDecodeError as e:
        text, enc = raw.decode("latin-1"), f"NOT utf-8 ({e.reason} at {e.start})"
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    sample = text[:5000]
    sep = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=sep))
    header, body = rows[0], rows[1:]
    ncol = len(header)
    bad_width = sum(len(r) != ncol for r in body)
    fields_with_newline = sum(("\n" in c or "\r" in c) for r in rows for c in r)
    quoted_all = text.split("\n", 2)[1].startswith('"') if "\n" in text else None
    df = pd.read_csv(f, sep=sep, dtype=str, keep_default_na=False, encoding="utf-8")
    renamed = {c: re.sub(r"\s+", "", c) for c in df.columns}
    df = df.rename(columns=renamed)
    if "Accident_Id" in df.columns:
        df = df.rename(columns={"Accident_Id": "Num_Acc"})
    frames[(year, table)] = df
    fmt_rows.append({
        "year": year, "table": table, "file": f.name, "bytes": len(raw), "encoding": enc,
        "bom": raw.startswith(b"\xef\xbb\xbf"), "separator": sep,
        "line_endings": "CRLF" if crlf and not lf else "LF" if lf and not crlf else f"mixed crlf={crlf} lf={lf}",
        "rows": len(body), "pandas_rows": len(df), "columns": ncol, "rows_bad_field_count": bad_width,
        "fields_with_embedded_newline": fields_with_newline, "first_data_row_quoted": quoted_all,
        "raw_header": "|".join(h.replace("\n", "\\n") for h in header),
        "header_anomalies": "; ".join(
            [f"{k!r}->{v!r}" for k, v in renamed.items() if k != v]
            + (["Accident_Id used instead of Num_Acc"] if "Accident_Id" in header else [])),
    })
fmt = pd.DataFrame(fmt_rows)
fmt.to_csv(OUT / "01_file_format.csv", index=False)

# ---------------------------------------------------------------- 2. schema
sch = []
for t in TABLES:
    cols = []
    for y in sorted({y for y, tt in frames if tt == t}):
        for c in frames[(y, t)].columns:
            if c not in cols:
                cols.append(c)
    for c in cols:
        row = {"table": t, "column": c}
        for y in sorted({y for y, tt in frames if tt == t}):
            dfc = frames[(y, t)].columns
            row[str(y)] = (list(dfc).index(c) + 1) if c in dfc else ""
        sch.append(row)
schema = pd.DataFrame(sch)
schema.to_csv(OUT / "02_schema_matrix.csv", index=False)

# ---------------------------------------------------------------- 3. column profile
prof = []
for (y, t), df in frames.items():
    n = len(df)
    for c in df.columns:
        s = df[c]
        st = s.str.strip()
        rec = {"year": y, "table": t, "column": c, "rows": n, "inferred_type": infer_type(s),
               "n_unique": st.nunique()}
        for tok, name in MISSING_TOKENS.items():
            rec[f"pct_{name}"] = round(100 * (st == tok).mean(), 3)
        rec["pct_leading_trailing_space"] = round(100 * (s != st).mean(), 3)
        if c in CODES:
            nc = st.map(norm_code)
            invalid = nc[~nc.isin(CODES[c])]
            rec["pct_invalid_code"] = round(100 * len(invalid) / n, 3)
            rec["invalid_values_top"] = "; ".join(f"{k!r}:{v}" for k, v in invalid.value_counts().head(6).items())
        rec["top_values"] = "; ".join(f"{k!r}:{v}" for k, v in st.value_counts().head(5).items())
        prof.append(rec)
profile = pd.DataFrame(prof)
profile.to_csv(OUT / "03_column_profile.csv", index=False)

# ---------------------------------------------------------------- 4. keys & duplicates
def ids(s: pd.Series) -> pd.Series:
    return s.str.replace(r"\s", "", regex=True)

KEYS = {
    "caracteristiques": [["Num_Acc"]],
    "lieux": [["Num_Acc"]],
    "vehicules": [["id_vehicule"], ["Num_Acc", "num_veh"], ["Num_Acc", "id_vehicule"]],
    "usagers": [["id_usager"], ["Num_Acc", "id_vehicule", "num_veh", "place", "catu", "sexe", "an_nais"]],
}
dup = []
for (y, t), df in frames.items():
    d = df.apply(lambda s: s.str.strip())
    rec = {"year": y, "table": t, "rows": len(d), "exact_duplicate_rows": int(d.duplicated().sum())}
    for key in KEYS[t]:
        if not all(k in d.columns for k in key):
            rec[f"dupkey[{'+'.join(key)}]"] = "column absent"
            continue
        kk = d[key].apply(ids)
        rec[f"dupkey[{'+'.join(key)}]"] = int(kk.duplicated(keep=False).sum())
    dup.append(rec)
dups = pd.DataFrame(dup)
dups.to_csv(OUT / "04_duplicates_keys.csv", index=False)

# ---------------------------------------------------------------- 5. joins
join = []
card = []
for y in sorted({y for y, _ in frames}):
    C, L, V, U = (frames[(y, t)].apply(lambda s: s.str.strip()) for t in TABLES)
    for D in (C, L, V, U):
        D["Num_Acc"] = ids(D["Num_Acc"])
    V["id_vehicule"] = ids(V["id_vehicule"]); U["id_vehicule"] = ids(U["id_vehicule"])
    cA, lA, vA, uA = (set(D["Num_Acc"]) for D in (C, L, V, U))
    lc = L.groupby("Num_Acc").size()
    vc = V.groupby("Num_Acc").size()
    uv = U.groupby("id_vehicule").size().reindex(V["id_vehicule"]).fillna(0)
    # vehicle -> usager key consistency
    m = U.merge(V[["id_vehicule", "Num_Acc", "num_veh"]], on="id_vehicule", how="left",
                suffixes=("", "_veh"), indicator=True)
    matched = m[m["_merge"] == "both"]
    # composite-key alternative
    mk = U.merge(V[["Num_Acc", "num_veh"]].drop_duplicates(), on=["Num_Acc", "num_veh"], how="left", indicator=True)
    join.append({
        "year": y,
        "accidents_caract": len(cA), "caract_rows": len(C),
        "caract_without_lieux": len(cA - lA), "lieux_without_caract": len(lA - cA),
        "accidents_with_>1_lieux": int((lc > 1).sum()), "max_lieux_per_accident": int(lc.max()),
        "caract_without_vehicule": len(cA - vA), "vehicule_acc_not_in_caract": len(vA - cA),
        "caract_without_usager": len(cA - uA), "usager_acc_not_in_caract": len(uA - cA),
        "vehicules": len(V), "usagers": len(U),
        "usager_id_vehicule_not_in_vehicules": int((m["_merge"] == "left_only").sum()),
        "usager_veh_Num_Acc_mismatch": int((matched["Num_Acc"] != matched["Num_Acc_veh"]).sum()),
        "usager_veh_num_veh_mismatch": int((matched["num_veh"] != matched["num_veh_veh"]).sum()),
        "vehicules_without_usager": int((uv == 0).sum()),
        "usager_(Num_Acc,num_veh)_not_in_vehicules": int((mk["_merge"] == "left_only").sum()),
        "vehicules_per_acc_mean": round(vc.mean(), 3), "vehicules_per_acc_max": int(vc.max()),
        "usagers_per_veh_mean": round(uv.mean(), 3), "usagers_per_veh_max": int(uv.max()),
        "id_vehicule_min": int(V["id_vehicule"].astype("int64").min()),
        "id_vehicule_max": int(V["id_vehicule"].astype("int64").max()),
    })
    for name, ser in (("lieux_per_accident", lc.reindex(list(cA)).fillna(0)),
                      ("vehicules_per_accident", vc.reindex(list(cA)).fillna(0)),
                      ("usagers_per_vehicule", uv)):
        vcnt = ser.astype(int).clip(upper=10).value_counts().sort_index()
        for k, v in vcnt.items():
            card.append({"year": y, "relation": name, "n (10 = 10+)": k, "count": v})
joins = pd.DataFrame(join)
joins.to_csv(OUT / "05_joins.csv", index=False)
pd.DataFrame(card).to_csv(OUT / "05b_cardinality_distribution.csv", index=False)

# id overlap across years (are id_vehicule / id_usager globally unique?)
idov = []
yrs = sorted({y for y, _ in frames})
for col, t in (("id_vehicule", "vehicules"), ("id_usager", "usagers")):
    sets = {y: set(ids(frames[(y, t)][col])) for y in yrs if col in frames[(y, t)].columns}
    ys = sorted(sets)
    for i, a in enumerate(ys):
        for b in ys[i + 1:]:
            idov.append({"id": col, "year_a": a, "year_b": b, "overlap": len(sets[a] & sets[b])})
pd.DataFrame(idov).to_csv(OUT / "05c_id_overlap_across_years.csv", index=False)

# ---------------------------------------------------------------- 6. temporal / identity sanity
tmp = []
for y in yrs:
    C = frames[(y, "caracteristiques")].apply(lambda s: s.str.strip())
    num = ids(C["Num_Acc"])
    hr = C["hrmn"]
    hm = hr.str.extract(r"^(\d{1,2}):(\d{2})$").astype(float)
    dates = pd.to_datetime(dict(year=pd.to_numeric(C["an"], errors="coerce"),
                                month=pd.to_numeric(C["mois"], errors="coerce"),
                                day=pd.to_numeric(C["jour"], errors="coerce")), errors="coerce")
    U = frames[(y, "usagers")].apply(lambda s: s.str.strip())
    an_n = pd.to_numeric(U["an_nais"], errors="coerce")
    age = y - an_n
    tmp.append({
        "year": y, "an_values": "|".join(sorted(C["an"].unique())),
        "Num_Acc_prefix_not_year": int((~num.str.startswith(str(y))).sum()),
        "Num_Acc_len_values": "|".join(map(str, sorted(num.str.len().unique()))),
        "hrmn_bad_format": int(hm.isna().any(axis=1).sum()),
        "hrmn_out_of_range": int(((hm[0] > 23) | (hm[1] > 59)).sum()),
        "invalid_dates": int(dates.isna().sum()),
        "accidents_per_month_min": int(dates.dt.month.value_counts().min()),
        "accidents_per_month_max": int(dates.dt.month.value_counts().max()),
        "usager_an_nais_missing_or_nonnum": int(an_n.isna().sum()),
        "usager_age_<0": int((age < 0).sum()), "usager_age_>100": int((age > 100).sum()),
        "usager_grav_-1": int((U["grav"] == "-1").sum()),
        "usager_sexe_-1": int((U["sexe"] == "-1").sum()),
    })
pd.DataFrame(tmp).to_csv(OUT / "06_temporal_identity_checks.csv", index=False)

# numeric ranges of continuous Lieux fields
rngs = []
for y in yrs:
    L = frames[(y, "lieux")].apply(lambda s: s.str.strip())
    for c in ("vma", "nbv", "larrout", "lartpc", "pr", "pr1"):
        v = L[c]
        x = pd.to_numeric(v.str.replace(",", ".", regex=False), errors="coerce")
        rngs.append({"year": y, "column": c, "non_numeric": int(x.isna().sum() - (v == "").sum()),
                     "blank": int((v == "").sum()), "eq_-1": int((x == -1).sum()),
                     "min": x.min(), "p50": x.median(), "p99": x.quantile(.99), "max": x.max(),
                     "non_numeric_examples": "; ".join(v[x.isna() & (v != "")].value_counts().head(5).index)})
    vma = pd.to_numeric(L["vma"], errors="coerce")
    std = {10, 15, 20, 30, 40, 45, 50, 60, 70, 80, 90, 100, 110, 120, 130}
    rngs.append({"year": y, "column": "vma_not_standard_limit",
                 "non_numeric": int((~vma.isin(std) & (vma > 0)).sum()),
                 "non_numeric_examples": "; ".join(map(str, vma[~vma.isin(std) & (vma > 0)].value_counts().head(8).index))})
pd.DataFrame(rngs).to_csv(OUT / "07_lieux_numeric_ranges.csv", index=False)

# ---------------------------------------------------------------- 8. geography
geo, depfmt = [], []
for y in yrs:
    C = frames[(y, "caracteristiques")].apply(lambda s: s.str.strip())
    dep, com = C["dep"], C["com"]
    is_metro = dep.isin(METRO_DEPS)
    lat_raw, lon_raw = C["lat"], C["long"]
    lat = pd.to_numeric(lat_raw.str.replace(",", ".", regex=False), errors="coerce")
    lon = pd.to_numeric(lon_raw.str.replace(",", ".", regex=False), errors="coerce")
    missing = lat.isna() | lon.isna()
    zero = (lat == 0) & (lon == 0)
    inbox = lat.between(METRO_BBOX[0], METRO_BBOX[1]) & lon.between(METRO_BBOX[2], METRO_BBOX[3])
    M = pd.DataFrame({"dep": dep, "lat": lat, "lon": lon})[is_metro & ~missing & inbox]
    med = M.groupby("dep")[["lat", "lon"]].transform("median")
    R = 6371.0
    p1, p2 = np.radians(M["lat"]), np.radians(med["lat"])
    dlat, dlon = p2 - p1, np.radians(med["lon"] - M["lon"])
    dist = 2 * R * np.arcsin(np.sqrt(np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2))
    decs = lat_raw.str.extract(r"[.,](\d+)$")[0].str.len()
    coord_counts = M.groupby(["lat", "lon"]).size()
    com_prefix_ok = pd.Series([c.startswith(d) for d, c in zip(dep, com)], index=C.index)
    geo.append({
        "year": y, "accidents": len(C),
        "metro": int(is_metro.sum()), "non_metro": int((~is_metro).sum()),
        "non_metro_deps": "|".join(f"{k}:{v}" for k, v in dep[~is_metro].value_counts().sort_index().items()),
        "dep_len_values": "|".join(map(str, sorted(dep.str.len().unique()))),
        "com_len_values": "|".join(map(str, sorted(com.str.len().unique()))),
        "com_not_prefixed_by_dep": int((~com_prefix_ok).sum()),
        "com_not_prefixed_examples": "; ".join(f"{d}/{c}" for d, c in C.loc[~com_prefix_ok, ["dep", "com"]].head(6).values),
        "coord_decimal_sep": "comma" if lat_raw.str.contains(",").any() else "point",
        "lat_decimals_values": "|".join(map(str, sorted(decs.dropna().astype(int).unique()))),
        "metro_coord_missing": int((is_metro & missing).sum()),
        "metro_coord_zero": int((is_metro & zero).sum()),
        "metro_coord_outside_bbox": int((is_metro & ~missing & ~inbox).sum()),
        "metro_coord_>50km_from_dep_median": int((dist > 50).sum()),
        "metro_coord_>100km_from_dep_median": int((dist > 100).sum()),
        "metro_valid_coord_pct": round(100 * len(M) / is_metro.sum(), 3),
        "metro_distinct_coords": int(len(coord_counts)),
        "metro_coords_shared_by_>=5_accidents": int(coord_counts[coord_counts >= 5].sum()),
        "metro_max_accidents_same_coord": int(coord_counts.max()),
        "metro_adr_blank_or_NA": int((is_metro & C["adr"].isin(["", "N/A"])).sum()),
    })
    for k, v in dep.value_counts().items():
        depfmt.append({"year": y, "dep": k, "accidents": v})
pd.DataFrame(geo).to_csv(OUT / "08_geography.csv", index=False)
pd.DataFrame(depfmt).sort_values(["year", "dep"]).to_csv(OUT / "08b_dep_counts.csv", index=False)

# ---------------------------------------------------------------- console summary
pd.set_option("display.width", 250, "display.max_columns", 60, "display.max_colwidth", 120)
print(fmt.drop(columns=["raw_header", "file"]).to_string(index=False))
print("\nSCHEMA\n", schema.to_string(index=False))
print("\nDUPLICATES\n", dups.to_string(index=False))
print("\nJOINS\n", joins.T.to_string())
print("\nGEO\n", pd.DataFrame(geo).T.to_string())
