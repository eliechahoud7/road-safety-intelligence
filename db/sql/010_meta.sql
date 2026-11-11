-- Phase 3 Step 2 — META layer (lineage, load runs, data-quality checks)
-- Design: reports/phase2/database_schema.md §2. Idempotent.

CREATE TABLE IF NOT EXISTS meta.load_run (
    load_run_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    step             text        NOT NULL,                       -- e.g. 'staging_baac'
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    status           text        NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'succeeded', 'failed')),
    code_fingerprint text        NOT NULL,                       -- SHA-256 of the loader script(s)
    parameters       jsonb
);

CREATE TABLE IF NOT EXISTS meta.source_file (
    source_file_id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_system              text        NOT NULL CHECK (source_system IN ('BAAC', 'IGN', 'INSEE', 'ONISR_DOC')),
    entity                     text        NOT NULL,
    reference_year             smallint,
    file_path                  text        NOT NULL UNIQUE,      -- relative to project root
    file_name                  text        NOT NULL,
    source_url                 text        NOT NULL,
    bytes                      bigint      NOT NULL,
    sha256                     char(64)    NOT NULL,
    licence                    text        NOT NULL,
    producer                   text        NOT NULL,
    published_or_edition_date  date,
    retrieved_at               timestamptz NOT NULL,
    raw_header                 text,                              -- exact header record (newlines escaped as \n)
    registered_at              timestamptz NOT NULL DEFAULT now()
);

-- exact source column names, in file order (annual schema differences preserved here)
CREATE TABLE IF NOT EXISTS meta.source_column (
    source_file_id   integer  NOT NULL REFERENCES meta.source_file ON DELETE CASCADE,
    ordinal_position smallint NOT NULL,
    raw_name         text     NOT NULL,                          -- exactly as in the file (e.g. 'Accident_Id', E'id_vehicule\n')
    staging_column   text     NOT NULL,                          -- canonical staging column it was loaded into
    PRIMARY KEY (source_file_id, ordinal_position)
);

CREATE TABLE IF NOT EXISTS meta.dq_check (
    dq_check_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    load_run_id    integer NOT NULL REFERENCES meta.load_run,
    layer          text    NOT NULL CHECK (layer IN ('raw', 'staging', 'ref', 'clean', 'analytics')),
    check_code     text    NOT NULL,
    entity         text,
    reference_year smallint,
    expected       text,
    observed       text,
    status         text    NOT NULL CHECK (status IN ('pass', 'warn', 'fail')),
    details        jsonb,
    checked_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS dq_check_run_status_idx ON meta.dq_check (load_run_id, status);
