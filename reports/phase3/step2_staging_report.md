# Phase 3 — Step 2: BAAC Staging Import
**Road Safety Intelligence — France** · 2026-11-11 · Database `road_safety` (Docker `rsi_postgis`, PostgreSQL 18.6 / PostGIS 3.6.4)

Result: **all 28 BAAC files (2019–2025) imported into staging; 204/204 validation checks pass** (validation run `load_run_id = 5`, on data from load run 4). Raw files unchanged (SHA-256 re-verified from disk after loading).

---

## 1. Files created / modified

| Path | Type | Purpose |
|---|---|---|
| `db/sql/010_meta.sql` | new | `meta.load_run`, `meta.source_file`, `meta.source_column`, `meta.dq_check` |
| `db/sql/020_staging_baac.sql` | new | `staging.stg_baac_{caracteristiques,lieux,vehicules,usagers}` (all value columns `text`) |
| `scripts/11_load_staging_baac.py` | new | E0 hash gate → DDL → register sources & exact columns → psycopg `COPY` (one transaction) |
| `scripts/12_validate_staging.py` | new | independent re-read of raw CSVs and checks V1–V9, results in `meta.dq_check` |
| `reports/phase3/step2_staging_report.md` | new | this report |
| Database | new objects | 4 meta tables, 4 staging tables (no clean / ref / analytics objects) |

No raw file, no earlier script and no earlier report was modified.

## 2. Import design (as implemented)

- **Values untouched**: parsed with Python's `csv` module (UTF-8 strict, `;`); CSV quoting removed by the parser only; every field stored as `text` exactly as read — `" -1"`, `N/A`, `(1)`, `#VALEURMULTI`, U+00A0 separators, decimal commas, space-separated IDs (`"138 306 524"`) all preserved. Empty fields are stored as `''`, never `NULL`.
- **`NULL` only for absent columns**: `stg_baac_usagers.id_usager` for 2019–2020 (column not in those files).
- **Header**: only canonicalisation to lower-case names; the exact source names are stored in `meta.source_column` (only two differ beyond case: `Accident_Id` in `carcteristiques-2022.csv` → `num_acc`; `"id_vehicule\n"` in `vehicules-2025.csv` → `id_vehicule`). The exact header line is also in `meta.source_file.raw_header`.
- **Lineage on every row**: `source_file_id` (→ file name, path, URL, SHA-256, licence, producer, publication date), `source_year`, `source_row_number` (1-based data record), `load_run_id` (→ ingestion timestamp, script fingerprint). PK = (`source_file_id`, `source_row_number`).
- **No constraint on value columns**; `COPY` is all-or-nothing inside one transaction (no `ON CONFLICT DO NOTHING`, no row filtering) → no record can be silently discarded.
- **Skipped**: only completely empty trailing records (1 per file in 24 files; none in 2020 Lieux/Usagers/Véhicules and 2024 Véhicules) — identical to the Phase 1 diagnosis.
- **Idempotent**: re-running replaces each file's rows (verified: second load = identical counts, one load run per row).

## 3. Imported row counts (= raw CSV records = Phase 1 counts)

| Year | Caractéristiques | Lieux | Véhicules | Usagers |
|---|---|---|---|---|
| 2019 | 58 840 | 58 840 | 100 710 | 132 977 |
| 2020 | 47 744 | 47 744 | 81 066 | 105 295 |
| 2021 | 56 518 | 56 518 | 97 315 | 129 248 |
| 2022 | 55 302 | 55 302 | 94 493 | 126 662 |
| 2023 | 54 822 | 70 860 | 93 585 | 125 789 |
| 2024 | 54 402 | 70 248 | 92 678 | 125 187 |
| 2025 | 55 093 | 71 116 | 93 865 | 126 376 |
| **Total** | **382 721** | **430 628** | **653 712** | **871 534** |

Grand total **2 338 595** staging rows (staging tables 119 / 111 / 144 / 241 MB).

## 4. Validation results (`scripts/12_validate_staging.py`, `meta.dq_check`)

| Check | Scope | Result |
|---|---|---|
| V1 files registered | 28 = 7 years × 4 entities | **pass** |
| V1 SHA-256 manifest = `meta.source_file` = file on disk | 28 files | **28 pass** |
| V2 row count: DB = raw records (`csv`) = Phase 1 pandas count | 28 files | **28 pass** |
| V3 `source_row_number` exactly 1..n, no gap/duplicate | 28 files | **28 pass** |
| V4 value fidelity: MD5 of all values in file order, Python (raw CSV) vs PostgreSQL | 28 files | **28 pass** (byte-identical values) |
| V5 duplicate value rows: DB = raw | 28 files | **28 pass** — source duplicates preserved: Usagers 2019: 101, 2020: 63 (years without `id_usager`); 0 elsewhere; import adds none |
| V6 exact source column names and order preserved | 28 files | **28 pass** |
| V7 `NULL` only in absent columns | 28 files | **28 pass** (`id_usager` 2019–2020 only) |
| V8 lineage: every row resolves to file name, year, row number, load run, ingestion time | 4 tables | **4 pass** |
| V9 accident totals & reconciliation | Caractéristiques | **3 pass** |
| **Total** | | **204 / 204** |

## 5. Reconciliation: 382 721 accidents vs 361 593 metropolitan

Computed from staging values (`dep`; single-digit 2019 codes padded *in the query only*):

| Year | All accidents | Metropolitan | of which 2019 `dep` written `1`–`9` | DROM (971–974, 976) | Overseas collectivities (975, 977, 978, 986–988) |
|---|---|---|---|---|---|
| 2019 | 58 840 | 56 016 | 2 966 | 2 273 | 551 |
| 2020 | 47 744 | 45 121 | 0 | 2 120 | 503 |
| 2021 | 56 518 | 53 540 | 0 | 2 503 | 475 |
| 2022 | 55 302 | 52 380 | 0 | 2 448 | 474 |
| 2023 | 54 822 | 51 641 | 0 | 2 740 | 441 |
| 2024 | 54 402 | 51 058 | 0 | 2 851 | 493 |
| 2025 | 55 093 | 51 837 | 0 | 2 729 | 527 |
| **Total** | **382 721** | **361 593** | 2 966 | **17 664** | **3 464** |

**382 721 = 361 593 metropolitan + 17 664 DROM + 3 464 overseas collectivities + 0 other.**
By code: 971 Guadeloupe 3 342 · 972 Martinique 3 615 · 973 Guyane 3 739 · 974 La Réunion 5 797 · 976 Mayotte 1 171 · 975 Saint-Pierre-et-Miquelon 19 · 977 Saint-Barthélemy 109 · 978 Saint-Martin 229 · 986 Wallis-et-Futuna 71 · 987 Polynésie française 1 259 · 988 Nouvelle-Calédonie 1 777.
A filter on raw `dep` without zero-padding would wrongly drop the 2 966 metropolitan accidents of 2019 coded `1`–`9`.

## 6. Problems encountered (reported honestly)

1. **Validation-script bug (fixed)** — first validation run (`load_run_id = 2`, status `failed`, kept in `meta`) counted 975 (Saint-Pierre-et-Miquelon) both as DROM (pattern `97[1-6]`) and as collectivity: 21 147 instead of 21 128. Pattern corrected to the explicit list 971–974, 976; data were not involved. Runs 3 and 5 pass.
2. Docker Desktop must be running for the database to be reachable (no change since Step 1).

## 7. Notes for Step 3+

- Staging is intentionally not harmonised: identifiers still contain spaces, codes keep leading spaces, `dep` is not padded, `pr`/`pr1` contain U+00A0 — all handled in the clean layer.
- The 101 / 63 identical Usagers rows (2019 / 2020) are genuine source records (mostly coach passengers and pedestrians, Phase 1) and remain distinct via `source_row_number`.
