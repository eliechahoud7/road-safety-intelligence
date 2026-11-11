-- Phase 3 Step 3 — reference data (IGN, INSEE, commune harmonisation, Phase 1C/1D results)
-- Design: reports/phase2/database_schema.md §3–4, geographic_data_model.md. Idempotent.

-- project-derived evidence files (Phase 1C / 1D outputs) are registered as lineage sources too
ALTER TABLE meta.source_file DROP CONSTRAINT IF EXISTS source_file_source_system_check;
ALTER TABLE meta.source_file ADD CONSTRAINT source_file_source_system_check
    CHECK (source_system IN ('BAAC', 'IGN', 'INSEE', 'ONISR_DOC', 'PROJECT_DERIVED'));

-- ---------------------------------------------------------------- INSEE staging (text, untouched)
CREATE TABLE IF NOT EXISTS staging.stg_insee_mvt_commune (
    source_file_id integer NOT NULL REFERENCES meta.source_file, source_row_number integer NOT NULL,
    load_run_id integer NOT NULL REFERENCES meta.load_run,
    mod text, date_eff text, typecom_av text, com_av text, tncc_av text, ncc_av text, nccenr_av text, libelle_av text,
    typecom_ap text, com_ap text, tncc_ap text, ncc_ap text, nccenr_ap text, libelle_ap text,
    PRIMARY KEY (source_file_id, source_row_number));

CREATE TABLE IF NOT EXISTS staging.stg_insee_commune_period (
    source_file_id integer NOT NULL REFERENCES meta.source_file, source_row_number integer NOT NULL,
    load_run_id integer NOT NULL REFERENCES meta.load_run,
    typecom text, com text, tncc text, ncc text, nccenr text, libelle text, date_debut text, date_fin text,
    PRIMARY KEY (source_file_id, source_row_number));

-- ---------------------------------------------------------------- IGN ADMIN EXPRESS COG (metropolitan, EPSG:2154)
CREATE TABLE IF NOT EXISTS ref.ign_commune (
    edition_year     smallint NOT NULL CHECK (edition_year BETWEEN 2019 AND 2025),
    insee_com        char(5)  NOT NULL,
    insee_dep        varchar(3) NOT NULL,
    commune_name     text,
    geom             geometry(MultiPolygon, 2154) NOT NULL,
    geom_was_invalid boolean  NOT NULL,
    source_file_id   integer  NOT NULL REFERENCES meta.source_file,
    PRIMARY KEY (edition_year, insee_com));
-- The 2019 edition's COMMUNE layer also contains the 45 Paris/Lyon/Marseille municipal arrondissements
-- (source field TYPE = 'ARM'), overlapping their parent communes 75056 / 69123 / 13055.
-- Commune-level spatial operations must filter commune_type = 'COM'.
ALTER TABLE ref.ign_commune ADD COLUMN IF NOT EXISTS commune_type varchar(3) NOT NULL DEFAULT 'COM'
    CHECK (commune_type IN ('COM', 'ARM'));
CREATE INDEX IF NOT EXISTS ign_commune_geom_gix ON ref.ign_commune USING gist (geom);
CREATE INDEX IF NOT EXISTS ign_commune_dep_idx ON ref.ign_commune (edition_year, insee_dep);

CREATE TABLE IF NOT EXISTS ref.ign_departement (
    edition_year     smallint NOT NULL CHECK (edition_year BETWEEN 2019 AND 2025),
    insee_dep        varchar(3) NOT NULL,
    departement_name text,
    geom             geometry(MultiPolygon, 2154) NOT NULL,
    geom_was_invalid boolean  NOT NULL,
    source_file_id   integer  NOT NULL REFERENCES meta.source_file,
    PRIMARY KEY (edition_year, insee_dep));
CREATE INDEX IF NOT EXISTS ign_departement_geom_gix ON ref.ign_departement USING gist (geom);

-- ---------------------------------------------------------------- INSEE COG 2026 (typed)
CREATE TABLE IF NOT EXISTS ref.insee_cog_event (
    event_id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mod               smallint NOT NULL CHECK (mod IN (10,20,21,30,31,32,33,34,35,41,50,70,71,72)),
    date_eff          date     NOT NULL,
    typecom_av        varchar(4) CHECK (typecom_av IN ('COM','COMA','COMD','ARM')),
    com_av            char(5)  NOT NULL,
    libelle_av        text,
    typecom_ap        varchar(4) CHECK (typecom_ap IN ('COM','COMA','COMD','ARM')),
    com_ap            char(5)  NOT NULL,
    libelle_ap        text,
    source_file_id    integer  NOT NULL REFERENCES meta.source_file,
    source_row_number integer  NOT NULL,
    UNIQUE (source_file_id, source_row_number));
CREATE INDEX IF NOT EXISTS insee_cog_event_av_idx ON ref.insee_cog_event (com_av, date_eff);
CREATE INDEX IF NOT EXISTS insee_cog_event_ap_idx ON ref.insee_cog_event (com_ap);

CREATE TABLE IF NOT EXISTS ref.insee_commune_period (
    typecom           varchar(4) NOT NULL CHECK (typecom IN ('COM','ARM')),
    com               char(5)  NOT NULL,
    libelle           text     NOT NULL,
    date_debut        date     NOT NULL,
    date_fin          date,                         -- NULL = still active (COG 2026)
    source_file_id    integer  NOT NULL REFERENCES meta.source_file,
    source_row_number integer  NOT NULL,
    PRIMARY KEY (typecom, com, date_debut));
CREATE INDEX IF NOT EXISTS insee_commune_period_com_idx ON ref.insee_commune_period (com);

-- ---------------------------------------------------------------- commune code harmonisation (all BAAC codes)
CREATE TABLE IF NOT EXISTS ref.commune_code_harmonisation (
    com_original                   text PRIMARY KEY,          -- trimmed BAAC value, never altered otherwise
    status_2026                    text NOT NULL CHECK (status_2026 IN
                                     ('active_com','active_arm','obsolete_resolved','unresolved','out_of_cog_scope')),
    arm_parent_com                 char(5),
    com_cog_2026                   char(5),
    transformation_class           text NOT NULL CHECK (transformation_class IN
                                     ('identity','arrondissement_to_commune','merger','code_change_one_to_one',
                                      'merger_chain','unresolved','out_of_scope')),
    first_mod                      smallint,
    n_steps                        smallint NOT NULL,
    chain                          text,
    obsolete_since                 date,
    became_delegated_or_associated varchar(9),
    accidents_2019_2025            integer NOT NULL,          -- informative: staging occurrences
    years_seen                     text NOT NULL,
    cog_reference                  text NOT NULL DEFAULT 'COG 2026',
    CHECK ((status_2026 IN ('unresolved','out_of_cog_scope')) = (com_cog_2026 IS NULL)));
CREATE INDEX IF NOT EXISTS commune_code_harmonisation_cog2026_idx ON ref.commune_code_harmonisation (com_cog_2026);

-- ---------------------------------------------------------------- Phase 1C / 1D results (as produced, typed)
CREATE TABLE IF NOT EXISTS ref.geo_validation_phase1c (
    num_acc                    bigint PRIMARY KEY,
    year                       smallint NOT NULL,
    dep_raw text, com_raw text, dep text, com text, com_norm text,
    lat_raw text NOT NULL, long_raw text NOT NULL,              -- original coordinate strings
    lat double precision, lon double precision,
    category                   text NOT NULL CHECK (category IN
                                 ('valid','nearby_commune','wrong_commune_same_dep','wrong_department','swapped',
                                  'placeholder_invalid','outside_coverage','commune_code_unresolved','out_of_scope_non_metro')),
    placeholder_reason         text,
    com_point text, com_point_dep text, dep_point text,
    dist_declared_m            double precision,
    swap_dist_declared_m       double precision,
    lonsign_dist_declared_m    double precision,
    lonsign_would_match        boolean,
    declared_in_edition        boolean,
    declared_in_any_edition    boolean,
    dep_layer_vs_commune_dep_mismatch boolean,
    source_file_id             integer NOT NULL REFERENCES meta.source_file);
CREATE INDEX IF NOT EXISTS geo_validation_phase1c_cat_idx ON ref.geo_validation_phase1c (year, category);

CREATE TABLE IF NOT EXISTS ref.coordinate_correction_proposal (
    num_acc                    bigint PRIMARY KEY REFERENCES ref.geo_validation_phase1c,
    method                     text NOT NULL CHECK (method IN ('swap_lat_long','flip_longitude_sign')),
    lat_original text NOT NULL, long_original text NOT NULL,
    lat_corrected double precision NOT NULL, lon_corrected double precision NOT NULL,
    evidence_distance_to_declared_commune_m double precision NOT NULL,
    correction_status          text NOT NULL DEFAULT 'proposed' CHECK (correction_status IN ('proposed','approved','rejected')),
    source_file_id             integer NOT NULL REFERENCES meta.source_file);

CREATE TABLE IF NOT EXISTS ref.obsolete_code_mapping_phase1d (
    num_acc                    bigint PRIMARY KEY REFERENCES ref.geo_validation_phase1c,
    year smallint NOT NULL, acc_date date NOT NULL,
    com_original text NOT NULL,
    transformation_class       text NOT NULL,
    is_comd_or_coma_on_accident_date boolean,
    successor_at_accident_date char(5),
    successor_2026             char(5),
    status_at_accident_date    text NOT NULL,
    com_from_point_admin_express text,
    point_in_successor_at_date boolean NOT NULL,
    mapping_confidence         text NOT NULL,
    source_file_id             integer NOT NULL REFERENCES meta.source_file);
