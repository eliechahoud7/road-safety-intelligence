# Phase 6 — Interactive Dashboard
**Road Safety Intelligence — France** · Streamlit + Plotly on the PostgreSQL/PostGIS analytical layer · 2026-11-11

## Launch

Prerequisites: Docker Desktop running (container `rsi_postgis`), local `.env` (see `.env.example`).

```
.venv\Scripts\streamlit run app\streamlit_app.py
```
Then open http://localhost:8501.

## Files created / modified

| Path | Purpose |
|---|---|
| `app/streamlit_app.py` | entry point: sidebar navigation, global filters, 6 sections |
| `app/data.py` | read-only, cached SQL queries (reuses `scripts/db_config.py`); aggregation done in PostgreSQL |
| `app/labels.py` | English labels for ONISR codes, colours, methodological notes |
| `app/theme.py` | Light / Dark display themes (added 2026-11-11, see "UI adjustment — Light / Dark mode") |
| `.streamlit/config.toml` | theme, headless server, usage statistics off |
| `scripts/22_validate_dashboard.py` | essential validation (AppTest + totals + read-only) |
| `requirements.txt` | added `streamlit==1.67.0`, `plotly==7.1.0` |
| `reports/phase6/dashboard_report.md` | this report |

No database object, raw file, script or report from earlier phases was changed.

## Dashboard structure

Sidebar: section navigation · **Years** (multi-select, default 2019–2025) · **Department** (all or one of 96) · COVID-2020 and "concentration ≠ risk" notices.

| Section | Content | Sources |
|---|---|---|
| National overview | KPIs (accidents, killed, injured, fatal accidents); accidents per year (2020 highlighted); killed & hospitalised per year; severity donut | `accident_fact` |
| Temporal analysis | accidents by month and year; average accidents per day by weekday; accidents + fatal share by hour; weekday vs weekend (per day, fatal share) | `accident_fact` |
| Severity & road users | users by outcome; outcome by user category; users by age × sex; killed-or-hospitalised share by age × sex (95 % CI); vulnerable vs other travel modes | `road_user_fact` (fugitive-like / unknown severity excluded) |
| Environmental conditions | tabs: weather, lighting, road category (4 + 7 grouped), built-up area — counts and fatal share with 95 % CI | `accident_fact` |
| Geospatial analysis | 1 km accident-distribution map (adjustable minimum); departments: concentration vs severity side by side + table; commune exploration per department; persistent hotspots (Phase 5 output, persistence slider) | `hotspot_point`, `agg_year_department`, `agg_year_commune`, IGN 2025 boundaries, `reports/phase5/tables/03_*.csv` |
| Hotspot explorer | Paris / Marseille / Lyon 50 km windows: 1 km cells, national top-1 % cells for the selected years, persistence, top-20 cell table | `hotspot_point`, Phase 5 output |

Design choices: one consistent palette (2020 always in red), thousands separated by spaces, hover tooltips with formatted values, log colour scales for skewed counts, captions under every view stating its population and limitations. Maps use Plotly MapLibre with the OpenStreetMap standard basemap (`MAP_STYLE`, keyless; requires internet for background tiles only — CARTO basemaps were replaced on 2026-11-11 because they now return "API KEY REQUIRED" placeholders, which showed as a grey map; maps without an explicit centre also opened at 0°/0° and now centre on France or the selected area). Point-map markers were enlarged (accident grid 9 px, explorer 8–12 px, opacity 0.9) and given a fixed colour range (log10 accidents −0.5…3; persistence 0…6 shifted) because the per-filter auto range and 2.5 px radius made markers near-white and invisible on OpenStreetMap; department views now zoom to the extent of their cells; boundaries are simplified for display (departments 500 m, communes 100 m).

## Performance and safeguards
- All heavy work is aggregated in PostgreSQL; the largest frame in memory is the 1 km grid (≤ 88 256 rows). Results are cached (`st.cache_data`, 1 h).
- **Read-only:** every connection uses `default_transaction_read_only=on` and `conn.read_only = True`; credentials come from `.env` via `db_config`.
- Geographic exclusions preserved (default hotspot population only; 606 wrong-commune points excluded; corrections **not** applied); concentration never labelled as risk; 2020 flagged; hospitalised, fugitive-user and road-category caveats shown.

## Validation (`scripts/22_validate_dashboard.py`) — 25 / 25 pass

| Check | Result |
|---|---|
| All 6 sections render without exception — default filters, 2020 only, department 75 | pass (×3) |
| KPIs = analytical layer: 361 593 accidents · 21 619 killed · 453 388 injured · 20 384 fatal accidents | pass |
| Year filter (2020: 45 121 / 2 541) and department filter (Paris: 33 111 / 258) | pass |
| User charts population = 809 407 (fugitive-like / unknown excluded) | pass |
| No double counting: month, weekday, hour, weather, lighting, built-up, road category, severity each sum to 361 593 | pass (×8) |
| Maps: 96 department polygons; department map total 361 593; commune total = department total (dep 13: 16 519); grid = 360 934 eligible accidents; cell centres inside metropolitan France; Phase 5 hotspots 897 / 132 persistent | pass |
| Write attempt through the dashboard connection rejected (`ReadOnlySqlTransaction`) | pass |
| Database write counters identical before/after | pass |
| Live server: `/_stcore/health` = ok, main page HTTP 200 | pass |

One defect found and fixed during testing: `scatter_map` in Plotly 7 does not accept `symbol` (Hotspot explorer crashed); argument removed, all sections re-tested.

## UI adjustment — chart toolbar (2026-11-11)

All charts share one Plotly configuration (`PLOTLY_CONFIG` in `app/streamlit_app.py`). Final toolbar (revised the
same day): **removed** Zoom (`zoom2d`), Pan (`pan2d`) and Autoscale (`autoScale2d`); **kept** Zoom in (`zoomIn2d`),
Zoom out (`zoomOut2d`) and Reset axes (`resetScale2d`); Plotly logo hidden (`displaylogo=False`). Hover tooltips,
legends, image download, responsiveness and all filters are unchanged. Applied to all 18 `st.plotly_chart()` calls
(25 rendered charts, maps included — verified on the rendered elements); dashboard validation re-run: 25 / 25 pass.
No SQL, data or analytical logic changed.

## UI adjustment — Light / Dark mode (2026-11-11)

A **Dark mode** toggle in the sidebar (below the caption, off by default) switches the display theme for the current
browser session only; Streamlit's server-wide configuration (`.streamlit/config.toml`, light theme) is unchanged, so
other users are unaffected.

| Component | Role |
|---|---|
| `app/theme.py` | `DARK` palette; `DARK_CSS` (page, sidebar, text, captions, KPI cards, info boxes, tabs, inputs, dropdowns, slider, radio buttons, tooltips, table frame); `style_figure(fig, dark)` — layout-only Plotly restyle (`plotly_dark` template, transparent backgrounds, light fonts, grid and hover colours); `style_table(df, dark)` — dark pandas Styler for the tables (no CSS colour inversion) |
| `app/streamlit_app.py` | `st.sidebar.toggle("Dark mode")`; CSS injected only when it is on; charts rendered through a `show()` helper (`theme.style_figure` + the shared `PLOTLY_CONFIG`; Streamlit chart theme in Light mode, none in Dark mode); the 3 tables wrapped with `theme.style_table` |

**Light mode is the previous appearance**: no CSS is injected and figures and tables are passed through unchanged.
In both modes, trace colours (including killed `#A52A2A` and hospitalised `#0077B6`), colour scales and ranges, the
OpenStreetMap basemap, map centres and zoom, filters, queries and all displayed values are identical.

Testing: all 6 sections rendered in both modes without exception (25 charts each, `AppTest`); the toggle and the year
filter persist across section navigation; Dark mode checked visually through headless-browser screenshots of all
six sections (backgrounds, text, KPIs, tabs, inputs, charts, maps with OSM tiles and markers); dashboard validation
re-run: 25 / 25 pass. No SQL, data or analytical logic changed.

Known cosmetic points (documented, not changed):
- Killed (`#A52A2A`) has lower contrast on the dark background; trace colours were deliberately kept.
- The darkest stop of the map colour scales (`#000004`, Inferno) is replaced by Streamlit's frontend in **both**
  modes (pre-existing, not caused by Dark mode); the figure specification sent is correct.
- The radio-button styling fix was applied but its final screenshot was not reviewed; some built-in Streamlit
  popovers may keep minor light details.

## Limitations
- Background map tiles need internet access; data and boundaries are local.
- Persistent-hotspot view shows the Phase 5 all-years result (not recomputed for the year filter); the Hotspot explorer recomputes the top-1 % threshold for the selected years.
- Commune values are counts (not rates); population is not shown as a denominator.
- Category labels cover the variables displayed; the full ONISR codebook table (`ref.code_label`) is still not populated.
- Visual layout was checked through automated rendering, not a manual browser review.
