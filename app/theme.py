"""Light / Dark display themes for the dashboard (session-specific).

* Light Mode = the existing appearance: no CSS is injected and figures are returned unchanged.
* Dark Mode  = CSS injected into the current user's page only (st.markdown) + a layout-only Plotly restyle.
  Nothing here changes Streamlit's server-wide config, so other users are unaffected.
Trace colours, colour scales, ranges, map styles, centres and zoom are never modified.
"""
from __future__ import annotations

import plotly.graph_objects as go

DARK = {
    "bg": "#0e1117",          # main background
    "panel": "#1a1d24",       # sidebar, inputs, popovers
    "input": "#262a33",       # input boxes (slightly lighter than the sidebar so they stay visible)
    "border": "#3a3f4b",
    "text": "#f0f2f6",
    "muted": "#a3a8b8",       # captions, secondary labels
    "grid": "#2f3440",
    "accent": "#63b3ed",
}

DARK_CSS = f"""
<style>
/* ---- page, header, sidebar ---- */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background-color: {DARK['bg']}; color: {DARK['text']}; }}
[data-testid="stHeader"] {{ background-color: {DARK['bg']}; }}
[data-testid="stToolbar"] *, [data-testid="stHeader"] button {{ color: {DARK['text']}; }}
[data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child {{ background-color: {DARK['panel']}; }}
[data-testid="stSidebar"] hr, .stApp hr {{ border-color: {DARK['border']}; }}

/* ---- text, headings, captions ---- */
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p, .stApp label, .stApp label p {{ color: {DARK['text']}; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: {DARK['muted']}; }}
[data-testid="stTooltipIcon"] svg, [data-testid="stTooltipHoverTarget"] svg {{ color: {DARK['muted']}; stroke: {DARK['muted']}; }}

/* ---- KPI cards ---- */
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {{ color: {DARK['muted']}; }}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] div {{ color: {DARK['text']}; }}

/* ---- info boxes ---- */
[data-testid="stAlert"] [data-testid="stAlertContainer"], [data-testid="stAlertContainer"] {{
    background-color: rgba(99, 179, 237, 0.14); }}
[data-testid="stAlertContainer"] p, [data-testid="stAlertContainer"] * {{ color: {DARK['text']}; }}

/* ---- tabs ---- */
[data-baseweb="tab-list"] {{ border-bottom-color: {DARK['border']}; }}
[data-baseweb="tab"] p {{ color: {DARK['muted']}; }}
[data-baseweb="tab"][aria-selected="true"] p {{ color: {DARK['accent']}; }}
[data-baseweb="tab-border"] {{ background-color: {DARK['border']}; }}

/* ---- inputs: selectbox, multiselect (Streamlit 1.67 markup), dropdown menus, slider, radio ---- */
[data-testid="stMultiSelect"] > div, [data-testid="stMultiSelect"] > div div,
[data-testid="stSelectbox"] > div, [data-testid="stSelectbox"] > div div {{
    background-color: {DARK['input']} !important; border-color: {DARK['border']} !important; }}
[data-testid="stMultiSelect"] > div input, [data-testid="stSelectbox"] > div input,
[data-testid="stSelectbox"] > div div {{ color: {DARK['text']} !important; }}
[data-testid="stMultiSelect"] > div svg, [data-testid="stSelectbox"] > div svg {{ color: {DARK['muted']} !important; fill: {DARK['muted']} !important; }}
[data-testid="stMultiSelect"] span[class] {{ color: #ffffff; }}          /* selected-year chips keep their blue */
[role="listbox"], [role="listbox"] li, [role="option"], [data-baseweb="popover"] ul, [data-baseweb="popover"] li {{
    background-color: {DARK['input']} !important; color: {DARK['text']} !important; }}
[role="option"]:hover, [role="option"][aria-selected="true"] {{ background-color: {DARK['border']} !important; }}
[data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"], [data-testid="stSliderThumbValue"] {{ color: {DARK['text']}; }}
[data-testid="stRadio"] label p, [data-testid="stCheckbox"] label p {{ color: {DARK['text']}; }}
/* radio option = label > span(hidden input) + div > [ring div > dot div] + markdown */
[data-testid="stRadioOption"] > div > div:first-child {{ background-color: {DARK['input']} !important; border: 1px solid {DARK['muted']} !important; }}
[data-testid="stRadioOption"] > div > div:first-child > div {{ background-color: {DARK['input']} !important; }}
[data-testid="stRadioOption"]:has(input:checked) > div > div:first-child {{ background-color: #2b6cb0 !important; border-color: #2b6cb0 !important; }}
[data-testid="stRadioOption"]:has(input:checked) > div > div:first-child > div {{ background-color: #ffffff !important; }}
[data-testid="stTooltipHoverTarget"] svg, [data-testid="stTooltipIcon"] svg {{ stroke: {DARK['muted']} !important; color: {DARK['muted']} !important; }}

/* ---- tables (canvas grid): only the frame is styled here; cell colours come from a dark pandas Styler ---- */
[data-testid="stDataFrame"] {{ border: 1px solid {DARK['border']}; border-radius: 0.5rem; background-color: {DARK['bg']}; }}
</style>
"""


def style_figure(fig: go.Figure, dark: bool) -> go.Figure:
    """Layout-only restyle for Dark Mode. Light Mode: figure returned unchanged."""
    if not dark:
        return fig
    axis = dict(gridcolor=DARK["grid"], zerolinecolor=DARK["grid"], linecolor=DARK["border"],
                tickfont=dict(color=DARK["text"]), title_font=dict(color=DARK["text"]))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=DARK["text"]), title_font=dict(color=DARK["text"]),
        legend=dict(font=dict(color=DARK["text"]), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=DARK["panel"], bordercolor=DARK["border"], font=dict(color=DARK["text"])),
    )
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    if fig.layout.coloraxis and fig.layout.coloraxis.colorbar is not None:
        fig.update_layout(coloraxis_colorbar=dict(tickfont=dict(color=DARK["text"]), title_font=dict(color=DARK["text"])))
    return fig


def style_table(df, dark: bool):
    """Dark Mode: a pandas Styler with dark cells and light text (drawn by Streamlit's grid itself, no CSS inversion).
    Light Mode: the DataFrame is returned unchanged."""
    if not dark:
        return df
    return df.style.set_properties(**{"background-color": DARK["bg"], "color": DARK["text"]})
