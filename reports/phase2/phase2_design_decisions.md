# Phase 2 — Design Decisions, Risks and Open Questions
**Road Safety Intelligence — France** · Status: **DESIGN ONLY — awaiting approval**

Each decision: context → decision → alternatives considered → justification. "**Approval needed**" marks decisions that change scope, tooling or analytical results.

---

## A. Architecture & tooling

**D-01 Five schemas (`meta`, `staging`, `ref`, `clean`, `analytics`) in one PostgreSQL database.**
Alternatives: single schema; separate databases per layer. Justification: clear layer boundaries and permissions with one connection; cross-layer SQL without dblink.

**D-02 Full deterministic rebuild instead of incremental loads.**
Alternatives: incremental per year; CDC. Justification: ~2.3 M rows total; ONISR republishes files (e.g. 2023/2024 corrected after user reports), so a rebuild from hashed raw files is the only fully reproducible option.

**D-03 Staging stores all values as untouched `TEXT`, one table per entity across years.**
Alternatives: typed staging; one table per year. Justification: raw tokens (`" -1"`, `(1)`, `#VALEURMULTI`, U+00A0) must remain inspectable; a `source_year` column avoids 28 near-identical tables. Header canonicalisation (2022 `Accident_Id`, 2025 `"id_vehicule\n"`) is the only staging transformation and is recorded in `meta.source_file.raw_header`.

**D-04 PostGIS installation — Approval needed.**
Verified: PostgreSQL **18.6** is installed and running; the **PostGIS extension is not installed**; Docker 29.9.2 is available. Options: (a) install the PostGIS bundle for PostgreSQL 18 (EDB Stack Builder) into the existing server; (b) run a dedicated `postgis/postgis` container (isolated, reproducible, no change to the existing server). Recommendation: **(b) Docker container** — reproducible, no interference with the existing instance — unless you prefer a native install.

**D-05 Python database libraries for Phase 3 — Approval needed.**
Needed: `psycopg` (v3, `COPY` for bulk loads), `SQLAlchemy` + `GeoAlchemy2` (required by `GeoDataFrame.to_postgis`). Alternatives: `ogr2ogr`/`shp2pgsql` (not installed; GDAL CLI adds a new tool). Recommendation: these three Python packages only.

**D-06 Pipeline = plain Python entry point + SQL files; no orchestrator.**
Alternatives: Airflow, Prefect, dbt. Justification: single-machine, annual data; an orchestrator adds infrastructure without benefit. Run metadata in `meta.load_run`, checks in `meta.dq_check`.

## B. Keys and relationships

**D-07 Natural keys where verified, surrogates where not.**
`clean.accident.num_acc` (bigint) and `clean.vehicle.id_vehicule` (integer) are PKs — both unique across all 7 years. `clean.road_user` uses a surrogate `road_user_id`, with `id_usager` kept as a nullable UNIQUE column (absent 2019–2020). `clean.accident_location` uses a surrogate `location_id` + `(num_acc, segment_seq)` UQ (Lieux has no identifier).
Alternative rejected: `(num_acc, num_veh)` — not unique (verified duplicates).

**D-08 Composite FK `road_user(id_vehicule, num_acc) → vehicle(id_vehicule, num_acc)`.**
Enforces that a user's vehicle belongs to the same accident (verified 0 mismatches today; protects future years).

**D-09 Vehicles without users are legitimate rows.**
The vehicle→user relationship is 0..n (fugitive drivers 2019–2020: 1 972 / 1 838 metro vehicles). Flagged `has_no_user`; never deleted.

## C. Lieux

**D-10 Lieux is a 1:N child (`accident_location`) for all years; accident-level road attributes come only from `analytics.accident_lieu_summary` (exactly one row per accident).**
Alternatives rejected: first row (arbitrary — first row matches `adr` in only 33 % of multi-row accidents); address-matching row (resolves only 56 %); widening to fixed columns (max 5 segments, sparse). Rules: `catr` taken directly (verified constant within accident); numeric attributes as min/max (`vma_min`, `vma_max`); categorical attributes kept only when identical across segments, else NULL + `*_conflict = true`; `any_cycle_facility` as an "any" flag; `lieux_regime` distinguishes 2019–2022 (one row chosen by unknown ONISR rule) from 2023+ (all intersecting roads).
**Approval needed** for the conflict rule (NULL vs. "most severe" value).

## D. Harmonisation and quality

**D-11 Missing-token policy:** `""`, `-1`, `N/A`, `.`, `(1)`, `#ERREUR`, `#VALEURMULTI` → NULL; documented `0` modalities kept; `trajet` 0 → NULL (documented "non renseigné"). Undocumented codes (e.g. `actp` 7/8) → NULL + `dq_issue`. Original values remain in staging and in `dq_issue.original_value`.

**D-12 Flag, don't delete:** implausible `vma` (500–901, 1, 2, 5…), `an_nais` 1900/1901, `larrout` outliers, odd `num_veh`, error tokens — flagged or logged; analytics decide exclusion explicitly.

**D-13 Fugitive users:** `road_user.is_fugitive_like` (2021+) and `vehicle.has_no_user` (mainly 2019–2020). Comparable user totals across 2019–2025 = users excluding fugitive-like (documented in `ref.methodological_break FUGITIVE_USERS_2021`). Victim counts are unaffected (fugitive-like users are never killed/hospitalised/light — verified).

**D-14 Severity:** user-level `severity_rank` (0 unhurt < 1 light < 2 hospitalised < 3 killed) derived from non-ordinal `grav`; accident-level `accident_severity` = most severe user outcome (`fatal`, `hospitalised`, `light`, `unknown`). Hospitalised-based indicators carry `HOSP_NOT_CERTIFIED`. `grav = -1` (2021–2023) → NULL, counted as `n_grav_unknown`.

**D-15 Scope handled in analytics, not by deletion:** overseas accidents (21 128) are loaded to staging/clean; `in_core_scope` filters analytics. Overseas geographic validation and commune harmonisation are out of scope (INSEE file used covers metro + DROM; COM 975–988 not covered).

## E. Geography

**D-16 EPSG:2154 for all stored geometries;** 4326 only for display views.

**D-17 Commune harmonisation to COG 2026 applied to all 25 394 metro codes** with `com_original`, `com_cog_at_date`, `com_cog_2026`, class and confidence kept separately. IGN 2025 polygons serve as COG 2026 geometry (verified identical code set).

**D-18 Validation recomputed in PostGIS (not imported from the Phase 1C CSV),** then reconciled exactly with Phase 1C/1D counts as a DQ gate. A second category (`category_harmonised`) re-evaluates the 598 obsolete-code accidents against their successor commune.

**D-19 Coordinate corrections are proposals.** 11 corrections (4 swaps, 7 longitude-sign errors) stored in `accident_geo_validation` with `correction_status = 'proposed'`. **Approval needed** to mark them `approved` and include them in hotspot analysis.

**D-20 Default hotspot population = `valid` + `nearby_commune` (+ approved corrections).** `wrong_commune_same_dep` (606) excluded by default, used in sensitivity analysis. **Approval needed.**

## F. Analytics & performance

**D-21 Materialised views for the 1:1 accident summaries, `accident_fact`, `hotspot_point` and aggregates; plain views for row-level facts.** Justification: summaries involve grouping over ~0.4–0.9 M rows and are reused by every analysis and the app; row-level facts are simple many-to-one joins. Unique index on each MV key (for `REFRESH … CONCURRENTLY`).

**D-22 Indexes limited to:** PKs/UQs; FK columns (`num_acc` on children, `(id_vehicule, num_acc)`); `(year)`, `(dep_code, year)`, `(com_cog_2026)` on accident; GiST on every geometry. No index on low-cardinality codes (`grav`, `catu`, `lum` …): the tables are small enough for sequential scans; revisit only if measured queries are slow. No partitioning (< 1 M rows per table).

## G. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | Lieux 2023+ structure undocumented by ONISR (producer forum reply only) | road-attribute comparability 2022→2023 | `lieux_regime`, conflict flags, `LIEUX_MULTIROW_2023` break |
| R2 | Hospitalised indicator not certified; possible further recording changes | trends of hospitalised casualties | label all hospitalised outputs; prefer killed / accident counts for trends |
| R3 | No exposure data | hotspots ≠ risk | explicit `NO_EXPOSURE_DENOMINATOR` on every output |
| R4 | ONISR republishes corrected files (2023, 2024 precedents) | silent data drift | E0 hash gate; manifests; rebuild |
| R5 | 2019–2020 lower coordinate precision; 2020 COVID | spatial and temporal bias | break flags; sensitivity analyses |
| R6 | `catr = 7` and EDP/VAE codes unstable over time | misleading category trends | `CATR7_UNSTABLE`, `EDP_VAE_CATEGORIES`; group 4+7 for trends |
| R7 | PostGIS not installed | blocks Phase 3 | D-04 |
| R8 | Phase 1B investigation exists only as chat output | weaker audit trail | recommend saving it as `reports/phase1/critical_investigation.md` (not done — outside this phase's deliverables) |

## H. Open questions requiring your approval

1. **D-04** PostGIS via Docker container (recommended) or native install into PostgreSQL 18.6.
2. **D-05** Add `psycopg`, `SQLAlchemy`, `GeoAlchemy2` in Phase 3.
3. **D-10** Lieux conflict rule: NULL + flag (recommended) vs. most-severe value.
4. **D-19** Approve the 11 proposed coordinate corrections for analytical use (yes/no).
5. **D-20** Exclude `wrong_commune_same_dep` from default hotspots (recommended) vs. include.
6. Whether to add Paris/Lyon/Marseille arrondissement polygons (`ref.ign_arrondissement_municipal`, available in the 2025 GeoPackage).
7. Whether to save the Phase 1B investigation as a report file (R8).
