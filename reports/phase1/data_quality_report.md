# Phase 1 — Data Acquisition & Profiling Report
**Road Safety Intelligence — France** · BAAC 2019–2025 · generated 2026-11-11

All figures below are measured on the raw files and reproducible from:
`scripts/01_acquire_baac.py` → `scripts/02_profile_baac.py` → `scripts/03_deep_checks.py`.
Evidence tables: `reports/phase1/tables/NN_*.csv` (cited as **[T-NN]**).

---

## 1. Dataset inventory

| Item | Value |
|---|---|
| Source | data.gouv.fr API, dataset *Bases de données annuelles des accidents corporels… 2005 à 2025* |
| Producer | Ministère de l'intérieur (ONISR administers the BAAC file) |
| Licence | `fr-lo` — Licence Ouverte / Open Licence |
| Dataset last update | 2026-10-30 (frequency: annual) |
| Files | 28 CSV (7 years × 4 tables) + 2 official PDFs, **223.3 MB** |
| Integrity | Size = API `filesize` for all 30 files; SHA-256 in `data/raw/baac/_manifest.csv`; files set read-only; re-verified unchanged after profiling |

Rows per table (pandas, header excluded) **[T-01, T-05]**:

| Year | Caract. (= accidents) | Lieux | Véhicules | Usagers | Metro accidents* |
|---|---|---|---|---|---|
| 2019 | 58 840 | 58 840 | 100 710 | 132 977 | 56 016 |
| 2020 | 47 744 | 47 744 | 81 066 | 105 295 | 45 121 |
| 2021 | 56 518 | 56 518 | 97 315 | 129 248 | 53 540 |
| 2022 | 55 302 | 55 302 | 94 493 | 126 662 | 52 380 |
| 2023 | 54 822 | **70 860** | 93 585 | 125 789 | 51 641 |
| 2024 | 54 402 | **70 248** | 92 678 | 125 187 | 51 058 |
| 2025 | 55 093 | **71 116** | 93 865 | 126 376 | 51 837 |

\* `dep` ∈ {01–95, 2A, 2B} after zero-padding 2019 single-digit codes (see §6).

## 2. File format **[T-01, T-09]**

| Property | Finding |
|---|---|
| Encoding | UTF-8, no BOM, all 28 files decode strictly |
| Separator | `;` everywhere |
| Quoting | Values double-quoted; some empty fields unquoted (e.g. `;;` in 2020) |
| Line endings | LF, except **2020 Lieux/Véhicules/Usagers = CRLF** |
| Trailing blank line | Present in 25/28 files → `csv` module sees 1 extra empty record; pandas row counts are correct; no malformed row in any file |
| Decimal separator | **comma** in `lat`, `long`, `larrout`, `lartpc` |
| Header anomalies | 2022 Caract.: key named **`Accident_Id`** (not `Num_Acc`). 2025 Véhicules: header contains **`"id_vehicule\n"`** (embedded newline) |
| Padding | Codes stored with a leading space: `" -1"` (all years, many columns) |
| Thousands separators in IDs | `id_vehicule`, `id_usager` written with spaces: `"138 306 524"` |
| Thousands separators in numbers | 2023–2025 `pr`/`pr1`: **U+00A0 no-break space** (`"1 000"`), ~580 rows/yr **[T-14]** |
| Spreadsheet error tokens | `nbv`: `#ERREUR` (2022: 1), `#VALEURMULTI` (2023: 54, 2024: 50, 2025: 24) **[T-14]** |
| Text placeholders | `"N/A"` in `v2`, `adr`; `"(1)"` in `pr`/`pr1` 2019–2022 (7.3k–19.7k rows/yr) **[T-07]**; `"N/C"` as a commune code (2022: 1) |

## 3. Schema comparison 2019–2025 **[T-02]**

- **Caractéristiques, Lieux, Véhicules**: identical column names and order in all 7 years (after header normalisation above).
- **Usagers**: `id_usager` **absent in 2019–2020**, present (position 2) from 2021; all other columns shift by one position.
- All columns match the official ONISR 2026 documentation; no undocumented column.
- Coordinate precision changes by year: 7 decimals (2019–20), 10 (2021–22), 8 (2023–25) **[T-08]**.
- `id_vehicule` numbering scheme changes: 2019–20 and 2023–25 ≈ 1.38e8–1.56e8; **2021 = 100 882–201 765; 2022 = 715 629–813 953**. No ID overlaps across years **[T-05, T-05c]** — but IDs are only safe to use *within* a year or combined with year.

## 4. Keys, duplicates and joins

### 4.1 Primary keys **[T-04, T-13]**
| Table | Key | Result |
|---|---|---|
| Caractéristiques | `Num_Acc` | Unique all years; 12 chars, prefix = year **[T-06]** |
| Lieux | `Num_Acc` | Unique 2019–2022; **not unique 2023–2025** (§4.3) |
| Véhicules | `id_vehicule` | Unique all years |
| Véhicules | (`Num_Acc`,`num_veh`) | **Not unique**: 2019 106 rows/53 accidents; 2022 4/2; 2024 2/1 → `num_veh` is not a reliable key |
| Usagers | `id_usager` | Unique 2021–2025; column absent 2019–2020 → **no user PK** for those years |

Exact duplicate rows: none, except Usagers 2019 (101) and 2020 (63) where no `id_usager` exists. Rows identical on all fields except `id_usager` (187–370/yr) are mostly passengers of coaches/buses (`catv` 37/38) and pedestrians → plausibly distinct people; **not to be deduplicated** **[T-12]**.

### 4.2 Join validation **[T-05, T-05b]**
| Check (every year 2019–2025) | Result |
|---|---|
| Caract. ↔ Lieux orphans (both directions) | 0 |
| Caract. ↔ Véhicules orphans | 0 |
| Caract. ↔ Usagers orphans | 0 |
| Usager `id_vehicule` not in Véhicules | 0 |
| Usager `Num_Acc` ≠ its vehicle's `Num_Acc` | 0 |
| Usager `num_veh` ≠ its vehicle's `num_veh` | 0 |
| Vehicles per accident (mean / max) | 1.70–1.72 / 10–25 |
| Users per vehicle (mean / max) | 1.30–1.35 / 28–65 |

**Vehicles without any user** **[T-11]**: 2019 **2 040**, 2020 **1 899**, 2021 6, 2022 0, 2023 40, 2024 24, 2025 4.
In 2019–2020 these are mostly `num_veh` = `Z01` (958/880) and passenger cars hitting a vehicle (`obsm`=2). This matches the ONISR statement that fugitive users were only added **from 2021**: in 2019–2020 fugitive drivers are simply absent from Usagers → **break in user counts between 2020 and 2021**.

### 4.3 Lieux is no longer 1:1 from 2023 **[T-10, T-10b]** — CRITICAL
| Year | Accidents with >1 Lieux row | Max rows/accident |
|---|---|---|
| 2019–2022 | 0 | 1 |
| 2023 | 15 870 (28.9 %) | 5 |
| 2024 | 15 645 (28.8 %) | 5 |
| 2025 | 15 831 (28.7 %) | 5 |

The extra rows are not exact duplicates. Within an accident `catr` is always identical, while `voie` differs in ~14k accidents/yr, and `vma`, `nbv`, `pr`, `circ`, `infra` etc. also vary — i.e. several road segments (e.g. intersecting roads) are recorded. **No column flags the "principal" location** described in the documentation. A naive Caract.→Lieux→Usagers join would inflate 2023–2025 counts by ~29 % of accidents.

## 5. Missingness **[T-17]** (% of rows: blank, `-1`, `N/A`, `#…`; `trajet` also `0`)

| Column | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | Note |
|---|---|---|---|---|---|---|---|---|
| lieux.pr / pr1 | 0* | 0* | 0* | 0* | 42.1 | 39.0 | 41.3 | *2019–22 use `(1)` instead (12–35 %) |
| lieux.vma | 1.5 | 1.6 | 1.6 | 1.6 | 6.5 | 5.2 | 6.0 | jump in 2023 |
| lieux.nbv | 1.1 | 1.0 | 1.0 | 1.0 | 5.9 | 6.0 | 5.6 | jump in 2023 |
| lieux.vosp | 1.1 | 0.6 | 0.4 | 0.3 | 5.6 | 5.5 | 4.7 | jump in 2023 |
| lieux.voie | 5.0 | 22.9 | 7.8 | 8.7 | 18.0 | 18.8 | 13.7 | |
| lieux.larrout | 99.4 | 92.6 | 95.2 | 93.1 | 74.2 | 69.3 | 67.8 | unusable |
| lieux.lartpc | 99.6 | 99.7 | 99.8 | 100 | 100 | 100 | 100 | unusable |
| caract.adr | 0.7 | 0.8 | 1.0 | 2.2 | 2.5 | 4.4 | 3.8 | rising |
| caract.col | 0.0 | 3.2 | 0.0 | 0.1 | 0.0 | 0.0 | 0.0 | |
| usagers.sexe / an_nais | 0 | 0 | 2.4 | 2.2 | 2.0 | 1.9 | 1.8 | fugitives added 2021 |
| usagers.trajet | 26.3 | 25.7 | 27.7 | 28.1 | 28.5 | 30.1 | 30.6 | |
| usagers.secu1 | 0.1 | 0.0 | 2.2 | 2.1 | 1.8 | 1.7 | 1.4 | |
| usagers.secu2 / secu3 | 30 / 99 | 37 / 99 | 43 / 99 | 46 / 99 | 44 / 98 | 43 / 90 | 44 / 91 | 2nd/3rd equipment mostly N/A |
| usagers.locp/actp/etatp | 38–92 | | | | | | | pedestrian-only fields (structural) |
| vehicules.occutc | ~99 | | | | | | | public-transport only (structural) |

Core analytical fields, max missing over 2019–2025:
- ≤ 0.05 %: `jour, mois, an, hrmn, lum, dep, com, agg, int, atm, lat, long, catr, catv, catu, place, manv`
- 0.05–1 %: `obs, obsm, choc` (0.07), `grav` (0.19), `plan` (0.23), `situ` (0.28), `surf` (0.29), `prof` (0.30), `motor` (0.32), `senc` (0.68)
- > 1 %: `infra` (1.84), `circ` (7.09)

## 6. Invalid / inconsistent values **[T-03, T-06, T-07, T-16, T-18]**

| Issue | Measurement |
|---|---|
| Dates / times | 0 invalid dates, 0 bad `hrmn`, `an` = file year, `Num_Acc` prefix = year (all years) |
| **2019 `dep` not zero-padded** | 2 966 accidents with `dep` = `1`…`9` (2020+ use `01`…`09`); `com` is correct (`02242`) |
| `grav` = `-1` (undocumented) | 2021: 60, 2022: 241, 2023: 118 users; 0 in other years |
| Codes outside official lists | `-1` in `lum`/`int`/`catv`/`place`/`catr` (≤ 17 rows/yr); `actp` = `7`/`8` (undocumented, 19–35/yr) |
| `an_nais` placeholders | 1900/1901: 2019 = 176, 2020 = 15, then 0 → ages > 100 are artefacts |
| `vma` (speed limit) | `-1`: 740–897/yr (2019–22) → 3 630–4 578/yr (2023–25); >130 km/h (500, 700, 800, 900, 901): 0–29/yr; non-standard (1, 2, 5, 25, 35…) 43–197/yr |
| `larrout` | max 730 m (2019) — implausible |
| Addresses | `#…#`-wrapped strings 2024: 75, 2025: 37 (Corsican communes); mojibake (`Ã`) ≤ 2/yr |
| COVID signal | 2020 min month = 1 208 accidents (vs 3 350–4 225 other years' minimum) |

Severity distribution (users; context only, no analysis): `grav` 2 (killed) 2 780–3 550/yr; 3 (hospitalised) 16 775–20 858/yr **[T-16]**.

## 7. Geographic quality **[T-08, T-08b, T-15, T-15b]**

| Check (metropolitan, after dep normalisation) | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| Metro accidents | 56 016 | 45 121 | 53 540 | 52 380 | 51 641 | 51 058 | 51 837 |
| Missing / zero coordinates | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Outside metro bounding box | 1 | 0 | 0 | 0 | 0 | 3 | 1 |
| … of which lat/long swapped | 0 | 0 | 0 | 0 | 0 | 3 | 1 |
| > 100 km from dept. median | 32 | 37 | 23 | 23 | 26 | 15 | 8 |
| ≥ 5 effective decimals (~1 m) | 86.5 % | 87.9 % | 89.8 % | 90.3 % | 90.2 % | 90.6 % | 90.3 % |
| ≤ 3 effective decimals (≥ ~100 m) | 2.8 % | 2.2 % | 1.9 % | 1.7 % | 1.8 % | 1.7 % | 1.9 % |
| Max accidents on one identical point | 14 | 18 | 7 | 11 | 12 | 8 | 7 |

- Non-metro accidents excluded by the filter: 2 623–3 256/yr (DOM 971–976 and COM 975/977/978/986/987/988) **[T-08]**.
- `com` always starts with `dep` from 2020 (2019 mismatch is entirely the padding issue; 2022 has one `N/C`).
- Corsica is coded `2A`/`2B` in all years (no `20`/`201`/`202`).
- The precision test cannot distinguish a true GPS fix from a geocoded commune/street centroid; repeated identical points are rare (max 18), so centroid-stacking is limited but not excluded.

**Assessment:** coordinates are complete and plausible for ≥ 99.9 % of metropolitan accidents → **suitable for spatial analysis and hotspot detection**, after removing/repairing ~5–40 outliers/yr. Point-in-department validation against official boundaries (GeoPandas, Phase 2+) is still required.

## 8. Critical data-quality issues

1. **Lieux 1:N from 2023** (~29 % of accidents, up to 5 rows) with no principal-location flag → join explosion and ambiguous road attributes.
2. **2019 `dep` codes unpadded** → silent loss of 2 966 accidents from any `dep`-based metro filter or join.
3. **Fugitive-user break 2020→2021**: ~1.9–2.0k vehicles/yr have no users in 2019–20; from 2021 fugitive users are present with missing sex/age (and sometimes `grav = -1`).
4. **No `id_usager` in 2019–2020**; `num_veh` not unique within accidents → vehicle↔user joins must use `id_vehicule` (validated: 0 mismatches).
5. **Header inconsistencies**: `Accident_Id` (2022), embedded newline (2025 Véhicules).
6. **Mixed missing/format tokens**: `" -1"`, `-1`, `""`, `N/A`, `(1)`, `#ERREUR`, `#VALEURMULTI`, U+00A0 / space thousands separators, decimal commas.
7. **Lieux coding change in 2023**: `pr`/`pr1` `(1)` → `-1`, and step increases in missing `vma`, `nbv`, `vosp`.
8. Implausible values: `vma` > 130, `an_nais` 1900/1901, `larrout` 730 m, a handful of swapped coordinates.

## 9. Recommendations for cleaning and integration (Phase 2 input)

1. **Header normalisation**: strip whitespace/newlines; map `Accident_Id` → `Num_Acc`.
2. **Read everything as text, then type explicitly**: strip spaces; remove space/U+00A0 thousands separators in IDs and `pr`/`pr1`; convert decimal commas.
3. **Unified missing value**: map `""`, `-1`, `N/A`, `(1)`, `#ERREUR`, `#VALEURMULTI` → NULL, keeping a per-field record of the original token (2019–22 `(1)` vs 2023+ `-1` is a coding change, not a data change). Keep documented `0` codes ("sans objet"/"inconnu") distinct from NULL.
4. **Geography**: zero-pad `dep` to 2 chars (2019); define metro = 01–95 + 2A/2B; flag (not drop) swapped coordinates and > 100 km outliers; validate with official boundaries in Phase 2.
5. **Keys**: accident = `Num_Acc`; vehicle = `id_vehicule` (+ year); user = `id_usager` where available, otherwise a surrogate key for 2019–2020. Do not deduplicate identical-looking users.
6. **Lieux**: model as a 1:N child table (`lieux_segment`) for all years; derive an accident-level location only via an explicit, documented rule (e.g. aggregate or select one segment) — to be decided in Phase 2. Never join Lieux into user-level facts without aggregation.
7. **Severity fields**: treat `grav = -1` as unknown; report fugitive users separately; flag 2019–20 vs 2021+ user-count comparability.
8. **Plausibility flags**: `vma` ∉ standard limits, `an_nais` < 1910, `larrout` outliers → flag columns, not deletion.
9. Keep raw files immutable; every transformation traceable to this report's tables.

## 10. Limitations of this profiling

- Code validity is checked against the 2026 ONISR documentation; semantic correctness of codes (e.g. whether a reported `catr` is true) cannot be verified from the data.
- Coordinate validity uses a bounding box and distance to the department median, not official boundaries.
- Interpretation of the 2023+ multi-row Lieux (several road segments) is inferred from which columns vary; it is **not documented** by ONISR.
- No statistical analysis performed (out of Phase 1 scope).
