-- Phase 3 Step 4 — CLEAN layer (approved design: reports/phase2/database_schema.md §5, data_dictionary.md)
-- Tables: clean.accident, clean.accident_location, clean.vehicle, clean.road_user, clean.dq_issue (§5.6).
-- Every clean row keeps (source_file_id, source_row_number) -> exact staging row (original values).
-- Idempotent DDL; data are rebuilt by scripts/15_build_clean.py.

-- ------------------------------------------------------------------ helper functions (data dictionary G1–G7)
-- G1+G2: trim; documented "not recorded" tokens -> NULL
CREATE OR REPLACE FUNCTION clean.f_txt(v text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN btrim(v) IN ('', '-1', 'N/A', '.', '(1)') OR btrim(v) LIKE '#%' THEN NULL ELSE btrim(v) END $$;

-- G7: integer code restricted to the documented list (anything else -> NULL; logged separately in dq_issue)
CREATE OR REPLACE FUNCTION clean.f_code(v text, allowed int[]) RETURNS smallint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN clean.f_txt(v) ~ '^-?[0-9]+$' AND clean.f_txt(v)::int = ANY (allowed)
              THEN clean.f_txt(v)::smallint END $$;

-- non-missing value that is not a documented code (for dq_issue)
CREATE OR REPLACE FUNCTION clean.f_undocumented(v text, allowed int[]) RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT clean.f_txt(v) IS NOT NULL AND clean.f_code(v, allowed) IS NULL $$;

-- G5: integers written with thousands separators (space, U+00A0) -> integer; missing tokens -> NULL
CREATE OR REPLACE FUNCTION clean.f_int(v text) RETURNS integer LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN regexp_replace(clean.f_txt(v), '[\s ]', '', 'g') ~ '^-?[0-9]+$'
              THEN regexp_replace(clean.f_txt(v), '[\s ]', '', 'g')::integer END $$;

-- G6: decimal comma or point -> numeric
CREATE OR REPLACE FUNCTION clean.f_num(v text) RETURNS numeric LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN replace(clean.f_txt(v), ',', '.') ~ '^-?[0-9]+(\.[0-9]+)?$'
              THEN replace(clean.f_txt(v), ',', '.')::numeric END $$;

-- identifiers: remove all whitespace (incl. thousands separators)
CREATE OR REPLACE FUNCTION clean.f_id(v text) RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT regexp_replace(v, '[\s ]', '', 'g')::bigint $$;

-- ------------------------------------------------------------------ clean.accident
CREATE TABLE IF NOT EXISTS clean.accident (
    num_acc                bigint      PRIMARY KEY,
    year                   smallint    NOT NULL CHECK (year BETWEEN 2019 AND 2025),
    acc_date               date        NOT NULL,
    acc_time               time        NOT NULL,
    hour                   smallint    NOT NULL CHECK (hour BETWEEN 0 AND 23),
    weekday                smallint    NOT NULL CHECK (weekday BETWEEN 1 AND 7),   -- ISO, 1 = Monday
    lum                    smallint    CHECK (lum BETWEEN 1 AND 5),
    agg                    smallint    NOT NULL CHECK (agg IN (1, 2)),
    intersection           smallint    CHECK (intersection BETWEEN 1 AND 9),        -- source column "int"
    atm                    smallint    CHECK (atm BETWEEN 1 AND 9),
    col                    smallint    CHECK (col BETWEEN 1 AND 7),
    dep_original           text        NOT NULL,                                   -- verbatim
    dep_code               varchar(3)  NOT NULL,                                   -- zero-padded
    is_metro               boolean     NOT NULL,
    com_original           text        NOT NULL REFERENCES ref.commune_code_harmonisation,
    com_arm                char(5),
    com_cog_at_date        char(5),
    com_cog_2026           char(5),
    com_mapping_class      text        NOT NULL,
    com_mapping_confidence text        NOT NULL CHECK (com_mapping_confidence IN ('exact', 'high', 'medium', 'none')),
    adr_original           text        NOT NULL,                                   -- verbatim free text
    lat_original           text        NOT NULL,                                   -- verbatim
    long_original          text        NOT NULL,                                   -- verbatim
    lat                    double precision,
    lon                    double precision,
    geom_original          geometry(Point, 2154),                                  -- metropolitan only; never corrected
    geo_category           text        NOT NULL,                                   -- Phase 1C category (ref.geo_validation_phase1c)
    geo_dist_declared_m    double precision,
    has_correction_proposal boolean    NOT NULL,                                   -- ref.coordinate_correction_proposal (NOT applied)
    correction_method      text,
    source_file_id         integer     NOT NULL REFERENCES meta.source_file,
    source_row_number      integer     NOT NULL,
    load_run_id            integer     NOT NULL REFERENCES meta.load_run,
    UNIQUE (source_file_id, source_row_number),
    CONSTRAINT accident_geo_fk FOREIGN KEY (num_acc) REFERENCES ref.geo_validation_phase1c (num_acc),
    CHECK (year = left(num_acc::text, 4)::smallint));
CREATE INDEX IF NOT EXISTS accident_year_idx     ON clean.accident (year);
CREATE INDEX IF NOT EXISTS accident_dep_year_idx ON clean.accident (dep_code, year);
CREATE INDEX IF NOT EXISTS accident_cog2026_idx  ON clean.accident (com_cog_2026);
CREATE INDEX IF NOT EXISTS accident_geom_gix     ON clean.accident USING gist (geom_original);

-- ------------------------------------------------------------------ clean.accident_location (grain: Lieux row)
CREATE TABLE IF NOT EXISTS clean.accident_location (
    location_id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    num_acc                bigint      NOT NULL REFERENCES clean.accident,
    segment_seq            smallint    NOT NULL,
    n_segments_in_accident smallint    NOT NULL CHECK (n_segments_in_accident BETWEEN 1 AND 10),
    catr                   smallint    CHECK (catr IN (1, 2, 3, 4, 5, 6, 7, 9)),
    voie_original          text        NOT NULL,
    v1                     smallint,
    v2                     text,
    circ                   smallint    CHECK (circ BETWEEN 1 AND 4),
    nbv                    smallint    CHECK (nbv BETWEEN 0 AND 12),
    vosp                   smallint    CHECK (vosp BETWEEN 0 AND 3),
    prof                   smallint    CHECK (prof BETWEEN 1 AND 4),
    pr                     integer     CHECK (pr >= 0),
    pr1                    integer     CHECK (pr1 >= 0),
    plan                   smallint    CHECK (plan BETWEEN 1 AND 4),
    lartpc                 numeric(6, 2),
    larrout                numeric(6, 2),
    surf                   smallint    CHECK (surf BETWEEN 1 AND 9),
    infra                  smallint    CHECK (infra BETWEEN 0 AND 9),
    situ                   smallint    CHECK (situ IN (0, 1, 2, 3, 4, 5, 6, 8)),
    vma                    smallint,
    vma_plausible          boolean,
    source_file_id         integer     NOT NULL REFERENCES meta.source_file,
    source_row_number      integer     NOT NULL,
    load_run_id            integer     NOT NULL REFERENCES meta.load_run,
    UNIQUE (num_acc, segment_seq),
    UNIQUE (source_file_id, source_row_number),
    CHECK (segment_seq BETWEEN 1 AND n_segments_in_accident));

-- ------------------------------------------------------------------ clean.vehicle
CREATE TABLE IF NOT EXISTS clean.vehicle (
    id_vehicule            integer     PRIMARY KEY,
    num_acc                bigint      NOT NULL REFERENCES clean.accident,
    num_veh                text        NOT NULL,                                    -- label only, NOT a key
    senc                   smallint    CHECK (senc BETWEEN 0 AND 3),
    catv                   smallint    CHECK (catv BETWEEN 0 AND 21 OR catv BETWEEN 30 AND 43 OR catv IN (50, 60, 80, 99)),
    obs                    smallint    CHECK (obs BETWEEN 0 AND 17),
    obsm                   smallint    CHECK (obsm IN (0, 1, 2, 4, 5, 6, 9)),
    choc                   smallint    CHECK (choc BETWEEN 0 AND 9),
    manv                   smallint    CHECK (manv BETWEEN 0 AND 26),
    motor                  smallint    CHECK (motor BETWEEN 0 AND 6),
    occutc                 smallint    CHECK (occutc >= 0),
    n_users                smallint    NOT NULL DEFAULT 0,
    has_no_user            boolean     NOT NULL DEFAULT false,
    source_file_id         integer     NOT NULL REFERENCES meta.source_file,
    source_row_number      integer     NOT NULL,
    load_run_id            integer     NOT NULL REFERENCES meta.load_run,
    UNIQUE (id_vehicule, num_acc),                                                  -- target of road_user composite FK
    UNIQUE (source_file_id, source_row_number));
CREATE INDEX IF NOT EXISTS vehicle_num_acc_idx ON clean.vehicle (num_acc);

-- ------------------------------------------------------------------ clean.road_user
CREATE TABLE IF NOT EXISTS clean.road_user (
    road_user_id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_usager              integer     UNIQUE,                                      -- NULL 2019–2020 (absent)
    num_acc                bigint      NOT NULL REFERENCES clean.accident,
    id_vehicule            integer     NOT NULL,
    num_veh                text        NOT NULL,
    place                  smallint    CHECK (place BETWEEN 1 AND 10),
    catu                   smallint    NOT NULL CHECK (catu BETWEEN 1 AND 3),
    grav                   smallint    CHECK (grav BETWEEN 1 AND 4),
    severity_rank          smallint    CHECK (severity_rank BETWEEN 0 AND 3),       -- 0 unhurt, 1 light, 2 hospitalised, 3 killed
    is_victim              boolean,
    sexe                   smallint    CHECK (sexe IN (1, 2)),
    an_nais                smallint,
    age_at_accident        smallint,
    an_nais_placeholder    boolean     NOT NULL,
    trajet                 smallint    CHECK (trajet IN (1, 2, 3, 4, 5, 9)),
    secu1                  smallint    CHECK (secu1 BETWEEN 0 AND 9),
    secu2                  smallint    CHECK (secu2 BETWEEN 0 AND 9),
    secu3                  smallint    CHECK (secu3 BETWEEN 0 AND 9),
    locp                   smallint    CHECK (locp BETWEEN 0 AND 9),
    actp                   char(1)     CHECK (actp IN ('0','1','2','3','4','5','6','9','A','B')),
    etatp                  smallint    CHECK (etatp BETWEEN 1 AND 3),
    is_fugitive_like       boolean     NOT NULL,
    source_file_id         integer     NOT NULL REFERENCES meta.source_file,
    source_row_number      integer     NOT NULL,
    load_run_id            integer     NOT NULL REFERENCES meta.load_run,
    UNIQUE (source_file_id, source_row_number),
    CONSTRAINT road_user_vehicle_fk FOREIGN KEY (id_vehicule, num_acc) REFERENCES clean.vehicle (id_vehicule, num_acc));
CREATE INDEX IF NOT EXISTS road_user_num_acc_idx ON clean.road_user (num_acc);
CREATE INDEX IF NOT EXISTS road_user_vehicle_idx ON clean.road_user (id_vehicule, num_acc);

-- ------------------------------------------------------------------ clean.dq_issue (approved design §5.6)
CREATE TABLE IF NOT EXISTS clean.dq_issue (
    dq_issue_id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity                 text        NOT NULL CHECK (entity IN ('accident', 'accident_location', 'vehicle', 'road_user')),
    entity_key             text        NOT NULL,
    num_acc                bigint      NOT NULL REFERENCES clean.accident,
    column_name            text        NOT NULL,
    issue_code             text        NOT NULL,
    original_value         text        NOT NULL,
    treatment              text        NOT NULL CHECK (treatment IN ('set_null', 'kept_flagged')),
    source_file_id         integer     NOT NULL REFERENCES meta.source_file,
    source_row_number      integer     NOT NULL,
    load_run_id            integer     NOT NULL REFERENCES meta.load_run);
CREATE INDEX IF NOT EXISTS dq_issue_num_acc_idx ON clean.dq_issue (num_acc);
CREATE INDEX IF NOT EXISTS dq_issue_code_idx    ON clean.dq_issue (issue_code);
