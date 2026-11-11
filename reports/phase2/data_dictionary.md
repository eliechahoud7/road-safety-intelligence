# Phase 2 — Data Dictionary
**Road Safety Intelligence — France** · Status: **DESIGN ONLY**

Code definitions follow the ONISR *Description des bases de données annuelles 2005–2025* (21/10/2026, `data/raw/baac/docs/`). Percentages of missing values are Phase 1 measurements (`reports/phase1/tables/17_missingness_pct.csv`).

**Analytical relevance** — **Core**: primary analytical variable · **Context**: secondary / descriptive · **Restricted**: usable only with a documented caveat or sub-population · **Excluded**: not used for analysis (kept for lineage).

---

## 0. Global transformation rules (staging → clean)

| Rule | Applies to | Detail |
|---|---|---|
| G1 Trim | all text values | remove leading/trailing whitespace (e.g. `" -1"` → `-1`) |
| G2 Missing tokens → NULL | coded and numeric fields | `""`, `-1`, `N/A`, `.`, `(1)`, `#ERREUR`, `#VALEURMULTI` → NULL; each non-blank token also written to `clean.dq_issue` when it is not a documented code |
| G3 Documented zero codes kept | catv 0, senc 0, manv 0, motor 0, vosp 0, infra 0, situ 0, obs 0, obsm 0, choc 0, secu 0, locp 0, actp 0 | `0` is a real modality ("Sans objet", "Aucun", "Inconnu", "Indéterminable") — **not** NULL |
| G4 `trajet` zero | trajet | documented as "Non renseigné" (both `0` and `-1`) → NULL |
| G5 Thousands separators | id_vehicule, id_usager, pr, pr1 | remove spaces and U+00A0 (`"138 306 524"` → 138306524; `"1 000"` → 1000) |
| G6 Decimal separator | lat, long, lartpc, larrout | comma → point (lartpc/larrout use a **point in 2019**, comma 2020+; both accepted) |
| G7 Integer codes | coded fields | `"07"` → 7; values outside the documented list → NULL + `dq_issue UNDOCUMENTED_CODE` |
| G8 Original preserved | dep, com, adr, lat, long, voie | kept verbatim in `*_original` columns; staging keeps every raw value |
| G9 No imputation | all | no value is inferred or filled |

---

## 1. `clean.accident` (source: Caractéristiques)

| Target | Source | Definition | Type | Transformation | Missing / invalid | Relevance |
|---|---|---|---|---|---|---|
| num_acc | `Num_Acc` (2022: `Accident_Id`) | Accident identifier | bigint | header mapping; G1 | never missing | Key |
| year | `an` | Year | smallint | cast; must equal left(num_acc,4) | never missing | Core |
| acc_date | an, mois, jour | Accident date | date | build date (0 invalid) | — | Core |
| acc_time | `hrmn` | Time HH:MM | time | parse | 0 bad formats | Core |
| hour, weekday | derived | hour 0–23, ISO weekday | smallint | from acc_time / acc_date | — | Core |
| season (analytics) | derived | meteorological season (DJF, MAM, JJA, SON) | text | from month | — | Core |
| lum | `lum` | Lighting (1 daylight … 5 night lit) | smallint | G1/G2/G7 | ≤ 5 rows `-1`/yr | Core |
| agg | `agg` | 1 outside / 2 inside built-up area | smallint | G7 | none | Core |
| intersection | `int` | Intersection type 1–9 | smallint | renamed (reserved word) | ≤ 7 rows `-1`/yr | Core |
| atm | `atm` | Weather 1–9 | smallint | G2/G7 | ≤ 0.03 % | Core |
| col | `col` | Collision type 1–7 | smallint | G2/G7 | 0–3.2 % (2020) | Core |
| dep_original | `dep` | Department as published | text | G1 | none | Lineage |
| dep_code | `dep` | INSEE department | varchar(3) | zero-pad 1-digit 2019 codes (2 966 accidents) | none | Core |
| is_metro | derived | dep_code ∈ 01–95, 2A, 2B | boolean | — | — | Scope |
| com_original | `com` | Commune as published | text | G1 only — never overwritten | `N/C` 1 case (2022) | Lineage |
| com_arm | derived | Municipal arrondissement (Paris/Lyon/Marseille) | char(5) | when com_original is an active ARM | 46 883 accidents | Context |
| com_cog_at_date | derived | INSEE commune valid on acc_date | char(5) | INSEE chain until valid on date | NULL if unresolved | Context |
| com_cog_2026 | derived | Commune in COG 2026 | char(5) | `ref.commune_code_harmonisation` | NULL for `N/C` and out-of-scope overseas | Core (commune analysis) |
| com_mapping_class / _confidence | derived | how com_cog_2026 was obtained | text | see geographic model §4 | — | Quality |
| adr_original | `adr` | Partial postal address (built-up areas) | text | G1 only | 0.7–4.4 % blank/N/A; `#…#` 75/37 rows 2024/25 | Excluded (free text) |
| lat_original / long_original | `lat`, `long` | Raw coordinate strings | text | none | none missing | Lineage |
| lat / lon | `lat`, `long` | WGS84 decimal degrees | double | G6 | 2 placeholders (11/11, 44/5) kept + flagged | Core (spatial) |
| geom_original | derived | Point EPSG:2154 | geometry | ST_Transform(ST_SetSRID(ST_MakePoint(lon,lat),4326),2154) | NULL only if unparsable | Core (spatial) |

## 2. `clean.accident_location` (source: Lieux) — grain: road segment

| Target | Source | Definition | Type | Transformation | Missing / invalid | Relevance |
|---|---|---|---|---|---|---|
| location_id | — | Surrogate key | bigint | identity | — | Key |
| num_acc | `Num_Acc` | Accident | bigint | G1 | — | Key |
| segment_seq, n_segments_in_accident | derived | order / count of rows within accident | smallint | by source_row_number | — | Structure |
| catr | `catr` | Road category (7 = urban metropolitan roads) | smallint | G2/G7 | 1 row `-1` (2025) | Core — **constant within accident** (verified); `catr=7` unstable over time |
| voie_original | `voie` | Road number / street name | text | G1 | 5–23 % missing | Excluded (free text) |
| v1 | `v1` | Numeric index of road number | smallint | G2 | 17–23 % | Excluded |
| v2 | `v2` | Alphanumeric road index letter | text | G2 | ~90 % | Excluded |
| circ | `circ` | Traffic regime 1–4 | smallint | G2/G7 | 5.4–7.1 % | Context |
| nbv | `nbv` | Number of lanes | smallint | G2; error tokens → NULL + dq_issue (`#ERREUR` 1; `#VALEURMULTI` 54/50/24) | 1.0 % → 5.6–6.0 % from 2023 | Restricted (2023 break) |
| vosp | `vosp` | Reserved lane (1 cycle track, 2 cycle lane, 3 reserved) | smallint | G2/G3 | 0.3–1.1 % → 4.7–5.6 % 2023+ | Context |
| prof | `prof` | Gradient 1–4 | smallint | G2/G7 | ≤ 0.3 % | Context |
| pr, pr1 | `pr`, `pr1` | Milestone number / distance to milestone (m) | integer | G2 (`(1)` 2019–22, `-1` 2023+), G5 | 12–35 % (`(1)`) / 39–42 % (2023+) | Excluded (coding break; location via coordinates) |
| plan | `plan` | Horizontal alignment 1–4 | smallint | G2/G7 | ≤ 0.23 % | Context |
| lartpc | `lartpc` | Central reserve width (m) | numeric(6,2) | G2/G6 | ≈ 100 % | **Excluded** |
| larrout | `larrout` | Carriageway width (m) | numeric(6,2) | G2/G6; max 730 m (2019) flagged | 68–99 % | **Excluded** |
| surf | `surf` | Surface condition 1–9 | smallint | G2/G7 | ≤ 0.3 % | Core |
| infra | `infra` | Infrastructure 0–9 | smallint | G2/G3 | ≤ 1.8 % | Context |
| situ | `situ` | Accident situation 0–6, 8 | smallint | G2/G3 | ≤ 0.3 % | Context |
| vma | `vma` | Speed limit (km/h) | smallint | G2 | 1.5 % → 5.2–6.5 % 2023+ | Core (with `vma_plausible`) |
| vma_plausible | derived | vma ∈ standard French limits | boolean | 500–901 km/h (0–29/yr) and 1, 2, 5, 25, 35… (43–197/yr) → false | — | Quality |

## 3. `clean.vehicle` (source: Véhicules)

| Target | Source | Definition | Type | Transformation | Missing / invalid | Relevance |
|---|---|---|---|---|---|---|
| id_vehicule | `id_vehicule` (2025 header `"id_vehicule\n"`) | Vehicle identifier | integer | header fix; G5 | never | Key |
| num_acc | `Num_Acc` | Accident | bigint | G1 | never | Key |
| num_veh | `num_veh` | Vehicle label within accident (A01, B01, Z01…) | text | G1; 4 odd values flagged (`[01`, `\01`, `]01`, `_01`) | never | Context (not a key) |
| senc | `senc` | Direction relative to PR/address | smallint | G2/G3 | ≤ 0.7 % | Excluded (technical) |
| catv | `catv` | Vehicle category | smallint | G2/G7; `-1` ≤ 5/yr | ≤ 0.01 % | Core (EDP 50/60, VAE 80 adoption trend) |
| obs | `obs` | Fixed obstacle hit 0–17 | smallint | G2/G3 | ≤ 0.07 % | Core |
| obsm | `obsm` | Mobile obstacle hit | smallint | G2/G3 | ≤ 0.07 % | Core |
| choc | `choc` | Initial impact point 0–9 | smallint | G2/G3 | ≤ 0.07 % | Context |
| manv | `manv` | Main manoeuvre 0–26 | smallint | G2/G3 | ≤ 0.05 % | Context |
| motor | `motor` | Engine type 0–6 | smallint | G2/G3 | ≤ 0.32 % | Context |
| occutc | `occutc` | Public-transport occupants | smallint | G2 | ~99 % (structural) | Restricted (bus/coach only) |
| n_users, has_no_user | derived | linked users; fugitive vehicle without user | smallint, boolean | count | 2019: 1 972, 2020: 1 838 metro vehicles without users; ≤ 28/yr after | Quality / comparability |

## 4. `clean.road_user` (source: Usagers)

| Target | Source | Definition | Type | Transformation | Missing / invalid | Relevance |
|---|---|---|---|---|---|---|
| road_user_id | — | Surrogate key | bigint | identity | — | Key |
| id_usager | `id_usager` (2021+) | Source user id | integer | G5 | NULL 2019–2020 (column absent) | Lineage |
| num_acc, id_vehicule | `Num_Acc`, `id_vehicule` | Accident / vehicle | bigint, integer | G1/G5 | never | Keys |
| num_veh | `num_veh` | Vehicle label (pedestrians: vehicle that hit them) | text | G1 | never | Context |
| place | `place` | Seat position 1–10 (10 = pedestrian) | smallint | G2 | ≤ 17 `-1`/yr | Context |
| catu | `catu` | 1 driver, 2 passenger, 3 pedestrian | smallint | G7 | none | Core |
| grav | `grav` | 1 unhurt, 2 killed, 3 hospitalised (> 24 h), 4 light — **not ordinal** | smallint | G2 (`-1` 60/241/118 in 2021–23) | — | Core |
| severity_rank | derived | 0 unhurt < 1 light < 2 hospitalised < 3 killed | smallint | mapping from grav | NULL if grav NULL | Core |
| is_victim | derived | grav ∈ {2,3,4} | boolean | — | — | Core |
| sexe | `sexe` | 1 male, 2 female | smallint | G2 | 0 % 2019–20; 1.8–2.4 % 2021+ (fugitives) | Core |
| an_nais | `an_nais` | Birth year | smallint | cast | 0 % 2019–20; 2.0–2.4 % 2021+ | Core |
| age_at_accident | derived | year − an_nais | smallint | NULL if placeholder | 1900/1901: 176 (2019), 15 (2020) | Core |
| trajet | `trajet` | Trip purpose 1–5, 9 | smallint | G4 | 26–31 % | Restricted |
| secu1 | `secu1` | 1st safety equipment used (0 none … 9 other; 8 = undeterminable) | smallint | G2/G3 | 0–2.2 % | Core (with 8 reported separately) |
| secu2, secu3 | `secu2`, `secu3` | 2nd / 3rd equipment | smallint | G2/G3 | 30–46 % / 90–99 % (structural) | Restricted |
| locp, actp, etatp | same | Pedestrian location / action / company | smallint / char(1) | G2/G3; actp `7`/`8` undocumented (19–35/yr) → NULL + dq_issue | structural for non-pedestrians | Restricted (catu = 3 only) |
| is_fugitive_like | derived | sexe NULL AND an_nais NULL AND year ≥ 2021 | boolean | — | 2 908 (2021) … 2 071 (2025) metro | Comparability flag |

## 5. Accident-level derived indicators (analytics)

| Column | Definition | Source |
|---|---|---|
| n_killed / n_hospitalised / n_light / n_unhurt / n_grav_unknown | counts of users by `grav` | `clean.road_user` |
| n_users_excl_fugitive | n_users − n_fugitive_like | `clean.road_user` |
| accident_severity | `fatal` if n_killed > 0; else `hospitalised` if n_hospitalised > 0; else `light` if n_light > 0; else `unknown` | casualty summary |
| n_segments, catr, vma_min, vma_max, vma_conflict, surf/circ/infra/plan/prof (+ `_conflict`), any_cycle_facility, lieux_regime | collapse of Lieux rows to one row per accident | `clean.accident_location` |
| n_vehicles, n_vehicles_without_user, any_bicycle (catv 1), any_powered_2_3_wheeler (catv 2, 30–34, 41–43), any_hgv (13–17), any_edp (50, 60) | vehicle summary | `clean.vehicle` |
| in_core_scope | is_metro AND year 2019–2025 | accident |
| is_covid_year | year = 2020 | `ref.methodological_break` |
| spatial_eligibility | see geographic model §6 | geo validation |

## 6. Fields excluded from analytical use (kept for lineage)

`adr`, `voie`, `v1`, `v2`, `pr`, `pr1`, `lartpc`, `larrout`, `senc` — free text, coding breaks or ≥ 68 % missing. `occutc`, `secu2`, `secu3`, `locp`, `actp`, `etatp`, `trajet` are **restricted** (sub-population or high missingness), not excluded.
