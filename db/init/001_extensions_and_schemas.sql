-- Road Safety Intelligence — database initialisation (Phase 3, Step 1)
-- Executed automatically by the postgis/postgis image on FIRST initialisation of the data volume,
-- connected to the database named by POSTGRES_DB. Idempotent (safe to re-run manually).

CREATE EXTENSION IF NOT EXISTS postgis;

-- Layers approved in Phase 2 (reports/phase2/architecture_design.md)
CREATE SCHEMA IF NOT EXISTS meta;       -- source files, load runs, data-quality checks
CREATE SCHEMA IF NOT EXISTS staging;    -- untouched source values as text + lineage
CREATE SCHEMA IF NOT EXISTS ref;        -- IGN / INSEE reference data, code labels, methodological breaks
CREATE SCHEMA IF NOT EXISTS clean;      -- typed, harmonised, flagged entities
CREATE SCHEMA IF NOT EXISTS analytics;  -- grain-safe views and materialised views

COMMENT ON SCHEMA meta      IS 'Lineage: source files, load runs, data-quality check results';
COMMENT ON SCHEMA staging   IS 'BAAC / INSEE source values as TEXT, untouched, with source_file_id + source_row_number';
COMMENT ON SCHEMA ref       IS 'Reference data: IGN ADMIN EXPRESS COG (EPSG:2154), INSEE COG 2026, codebook, methodological breaks';
COMMENT ON SCHEMA clean     IS 'Typed and harmonised accident / location / vehicle / road_user tables with quality flags';
COMMENT ON SCHEMA analytics IS 'Grain-safe analytical views; one-to-many Lieux collapsed before any join';
