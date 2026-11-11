# Geographic Reference Acquisition & Coordinate Validation
**Road Safety Intelligence — France** · BAAC 2019–2025, metropolitan France · 2026-11-11

Reproducible with `scripts/04_acquire_geography.py` → `scripts/05_validate_geography.py`.
Evidence tables: `reports/geography/tables/` (cited **[G-NN]**). No BAAC file was modified; no correction was applied to any data.

---

## 1. Geographic data source and licence

| Item | Value |
|---|---|
| Product | **IGN ADMIN EXPRESS COG** (non-generalised; *not* COG CARTO) |
| Producer | Institut national de l'information géographique et forestière (IGN) |
| Licence | **Licence Ouverte 2.0** (data.gouv.fr dataset `admin-express`, licence code `lov2`) |
| Distribution | IGN Géoplateforme download service `https://data.geopf.fr/telechargement/resource/ADMIN-EXPRESS-COG` (linked from data.gouv.fr) |
| Definition (IGN feed) | Annual edition taking into account the INSEE *Code Officiel Géographique* as of **1 January of the edition year** |
| Identifiers | Commune: `INSEE_COM` (2019–2024) / `code_insee` (2025). Department: `INSEE_DEP` / `code_insee`, `2A`/`2B` for Corsica |
| Layers used | `COMMUNE`, `DEPARTEMENT` |

## 2. Download inventory **[`data/raw/geography/_manifest.csv`]**

One edition per BAAC year (COG of 1 January of that year). Every archive matched the IGN-published length and MD5; SHA-256 recorded; archives set read-only.

| BAAC year | IGN resource | Coverage / CRS | Size | Communes (metro) | Depts (metro) |
|---|---|---|---|---|---|
| 2019 | ADMIN-EXPRESS-COG_2-0__SHP__FRA_2019-09-24 | France entière, WGS84 | 121.4 MB | 34 886 | 96 |
| 2020 | ADMIN-EXPRESS-COG_2-1__SHP__FRA_2020-11-20 | France entière, WGS84 | 160.9 MB | 34 839 | 96 |
| 2021 | ADMIN-EXPRESS-COG_3-0__SHP_LAMB93_FXX_2021-05-19 | Metro, Lambert-93 | 236.2 MB | 34 836 | 96 |
| 2022 | ADMIN-EXPRESS-COG_3-1__SHP_LAMB93_FXX_2022-04-15 | Metro, Lambert-93 | 248.6 MB | 34 826 | 96 |
| 2023 | ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2023-05-03 | Metro, Lambert-93 | 249.9 MB | 34 816 | 96 |
| 2024 | ADMIN-EXPRESS-COG_3-2__SHP_LAMB93_FXX_2024-02-22 | Metro, Lambert-93 | 249.4 MB | 34 806 | 96 |
| 2025 | ADMIN-EXPRESS-COG_4-0__GPKG_LAMB93_FXX_2025-01-01 | Metro, Lambert-93 (GeoPackage) | 245.2 MB | 34 746 | 96 |
| | **Total archives** | | **1 511.6 MB** | | |

- Extracted layers (derived, re-creatable from archives): `data/raw/geography/admin_express_cog/extracted/<year>/` (3.1 GB, mostly the 2025 GeoPackage which contains all layers). Flat per-year folders were required because archive paths exceed the Windows 260-character limit.
- Geometry quality **[G-00]**: 4 invalid commune and 4 invalid department geometries in the 2019 edition (repaired in memory with `make_valid`); 0 in other editions; 0 duplicate commune codes.
- New packages (justified by approved scope): `geopandas 1.2.0`, `shapely 2.2.0`, `pyproj 3.8.0`, `pyogrio 0.13.0` (in `requirements.txt`). 7z extraction uses the Windows built-in `bsdtar` (libarchive 3.8.9) — no extra package.

## 3. Validation methodology

1. **Scope**: accidents whose declared `dep` is metropolitan (01–95, 2A, 2B) after zero-padding the 2019 single-digit codes → 361 593 accidents. 21 128 non-metropolitan accidents are *out of scope* (not validated).
2. **Edition matching**: each accident is tested against the edition of its own year.
3. **Declared commune**: `com` as published; municipal arrondissements of Paris (751xx), Lyon (6938x) and Marseille (132xx) mapped to the commune codes 75056 / 69123 / 13055 because ADMIN EXPRESS `COMMUNE` holds whole communes. *Validation for these three cities is therefore at commune, not arrondissement, level.*
4. **Geometry**: BAAC `lat`/`long` (decimal comma → float, WGS84) projected to **Lambert-93 (EPSG:2154)**; spatial join `within` against commune and department polygons; distances in metres.
5. **Categories** (first match wins):

| Order | Category | Rule |
|---|---|---|
| 1 | `placeholder_invalid` | missing/unparsable, zero, out of range, or both coordinates integral (e.g. 11.0/11.0) |
| 2 | `valid` | point inside the declared commune (also if the declared code is absent from the year's edition but the point lies in that code's polygon from another edition) |
| 3 | `commune_code_unresolved` *(added)* | declared commune code exists in **no** 2019–2025 edition, and point lies in the declared department |
| 4 | `nearby_commune` | point outside declared commune but ≤ 500 m from its polygon |
| 5 | `swapped` | lat/long interchanged: swapped point within ≤ 500 m of the declared commune |
| 6 | `outside_coverage` | point inside no metropolitan commune polygon |
| 7 | `wrong_commune_same_dep` | point in another commune of the declared department (> 500 m) |
| 8 | `wrong_department` | point in a commune of another department |

6. **Additional diagnostics**: longitude-sign-flip test; department-layer vs commune-department consistency (0 conflicts); distance to declared commune for all mismatches.
7. **Corrections**: never applied. Proposed corrections (swap, longitude sign) are written to **[G-06]** with original strings, corrected values, method and evidence (distance of corrected point to declared commune).

`commune_code_unresolved` was added because these accidents carry obsolete (pre-2019) commune codes: their coordinates cannot be judged at commune level with the 2019–2025 editions, and counting them as "wrong commune" would wrongly blame the coordinates.

## 4. Results by year **[G-02]**

| Year | Metro accidents | Valid | Nearby ≤500 m | Wrong commune (same dep) | Wrong dept | Swapped | Placeholder | Outside coverage | Code unresolved | % valid | % valid + nearby |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2019 | 56 016 | 53 672 | 1 673 | 379 | 13 | 0 | 1 | 2 | 276 | 95.82 | 98.80 |
| 2020 | 45 121 | 43 936 | 897 | 118 | 2 | 0 | 0 | 2 | 166 | 97.37 | 99.36 |
| 2021 | 53 540 | 52 687 | 698 | 0 | 0 | 0 | 0 | 0 | 155 | 98.41 | 99.71 |
| 2022 | 52 380 | 51 781 | 591 | 7 | 0 | 0 | 0 | 0 | 1 | 98.86 | 99.99 |
| 2023 | 51 641 | 50 966 | 637 | 38 | 0 | 0 | 0 | 0 | 0 | 98.69 | 99.93 |
| 2024 | 51 058 | 50 269 | 756 | 25 | 4 | 3 | 0 | 1 | 0 | 98.46 | 99.94 |
| 2025 | 51 837 | 51 397 | 395 | 39 | 4 | 1 | 1 | 0 | 0 | 99.15 | 99.91 |
| **Total** | **361 593** | **354 708 (98.10 %)** | **5 647** | **606** | **23** | **4** | **2** | **5** | **598** | | **99.66** |

Distances to declared commune **[G-05]**: nearby — median 5 m, P90 141 m; wrong commune — median 1.35 km, P90 15.8 km, max 58.6 km; wrong department — median 2.3 km, max 655 km. 14 of 23 wrong-department points are ≤ 3 km from the declared commune (border cases, mostly Paris / Seine-Saint-Denis / Val-d'Oise / Val-de-Marne).
2019–2020 are clearly weaker (wrong commune 379 and 118; nearby median 15 m in 2019 vs 2–6 m later). Wrong-commune points have more low-precision coordinates (8.4 % with ≤ 3 effective decimals vs 2.0 % for valid points).

## 5. Results by department **[G-03, G-03b]**

- 96/96 metropolitan departments validated; `pct_valid` ranges from **89.5 % (50 Manche)** — driven by 213 unresolved commune codes, not by coordinate errors (problem share 0.36 %) — and 94.2 % (2B) to 99.7 %.
- Highest share of problem categories (wrong commune/dept, swapped, placeholder, outside): **2B Haute-Corse 2.33 %** (41 wrong commune, 2 wrong dept, 4 swapped, 1 outside); all others ≤ 0.7 % (14 Calvados 0.69 %, 86 Vienne 0.66 %, 36 Indre 0.59 %, 48 Lozère 0.57 %).
- `commune_code_unresolved` is concentrated in departments with many commune mergers: **50 Manche 213** (2019–2021), 74 Haute-Savoie, 49 Maine-et-Loire, 14 Calvados, 91 Essonne.
- Full year × department matrix: **[G-03b]**.

## 6. Identified anomalies **[G-04, G-06, G-07]**

| Case | Finding | Classification / proposed handling |
|---|---|---|
| 202400008235, 202400011273, 202400013466 (2B, 2024), 202500038525 (2B, 2025) | lat/long interchanged | `swapped`; swapped point lies **inside** the declared commune (0 m) → correction proposed [G-06] |
| 201900006562 (56) + 6 accidents in 14 Calvados (2019) | longitude sign missing (e.g. 2.7687 for −2.7687; 0.0988 for −0.0988) | wrong dept / wrong commune; sign-flipped point lies **inside** declared commune (0 m) → correction proposed [G-06] |
| 201900033874 (93) | 11.0 / 11.0 | `placeholder_invalid` — no correction possible |
| 202500014649 (84) | 44.0 / 5.0 | `placeholder_invalid` |
| 202400025734 (2B) | lat 46.61103 (should be ≈ 42.61, as reported on data.gouv.fr) | `outside_coverage`, 441 km — not corrected (digit error is plausible but not provable) |
| 202400022515, 202400032733 (2B Bastia) | identical longitude 1.407665 → points in Ariège (09) | `wrong_department`, 655 km — not correctable |
| 202500025963 (80) | 49.00000 / 2.27000 (2-decimal) | `wrong_department`, 92 km |
| 202500018181, 202500045544 (93) | identical coordinates, 652 m inside 94 | `wrong_department` (border) |
| 5 `outside_coverage` | 4 coastal points 0.6–4.0 km offshore (17 La Rochelle area, 06 Nice, 13 Marseille) + 202400025734 | flag, exclude from point analysis |

22 anomalous accidents share identical raw coordinates with another anomalous accident (repeated default/geocoded points).
Previously reported overseas cases (976 Mayotte, 971, 986, 987) are **out of scope** (non-metropolitan) and were not validated.

## 7. Remaining uncertainties

1. **Obsolete commune codes (598 accidents, 2019–2022)**: resolving them requires the INSEE COG history of commune changes (not downloaded — separate approval). Their department is consistent.
2. **Paris/Lyon/Marseille**: arrondissement-level consistency not tested (arrondissement layer exists in the 2025 GeoPackage only among the editions extracted).
3. **500 m tolerance** is a methodological choice; 5 647 "nearby" points (median 5 m) are almost certainly correct points near a boundary or geocoded to the road axis.
4. **Coastal points**: commune polygons follow the coastline; offshore points may be genuine (bridges, harbours) but imprecise.
5. **Point accuracy inside the correct commune is not tested** (e.g. a point geocoded to the commune centre is "valid").
6. Edition choice: each year uses the edition labelled with that COG year; IGN publication dates differ (e.g. 2019 edition published 2019-09-24).

## 8. Recommendation for Phase 2

1. **Adopt the validation output as a flag table** (`geo_validation_accidents.csv.gz`), joined on (`year`, `Num_Acc`); never overwrite BAAC coordinates.
2. **Point-based analyses (hotspots, KDE, clustering)**: use `valid` + `nearby_commune` (99.66 %); exclude the other categories; optionally use the 11 documented corrections (swap / sign) as a separate `geom_corrected` column with a `geom_source` flag.
3. **Area-based counts (commune/department)**: use the declared `com`/`dep` codes (complete), harmonised to a single COG vintage — requires the INSEE COG change history to map the 598 obsolete codes (request approval to download INSEE COG files).
4. **Treat 2019–2020 spatial precision as weaker** (higher wrong-commune and nearby rates); document in any multi-year hotspot comparison.
5. Load ADMIN EXPRESS COG into PostGIS in Phase 2 only for the editions actually needed (one reference vintage + historical codes), in EPSG:2154.
