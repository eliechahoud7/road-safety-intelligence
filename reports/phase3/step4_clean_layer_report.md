# Phase 3 — Step 4: Clean Layer
**Road Safety Intelligence — France** · 2026-11-11 · Database `road_safety` (PostgreSQL 18.6 / PostGIS 3.6.4)

Result: **clean layer built from staging + existing reference tables; 103 / 103 validation checks pass** (build `load_run_id = 12`, validation `load_run_id = 13`). No raw file, staging row or reference table was modified; no geographic data reloaded; no spatial validation repeated; the 11 coordinate corrections were **not** applied.

---

## 1. Files created / modified

| Path | Type | Purpose |
|---|---|---|
| `db/sql/040_clean_layer.sql` | new | helper functions `clean.f_txt / f_code / f_undocumented / f_int / f_num / f_id` (data-dictionary rules G1–G7) and the clean tables |
| `scripts/15_build_clean.py` | new | E0 raw hash gate → DDL → `com_cog_at_date` from INSEE history → `INSERT … SELECT` from staging (one transaction) → `dq_issue` |
| `scripts/16_validate_clean.py` | new | checks C1–C12 → `meta.dq_check` (layer `clean`) |
| `reports/phase3/step4_clean_layer_report.md` | new | this report |

## 2. Tables created (approved Phase 2 design, `database_schema.md` §5)

| Table | Grain / PK | Rows | Size | Key relationships |
|---|---|---|---|---|
| `clean.accident` | accident / `num_acc` | 382 721 | 145 MB | FK `com_original` → `ref.commune_code_harmonisation`; FK `num_acc` → `ref.geo_validation_phase1c` |
| `clean.accident_location` | Lieux row / `location_id` (+ UQ `num_acc, segment_seq`) | 430 628 | 79 MB | FK `num_acc` → accident (1:N) |
| `clean.vehicle` | vehicle / `id_vehicule` (+ UQ `id_vehicule, num_acc`) | 653 712 | 229 MB | FK `num_acc` → accident (1:N) |
| `clean.road_user` | road user / `road_user_id` (+ UQ `id_usager`) | 871 534 | 209 MB | composite FK `(id_vehicule, num_acc)` → vehicle (1:N); FK `num_acc` → accident |
| `clean.dq_issue` | issue / `dq_issue_id` | 1 360 | 0.3 MB | approved design §5.6 — anomaly log with original value |

Every clean row carries `source_file_id`, `source_row_number` (UNIQUE) and `load_run_id` → exact staging row, file, year and ingestion run. `(num_acc, num_veh)` is **not** a key anywhere (56 duplicated pairs preserved). Database size now 4.1 GB.

Row counts per year (= staging, check C1):

| Year | Accidents | Locations | Vehicles | Road users |
|---|---|---|---|---|
| 2019 | 58 840 | 58 840 | 100 710 | 132 977 |
| 2020 | 47 744 | 47 744 | 81 066 | 105 295 |
| 2021 | 56 518 | 56 518 | 97 315 | 129 248 |
| 2022 | 55 302 | 55 302 | 94 493 | 126 662 |
| 2023 | 54 822 | 70 860 | 93 585 | 125 789 |
| 2024 | 54 402 | 70 248 | 92 678 | 125 187 |
| 2025 | 55 093 | 71 116 | 93 865 | 126 376 |

## 3. Transformations

**Annual schema harmonisation** (already canonicalised in staging, values untouched until here):
2022 `Accident_Id` and 2025 `"id_vehicule\n"` → loaded as `num_acc` / `id_vehicule`; `id_usager` NULL for 2019–2020 (surrogate `road_user_id` for all years); identifiers stripped of spaces / U+00A0 and cast (`num_acc` bigint, `id_vehicule`, `id_usager` integer); `int` → `intersection`.

**Missing values and codes** (data dictionary): trim; `''`, `-1`, `N/A`, `.`, `(1)`, `#…` → NULL; documented `0` modalities kept; `trajet` 0 → NULL; values outside the documented ONISR code lists → NULL **and** logged in `dq_issue`; `pr`/`pr1` thousands separators removed, negative values → NULL + logged; `lartpc`/`larrout` decimal point (2019) or comma (2020+) → numeric.

**Derived fields**: `acc_date`, `acc_time`, `hour`, ISO `weekday`; `dep_code` (2019 single digits zero-padded) and `is_metro`; `severity_rank` (0 unhurt < 1 light < 2 hospitalised < 3 killed) and `is_victim` from non-ordinal `grav`; `age_at_accident` (NULL for 1900/1901 placeholders, flagged `an_nais_placeholder`); `is_fugitive_like` (2021+: sex and birth year missing); `vehicle.n_users` / `has_no_user`; `segment_seq` / `n_segments_in_accident` (file order within accident); `vma_plausible`.

**Lieux**: kept 1:N at segment grain (accident-level collapse with NULL + conflict flags is the approved Step 5 analytical summary — not built yet).

**Geography (reference tables reused, no spatial recomputation)**:
| Field | Source |
|---|---|
| `dep_original`, `com_original`, `adr_original`, `lat_original`, `long_original` | verbatim staging values |
| `lat`, `lon` | parsed (decimal comma), identical to Phase 1C |
| `geom_original` Point 2154 | metropolitan accidents only (Lambert-93 not meaningful overseas) |
| `com_arm` | Paris/Lyon/Marseille arrondissement codes kept (46 883 metro accidents) |
| `com_cog_at_date` | INSEE commune valid on the accident date (`ref.insee_*`), chains followed incl. later reinstatements |
| `com_cog_2026`, `com_mapping_class` | `ref.commune_code_harmonisation` |
| `com_mapping_confidence` | exact (identity / arrondissement) · high/medium (Phase 1D for the 598; otherwise high if Phase 1C point `valid`) · none |
| `geo_category`, `geo_dist_declared_m` | `ref.geo_validation_phase1c` |
| `has_correction_proposal`, `correction_method` | `ref.coordinate_correction_proposal` — flag only, coordinates unchanged |

Metropolitan confidence distribution: exact 360 514 · high 1 051 · medium 27 · none 1 (`N/C`).

## 4. Validation results (`meta.dq_check`, run 13) — 103 / 103 pass

| Group | Checks | Result |
|---|---|---|
| C1 staging = clean row counts, 4 entities × 7 years | 28 | pass |
| C2 PK/FK present & validated; user→vehicle FK on `(id_vehicule, num_acc)`; `num_veh` never a key; 0 orphans (4 tests); 56 duplicate `(num_acc, num_veh)` pairs preserved | 8 | pass |
| C3 every accident has ≥ 1 location, vehicle, user; vehicles without users = Phase 1 (2 040 · 1 899 · 6 · 0 · 40 · 24 · 4) | 10 | pass |
| C4 totals 382 721 / 430 628 / 653 712 / 871 534; users by `grav` × year = staging; metro killed = Phase 1B (3 244 · 2 541 · 2 944 · 3 267 · 3 167 · 3 193 · 3 263); 361 593 metro accidents | 13 | pass |
| C5 all years 2019–2025 in every table | 4 | pass |
| C6 metro `com_cog_2026` and `com_cog_at_date` NULL only for `N/C`; 46 883 arrondissement ids; `com_cog_at_date` valid on accident date; = harmonisation; = Phase 1D for 598 (+ confidence 579/18/1); no text `'nan'` | 9 | pass |
| C7 user→vehicle→accident join = 871 534 rows (no fan-out); vehicle→accident = 653 712; segment numbering consistent; multi-segment accidents = Phase 1 (0 … 15 870 · 15 645 · 15 831) | 11 | pass |
| C8 original strings identical to staging; lat/lon and geo category = Phase 1C; 11 proposals flagged and coordinates unchanged; metro geometries SRID 2154 | 4 | pass |
| C9 `dq_issue` = Phase 1: `nbv` error tokens (1 · 54 · 50 · 24), `actp` 7/8 (31 · 19 · 29 · 33 · 33 · 37 · 35), birth-year placeholders (176 · 15), 4 odd `num_veh` values | 6 | pass |
| C10 `grav = -1` → NULL (60 · 241 · 118 in 2021–23); fugitive-like metro users = Phase 1B (2 908 · 2 610 · 2 278 · 2 240 · 2 071) | 2 | pass |
| C11 raw BAAC files (SHA-256) and staging (count + MD5) unchanged | 5 | pass |
| C12 every clean row maps to exactly one staging row | 4 | pass |

Fan-out evidence: joining road users directly to raw Lieux rows would yield 984 631 rows instead of 871 534 (+13 %) — the reason Lieux will only be joined through a one-row-per-accident summary in Step 5.

`dq_issue` content (1 360 rows): `vma` implausible 763 (kept, flagged) · `actp` undocumented 217 (NULL) · birth-year placeholder 191 (kept, flagged) · `nbv` error tokens 129 (NULL) · negative `pr1` 35 (NULL) · odd `num_veh` 25 rows / 4 values (kept, flagged).

## 5. Problems and limitations

1. **Build-script bug (fixed)** — first build (run 10, validation run 11: 98/102) wrote unresolved `com_cog_at_date` values as the text `'nan'` (pandas NaN passed to `COPY`) for `N/C` and out-of-scope overseas codes. Fixed (real NULL) and rebuilt (run 12); a check against `'nan'` was added.
2. **Validation expectation error (fixed)** — Phase 1 reported 4 *distinct* odd `num_veh` values; the check first compared with the *row* count (25). Corrected to distinct values.
3. A diagnostic query run before the build (code validity on accident date) was too slow (text vs `char(5)` comparison) and was cancelled on the server; the logic was implemented in the build instead.
4. Overseas-collectivity codes (975, 977, 978, 986–988) have no INSEE history in the loaded file → `com_cog_at_date` / `com_cog_2026` NULL, `com_mapping_confidence = 'none'` (outside core scope).
5. Point/commune agreement for the ~481 codes merged *after* the accident is inferred from the Phase 1C category (no new spatial check, by instruction).
6. The 2019 Beugnies/Floursies polygon overlap (60.5 m²) remains documented in Step 3; not fixed.
7. Full clean rebuild takes ~10 minutes (one transaction).
