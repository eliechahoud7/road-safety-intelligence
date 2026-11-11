# Phase 3 — Step 5: Analytical Layer
**Road Safety Intelligence — France** · 2026-11-11 · Database `road_safety` (PostgreSQL 18.6 / PostGIS 3.6.4)

Result: **analytics layer built from the clean tables; 19 / 19 essential checks pass** (build `load_run_id = 14`, validation `load_run_id = 15`). Build time ≈ 7 s. No raw, staging, clean or geographic data reloaded or modified; no correction applied; no statistical analysis performed.

---

## 1. Files created / modified

| Path | Type | Purpose |
|---|---|---|
| `db/sql/050_analytics_layer.sql` | new | `ref.methodological_break`, 3 summary views, `analytics.accident_fact` (materialised), 5 views |
| `scripts/17_build_analytics.py` | new | applies the SQL in one transaction (idempotent: drop + create) |
| `scripts/18_validate_analytics.py` | new | essential checks A1–A8 → `meta.dq_check` (layer `analytics`) |
| `reports/phase3/step5_analytical_layer_report.md` | new | this report |

## 2. Objects created (approved Phase 2 design, minimal storage)

Only **one** object stores data (`accident_fact`); all others are views (no duplicated data).

| Object | Kind | Grain | Rows | Purpose |
|---|---|---|---|---|
| `analytics.accident_casualty_summary` | view | accident (all) | 382 721 | users by severity (killed / hospitalised / light / unhurt / unknown), fugitive-like, drivers / passengers / pedestrians |
| `analytics.accident_vehicle_summary` | view | accident (all) | 382 721 | vehicle count, vehicles without user, category flags (bicycle, e-bike, EDP, powered 2/3-wheeler, car, LCV, HGV, bus/coach) |
| `analytics.accident_location_summary` | view | accident (all) | 382 721 | Lieux collapsed: `n_segments`; for catr, circ, prof, plan, surf, infra, situ, nbv, vma → single value or **NULL + `*_conflict`**; vma_min/max; cycle facility / reserved lane flags |
| **`analytics.accident_fact`** | **materialised view** | **metropolitan accident** | **361 593** | main dataset: date, year, month, weekday, weekend, hour, time-of-day band, season; lum, atm, agg, intersection, col; severity counts + `accident_severity`; vehicle summary; location summary + conflicts; dep / commune ids (original, arrondissement, at-date, COG 2026, mapping class & confidence); original + parsed coordinates, `geom` (2154); Phase 1C category, correction-proposal flag, `spatial_eligibility`, `in_default_hotspot_population`; `is_covid_year`, `fugitive_regime`, `lieux_regime` |
| `analytics.road_user_fact` | view | road user (metro) | 821 517 | user attributes incl. `age_group`, sex, category, severity + vehicle category + accident context |
| `analytics.vehicle_fact` | view | vehicle (metro) | 617 688 | vehicle attributes + accident context |
| `analytics.agg_year_department` | view | year × department | 672 (96 × 7) | accidents, fatal accidents, casualties by severity, users, vehicles, spatially eligible accidents |
| `analytics.agg_year_commune` | view | year × `com_cog_2026` | — | same measures at commune level (COG 2026); NULL group = `N/C` |
| `analytics.hotspot_point` | view | eligible accident | 360 934 | default hotspot population with geometry (2154) and lon/lat for display |
| `ref.methodological_break` | table | break | 11 | COVID 2020, non-certified hospitalised indicator, 2018 break, fugitive users 2021, grav −1, Lieux 2023 (structure, coding), catr 7, EDP/VAE codes, 2019–20 coordinate precision, **no exposure denominator** |

Indexes on `accident_fact`: unique `num_acc`; `year`; `(dep_code, year)`; `com_cog_2026`; GiST `geom`.

### Grain safety
Users, vehicles and Lieux reach the accident grain only through their 1-row-per-accident summary views; row-level views join only child → parent. `accident_fact` is restricted to metropolitan accidents (`clean.accident.is_metro`).

### Spatial eligibility (metropolitan accidents; approved D-19/D-20)
| `spatial_eligibility` | Accidents | Default hotspot population |
|---|---|---|
| eligible_exact (Phase 1C valid) | 354 708 | yes |
| eligible_tolerance (≤ 500 m) | 5 647 | yes |
| eligible_after_code_harmonisation (Phase 1D high) | 579 | yes |
| review_wrong_commune | 606 | no — sensitivity only |
| review_code_harmonisation (Phase 1D medium) | 18 | no |
| excluded_wrong_department | 23 | no |
| excluded_outside_coverage | 5 | no |
| excluded_swapped_correction_not_applied | 4 | no |
| excluded_placeholder | 2 | no |
| excluded_unresolved_code (`N/C`) | 1 | no |
| **Default population** | **360 934 (99.82 %)** | |

Accident severity (metropolitan): light 232 817 · hospitalised 108 392 · fatal 20 384 (every accident has ≥ 1 recorded victim).

## 3. Validation results (run 15) — 19 / 19 pass

| # | Check | Result |
|---|---|---|
| A1 | `accident_fact` = 361 593 = metropolitan accidents in `clean.accident` | pass |
| A2 | one row per accident in `accident_fact` and in the 3 summaries (382 721 each) | 4 pass |
| A3 | Σ users / killed / hospitalised / light / unhurt / grav unknown / fugitive-like = `clean.road_user` (metro): 821 517 / 21 619 / 125 312 / 328 076 / 346 145 / 365 / 12 107; `road_user_fact` = 821 517; all-territory summary = 871 534 | 3 pass |
| A4 | Σ vehicles = `clean.vehicle` (metro) 617 688; `vehicle_fact` = 617 688; all-territory summary = 653 712 | 3 pass |
| A5 | 407 657 metro road segments aggregated into 361 593 rows (no inflation); conflict flags only on multi-segment accidents (45 517 multi-segment; vma conflict 5 379, surf 458, catr 0) | 2 pass |
| A6 | department and commune aggregates reconcile with `accident_fact` (accidents, killed, vehicles, users); 96 departments, no duplicate (year, dep) | 3 pass |
| A7 | no NULL `num_acc`, year, dep_code, geom, eligibility, severity; `com_cog_2026` NULL only for `N/C`; no duplicate ids in fact views | 2 pass |
| A8 | all 7 years with expected counts (56 016 · 45 121 · 53 540 · 52 380 · 51 641 · 51 058 · 51 837) | pass |

## 4. Limitations

1. **Concentration, not risk** — no traffic-volume denominator; stated in `ref.methodological_break` and in view comments.
2. Category variables are stored as ONISR codes; human-readable labels (`ref.code_label` in the Phase 2 design) are **not yet populated** — needed before the dashboard.
3. `accident_severity` "hospitalised" relies on a non-certified indicator (`HOSP_NOT_CERTIFIED`).
4. User totals across 2020/2021 need `n_users_excl_fugitive`; location attributes across 2022/2023 need `lieux_regime` / conflict flags.
5. The 11 coordinate corrections remain unapplied; 4 swapped and 7 sign-error accidents stay outside the default hotspot population (sign errors fall under `review_wrong_commune` / `excluded_wrong_department`).
6. `agg_year_commune` contains no geometry; maps must join `ref.ign_commune` (edition 2025, `commune_type = 'COM'`).
7. Overseas accidents are excluded from all analytical objects except the three all-territory summary views.
