# Obsolete Commune Codes — INSEE Historical Mapping
**Road Safety Intelligence — France** · 598 accidents (`commune_code_unresolved`) · 2026-11-11

Reproducible with `scripts/06_acquire_insee_cog.py` → `scripts/07_map_obsolete_communes.py`.
Evidence tables: `reports/geography/tables/10_*`–`13_*`. BAAC raw files unchanged (SHA-256 re-verified); original codes are never altered — derived codes live in separate fields.

---

## 1. Source and licence

| Item | Value |
|---|---|
| Source | INSEE — *Code officiel géographique (COG) au 1er janvier 2026* (insee.fr, page 8740222) |
| Catalogue | data.gouv.fr dataset `58c984b088ee386cdb1261f3` (organisation: Insee) |
| Licence | **Licence Ouverte** (`fr-lo`, as declared on the INSEE data.gouv.fr record) |
| Reference date | Situation at 1 January 2026; each vintage includes territorial changes effective between 2 January of the previous year and 1 January of the vintage year (INSEE "Diffusion du COG") |
| Coverage | Metropolitan France + DROM; events since 1943 (Mayotte communes from 31/03/2011) |
| Methodology (INSEE) | `v_mvt_commune` "est une table de passage : à la date « date_eff », la commune « avant » devient la commune « après »"; several rows per transformation possible; `MOD` = event type; `TYPECOM` ∈ COM, COMA (associée), COMD (déléguée), ARM |
| Format | UTF-8, comma-separated, quoted |

## 2. Download inventory (`data/raw/geography/insee_cog/_manifest.csv`)

| File | Bytes | SHA-256 | data.gouv resource / last modified |
|---|---|---|---|
| `2026/v_mvt_commune_2026.csv` (13 734 events, 1943-02-19 → 2026-01-01) | 2 076 555 | `8b339fad…8645f1` | 1b96750d… / 2026-02-24 |
| `2026/v_commune_depuis_1943.csv` (42 333 code-label periods) | 3 440 210 | `08c532ed…d6eeee` | eb836ef4… / 2026-02-24 |

Files are read-only. Note: `v_commune_depuis_1943` contains only `COM` and `ARM` rows; delegated/associated status was therefore derived from `v_mvt_commune` events.

`MOD` codes 41 and 50 were checked against actual rows (41: Pont-Farcy 14513 → 50649 in 2018, department change; 50: Orée d'Anjou 49069 → 49126 in 2025, chef-lieu transfer).

## 3. Mapping method

1. For each obsolete BAAC code, the end of its validity as a commune (`TYPECOM = COM`) is read from `v_commune_depuis_1943`.
2. Successors = `COM_AP` of `v_mvt_commune` rows with `COM_AV` = code, `TYPECOM_AV = COM`, `TYPECOM_AP = COM`, `COM_AP ≠ code`, at that date.
3. Chains are followed until the code valid on the **accident date** (`successor_at_accident_date`) and on **2026-01-01** (`successor_2026`).
4. Exactly one successor at every step → deterministic mapping; > 1 → ambiguous (no mapping); none → unresolved.
5. Class from the INSEE `MOD` of the first step: 31/32/33/34 → merger; 41/50 → one-to-one code change; 20/21 or multiple successors → split/complex.
6. Independent check: is the accident point (IGN ADMIN EXPRESS edition of the year) inside the derived successor commune?

## 4. Mapping results

| Class | Codes | Accidents | Mapping |
|---|---|---|---|
| Merger (MOD 32 commune nouvelle: 238 codes; MOD 33 fusion-association: 4) | 242 | **594** | deterministic |
| Direct one-to-one code change (MOD 41, department change) | 3 | **3** | deterministic |
| Split / complex transformation | 0 | **0** | — |
| Unresolvable (no INSEE correspondence) | 1 | **1** | none |
| **Total** | **246** | **598** | 597 mapped (99.8 %) |

By year: 2019 = 276 (273 merger, 3 code change), 2020 = 166, 2021 = 155 (all mergers), 2022 = 1 (unresolvable) **[12b]**.

**Point-based confirmation [12c, 13]:**
- **579 accidents (96.8 %)**: point lies inside the derived successor commune → *high confidence*.
- **18 accidents**: point lies in a neighbouring commune; distance to the successor polygon median **58 m**, P90 306 m, max 662 m (17/18 ≤ 500 m) → boundary effects; mapping still deterministic → *medium confidence*.
- Successor on accident date ≠ successor 2026 for **3 codes** (later re-merger); both are kept.

**Why BAAC still uses these codes:**
- 236 of 246 codes became a **commune déléguée/associée with the same code** at the merger (230 COMD, 6 COMA, 2 COMA/COMD); for **585 / 598 accidents** this delegated status was still active on the accident date. Police forces apparently record the *delegated* commune.
- Code obsolete as a commune since: 2019 (106 codes / 209 accidents), 2016 (65 / 259), 2017 (51 / 99), 2015 (11 / 14), 2018 (5 / 7); median 2.6 years before the accident.
- Legacy cases: 3 codes from the 1968 Paris-region / 1967 Rhône department reorganisation (38411 Saint-Laurent-de-Mure → 69288; 75075 Vanves → 92075; 78469 Ormoy-la-Rivière → 91469) and associated communes Lomme (59355 → 59350 Lille), Saint-Pol-sur-Mer (59540 → 59183 Dunkerque), Maconcourt, Sennecé-lès-Mâcon. All mapped deterministically and confirmed by the point.
- Concentration: Manche (50) 213 accidents; also 74, 49, 14, 91.

## 5. Unresolved cases

| Accident | Code | Reason | Note |
|---|---|---|---|
| one accident, 2022, dep 14 | `N/C` | not a commune code ("non connu"); absent from INSEE history | the coordinate places it in a commune of dep 14, but **no code is derived** (would be inference from the point, not from INSEE) |

No ambiguous (multi-successor) mapping occurred, so no mapping had to be refused for ambiguity.

## 6. Recommended treatment for historical geographical analysis

1. **Keep three fields**, never overwrite: `com_original` (BAAC as published), `com_cog_at_date` (INSEE successor valid on the accident date), `com_cog_2026` (successor in the reference vintage), plus `com_mapping_class` and `com_mapping_confidence`.
2. **Use a single reference vintage (COG 2026)** for all multi-year commune-level aggregations 2019–2025; map *all* BAAC codes (not only the 598) through the same INSEE chain so that later mergers (e.g. 2020–2025) are also harmonised.
3. **Mergers are many-to-one and lossless upward**: counts by successor commune are exact; counts by pre-merger (delegated) commune are *not* recoverable from ADMIN EXPRESS COG polygons — use delegated codes only as attributes, not as spatial units.
4. Leave the `N/C` accident without a commune code; it remains usable for department-level and point-based analysis.
5. For the 18 medium-confidence cases, prefer the INSEE mapping for code-based statistics and the point for spatial analysis; record both.
6. Department codes are unaffected except the 3 legacy MOD-41 cases (38→69, 75→92, 78→91); BAAC `dep` for those accidents already equals the successor's department.
