"""Road Safety Intelligence — France · interactive dashboard (Phase 6).

Run:  .venv\\Scripts\\streamlit run app\\streamlit_app.py
Data: PostgreSQL/PostGIS analytical layer (read-only) + Phase 5 hotspot output. Descriptive only — no models.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import data
import labels as L
import theme

st.set_page_config(page_title="Road Safety Intelligence — France", page_icon="🚦", layout="wide")
PX = dict(template="plotly_white")
# Shared toolbar configuration for every chart: Zoom (box), Pan and Autoscale removed; Zoom in / Zoom out /
# Reset axes kept; no Plotly logo. Hover tooltips, legends, image download and responsiveness are unchanged.
# Basemap for all maps. CARTO basemaps ("carto-positron") now return "API KEY REQUIRED" placeholders to keyless
# browser requests (grey map); OpenStreetMap standard tiles are keyless (© OpenStreetMap contributors).
MAP_STYLE = "open-street-map"
FRANCE_CENTER = {"lat": 46.6, "lon": 2.4}   # explicit centre: without it Plotly maps open at (0°, 0°)
# Fixed colour range for log10(accidents per cell) on point maps: an auto range (recomputed per filter) gave the
# lowest visible cells Inferno_r's near-white end, invisible on OpenStreetMap. Colour bar ticks (1–1 000) unchanged.
ACCIDENT_LOG_RANGE = [-0.5, 3.0]
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": ["zoom2d", "pan2d", "autoScale2d"],
}


def fmt(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def wilson(k, n, z=1.96):
    k, n = np.asarray(k, float), np.asarray(n, float)
    p = np.divide(k, n, out=np.zeros_like(k), where=n > 0)
    d = 1 + z ** 2 / n
    c = (p + z ** 2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / d
    return p, c - h, c + h


# ------------------------------------------------------------------ sidebar: navigation + global filters
st.sidebar.title("🚦 Road Safety Intelligence")
st.sidebar.caption("Metropolitan France · BAAC 2019–2025 (ONISR)")
# Session-specific theme: keyed widget state persists across sections and reruns; Light Mode is the default.
DARK_MODE = st.sidebar.toggle("Dark mode", key="dark_mode", value=False)
if DARK_MODE:
    st.markdown(theme.DARK_CSS, unsafe_allow_html=True)


def show(fig, where=st) -> None:
    """Render every Plotly chart with the shared toolbar config and the current theme."""
    where.plotly_chart(theme.style_figure(fig, DARK_MODE), width="stretch", config=PLOTLY_CONFIG,
                       theme=None if DARK_MODE else "streamlit")
PAGES = ["National overview", "Temporal analysis", "Severity & road users", "Environmental conditions",
         "Geospatial analysis", "Hotspot explorer"]
page = st.sidebar.radio("Section", PAGES, label_visibility="collapsed")
st.sidebar.divider()
years = tuple(st.sidebar.multiselect("Years", L.YEARS, default=L.YEARS, help="All charts and totals use the selected years."))
if not years:
    st.sidebar.warning("Select at least one year.")
    st.stop()
deps = data.departments()
dep_options = ["All metropolitan France"] + [f"{r.dep_code} – {r.name}" for r in deps.itertuples()]
dep_choice = st.sidebar.selectbox("Department", dep_options, help="Filters all sections except the national maps.")
dep = None if dep_choice == dep_options[0] else dep_choice.split(" – ")[0]
st.sidebar.divider()
if 2020 in years:
    st.sidebar.info(L.COVID_NOTE)
st.sidebar.caption(L.CONCENTRATION_NOTE)
scope = "metropolitan France" if dep is None else dep_choice
period = f"{min(years)}–{max(years)}" if len(years) > 1 else str(years[0])


def header(title: str, subtitle: str = "") -> None:
    st.title(title)
    st.caption(f"{scope} · {period} ({len(years)} year{'s' if len(years) > 1 else ''} selected)" + (f" · {subtitle}" if subtitle else ""))


# ------------------------------------------------------------------ A. national overview
if page == "National overview":
    header("National overview")
    k = data.kpis(years, dep)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Injury accidents", fmt(k.accidents))
    c2.metric("Persons killed (≤ 30 days)", fmt(k.killed), help="Killed on the spot or within 30 days.")
    c3.metric("Injured road users", fmt(k.hospitalised + k.light),
              help=f"Hospitalised: {fmt(k.hospitalised)} · light injury: {fmt(k.light)}. {L.HOSP_NOTE}")
    c4.metric("Fatal accidents", fmt(k.fatal_accidents),
              help=f"{100 * k.fatal_accidents / max(k.accidents, 1):.1f} % of accidents")
    y = data.by_year(years, dep)
    left, right = st.columns([3, 2])
    with left:
        y["colour"] = np.where(y.year == 2020, "2020 (COVID-19)", "Other years")
        fig = px.bar(y, x="year", y="accidents", color="colour", text="accidents", title="Injury accidents per year",
                     color_discrete_map={"2020 (COVID-19)": L.COLORS["covid"], "Other years": L.COLORS["main"]},
                     labels={"accidents": "Accidents", "year": "", "colour": ""}, **PX)
        fig.update_traces(texttemplate="%{text:,}", hovertemplate="%{x}: %{y:,} accidents")
        fig.update_layout(separators=". ", legend=dict(orientation="h", y=1.1), xaxis=dict(dtick=1))
        show(fig)
        fig = px.line(y, x="year", y=["killed", "hospitalised"], markers=True, title="Persons killed and hospitalised per year",
                      labels={"value": "Persons", "year": "", "variable": ""}, **PX,
                      color_discrete_map={"killed": "#A52A2A", "hospitalised": "#0077B6"})
        fig.update_layout(separators=". ", legend=dict(orientation="h", y=1.1), xaxis=dict(dtick=1))
        show(fig)
    with right:
        s = data.by_column("accident_severity", years, dep)
        s["label"] = s.value.map(L.SEVERITY)
        fig = px.pie(s, names="label", values="accidents", hole=.5, title="Accidents by most severe outcome",
                     color="label", color_discrete_map=L.SEVERITY_COLORS, category_orders={"label": L.SEVERITY_ORDER}, **PX)
        fig.update_traces(textinfo="percent+label", hovertemplate="%{label}: %{value:,} accidents (%{percent})")
        fig.update_layout(showlegend=False, separators=". ")
        show(fig)
    st.info(L.CONCENTRATION_NOTE)

# ------------------------------------------------------------------ B. temporal
elif page == "Temporal analysis":
    header("Temporal analysis")
    m = data.month_by_year(years, dep)
    m["Month"] = m.month.map(L.MONTHS)
    fig = px.line(m, x="Month", y="accidents", color=m.year.astype(str), markers=True, title="Accidents by month",
                  labels={"accidents": "Accidents", "color": "Year"}, **PX,
                  color_discrete_map={"2020": L.COLORS["covid"]})
    fig.update_layout(separators=". ")
    show(fig)
    if 2020 in years:
        st.caption(L.COVID_NOTE)
    c1, c2 = st.columns(2)
    wd = data.by_column("weekday", years, dep)
    wd["Weekday"] = wd.value.map(L.WEEKDAYS)
    wd["per_day"] = wd.accidents / wd.days
    with c1:
        fig = px.bar(wd, x="Weekday", y="per_day", title="Average accidents per day, by weekday", **PX,
                     labels={"per_day": "Accidents per day"}, color_discrete_sequence=[L.COLORS["main"]])
        fig.update_traces(hovertemplate="%{x}: %{y:.1f} accidents/day")
        show(fig)
    h = data.by_column("hour", years, dep)
    h["fatal_share"], h["lo"], h["hi"] = wilson(h.fatal, h.accidents)
    with c2:
        fig = go.Figure()
        fig.add_bar(x=h.value, y=h.accidents, name="Accidents", marker_color=L.COLORS["main"],
                    hovertemplate="%{x}:00 — %{y:,} accidents<extra></extra>")
        fig.add_scatter(x=h.value, y=100 * h.fatal_share, name="Fatal share (%)", yaxis="y2", mode="lines+markers",
                        line=dict(color=L.COLORS["covid"]), hovertemplate="%{x}:00 — %{y:.1f} % fatal<extra></extra>")
        fig.update_layout(template="plotly_white", title="Accidents and fatal share by hour", separators=". ",
                          xaxis=dict(title="Hour of day", dtick=2), yaxis=dict(title="Accidents"),
                          yaxis2=dict(title="Fatal accidents (%)", overlaying="y", side="right", showgrid=False),
                          legend=dict(orientation="h", y=1.12))
        show(fig)
    we = data.by_column("is_weekend", years, dep).set_index("value")
    st.subheader("Weekday versus weekend")
    c1, c2, c3, c4 = st.columns(4)
    for col, key, lab in ((c1, False, "Weekday"), (c3, True, "Weekend")):
        if key in we.index:
            r = we.loc[key]
            col.metric(f"{lab}: accidents per day", f"{r.accidents / r.days:.1f}")
    for col, key, lab in ((c2, False, "Weekday"), (c4, True, "Weekend")):
        if key in we.index:
            r = we.loc[key]
            col.metric(f"{lab}: fatal share", f"{100 * r.fatal / r.accidents:.1f} %")
    st.caption("Fatal share = fatal accidents / injury accidents in the group (severity given an accident, not risk).")

# ------------------------------------------------------------------ C. severity & road users
elif page == "Severity & road users":
    header("Severity & road users", "fugitive-like users and unknown severity excluded")
    u = data.users(years, dep)
    u["Outcome"] = u.grav.map(L.GRAV)
    c1, c2 = st.columns(2)
    with c1:
        t = u.groupby("Outcome", as_index=False).n.sum()
        fig = px.bar(t, x="Outcome", y="n", text="n", title="Road users involved, by outcome", **PX,
                     category_orders={"Outcome": L.GRAV_ORDER}, color="Outcome", color_discrete_map=L.SEVERITY_COLORS,
                     labels={"n": "Road users"})
        fig.update_traces(texttemplate="%{text:,}")
        fig.update_layout(showlegend=False, separators=". ")
        show(fig)
    with c2:
        t = u.assign(Category=u.catu.map(L.CATU)).groupby(["Category", "Outcome"], as_index=False).n.sum()
        t["share"] = 100 * t.n / t.groupby("Category").n.transform("sum")
        fig = px.bar(t, x="share", y="Category", color="Outcome", orientation="h", title="Outcome by road-user category (%)",
                     category_orders={"Outcome": L.GRAV_ORDER}, color_discrete_map=L.SEVERITY_COLORS, **PX,
                     labels={"share": "% of users in category"}, hover_data={"n": ":,", "share": ":.1f"})
        fig.update_layout(legend=dict(orientation="h", y=1.15, title=""))
        show(fig)
    c1, c2 = st.columns(2)
    a = u.dropna(subset=["age_group", "sexe"]).assign(Sex=lambda d: d.sexe.map(L.SEXE))
    with c1:
        t = a.groupby(["age_group", "Sex"], as_index=False).n.sum()
        fig = px.bar(t, x="age_group", y="n", color="Sex", barmode="group", title="Road users involved, by age and sex",
                     labels={"age_group": "Age group", "n": "Road users"}, **PX,
                     color_discrete_map={"Male": L.COLORS["main"], "Female": L.COLORS["alt"]})
        fig.update_layout(separators=". ", legend=dict(orientation="h", y=1.12, title=""))
        show(fig)
    with c2:
        g = a.groupby(["age_group", "Sex"]).apply(lambda d: pd.Series({"n": d.n.sum(), "ksi": d.loc[d.grav.isin([2, 3]), "n"].sum()}),
                                                  include_groups=False).reset_index()
        g["share"], g["lo"], g["hi"] = wilson(g.ksi, g.n)
        fig = px.line(g, x="age_group", y=100 * g.share, color="Sex", markers=True, **PX,
                      title="Killed or hospitalised (% of users involved)",
                      error_y=100 * (g.hi - g.share), error_y_minus=100 * (g.share - g.lo),
                      labels={"age_group": "Age group", "y": "% killed or hospitalised"},
                      color_discrete_map={"Male": L.COLORS["main"], "Female": L.COLORS["alt"]})
        fig.update_layout(legend=dict(orientation="h", y=1.12, title=""))
        show(fig)
    st.subheader("Vulnerable road users")
    m = u.groupby("mode").apply(lambda d: pd.Series({"n": d.n.sum(), "killed": d.loc[d.grav == 2, "n"].sum(),
                                                      "ksi": d.loc[d.grav.isin([2, 3]), "n"].sum()}), include_groups=False).reset_index()
    m["killed_pct"], m["ksi_pct"] = 100 * m.killed / m.n, 100 * m.ksi / m.n
    vulnerable = {"Pedestrian", "Bicycle", "E-bike", "Personal mobility device", "Powered 2/3-wheeler"}
    m["Group"] = np.where(m["mode"].isin(vulnerable), "Vulnerable", "Other")
    m = m.sort_values("ksi_pct")
    fig = px.bar(m, x="ksi_pct", y="mode", color="Group", orientation="h", **PX,
                 title="Killed or hospitalised (% of users involved), by travel mode",
                 hover_data={"n": ":,", "killed_pct": ":.2f", "ksi_pct": ":.1f", "Group": False},
                 labels={"ksi_pct": "% killed or hospitalised", "mode": "", "n": "users", "killed_pct": "% killed"},
                 color_discrete_map={"Vulnerable": L.COLORS["covid"], "Other": L.COLORS["grey"]})
    show(fig)
    st.caption(f"{L.FUGITIVE_NOTE} {L.HOSP_NOTE} Shares describe outcomes once involved in an injury accident — not risk.")

# ------------------------------------------------------------------ D. environmental conditions
elif page == "Environmental conditions":
    header("Environmental conditions", "accident level; not recorded / conflicting values excluded")
    tabs = st.tabs(["Weather", "Lighting", "Road category", "Built-up area"])
    for tab, (col, lab) in zip(tabs, (("atm", L.ATM), ("lum", L.LUM), ("catr", L.CATR), ("agg", L.AGG))):
        with tab:
            d = data.by_column(col, years, dep).dropna(subset=["value"])
            d["label"] = d.value.astype(int).map(lab)
            d["share"], d["lo"], d["hi"] = wilson(d.fatal, d.accidents)
            c1, c2 = st.columns(2)
            fig = px.bar(d.sort_values("accidents"), x="accidents", y="label", orientation="h", title="Accidents", **PX,
                         labels={"accidents": "Accidents", "label": ""}, color_discrete_sequence=[L.COLORS["main"]])
            fig.update_layout(separators=". ")
            show(fig, c1)
            ds = d.sort_values("share")
            fig = px.scatter(ds, x=100 * ds.share, y="label", title="Fatal accidents (% of accidents, 95 % CI)", **PX,
                             error_x=100 * (ds.hi - ds.share), error_x_minus=100 * (ds.share - ds.lo),
                             hover_data={"accidents": ":,"}, labels={"x": "Fatal share (%)", "label": ""},
                             color_discrete_sequence=[L.COLORS["covid"]])
            show(fig, c2)
            if col == "catr":
                st.caption("Road categories 4 (communal) and 7 (metropolitan) are grouped: code 7 is unstable over time.")
    st.caption("Lighting, road category and built-up area are strongly inter-related (e.g. unlit roads are mostly rural); "
               "these are unadjusted, non-causal comparisons.")

# ------------------------------------------------------------------ E. geospatial analysis
elif page == "Geospatial analysis":
    header("Geospatial analysis", "IGN ADMIN EXPRESS COG 2025 (= COG 2026) boundaries")
    tabs = st.tabs(["Accident distribution", "Departments: count vs severity", "Communes", "Persistent hotspots"])
    with tabs[0]:
        min_n = st.slider("Show 1 km cells with at least … accidents", 1, 50, 5,
                          help="Default hotspot population; 1 km cells in Lambert-93 (EPSG:2154).")
        g = data.grid_cells(years, dep)
        g = g[g.accidents >= min_n]
        if dep is None or g.empty:
            view_center, view_zoom = FRANCE_CENTER, 4.6
        else:   # fit the view to the displayed cells so individual 1 km cells are distinguishable
            span = max(g.lon.max() - g.lon.min(), 1.4 * (g.lat.max() - g.lat.min()), 0.02)
            view_center = {"lat": float((g.lat.min() + g.lat.max()) / 2), "lon": float((g.lon.min() + g.lon.max()) / 2)}
            view_zoom = float(np.clip(np.log2(360 / span) - 1.2, 6, 12))
        fig = px.scatter_map(g, lat="lat", lon="lon", color=np.log10(g.accidents), hover_name=g.com.map(data.commune_names()),
                             hover_data={"accidents": ":,", "fatal": True, "lat": False, "lon": False},
                             color_continuous_scale="Inferno_r", zoom=view_zoom, height=620, center=view_center,
                             map_style=MAP_STYLE, title=f"{fmt(len(g))} cells with ≥ {min_n} accidents")
        fig.update_traces(marker=dict(size=9, opacity=.9))
        fig.update_layout(coloraxis=dict(cmin=ACCIDENT_LOG_RANGE[0], cmax=ACCIDENT_LOG_RANGE[1]))
        fig.update_layout(coloraxis_colorbar=dict(title="accidents", tickvals=[0, 1, 2, 3], ticktext=["1", "10", "100", "1 000"]),
                          margin=dict(l=0, r=0, t=40, b=0))
        show(fig)
        st.caption("Excludes 659 accidents with unreliable points (606 wrong-commune points, kept for sensitivity analysis only). "
                   "The 11 proposed coordinate corrections are not applied.")
    with tabs[1]:
        ds = data.department_stats(years).merge(deps, on="dep_code")
        ds["accidents_per_year"] = ds.accidents / len(years)
        ds["fatal_share_pct"] = 100 * ds.fatal_accidents / ds.accidents
        gj = data.department_geojson()
        c1, c2 = st.columns(2)
        for col, metric, title, scale in ((c1, "accidents_per_year", "Accidents per year (concentration)", "Blues"),
                                          (c2, "fatal_share_pct", "Fatal accidents, % of accidents (severity)", "OrRd")):
            fig = px.choropleth_map(ds, geojson=gj, locations="dep_code", color=metric if metric != "accidents_per_year" else np.log10(ds[metric]),
                                    hover_name="name", color_continuous_scale=scale, map_style=MAP_STYLE,
                                    zoom=4.3, center={"lat": 46.6, "lon": 2.4}, opacity=.8, height=520, title=title,
                                    hover_data={"dep_code": True, "accidents": ":,", "killed": ":,", "fatal_share_pct": ":.1f"})
            if metric == "accidents_per_year":
                fig.update_layout(coloraxis_colorbar=dict(title="per year", tickvals=[2, 2.5, 3, 3.5],
                                                          ticktext=["100", "316", "1 000", "3 162"]))
            else:
                fig.update_layout(coloraxis_colorbar=dict(title="% fatal"))
            fig.update_layout(margin=dict(l=0, r=0, t=40, b=0))
            show(fig, col)
        st.caption("Dense urban departments record the most accidents but the lowest fatal share; rural departments the reverse.")
        st.dataframe(theme.style_table(ds.sort_values("accidents", ascending=False)[["dep_code", "name", "accidents", "fatal_accidents", "killed", "fatal_share_pct"]], DARK_MODE),
                     hide_index=True, width="stretch",
                     column_config={"fatal_share_pct": st.column_config.NumberColumn("fatal share (%)", format="%.1f"),
                                    "accidents": st.column_config.NumberColumn(format="%d")})
    with tabs[2]:
        cdep = dep or st.selectbox("Department to explore", deps.dep_code, format_func=lambda c: f"{c} – {deps.set_index('dep_code').name[c]}",
                                   index=int(np.flatnonzero(deps.dep_code == "75")[0]))
        cs = data.commune_stats(years, cdep)
        fig = px.choropleth_map(cs, geojson=data.commune_geojson(cdep), locations="com", color=np.log10(cs.accidents.clip(lower=1)),
                                hover_name="name", hover_data={"com": False, "accidents": ":,", "killed": True},
                                color_continuous_scale="Viridis_r", map_style=MAP_STYLE, zoom=7.5 if cdep != "75" else 10.5,
                                center={"lat": float(data.grid_cells(years, cdep).lat.median()), "lon": float(data.grid_cells(years, cdep).lon.median())},
                                opacity=.75, height=560, title=f"Accidents per commune (COG 2026), department {cdep}")
        fig.update_layout(coloraxis_colorbar=dict(title="accidents", tickvals=[0, 1, 2, 3, 4], ticktext=["1", "10", "100", "1 000", "10 000"]),
                          margin=dict(l=0, r=0, t=40, b=0))
        show(fig)
        st.dataframe(theme.style_table(cs.sort_values("accidents", ascending=False).head(15), DARK_MODE), hide_index=True, width="stretch")
        st.caption("Communes differ greatly in size and traffic: counts are not comparable as risk.")
    with tabs[3]:
        hp = data.phase5_hotspots()
        k = st.slider("Persistence: top-1 % in at least … of the 6 normal years (2019, 2021–2025)", 0, 6, 6)
        h = hp[hp.years_top1pct >= k]
        fig = px.scatter_map(h, lat="lat", lon="lon", size="n", color="years_top1pct", hover_name="commune",
                             hover_data={"n": ":,", "fatal": True, "years_top1pct": True, "lat": False, "lon": False},
                             color_continuous_scale="Reds", zoom=4.6, height=600, map_style=MAP_STYLE, center=FRANCE_CENTER,
                             range_color=[-2, 6], opacity=.9,   # fixed range: a single persistence value is not near-white
                             title=f"{fmt(len(h))} hotspot cells (1 km, ≥ 57 accidents 2019–2025) — Phase 5 result")
        fig.update_layout(margin=dict(l=0, r=0, t=40, b=0), coloraxis_colorbar=dict(title="years in top 1 %"))
        show(fig)
        st.caption("Phase 5 hotspots are computed on all years 2019–2025 (year filter not applied here). Hotspot cells hold "
                   "32.5 % of accidents but only 6.2 % of fatal accidents.")

# ------------------------------------------------------------------ F. hotspot explorer
elif page == "Hotspot explorer":
    header("Hotspot explorer", "1 km cells, default hotspot population (Phase 5 method)")
    city = st.radio("Area", list(L.CITIES), horizontal=True)
    cx, cy = L.CITIES[city]
    hw = L.CITY_HALF_WIDTH_M
    g = data.grid_cells(years, None, (cx - hw, cy - hw, cx + hw, cy + hw))
    thr = data.national_top1pct_threshold(years)
    g["hotspot"] = np.where(g.accidents >= thr, "Top 1 % nationally", "Other cells")
    g["commune"] = g.com.map(data.commune_names())
    persist = data.phase5_hotspots().set_index(["gx", "gy"]).years_top1pct
    g = g.join(persist, on=["gx", "gy"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Cells with accidents (50 km window)", fmt(len(g)))
    c2.metric("Hotspot cells (national top 1 %)", fmt((g.accidents >= thr).sum()), help=f"Threshold for selected years: ≥ {thr:.0f} accidents per cell")
    c3.metric("Accidents in hotspot cells", fmt(g.loc[g.accidents >= thr, "accidents"].sum()))
    fig = px.scatter_map(g, lat="lat", lon="lon", color=np.log10(g.accidents), size=np.where(g.accidents >= thr, 12, 8),
                         hover_name="commune", hover_data={"accidents": ":,", "fatal": True, "years_top1pct": True, "lat": False, "lon": False},
                         color_continuous_scale="Inferno_r", zoom=9.3, height=620, map_style=MAP_STYLE, size_max=12,
                         range_color=ACCIDENT_LOG_RANGE,
                         center=dict(zip(("lon", "lat"), data.TO_WGS84.transform(cx, cy))))
    fig.update_layout(coloraxis_colorbar=dict(title="accidents", tickvals=[0, 1, 2, 3], ticktext=["1", "10", "100", "1 000"]),
                      margin=dict(l=0, r=0, t=10, b=0))
    show(fig)
    st.subheader("Top cells in the window")
    st.dataframe(theme.style_table(g.sort_values("accidents", ascending=False).head(20)[["commune", "accidents", "fatal", "years_top1pct", "gx", "gy"]]
                 .rename(columns={"gx": "x (km, L93)", "gy": "y (km, L93)", "years_top1pct": "years in top 1 % (all-years run)"}), DARK_MODE),
                 hide_index=True, width="stretch")
    st.caption(f"Larger dots = cells in the national top 1 % for the selected years. {L.CONCENTRATION_NOTE}")
