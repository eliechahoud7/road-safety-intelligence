-- Phase 3 Step 2 — STAGING layer for BAAC 2019–2025
-- Design: reports/phase2/database_schema.md §3.
-- * One table per BAAC entity, all years together.
-- * Every value column is TEXT and holds the source value UNTOUCHED (whitespace, ' -1', 'N/A',
--   '(1)', '#VALEURMULTI', NBSP, decimal commas...). An empty CSV field is stored as '' (never NULL).
-- * NULL appears only where the column does not exist in that year's file (usagers.id_usager 2019–2020).
-- * Column names are canonical lower-case; exact source names are in meta.source_column.
-- * No CHECK / NOT NULL on value columns: constraints must never reject or alter a source record.
-- Idempotent.

CREATE TABLE IF NOT EXISTS staging.stg_baac_caracteristiques (
    source_file_id    integer  NOT NULL REFERENCES meta.source_file,
    source_year       smallint NOT NULL,
    source_row_number integer  NOT NULL,      -- 1-based data record number in the file (header excluded)
    load_run_id       integer  NOT NULL REFERENCES meta.load_run,
    num_acc text, jour text, mois text, an text, hrmn text, lum text, dep text, com text,
    agg text, "int" text, atm text, col text, adr text, lat text, long text,
    PRIMARY KEY (source_file_id, source_row_number)
);

CREATE TABLE IF NOT EXISTS staging.stg_baac_lieux (
    source_file_id    integer  NOT NULL REFERENCES meta.source_file,
    source_year       smallint NOT NULL,
    source_row_number integer  NOT NULL,
    load_run_id       integer  NOT NULL REFERENCES meta.load_run,
    num_acc text, catr text, voie text, v1 text, v2 text, circ text, nbv text, vosp text, prof text,
    pr text, pr1 text, plan text, lartpc text, larrout text, surf text, infra text, situ text, vma text,
    PRIMARY KEY (source_file_id, source_row_number)
);

CREATE TABLE IF NOT EXISTS staging.stg_baac_vehicules (
    source_file_id    integer  NOT NULL REFERENCES meta.source_file,
    source_year       smallint NOT NULL,
    source_row_number integer  NOT NULL,
    load_run_id       integer  NOT NULL REFERENCES meta.load_run,
    num_acc text, id_vehicule text, num_veh text, senc text, catv text, obs text, obsm text,
    choc text, manv text, motor text, occutc text,
    PRIMARY KEY (source_file_id, source_row_number)
);

CREATE TABLE IF NOT EXISTS staging.stg_baac_usagers (
    source_file_id    integer  NOT NULL REFERENCES meta.source_file,
    source_year       smallint NOT NULL,
    source_row_number integer  NOT NULL,
    load_run_id       integer  NOT NULL REFERENCES meta.load_run,
    num_acc text,
    id_usager text,                           -- NULL for 2019–2020: column absent from those files
    id_vehicule text, num_veh text, place text, catu text, grav text, sexe text, an_nais text,
    trajet text, secu1 text, secu2 text, secu3 text, locp text, actp text, etatp text,
    PRIMARY KEY (source_file_id, source_row_number)
);

COMMENT ON TABLE staging.stg_baac_caracteristiques IS 'BAAC Caractéristiques 2019–2025, values untouched (TEXT). 2022 source key column "Accident_Id" loaded into num_acc.';
COMMENT ON TABLE staging.stg_baac_lieux            IS 'BAAC Lieux 2019–2025, values untouched (TEXT). 1 row/accident until 2022; several rows at intersections from 2023.';
COMMENT ON TABLE staging.stg_baac_vehicules        IS 'BAAC Véhicules 2019–2025, values untouched (TEXT). 2025 source header "id_vehicule\n" loaded into id_vehicule.';
COMMENT ON TABLE staging.stg_baac_usagers          IS 'BAAC Usagers 2019–2025, values untouched (TEXT). id_usager absent (NULL) in 2019–2020.';
