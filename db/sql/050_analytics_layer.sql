-- Phase 3 Step 5 — ANALYTICS layer (approved design: reports/phase2/database_schema.md §6, D-20, D-21)
-- Storage policy: ONE materialised view (analytics.accident_fact); everything else is a plain view.
-- Grain rules: every object joins only child -> parent (many-to-one); Lieux / vehicles / users reach the
-- accident grain only through the 1-row-per-accident summary views below.
-- Rebuilt idempotently (drop + create).

DROP VIEW IF EXISTS analytics.hotspot_point, analytics.agg_year_commune, analytics.agg_year_department,
                    analytics.road_user_fact, analytics.vehicle_fact CASCADE;
DROP MATERIALIZED VIEW IF EXISTS analytics.accident_fact CASCADE;
DROP VIEW IF EXISTS analytics.accident_location_summary, analytics.accident_casualty_summary,
                    analytics.accident_vehicle_summary CASCADE;

-- ------------------------------------------------------------------ methodological breaks (design: ref schema)
CREATE TABLE IF NOT EXISTS ref.methodological_break (
    break_code            text PRIMARY KEY,
    effective_from        date,
    effective_to          date,
    affected_objects      text[] NOT NULL,
    description           text NOT NULL,
    evidence              text NOT NULL,
    recommended_treatment text NOT NULL);
TRUNCATE ref.methodological_break;
INSERT INTO ref.methodological_break VALUES
 ('COVID_2020', '2020-01-01', '2020-12-31', '{accident_fact.year}', 'Lockdowns: 45 121 metro accidents (lowest month 1 208).',
  'reports/phase1/tables/06_temporal_identity_checks.csv', 'Treat 2020 as an outlier (accident_fact.is_covid_year).'),
 ('HOSP_NOT_CERTIFIED', '2019-01-01', NULL, '{road_user.grav=3, accident_fact.n_hospitalised}', 'Indicator "blessé hospitalisé" no longer certified by the official-statistics authority since 2019.',
  'ONISR description des bases 2005-2025', 'Label hospitalised outputs as not certified; prefer killed / accident counts for trends.'),
 ('HOSP_BREAK_2018', '2018-01-01', NULL, '{road_user.grav=3}', 'Hospitalised injuries not comparable with years before 2018.',
  'ONISR description des bases 2005-2025', 'No comparison with years <= 2017 (outside core period).'),
 ('FUGITIVE_USERS_2021', '2021-01-01', NULL, '{road_user.is_fugitive_like, vehicle.has_no_user}', 'From 2021 fugitive users are recorded (sex/age missing); in 2019-2020 they appear as vehicles without users.',
  'reports/phase3/step4_clean_layer_report.md', 'Use n_users_excl_fugitive for user totals; victim counts unaffected.'),
 ('PSEUDO_GRAV_MINUS1_2021_2023', '2021-01-01', '2023-12-31', '{road_user.grav}', 'grav = -1 (undocumented) for 60 / 241 / 118 users.',
  'reports/phase1/data_quality_report.md', 'Counted as n_grav_unknown; never as victims.'),
 ('LIEUX_MULTIROW_2023', '2023-01-01', NULL, '{accident_location, accident_fact.n_segments}', 'Several Lieux rows per accident at intersections from 2023 (one row 2019-2022, selection rule unknown).',
  'data.gouv.fr discussion lieux-2023 (ONISR reply 2024-12-12)', 'Use accident_fact location columns with *_conflict flags and lieux_regime.'),
 ('LIEUX_CODING_2023', '2023-01-01', NULL, '{accident_location.pr, pr1, vma, nbv, vosp}', 'pr/pr1 "(1)" -> "-1"; missing vma/nbv/vosp rise from ~1 % to ~5-6 %.',
  'reports/phase1/tables/17_missingness_pct.csv', 'Compare these fields across 2022/2023 only with caution.'),
 ('CATR7_UNSTABLE', '2019-01-01', NULL, '{accident_location.catr=7}', 'catr 7 (urban metropolitan roads) count fluctuates 710-2 782 per year.',
  'Phase 1B investigation', 'Group catr 4 + 7 for trends.'),
 ('EDP_VAE_CATEGORIES', '2019-01-01', NULL, '{vehicle.catv in (50,60,80)}', 'Personal mobility devices and e-bikes: real growth mixed with adoption of new codes.',
  'Phase 1B investigation', 'Interpret trends of these categories with caution.'),
 ('COORD_PRECISION_2019_2020', '2019-01-01', '2020-12-31', '{accident_fact.geom, geo_category}', 'Lower coordinate precision (more nearby / wrong-commune points).',
  'reports/geography/geographic_validation_report.md', 'Flag in multi-year hotspot comparisons.'),
 ('NO_EXPOSURE_DENOMINATOR', NULL, NULL, '{analytics.*}', 'No traffic-volume data: counts and densities measure concentration of recorded injury accidents, not risk.',
  'reports/phase2/phase2_design_decisions.md', 'Never present hotspots or counts as risk rates.');

-- ------------------------------------------------------------------ 1-row-per-accident summaries (views, all accidents)
CREATE VIEW analytics.accident_casualty_summary AS
SELECT num_acc,
       count(*)::int                                           AS n_users,
       count(*) FILTER (WHERE grav = 2)::int                   AS n_killed,
       count(*) FILTER (WHERE grav = 3)::int                   AS n_hospitalised,
       count(*) FILTER (WHERE grav = 4)::int                   AS n_light,
       count(*) FILTER (WHERE grav = 1)::int                   AS n_unhurt,
       count(*) FILTER (WHERE grav IS NULL)::int               AS n_grav_unknown,
       count(*) FILTER (WHERE is_fugitive_like)::int           AS n_fugitive_like,
       count(*) FILTER (WHERE NOT is_fugitive_like)::int       AS n_users_excl_fugitive,
       count(*) FILTER (WHERE catu = 1)::int                   AS n_drivers,
       count(*) FILTER (WHERE catu = 2)::int                   AS n_passengers,
       count(*) FILTER (WHERE catu = 3)::int                   AS n_pedestrians,
       count(*) FILTER (WHERE catu = 3 AND grav = 2)::int      AS n_pedestrians_killed
FROM clean.road_user GROUP BY num_acc;

CREATE VIEW analytics.accident_vehicle_summary AS
SELECT num_acc,
       count(*)::int                                                         AS n_vehicles,
       count(*) FILTER (WHERE has_no_user)::int                              AS n_vehicles_without_user,
       bool_or(catv = 1)                                                     AS any_bicycle,
       bool_or(catv = 80)                                                    AS any_e_bike,
       bool_or(catv IN (50, 60))                                             AS any_personal_mobility_device,
       bool_or(catv IN (2, 30, 31, 32, 33, 34, 41, 42, 43))                  AS any_powered_2_3_wheeler,
       bool_or(catv = 7)                                                     AS any_car,
       bool_or(catv = 10)                                                    AS any_light_commercial,
       bool_or(catv BETWEEN 13 AND 17)                                       AS any_heavy_goods,
       bool_or(catv IN (37, 38))                                             AS any_bus_coach,
       count(*) FILTER (WHERE catv IS NULL)::int                             AS n_vehicles_catv_unknown
FROM clean.vehicle GROUP BY num_acc;

-- conflict rule (approved D-10): one distinct non-NULL value -> that value; several -> NULL + conflict flag
CREATE VIEW analytics.accident_location_summary AS
SELECT num_acc,
       count(*)::smallint                                                    AS n_segments,
       CASE WHEN count(DISTINCT catr) = 1 THEN min(catr) END                 AS catr,
       count(DISTINCT catr) > 1                                              AS catr_conflict,
       CASE WHEN count(DISTINCT circ) = 1 THEN min(circ) END                 AS circ,
       count(DISTINCT circ) > 1                                              AS circ_conflict,
       CASE WHEN count(DISTINCT prof) = 1 THEN min(prof) END                 AS prof,
       count(DISTINCT prof) > 1                                              AS prof_conflict,
       CASE WHEN count(DISTINCT plan) = 1 THEN min(plan) END                 AS plan,
       count(DISTINCT plan) > 1                                              AS plan_conflict,
       CASE WHEN count(DISTINCT surf) = 1 THEN min(surf) END                 AS surf,
       count(DISTINCT surf) > 1                                              AS surf_conflict,
       CASE WHEN count(DISTINCT infra) = 1 THEN min(infra) END               AS infra,
       count(DISTINCT infra) > 1                                             AS infra_conflict,
       CASE WHEN count(DISTINCT situ) = 1 THEN min(situ) END                 AS situ,
       count(DISTINCT situ) > 1                                              AS situ_conflict,
       CASE WHEN count(DISTINCT nbv) = 1 THEN min(nbv) END                   AS nbv,
       count(DISTINCT nbv) > 1                                               AS nbv_conflict,
       CASE WHEN count(DISTINCT vma) = 1 THEN min(vma) END                   AS vma,
       count(DISTINCT vma) > 1                                               AS vma_conflict,
       min(vma)                                                              AS vma_min,
       max(vma)                                                              AS vma_max,
       coalesce(bool_or(NOT vma_plausible), false)                           AS vma_any_implausible,
       coalesce(bool_or(vosp IN (1, 2)), false)                              AS any_cycle_facility,
       coalesce(bool_or(vosp = 3), false)                                    AS any_reserved_lane
FROM clean.accident_location GROUP BY num_acc;

-- ------------------------------------------------------------------ accident_fact: 1 row per METROPOLITAN accident
CREATE MATERIALIZED VIEW analytics.accident_fact AS
SELECT a.num_acc, a.year, a.acc_date,
       extract(month FROM a.acc_date)::smallint                                         AS month,
       a.weekday, a.weekday >= 6                                                         AS is_weekend,
       a.acc_time, a.hour,
       CASE WHEN a.hour < 6 THEN 'night_00_05' WHEN a.hour < 12 THEN 'morning_06_11'
            WHEN a.hour < 18 THEN 'afternoon_12_17' ELSE 'evening_18_23' END            AS time_of_day,
       CASE WHEN extract(month FROM a.acc_date) IN (12, 1, 2) THEN 'winter'
            WHEN extract(month FROM a.acc_date) IN (3, 4, 5) THEN 'spring'
            WHEN extract(month FROM a.acc_date) IN (6, 7, 8) THEN 'summer' ELSE 'autumn' END AS season,
       -- conditions (codes as in clean layer; NULL = not recorded)
       a.lum, a.atm, a.agg, a.intersection, a.col,
       -- severity (from casualty summary)
       cs.n_users, cs.n_killed, cs.n_hospitalised, cs.n_light, cs.n_unhurt, cs.n_grav_unknown,
       cs.n_killed + cs.n_hospitalised + cs.n_light                                     AS n_victims,
       cs.n_fugitive_like, cs.n_users_excl_fugitive, cs.n_drivers, cs.n_passengers, cs.n_pedestrians,
       cs.n_pedestrians_killed,
       CASE WHEN cs.n_killed > 0 THEN 'fatal' WHEN cs.n_hospitalised > 0 THEN 'hospitalised'
            WHEN cs.n_light > 0 THEN 'light' WHEN cs.n_grav_unknown > 0 THEN 'unknown'
            ELSE 'no_injury_recorded' END                                               AS accident_severity,
       -- vehicles
       vs.n_vehicles, vs.n_vehicles_without_user, vs.n_vehicles_catv_unknown, vs.any_bicycle, vs.any_e_bike,
       vs.any_personal_mobility_device, vs.any_powered_2_3_wheeler, vs.any_car, vs.any_light_commercial,
       vs.any_heavy_goods, vs.any_bus_coach,
       -- road segments (Lieux collapsed; conflicts -> NULL + flag)
       ls.n_segments, ls.catr, ls.catr_conflict, ls.circ, ls.circ_conflict, ls.prof, ls.prof_conflict,
       ls.plan, ls.plan_conflict, ls.surf, ls.surf_conflict, ls.infra, ls.infra_conflict, ls.situ, ls.situ_conflict,
       ls.nbv, ls.nbv_conflict, ls.vma, ls.vma_conflict, ls.vma_min, ls.vma_max, ls.vma_any_implausible,
       ls.any_cycle_facility, ls.any_reserved_lane,
       -- geography
       a.dep_code, a.com_original, a.com_arm, a.com_cog_at_date, a.com_cog_2026, a.com_mapping_class,
       a.com_mapping_confidence, a.lat_original, a.long_original, a.lat, a.lon, a.geom_original AS geom,
       a.geo_category, a.geo_dist_declared_m, a.has_correction_proposal, a.correction_method,
       CASE WHEN a.geo_category = 'valid' THEN 'eligible_exact'
            WHEN a.geo_category = 'nearby_commune' THEN 'eligible_tolerance'
            WHEN a.geo_category = 'commune_code_unresolved' AND a.com_mapping_confidence = 'high' THEN 'eligible_after_code_harmonisation'
            WHEN a.geo_category = 'commune_code_unresolved' AND a.com_mapping_confidence = 'medium' THEN 'review_code_harmonisation'
            WHEN a.geo_category = 'commune_code_unresolved' THEN 'excluded_unresolved_code'
            WHEN a.geo_category = 'wrong_commune_same_dep' THEN 'review_wrong_commune'
            WHEN a.geo_category = 'swapped' THEN 'excluded_swapped_correction_not_applied'
            WHEN a.geo_category = 'wrong_department' THEN 'excluded_wrong_department'
            WHEN a.geo_category = 'placeholder_invalid' THEN 'excluded_placeholder'
            WHEN a.geo_category = 'outside_coverage' THEN 'excluded_outside_coverage' END AS spatial_eligibility,
       a.geo_category IN ('valid', 'nearby_commune')
         OR (a.geo_category = 'commune_code_unresolved' AND a.com_mapping_confidence = 'high') AS in_default_hotspot_population,
       -- comparability flags (see ref.methodological_break)
       a.year = 2020                                                                    AS is_covid_year,
       CASE WHEN a.year <= 2020 THEN 'fugitive_as_vehicle_without_user_2019_2020'
            ELSE 'fugitive_as_user_2021_2025' END                                       AS fugitive_regime,
       CASE WHEN a.year <= 2022 THEN 'single_segment_2019_2022'
            ELSE 'multi_segment_capable_2023_2025' END                                  AS lieux_regime
FROM clean.accident a
JOIN analytics.accident_casualty_summary cs USING (num_acc)
JOIN analytics.accident_vehicle_summary  vs USING (num_acc)
JOIN analytics.accident_location_summary ls USING (num_acc)
WHERE a.is_metro;

CREATE UNIQUE INDEX accident_fact_pk        ON analytics.accident_fact (num_acc);
CREATE INDEX accident_fact_year_idx         ON analytics.accident_fact (year);
CREATE INDEX accident_fact_dep_year_idx     ON analytics.accident_fact (dep_code, year);
CREATE INDEX accident_fact_cog2026_idx      ON analytics.accident_fact (com_cog_2026);
CREATE INDEX accident_fact_geom_gix         ON analytics.accident_fact USING gist (geom);

-- ------------------------------------------------------------------ row-level facts (views, many-to-one joins only)
CREATE VIEW analytics.road_user_fact AS
SELECT u.road_user_id, u.id_usager, u.num_acc, u.id_vehicule, u.catu, u.place, u.grav, u.severity_rank, u.is_victim,
       u.sexe, u.age_at_accident,
       CASE WHEN u.age_at_accident IS NULL THEN NULL WHEN u.age_at_accident < 15 THEN '00_14'
            WHEN u.age_at_accident < 18 THEN '15_17' WHEN u.age_at_accident < 25 THEN '18_24'
            WHEN u.age_at_accident < 35 THEN '25_34' WHEN u.age_at_accident < 45 THEN '35_44'
            WHEN u.age_at_accident < 55 THEN '45_54' WHEN u.age_at_accident < 65 THEN '55_64'
            WHEN u.age_at_accident < 75 THEN '65_74' ELSE '75_plus' END                  AS age_group,
       u.an_nais_placeholder, u.trajet, u.secu1, u.secu2, u.secu3, u.locp, u.actp, u.etatp, u.is_fugitive_like,
       v.catv, v.motor,
       f.year, f.month, f.hour, f.time_of_day, f.dep_code, f.com_cog_2026, f.accident_severity, f.agg, f.lum, f.atm,
       f.catr, f.is_covid_year, f.fugitive_regime
FROM clean.road_user u
JOIN clean.vehicle v USING (id_vehicule, num_acc)
JOIN analytics.accident_fact f USING (num_acc);

CREATE VIEW analytics.vehicle_fact AS
SELECT v.id_vehicule, v.num_acc, v.num_veh, v.catv, v.motor, v.obs, v.obsm, v.choc, v.manv, v.n_users, v.has_no_user,
       f.year, f.month, f.hour, f.dep_code, f.com_cog_2026, f.accident_severity, f.agg, f.catr, f.is_covid_year, f.fugitive_regime
FROM clean.vehicle v
JOIN analytics.accident_fact f USING (num_acc);

-- ------------------------------------------------------------------ geographic aggregates (views over accident_fact)
CREATE VIEW analytics.agg_year_department AS
SELECT year, dep_code,
       count(*)::int                                              AS n_accidents,
       count(*) FILTER (WHERE accident_severity = 'fatal')::int   AS n_fatal_accidents,
       sum(n_killed)::int AS n_killed, sum(n_hospitalised)::int AS n_hospitalised, sum(n_light)::int AS n_light,
       sum(n_unhurt)::int AS n_unhurt, sum(n_grav_unknown)::int AS n_grav_unknown, sum(n_users)::int AS n_users,
       sum(n_users_excl_fugitive)::int AS n_users_excl_fugitive, sum(n_vehicles)::int AS n_vehicles,
       count(*) FILTER (WHERE in_default_hotspot_population)::int AS n_accidents_spatially_eligible
FROM analytics.accident_fact GROUP BY year, dep_code;

CREATE VIEW analytics.agg_year_commune AS
SELECT year, com_cog_2026,                                         -- NULL = unresolved commune code (N/C)
       count(*)::int                                              AS n_accidents,
       count(*) FILTER (WHERE accident_severity = 'fatal')::int   AS n_fatal_accidents,
       sum(n_killed)::int AS n_killed, sum(n_hospitalised)::int AS n_hospitalised, sum(n_light)::int AS n_light,
       sum(n_unhurt)::int AS n_unhurt, sum(n_users)::int AS n_users, sum(n_vehicles)::int AS n_vehicles,
       count(*) FILTER (WHERE in_default_hotspot_population)::int AS n_accidents_spatially_eligible
FROM analytics.accident_fact GROUP BY year, com_cog_2026;

-- ------------------------------------------------------------------ default hotspot population (view)
CREATE VIEW analytics.hotspot_point AS
SELECT num_acc, year, month, hour, accident_severity, n_killed, n_hospitalised, n_light, n_victims,
       dep_code, com_cog_2026, spatial_eligibility, geom,
       lon, lat                                                     -- WGS84 values for Plotly display
FROM analytics.accident_fact
WHERE in_default_hotspot_population;

COMMENT ON MATERIALIZED VIEW analytics.accident_fact IS
  'One row per metropolitan accident 2019-2025. Counts = concentration of recorded injury accidents, NOT risk (no exposure data). Corrections not applied.';
COMMENT ON VIEW analytics.hotspot_point IS
  'Default hotspot population (valid + nearby <= 500 m + high-confidence harmonised codes). Excludes 606 wrong-commune points (sensitivity only). Concentration, not risk.';
