# Phase 3 — Step 3: Reference Data
**Road Safety Intelligence — France** · 2026-11-11 · Database `road_safety` (PostgreSQL 18.6 / PostGIS 3.6.4)

Result: **reference data loaded; 157 / 158 validation checks pass, 1 warning, 0 failures** (validation run `load_run_id = 9`, on data from load run 8). No file was downloaded; raw files verified against their manifests before loading; staging data unchanged.

---

## 1. Files created / modified

| Path | Type | Purpose |
|---|---|---|
| `db/sql/030_ref_reference_data.sql` | new | INSEE staging tables, 9 `ref` tables, indexes; extends `meta.source_file.source_system` with `PROJECT_DERIVED` (Phase 1C/1D evidence files) |
| `scripts/13_load_reference_data.py` | new | hash gate → DDL → source registration → INSEE → IGN → harmonisation → Phase 1C/1D (one transaction, psycopg only) |
| `scripts/14_validate_reference_data.py` | new | checks R1–R8 → `meta.dq_check` (layer `ref`) |
| `reports/phase3/step3_reference_data_report.md` | new | this report |

No raw file, staging table, earlier script or earlier report was modified. SQLAlchemy / GeoAlchemy2 were **not** needed: geometries are sent as EWKB through `COPY` and reprojected/repaired in PostGIS.

## 2. Imported datasets

| Table | Rows | Content |
|---|---|---|
| `ref.ign_commune` | 34 886 · 34 839 · 34 836 · 34 826 · 34 816 · 34 806 · 34 746 (2019 → 2025) | metropolitan commune polygons per ADMIN EXPRESS COG edition, `MultiPolygon` EPSG:2154; `commune_type` (`COM`/`ARM`), `geom_was_invalid` |
| `ref.ign_departement` | 96 per edition (672) | metropolitan department polygons, EPSG:2154 |
| `staging.stg_insee_mvt_commune` → `ref.insee_cog_event` | 13 734 → 13 734 | INSEE COG 2026 events since 1943 (text untouched → typed) |
| `staging.stg_insee_commune_period` → `ref.insee_commune_period` | 42 333 → 42 333 | INSEE commune code/label validity periods |
| `ref.commune_code_harmonisation` | 25 588 | one row per distinct BAAC commune code (all years, all territories) → `com_cog_2026` |
| `ref.geo_validation_phase1c` | 382 721 | Phase 1C results incl. original `dep`/`com`/`lat`/`long` strings and categories |
| `ref.coordinate_correction_proposal` | 11 | 4 `swap_lat_long`, 7 `flip_longitude_sign` — status **`proposed`, not applied** |
| `ref.obsolete_code_mapping_phase1d` | 598 | Phase 1D accident-level mapping (579 high, 18 medium, 1 none) |
| `meta.source_file` | +12 | 7 IGN archives, 2 INSEE files, 3 Phase 1C/1D evidence files (with SHA-256) |

Database size after Step 3: 3.5 GB (`ref.ign_commune` 2.4 GB, `ref.ign_departement` 254 MB).

### Identifiers preserved
- `com_original` = trimmed BAAC code (incl. arrondissement codes 751xx / 6938x / 132xx and `N/C`); `arm_parent_com` for arrondissements; `com_cog_2026`; `transformation_class`, `chain`, `first_mod`, `obsolete_since`, `became_delegated_or_associated`.
- Arrondissement **identifiers** kept; no arrondissement boundaries acquired.
- Phase 1C original coordinate strings (`lat_raw`, `long_raw`) and categories kept as produced; Phase 1D `successor_at_accident_date`, `successor_2026`, `mapping_confidence` kept.

### Commune harmonisation coverage (metropolitan accidents)
| Class | Codes | Accidents |
|---|---|---|
| identity (active COM 2026) | 25 042 | 313 631 |
| arrondissement → parent commune | 45 | 46 883 |
| obsolete → resolved: merger | 293 | 994 |
| obsolete → resolved: one-to-one code change (MOD 41/50) | 8 | 79 |
| obsolete → resolved: merger chain (2 steps) | 5 | 5 |
| unresolved (`N/C`, 2022) | 1 | 1 |
| **Total** | **25 394** | **361 593** (361 592 harmonised) |

Non-metropolitan codes: DROM codes covered by INSEE; 69 overseas-collectivity codes `out_of_cog_scope` (INSEE file covers metro + DROM only).

## 3. Validation results (`meta.dq_check`, run 9)

| Check | Result |
|---|---|
| R1 commune / department counts = source layers (re-read) = Phase 1C reference counts | 14 / 14 pass |
| R2 geometries valid, `MULTIPOLYGON`, non-empty | 14 / 14 pass |
| R2 invalid inputs flagged (2019: 4 communes, 4 departments; others 0) | 14 / 14 pass |
| R2 Σ commune area = Σ department area (< 0.1 %) per edition; department area stable across editions (548 858–548 867 km²) | 8 / 8 pass |
| R2 arrondissement polygons flagged (`ARM`: 45, 2019 only); 2019 communes excl. ARM = 34 841 | 2 / 2 pass |
| R2 no interior overlap between `COM` polygons | **1 warning** (§4) |
| R3 SRID 2154 declared and on every row | 4 / 4 pass |
| R3 known points: Paris → 75056, Ajaccio → 2A004, Bastia → 2B033 in all 7 editions | 3 / 3 pass |
| R4 INSEE rows: file = staging = typed (13 734 / 42 333); 127 empty `TYPECOM_AV` kept as source; all successors active in COG 2026 | 4 / 4 pass |
| R5 all 25 588 BAAC codes covered; metro class counts; every metro accident harmonised except `N/C` (each year 2019–2025); `com_cog_2026` ∈ IGN 2025; agreement with Phase 1D | 14 / 14 pass |
| R6 382 721 validation records = staging accidents; category × year counts = Phase 1C (63 cells); 11 corrections `proposed`; 598 Phase 1D rows | 66 / 66 pass |
| R7 Phase 1C accidents and original `dep`/`com`/`lat`/`long` strings identical to staging; corrections & Phase 1D consistent with categories; lineage FKs | 10 / 10 pass |
| R8 staging tables unchanged (row count + MD5 fingerprint before/after Step 3) | 4 / 4 pass |
| **Total** | **157 pass · 1 warn · 0 fail** |

## 4. Warning: overlapping commune polygons (documented limitation)

- **Pair:** `59078` Beugnies and `59240` Floursies (Nord), **2019 edition only**.
- **Intersection area:** **60.5 m²**; neither input geometry was invalid.
- **Assessment:** a small topology artefact in the IGN 2019 source boundaries (shared border not perfectly coincident), not a data-loading error; the geometries were not altered. 60.5 m² is negligible for 2019 point validation (an accident would have to fall inside this sliver; it would then match one of two adjacent communes).
- **Treatment:** kept as published; documented as a limitation. Not investigated further, per instruction.

## 5. Problems encountered (reported honestly)

1. **Validation-script bug (fixed)** — run 7 reported 5 failures; 4 were false failures caused by tuple unpacking in the script (e.g. `(13734,)` compared with `13734`). Fixed; data were correct.
2. **2019 IGN layer contains arrondissement polygons (fixed in model, source unchanged)** — the 2019 `COMMUNE` layer includes the 45 Paris/Lyon/Marseille municipal arrondissements (source field `TYPE = 'ARM'`) overlapping their parent communes; later editions do not. Added `ref.ign_commune.commune_type` (from the source field) and re-ran the reference load once (run 8). Commune-level spatial work must filter `commune_type = 'COM'`. Phase 1C was not affected: none of the 8 484 Paris/Lyon/Marseille 2019 points was matched to an arrondissement polygon.
3. **Load duration** — a full reference load takes > 10 minutes (≈ 2 GB of geometry); it ran in the background.
4. Database size 3.5 GB, dominated by full-precision commune polygons for 7 editions (as designed).

## 6. Notes for Step 4
- Spatial validation in the clean layer must use `commune_type = 'COM'` and the edition matching the accident year.
- The 11 corrections remain proposals in `ref.coordinate_correction_proposal`; no coordinate was changed.
