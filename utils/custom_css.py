"""Institutional Premium design system for the Red Flag Intelligence Streamlit app."""
from __future__ import annotations

import streamlit as st

# Lucide icon paths (24x24, stroke 2). Source: lucide.dev (ISC licence).
_ICONS = {
    "shield-alert": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    "building": '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
    "leaf": '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z"/><path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12"/>',
    "landmark": '<line x1="3" x2="21" y1="22" y2="22"/><line x1="6" x2="6" y1="18" y2="11"/><line x1="10" x2="10" y1="18" y2="11"/><line x1="14" x2="14" y1="18" y2="11"/><line x1="18" x2="18" y1="18" y2="11"/><polygon points="12 2 20 7 4 7"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "trending-up": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
    "trending-down": '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/><polyline points="16 17 22 17 22 11"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    "check": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>',
    "chart": '<line x1="12" x2="12" y1="20" y2="10"/><line x1="18" x2="18" y1="20" y2="4"/><line x1="6" x2="6" y1="20" y2="16"/>',
    "briefcase": '<path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/><rect width="20" height="14" x="2" y="6" rx="2"/>',
    "file": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "grid": '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
}


def icon(name: str, size: int = 18, color: str = "currentColor") -> str:
    """Return an inline Lucide-style SVG string."""
    body = _ICONS.get(name, _ICONS["info"])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="rf-icon">{body}</svg>')


_INSTITUTIONAL_CSS = r"""
:root {
  color-scheme: dark;
  --rf-bg: #07111d;
  --rf-bg-deep: #050c15;
  --rf-surface: #0b1928;
  --rf-surface-2: #0e2031;
  --rf-surface-3: #12283b;
  --rf-border: rgba(137, 170, 195, .20);
  --rf-border-strong: rgba(81, 161, 198, .34);
  --rf-text: #edf4f8;
  --rf-muted: #a5b6c4;
  --rf-subtle: #7f95a6;
  --rf-accent: #55a9cb;
  --rf-accent-soft: rgba(85, 169, 203, .12);
  --rf-positive: #45c49a;
  --rf-warning: #e8b65a;
  --rf-negative: #e47e83;
  --rf-radius: 12px;
  --rf-shadow: 0 10px 26px rgba(0, 0, 0, .20);
}

html, body, [class*="css"], .stApp, button, input, select, textarea {
  font-family: Inter, "Segoe UI", Arial, sans-serif !important;
  color: var(--rf-text);
}
html, body { background: var(--rf-bg-deep) !important; }
.stApp, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(ellipse at 72% -8%, rgba(48, 115, 151, .13), transparent 32%),
    linear-gradient(180deg, #081523 0%, #07111d 48%, #060e18 100%) !important;
  color: var(--rf-text) !important;
}
[data-testid="stAppViewContainer"] > .main { background: transparent !important; }
[data-testid="stHeader"] {
  background: rgba(6, 15, 25, .88) !important;
  border-bottom: 1px solid rgba(137, 170, 195, .13) !important;
  backdrop-filter: blur(14px);
}
[data-testid="stToolbar"], #MainMenu, footer { visibility: hidden !important; }
.block-container {
  max-width: 1580px !important;
  padding-top: 2.15rem !important;
  padding-bottom: 3.2rem !important;
}

/* Consistent type scale and spacing across all research pages. */
.stApp h1 { font-size: clamp(1.75rem, 2.3vw, 2.15rem) !important; font-weight: 750 !important; letter-spacing: -.035em !important; color: var(--rf-text) !important; }
.stApp h2 { font-size: 1.34rem !important; font-weight: 700 !important; letter-spacing: -.02em !important; color: var(--rf-text) !important; }
.stApp h3 { font-size: 1.10rem !important; font-weight: 680 !important; color: var(--rf-text) !important; }
.stApp h4 { font-size: 1rem !important; font-weight: 650 !important; color: var(--rf-text) !important; }
.stApp p, .stApp li, .stApp label, .stApp [data-testid="stMarkdownContainer"] { color: var(--rf-text); }
.stApp p, .stApp li { font-size: 14.5px; line-height: 1.58; }
[data-testid="stCaptionContainer"], .stCaption, .rf-sub, .co-source { color: var(--rf-muted) !important; }
.rf-icon { vertical-align: -3px; flex: none; }

.rf-sidebar-brand { display:flex; align-items:center; gap:10px; padding:6px 4px 13px; margin-bottom:8px; border-bottom:1px solid var(--rf-border); }
.rf-sidebar-mark { display:flex; align-items:center; justify-content:center; width:34px; height:34px; border-radius:9px; background:#17415a; border:1px solid rgba(85,169,203,.42); color:#b9e0ee !important; font-size:12px; font-weight:800; letter-spacing:-.04em; }
.rf-sidebar-brand b { display:block; font-size:13px; line-height:1.2; color:var(--rf-text) !important; }
.rf-sidebar-brand small { display:block; font-size:10px; margin-top:3px; color:var(--rf-muted) !important; }
.co-system-tag { display:inline-block; vertical-align:2px; margin-left:7px; padding:3px 7px; border:1px solid rgba(85,169,203,.30); border-radius:5px; background:rgba(85,169,203,.10); color:#91c9de; font-size:9px; font-weight:750; letter-spacing:.07em; }

/* Sidebar and native page navigation. */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #081624 0%, #07121f 100%) !important;
  border-right: 1px solid var(--rf-border) !important;
  box-shadow: 8px 0 26px rgba(0, 0, 0, .18) !important;
}
[data-testid="stSidebar"] * { color: var(--rf-text) !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small { color: var(--rf-muted) !important; }
[data-testid="stSidebarNav"] { padding-top: .25rem; }
[data-testid="stSidebarNav"] a,
[data-testid="stSidebarNavLink"] {
  border-radius: 8px !important;
  border: 1px solid transparent !important;
  padding: .38rem .55rem !important;
  margin: 2px 0 !important;
  transition: background .18s ease, border-color .18s ease !important;
}
[data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebarNavLink"]:hover {
  background: rgba(85, 169, 203, .09) !important;
  border-color: rgba(85, 169, 203, .17) !important;
}
[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebarNavLink"][aria-current="page"] {
  background: linear-gradient(90deg, rgba(42, 107, 143, .36), rgba(24, 61, 86, .24)) !important;
  border-color: rgba(85, 169, 203, .32) !important;
  box-shadow: inset 3px 0 0 var(--rf-accent);
}
[data-testid="stSidebar"] hr { border-color: var(--rf-border) !important; }

/* App-wide card language. */
.rf-card, .rf-panel, .rf-intel-card, .rf-market-card, .rf-callout,
.co-panel, .co-header, .co-metric-card, .co-news,
[data-testid="stMetric"], [data-testid="stExpander"], [data-testid="stDataFrame"],
[data-testid="stTable"] {
  background: linear-gradient(145deg, rgba(14, 32, 49, .96), rgba(9, 22, 35, .97)) !important;
  border: 1px solid var(--rf-border) !important;
  border-radius: var(--rf-radius) !important;
  box-shadow: var(--rf-shadow) !important;
  color: var(--rf-text) !important;
}
.rf-card { padding: 1.1rem 1.2rem; }
.rf-card h3 { margin: 0 0 .35rem; font-size: 1.08rem !important; }
.rf-card.flat { box-shadow: none !important; }
.rf-card:hover, .rf-market-card:hover, .rf-welcome-picker:hover {
  border-color: var(--rf-border-strong) !important;
}
.rf-hero {
  padding: .65rem 0 1.35rem;
  margin-bottom: .25rem;
  animation: rf-enter .32s ease both;
}
.rf-hero h1 { margin: 0 0 .45rem !important; }
.rf-hero p { max-width: 940px; font-size: 15px !important; color: var(--rf-muted) !important; margin: 0; }
.rf-demo { display: inline-flex; gap: .4rem; align-items: center; margin-top: .65rem; padding: .22rem .62rem; border: 1px solid var(--rf-border); border-radius: 999px; color: var(--rf-muted); font-size: 11px; }
.rf-section { margin: 1.8rem 0 .75rem; }
.rf-section h2 { font-size: 1.23rem !important; margin: 0; display: flex; align-items: center; gap: .5rem; }
.rf-section p { color: var(--rf-muted) !important; font-size: 13px !important; margin: .22rem 0 0; }
.rf-grid { display: grid; gap: .85rem; }
.rf-grid.c4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.rf-grid.c3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.rf-grid.c2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.rf-label { color: var(--rf-muted) !important; font-size: 12px; font-weight: 600; display: flex; align-items: center; gap: .35rem; }
.rf-value { font-size: 1.8rem; font-weight: 740; line-height: 1.2; margin: .4rem 0 .15rem; letter-spacing: -.03em; }
.rf-sub { font-size: 12px; }
.rf-badge { display: inline-flex; align-items: center; border-radius: 6px; padding: .18rem .5rem; font-size: 11px; font-weight: 650; white-space: nowrap; }
.rf-badge.green { background: rgba(69, 196, 154, .12) !important; color: #80dfbc !important; }
.rf-badge.amber { background: rgba(232, 182, 90, .13) !important; color: #f0ca7d !important; }
.rf-badge.red, .rf-badge.crit { background: rgba(228, 126, 131, .12) !important; color: #f1a3a6 !important; }
.rf-badge.blue { background: rgba(85, 169, 203, .13) !important; color: #8cc9e0 !important; }
.rf-badge.gray { background: rgba(148, 163, 184, .10) !important; color: #bac8d2 !important; }
.rf-flag, .co-flag { background: rgba(11, 26, 41, .92) !important; border: 1px solid var(--rf-border) !important; border-left: 3px solid var(--rf-warning) !important; border-radius: 9px !important; padding: .85rem 1rem !important; margin-bottom: .7rem; }
.rf-flag.Low { border-left-color: var(--rf-accent) !important; }
.rf-flag.Medium { border-left-color: var(--rf-warning) !important; }
.rf-flag.High, .rf-flag.Critical { border-left-color: var(--rf-negative) !important; }
.rf-flag-title, .co-flag-title { color: var(--rf-text) !important; font-weight: 700; }
.rf-flag-metric, .rf-flag-logic, .rf-flag-text { color: var(--rf-muted) !important; }
.rf-flag-logic { border-top: 1px solid var(--rf-border) !important; }
.rf-callout { padding: 1rem 1.15rem; }
.rf-callout p { margin: .35rem 0; }
.rf-row { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: .72rem 0; border-bottom: 1px solid var(--rf-border); }
.rf-row:last-child { border-bottom: 0; }
.rf-row .m, .muted { color: var(--rf-muted) !important; font-size: 12px; }
.rf-analyst { margin: .55rem 0 .12rem; padding: .6rem .75rem; border-left: 2px solid var(--rf-accent); border-radius: 0 8px 8px 0; background: rgba(85, 169, 203, .07); color: #c9d8e2; font-size: 13px; line-height: 1.55; }
.rf-analyst b { color: #9bcfe3; }
.rf-source { color: var(--rf-subtle) !important; font-size: 11px; line-height: 1.45; }
.rf-source a, .co-source a, .co-news a { color: #86c4dc !important; }

/* Company Overview modules share these tokens; page-specific data layout remains intact. */
.co-header { padding: 1rem 1.2rem !important; margin-bottom: .8rem; border-color: var(--rf-border-strong) !important; }
.co-eyebrow { color: #8dc8df !important; font-size: 11px; letter-spacing: .09em; text-transform: uppercase; font-weight: 700; }
.co-company-name { color: var(--rf-text) !important; font-size: 1.8rem !important; font-weight: 760 !important; }
.co-company-sub { color: #c0ced8 !important; font-size: 13px !important; }
.co-tag { border: 1px solid var(--rf-border) !important; background: rgba(85, 169, 203, .08) !important; color: #b9d9e6 !important; border-radius: 6px !important; font-size: 11px !important; }
.co-panel { background: linear-gradient(145deg, #0e2031, #0a1827) !important; border: 1px solid var(--rf-border) !important; border-radius: 10px !important; padding: 1rem 1.05rem !important; margin: .55rem 0 .75rem !important; box-shadow: var(--rf-shadow) !important; }
.co-panel-title { color: var(--rf-text) !important; font-size: 1.02rem !important; font-weight: 700 !important; margin-bottom: .45rem !important; }
.co-panel-sub, .co-info-label, .co-metric-label, .co-metric-sub, .co-source, .co-table-caption { color: var(--rf-muted) !important; }
.co-info { background: rgba(7, 18, 30, .65) !important; border: 1px solid rgba(137, 170, 195, .14) !important; border-radius: 7px !important; }
.co-info-value, .co-health-name, .co-flag-evidence { color: #dce7ee !important; }
.co-metric-card { min-height: 94px !important; padding: .85rem .95rem !important; border-radius: 9px !important; background: linear-gradient(145deg, #11273a, #0b1a2a) !important; }
.co-metric-value { color: var(--rf-text) !important; font-size: 1.55rem !important; }
.co-observation { background: rgba(85, 169, 203, .07) !important; color: #d0dee7 !important; border-left-color: var(--rf-accent) !important; }
.co-observation.monitor { border-left-color: var(--rf-warning) !important; }
.co-observation.data { border-left-color: #8198a8 !important; }
.co-note { background: rgba(7, 18, 30, .55) !important; border-color: var(--rf-border) !important; color: var(--rf-muted) !important; }
.co-ratio-explain { background: #0b1b2a !important; border-color: var(--rf-border) !important; }
.co-ratio-explain h4 { color: var(--rf-text) !important; }
.co-ratio-explain p { color: #c3d2dc !important; }
.co-news { background: #0b1b2a !important; border-color: var(--rf-border) !important; }
.co-news-title { color: var(--rf-text) !important; }
.co-health-row { border-bottom-color: var(--rf-border) !important; }
.co-health-status.good { color: var(--rf-positive) !important; }
.co-health-status.bad { color: var(--rf-negative) !important; }
.co-health-status.stable { color: #8dc8df !important; }

/* Inputs, tabs, expanders and buttons. */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border: 1px solid rgba(137, 170, 195, .30) !important;
  background: linear-gradient(180deg, #142b40, #0d1d2e) !important;
  color: var(--rf-text) !important;
  border-radius: 8px !important;
  min-height: 2.35rem;
  font-weight: 650 !important;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
  border-color: rgba(85, 169, 203, .72) !important;
  background: #17364d !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: #1d6f94 !important;
  border-color: #2c83a8 !important;
  color: #fff !important;
}
.stButton > button[kind="primary"]:hover { background: #2381a8 !important; }
.stApp input, .stApp textarea, .stApp [data-baseweb="select"] > div {
  background: #091827 !important;
  color: var(--rf-text) !important;
  border-color: rgba(137, 170, 195, .30) !important;
  border-radius: 8px !important;
}
.stApp input::placeholder, .stApp textarea::placeholder { color: #8196a6 !important; }
.stApp [data-baseweb="popover"] > div, .stApp [data-baseweb="menu"],
.stApp [role="option"], .stApp [role="option"] * { background: #0d1c2b !important; color: var(--rf-text) !important; }
[data-testid="stTabs"] [role="tablist"] { gap: .3rem; border-bottom: 1px solid var(--rf-border); }
[data-testid="stTabs"] button[role="tab"] { color: var(--rf-muted) !important; border-radius: 7px 7px 0 0 !important; padding: .55rem .9rem !important; }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color: #a8d8e9 !important; border-bottom: 2px solid var(--rf-accent) !important; }
div[data-testid="stSegmentedControl"] { background: #091827 !important; border: 1px solid var(--rf-border) !important; border-radius: 9px !important; padding: 3px !important; }
div[data-testid="stSegmentedControl"] button { color: var(--rf-muted) !important; border-radius: 6px !important; font-size: 13px !important; }
div[data-testid="stSegmentedControl"] button[aria-pressed="true"] { background: #19415a !important; color: #eaf6fb !important; }
[data-testid="stExpander"] { background: rgba(11, 26, 41, .88) !important; border-radius: 9px !important; }

/* Tables and Plotly charts: consistent contrast and legible data density. */
[data-testid="stDataFrame"], [data-testid="stTable"] { overflow: hidden; }
[data-testid="stDataFrame"] [role="grid"], [data-testid="stDataFrame"] canvas { color: var(--rf-text) !important; }
[data-testid="stMetric"] { padding: .8rem .95rem !important; background: linear-gradient(145deg, #10253a, #0a1a2a) !important; }
[data-testid="stMetricLabel"] { color: var(--rf-muted) !important; font-size: 12px !important; }
[data-testid="stMetricValue"] { color: var(--rf-text) !important; font-size: 1.7rem !important; }
[data-testid="stMetricDelta"] { font-size: 12px !important; }
.stApp table { width: 100%; border-collapse: collapse; color: #dce7ee; font-size: 13px; }
.stApp table th { color: #a9c4d2; background: rgba(85, 169, 203, .08); font-weight: 650; text-align: left; }
.stApp table td, .stApp table th { padding: .55rem .65rem; border-bottom: 1px solid rgba(137, 170, 195, .14); }
.js-plotly-plot, .plot-container { background: transparent !important; }
.js-plotly-plot .plotly text, .js-plotly-plot .plotly .gtitle,
.js-plotly-plot .plotly .xtitle, .js-plotly-plot .plotly .ytitle,
.js-plotly-plot .plotly .legendtext { fill: #cbd9e2 !important; color: #cbd9e2 !important; }
.js-plotly-plot .plotly .gridlayer path { stroke: rgba(137, 170, 195, .15) !important; }
.js-plotly-plot .plotly .axis path, .js-plotly-plot .plotly .axis line { stroke: rgba(137, 170, 195, .30) !important; }

/* Welcome terminal modules use the same surfaces and readable scale. */
.rf-terminal-header, .rf-search-banner, .rf-panel, .rf-intel-card, .rf-workflow,
.rf-welcome-picker { border: 1px solid var(--rf-border-strong) !important; border-radius: 11px !important; box-shadow: var(--rf-shadow) !important; }
.rf-terminal-header { background: linear-gradient(110deg, #10283b, #0a1b2b) !important; }
.rf-brand-line { color: #f0f6f9 !important; font-size: clamp(27px, 2.8vw, 38px) !important; }
.rf-brand-line span { color: #84c8df !important; }
.rf-brand-sub, .rf-search-sub { color: var(--rf-muted) !important; }
.rf-shortcuts span { border-color: var(--rf-border) !important; color: #c8e2ec !important; background: rgba(7, 20, 32, .65) !important; }
.rf-search-banner { background: linear-gradient(110deg, #10283b, #0a1b2b) !important; }
.rf-search-title, .rf-heading, .rf-panel-title, .rf-intel-title { color: var(--rf-text) !important; }
.rf-heading span { color: #8bc6db !important; }
.rf-market-grid { gap: 10px !important; }
.rf-market-card { min-height: 118px !important; padding: 12px 14px !important; background: linear-gradient(145deg, #122a3e, #0a1a29) !important; border-color: var(--rf-border) !important; border-radius: 10px !important; }
.rf-market-card.positive { background: linear-gradient(145deg, #10352f, #0a1c29) !important; }
.rf-market-card.negative { background: linear-gradient(145deg, #38212a, #0a1c29) !important; }
.rf-market-top { color: #b5c6d1 !important; font-size: 12px !important; }
.rf-market-top b { color: #8dc8df !important; }
.rf-market-value { color: var(--rf-text) !important; font-size: 24px !important; }
.rf-market-change { color: var(--rf-positive) !important; font-size: 12px !important; }
.rf-market-card.negative .rf-market-change { color: var(--rf-negative) !important; }
.rf-market-date { color: var(--rf-subtle) !important; font-size: 10px !important; }
.rf-panel, .rf-intel-card { background: linear-gradient(145deg, #0e2234, #091827) !important; padding: 13px 14px !important; }
.rf-intel-card h4 { color: var(--rf-text) !important; font-size: 14px !important; }
.rf-intel-card table { font-size: 11px !important; }
.rf-intel-card th { color: #a8c1cf !important; }
.rf-intel-card td { color: #d1dde5 !important; }
.rf-intel-card .muted { font-size: 11px !important; }
.rf-intel-card .big { font-size: 21px !important; }
.rf-source { font-size: 10px !important; }
.rf-workflow { background: linear-gradient(100deg, #10283a, #0a1a29) !important; }
.rf-step, .rf-step strong { color: #dce7ee !important; }
.rf-step small { color: var(--rf-muted) !important; }
.rf-step b { background: #285e79 !important; color: white !important; }

.rf-space-stars { position: fixed; inset: 0; pointer-events: none; z-index: 0; opacity: .10; background-image: radial-gradient(circle, rgba(210,235,247,.7) 0 1px, transparent 1.4px); background-size: 180px 180px; }
@keyframes rf-enter { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 1050px) {
  .rf-grid.c4, .rf-grid.c3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rf-market-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
  .rf-intel-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
}
@media (max-width: 650px) {
  .block-container { padding-left: 1rem !important; padding-right: 1rem !important; }
  .rf-grid.c4, .rf-grid.c3, .rf-grid.c2, .rf-market-grid, .rf-intel-grid, .rf-workflow { grid-template-columns: 1fr !important; }
  .co-overview-grid, .co-info-grid, .co-metrics-grid { grid-template-columns: 1fr !important; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; scroll-behavior: auto !important; }
}
"""


_LIGHT_THEME_CSS = r"""
:root {
  color-scheme: light;
  --rf-bg: #f4f6f3; --rf-bg-deep: #eef1ed;
  --rf-surface: #ffffff; --rf-surface-2: #f8faf8; --rf-surface-3: #edf2ee;
  --rf-border: #dfe6e0; --rf-border-strong: #b9cec2;
  --rf-text: #202a25; --rf-muted: #637168; --rf-subtle: #7b8980;
  --rf-accent: #16856b; --rf-accent-soft: #e5f3ed;
  --rf-positive: #16845f; --rf-warning: #b7791f; --rf-negative: #c24145;
  --rf-radius: 12px; --rf-shadow: 0 5px 18px rgba(28, 45, 35, .055);
}
html, body, .stApp, [data-testid="stAppViewContainer"] { background: #f4f6f3 !important; color: #202a25 !important; }
.stApp, [data-testid="stAppViewContainer"] { background: linear-gradient(180deg,#f7f8f6 0%,#f1f4f0 100%) !important; }
[data-testid="stAppViewContainer"] > .main { background: transparent !important; }
[data-testid="stHeader"] { background: rgba(247,249,247,.94) !important; border-bottom:1px solid #e2e8e3 !important; }
.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp p,.stApp li,.stApp label,.stApp [data-testid="stMarkdownContainer"] { color:#202a25 !important; }
[data-testid="stCaptionContainer"],.stCaption,.rf-sub,.co-source,.rf-source { color:#68766d !important; }
[data-testid="stSidebar"] { background:#202a26 !important; border-right:1px solid #34423a !important; box-shadow:5px 0 20px rgba(20,35,27,.08) !important; }
[data-testid="stSidebar"] * { color:#edf3ee !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],[data-testid="stSidebar"] .stCaption,[data-testid="stSidebar"] small { color:#b7c5bc !important; }
[data-testid="stSidebarNav"] a[aria-current="page"],[data-testid="stSidebarNavLink"][aria-current="page"] { background:rgba(36,145,111,.20) !important; border-color:rgba(92,190,151,.38) !important; box-shadow:inset 3px 0 0 #36a47e !important; }
[data-testid="stSidebarNav"] a:hover,[data-testid="stSidebarNavLink"]:hover { background:rgba(255,255,255,.07) !important; border-color:rgba(255,255,255,.10) !important; }
.rf-card,.rf-panel,.rf-intel-card,.rf-market-card,.rf-callout,.co-panel,.co-header,.co-metric-card,.co-news,[data-testid="stMetric"],[data-testid="stExpander"],[data-testid="stDataFrame"],[data-testid="stTable"] { background:#fff !important; border:1px solid #dfe6e0 !important; box-shadow:0 5px 18px rgba(28,45,35,.055) !important; color:#202a25 !important; }
.rf-terminal-header,.rf-search-banner,.rf-workflow { background:linear-gradient(110deg,#ffffff,#f4f8f5) !important; border-color:#dce6df !important; }
.rf-brand-line,.rf-search-title,.rf-heading,.rf-panel-title,.rf-intel-title,.co-company-name,.co-panel-title,.co-news-title,.rf-flag-title,.co-flag-title { color:#202a25 !important; }
.rf-brand-line span,.rf-heading span,.co-eyebrow { color:#16856b !important; }
.rf-brand-sub,.rf-search-sub,.co-company-sub,.co-panel-sub,.co-info-label,.co-metric-label,.co-metric-sub,.co-source,.co-table-caption { color:#65746b !important; }
.rf-shortcuts span,.co-tag { border-color:#dce7df !important; color:#286e57 !important; background:#eef6f1 !important; }
.rf-market-card { background:#fff !important; }
.rf-market-card.positive { background:#eff8f3 !important; }
.rf-market-card.negative { background:#fff3f1 !important; }
.rf-market-top,.rf-market-top b { color:#50635a !important; }
.rf-market-value,.co-metric-value,.co-info-value,.co-health-name,.co-flag-evidence { color:#202a25 !important; }
.rf-market-change { color:#16845f !important; }
.rf-intel-card h4,.rf-step,.rf-step strong,.rf-intel-card td,.co-ratio-explain p { color:#34443a !important; }
.rf-intel-card th,.stApp table th { color:#3e6653 !important; background:#edf5ef !important; }
.rf-intel-card table,.stApp table { color:#27352d !important; }
.stApp table td,.stApp table th { border-bottom:1px solid #e5ebe6 !important; }
.rf-flag,.co-flag { background:#fff !important; border-color:#e1e7e2 !important; color:#27352d !important; }
.rf-flag-metric,.rf-flag-logic,.rf-flag-text { color:#65746b !important; }
.rf-analyst { background:#edf6f1 !important; color:#385548 !important; border-left-color:#16856b !important; }
.rf-analyst b { color:#176c54 !important; }
.stButton > button,.stDownloadButton > button,.stFormSubmitButton > button { background:#fff !important; color:#26342c !important; border:1px solid #d4dfd7 !important; box-shadow:0 2px 6px rgba(25,45,32,.04) !important; }
.stButton > button:hover,.stDownloadButton > button:hover,.stFormSubmitButton > button:hover { background:#eff7f2 !important; border-color:#83b99e !important; }
.stButton > button[kind="primary"],.stFormSubmitButton > button[kind="primary"] { background:#16856b !important; border-color:#16856b !important; color:#fff !important; }
.stApp input,.stApp textarea,.stApp [data-baseweb="select"] > div { background:#fff !important; color:#202a25 !important; border-color:#d3ded6 !important; }
.stApp input::placeholder,.stApp textarea::placeholder { color:#849188 !important; }
.stApp [data-baseweb="popover"] > div,.stApp [data-baseweb="menu"],.stApp [role="option"],.stApp [role="option"] * { background:#fff !important; color:#202a25 !important; }
[data-testid="stTabs"] [role="tablist"] { gap:.45rem !important; border-bottom:1px solid #dce5de !important; flex-wrap:wrap !important; }
[data-testid="stTabs"] button[role="tab"] { color:#65746b !important; background:#f8faf8 !important; border:1px solid #e0e7e1 !important; border-radius:8px 8px 0 0 !important; }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color:#126b54 !important; background:#fff !important; border-bottom:2px solid #16856b !important; }
div[data-testid="stSegmentedControl"] { background:#edf2ee !important; border:1px solid #dce5de !important; }
div[data-testid="stSegmentedControl"] button { color:#59685f !important; }
div[data-testid="stSegmentedControl"] button[aria-pressed="true"] { background:#fff !important; color:#176c54 !important; box-shadow:0 1px 4px rgba(30,55,39,.10) !important; }
[data-testid="stMetricLabel"] { color:#65746b !important; } [data-testid="stMetricValue"] { color:#202a25 !important; }
.js-plotly-plot .plotly text,.js-plotly-plot .plotly .gtitle,.js-plotly-plot .plotly .xtitle,.js-plotly-plot .plotly .ytitle,.js-plotly-plot .plotly .legendtext { fill:#526158 !important; color:#526158 !important; }
.js-plotly-plot .plotly .gridlayer path { stroke:rgba(80,105,87,.14) !important; }
.co-info,.co-note,.co-ratio-explain,.co-news { background:#f7faf7 !important; border-color:#e0e8e1 !important; color:#34443a !important; }
.co-observation { background:#edf6f1 !important; color:#385548 !important; }
.rf-source a,.co-source a,.co-news a { color:#14775e !important; }
.rf-space-stars { display:none !important; }
"""

_DARK_THEME_CSS = r"""
:root { color-scheme:dark; --rf-bg:#171d1a; --rf-bg-deep:#131916; --rf-surface:#202824; --rf-surface-2:#252e29; --rf-surface-3:#2d3932; --rf-border:rgba(183,205,190,.15); --rf-border-strong:rgba(72,174,129,.38); --rf-text:#edf3ee; --rf-muted:#aab9af; --rf-subtle:#87968c; --rf-accent:#39a77b; --rf-accent-soft:rgba(57,167,123,.13); --rf-positive:#55c596; --rf-warning:#e4b35b; --rf-negative:#e47d7d; --rf-shadow:0 8px 24px rgba(0,0,0,.18); }
html,body,.stApp,[data-testid="stAppViewContainer"] { background:#171d1a !important; color:#edf3ee !important; }
.stApp,[data-testid="stAppViewContainer"] { background:linear-gradient(180deg,#1b231e 0%,#171d1a 100%) !important; }
[data-testid="stHeader"] { background:rgba(23,29,26,.94) !important; border-bottom:1px solid #303b34 !important; }
[data-testid="stSidebar"] { background:#141b17 !important; border-right:1px solid #303b34 !important; }
[data-testid="stSidebar"] * { color:#edf3ee !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],[data-testid="stSidebar"] .stCaption,[data-testid="stSidebar"] small { color:#aab9af !important; }
[data-testid="stSidebarNav"] a[aria-current="page"],[data-testid="stSidebarNavLink"][aria-current="page"] { background:rgba(57,167,123,.16) !important; border-color:rgba(72,174,129,.35) !important; box-shadow:inset 3px 0 0 #39a77b !important; }
.rf-card,.rf-panel,.rf-intel-card,.rf-market-card,.rf-callout,.co-panel,.co-header,.co-metric-card,.co-news,[data-testid="stMetric"],[data-testid="stExpander"],[data-testid="stDataFrame"],[data-testid="stTable"] { background:#202824 !important; border-color:#344139 !important; color:#edf3ee !important; }
.rf-terminal-header,.rf-search-banner,.rf-workflow { background:linear-gradient(110deg,#26332b,#202824) !important; border-color:#3a4b40 !important; }
.rf-brand-line,.rf-search-title,.rf-heading,.rf-panel-title,.rf-intel-title,.co-company-name,.co-panel-title,.co-news-title { color:#edf3ee !important; }
.rf-brand-line span,.rf-heading span,.co-eyebrow { color:#68c49a !important; }
.rf-market-card { background:#202824 !important; } .rf-market-card.positive { background:#1e342a !important; } .rf-market-card.negative { background:#382725 !important; }
.rf-market-value,.co-metric-value,.co-info-value,.co-health-name,.co-flag-evidence { color:#edf3ee !important; }
.stButton > button,.stDownloadButton > button,.stFormSubmitButton > button { background:#29352e !important; color:#edf3ee !important; border-color:#46564b !important; }
.stButton > button:hover,.stDownloadButton > button:hover { background:#33463a !important; border-color:#55a982 !important; }
.stButton > button[kind="primary"],.stFormSubmitButton > button[kind="primary"] { background:#21865f !important; border-color:#2a9b70 !important; color:#fff !important; }
.stApp input,.stApp textarea,.stApp [data-baseweb="select"] > div { background:#1b241e !important; color:#edf3ee !important; border-color:#435248 !important; }
.stApp [data-baseweb="popover"] > div,.stApp [data-baseweb="menu"],[role="option"],[role="option"] * { background:#202824 !important; color:#edf3ee !important; }
[data-testid="stTabs"] [role="tablist"] { gap:.45rem !important; flex-wrap:wrap !important; border-bottom:1px solid #344139 !important; }
[data-testid="stTabs"] button[role="tab"] { color:#aab9af !important; background:#202824 !important; border:1px solid #344139 !important; border-radius:8px 8px 0 0 !important; }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] { color:#80d3aa !important; border-bottom:2px solid #39a77b !important; }
div[data-testid="stSegmentedControl"] { background:#1b241e !important; border-color:#344139 !important; }
div[data-testid="stSegmentedControl"] button[aria-pressed="true"] { background:#2b4435 !important; color:#eaf5ed !important; }
.rf-space-stars { display:none !important; }
"""

_MOTION_CSS = r"""
/* Moderate, restrained motion; respects the operating-system reduced-motion setting. */
:root { --rf-motion-fast: 160ms; --rf-motion: 240ms; }
.stButton > button,.stDownloadButton > button,[data-testid="stSidebarNav"] a,.rf-card,.rf-market-card,.rf-intel-card,.co-panel,[data-testid="stMetric"] { transition: transform var(--rf-motion) ease, box-shadow var(--rf-motion) ease, background var(--rf-motion) ease, border-color var(--rf-motion) ease !important; }
.stButton > button:hover,.stDownloadButton > button:hover { transform: translateY(-1px); }
.rf-card:hover,.rf-market-card:hover,.rf-intel-card:hover,.co-panel:hover,[data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow:0 9px 24px rgba(25,55,38,.10) !important; }
.rf-hero,.rf-terminal-header,.co-header { animation:rf-premium-enter 360ms cubic-bezier(.2,.7,.2,1) both; }
@keyframes rf-premium-enter { from { opacity:0; transform:translateY(7px); } to { opacity:1; transform:translateY(0); } }
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { animation-duration:.01ms !important; transition-duration:.01ms !important; transform:none !important; } }
"""

_SIDEBAR_NAV_FIX_CSS = r"""
/* FINAL LIGHT THEME OVERRIDES
   Loaded last by inject_css() after page-local styles. White navigation rail,
   light research cards, readable news links, and no dark navy leftovers. */
:root {
  color-scheme: light !important;
  --rf-bg: #f4f6f3 !important;
  --rf-bg-deep: #eef2ee !important;
  --rf-surface: #ffffff !important;
  --rf-surface-2: #f8faf8 !important;
  --rf-surface-3: #edf4ef !important;
  --rf-border: #dfe7e1 !important;
  --rf-border-strong: #c4d7ca !important;
  --rf-text: #202a25 !important;
  --rf-muted: #627168 !important;
  --rf-subtle: #7c8981 !important;
  --rf-accent: #16856b !important;
  --rf-accent-soft: #e8f4ed !important;
  --rf-positive: #16845f !important;
  --rf-warning: #a96d13 !important;
  --rf-negative: #bd3d45 !important;
  --rf-shadow: 0 5px 18px rgba(28,45,35,.055) !important;
}
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  color-scheme: light !important;
  background: #f4f6f3 !important;
  color: #202a25 !important;
}
.stApp [data-testid="stAppViewContainer"] > .main { background: transparent !important; }
[data-testid="stHeader"] {
  background: rgba(248,250,248,.97) !important;
  border-bottom: 1px solid #e0e7e1 !important;
}
.block-container { color: #202a25 !important; }

/* Sidebar is light as well; no charcoal/navy navigation rail. */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
  width: 285px !important; min-width: 285px !important;
  background: #ffffff !important;
  color: #26342c !important;
  border-right: 1px solid #dfe7e1 !important;
  box-shadow: 4px 0 18px rgba(25,45,32,.035) !important;
}
[data-testid="stSidebar"] * {
  color: #26342c !important;
  -webkit-text-fill-color: #26342c !important;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] small {
  color: #6b786f !important;
  -webkit-text-fill-color: #6b786f !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {
  display: flex !important;
  align-items: center !important;
  min-height: 40px !important;
  width: 100% !important;
  padding: .42rem .62rem !important;
  margin: 3px 0 !important;
  border: 1px solid transparent !important;
  border-radius: 9px !important;
  background: transparent !important;
  white-space: normal !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a *,
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] * {
  color: #34453b !important;
  -webkit-text-fill-color: #34453b !important;
  opacity: 1 !important;
  visibility: visible !important;
  font-size: 13px !important;
  line-height: 1.35 !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {
  background: #eaf5ee !important;
  border-color: #c8e0d1 !important;
  box-shadow: inset 3px 0 0 #16856b !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
  background: #f2f7f3 !important;
  border-color: #e0eae2 !important;
}
[data-testid="stSidebar"] hr { border-color: #e2e9e3 !important; }
[data-testid="stSidebar"] .stButton > button {
  color: #24513d !important;
  -webkit-text-fill-color: #24513d !important;
  background: #f0f7f2 !important;
  border: 1px solid #cddfd2 !important;
}

/* Universal page typography and links. */
.stApp h1, .stApp h2, .stApp h3, .stApp h4,
.stApp p, .stApp li, .stApp label,
.stApp [data-testid="stMarkdownContainer"] {
  color: #202a25 !important;
}
.stApp p, .stApp li { line-height: 1.58 !important; }
[data-testid="stCaptionContainer"], .stCaption, .muted,
.rf-sub, .co-source, .rf-source {
  color: #68766d !important;
}
.stApp a, .stApp a:visited { color: #176f56 !important; }
.stApp a:hover { color: #0f5b45 !important; text-decoration: underline !important; }

/* Cards, panels, hero blocks and metrics used across the research modules. */
.rf-card, .rf-panel, .rf-intel-card, .rf-market-card, .rf-callout,
.co-panel, .co-header, .co-metric-card, .co-news,
.ari-hero, .ari-panel, .ari-risk,
.cri-hero, .cri-panel, .cri-event,
.rf-terminal-header, .rf-search-banner, .rf-workflow,
[data-testid="stMetric"], [data-testid="stExpander"],
[data-testid="stDataFrame"], [data-testid="stTable"] {
  background: #ffffff !important;
  background-image: none !important;
  border: 1px solid #dfe7e1 !important;
  border-radius: 12px !important;
  box-shadow: 0 5px 18px rgba(28,45,35,.055) !important;
  color: #202a25 !important;
}
.rf-terminal-header, .rf-search-banner, .rf-workflow,
.co-header, .ari-hero, .cri-hero {
  background: linear-gradient(120deg,#ffffff 0%,#f3f8f4 100%) !important;
  border-color: #d9e6dd !important;
}
.rf-panel, .rf-intel-card, .co-panel, .co-news,
.ari-panel, .cri-panel, .ari-risk, .cri-event {
  background: #ffffff !important;
  background-image: none !important;
}
.rf-market-card { background: #ffffff !important; }
.rf-market-card.positive { background: #eff8f2 !important; }
.rf-market-card.negative { background: #fff3f1 !important; }
.rf-market-card, .rf-intel-card, .rf-panel, .co-panel,
.ari-panel, .cri-panel, .cri-event, .rf-summary {
  border-color: #dfe7e1 !important;
}
.rf-brand-line, .rf-heading, .rf-search-title, .rf-panel-title, .rf-section-label,
.rf-intel-title, .rf-intel-card h4, .rf-step, .rf-step strong,
.rf-terminal-header h1, .co-company-name, .co-panel-title,
.co-news-title, .co-info-value, .co-metric-value,
.ari-title, .ari-panel h3, .ari-risk-title,
.cri-title, .cri-event-title,
.rf-title, .rf-summary, .rf-flag-title, .rf-flag-evidence {
  color: #202a25 !important;
  -webkit-text-fill-color: #202a25 !important;
}
.rf-brand-line span, .rf-heading span, .co-eyebrow,
.ari-kicker, .cri-kicker, .rf-kicker {
  color: #16856b !important;
  -webkit-text-fill-color: #16856b !important;
}
.rf-brand-sub, .rf-search-sub, .co-company-sub, .co-panel-sub,
.co-info-label, .co-metric-label, .co-metric-sub,
.ari-sub, .ari-muted, .cri-sub, .cri-muted,
.cri-event-meta, .ari-risk-meta, .rf-subtitle, .rf-muted {
  color: #637168 !important;
  -webkit-text-fill-color: #637168 !important;
}
.rf-shortcuts span, .co-tag, .ari-pill {
  color: #24664e !important;
  background: #eef6f0 !important;
  border-color: #d6e6da !important;
}
.rf-market-top, .rf-market-top b { color: #52645a !important; }
.rf-market-value, .rf-intel-card .big { color: #202a25 !important; }
.rf-market-date, .rf-source, .rf-news-meta { color: #77847b !important; }
.rf-news-item { border-top-color: #e7ece8 !important; }
.rf-news-item a, .rf-news-item a:visited {
  color: #176f56 !important;
  -webkit-text-fill-color: #176f56 !important;
  font-size: 13px !important;
  font-weight: 650 !important;
  line-height: 1.45 !important;
  text-decoration: none !important;
}
.rf-news-item a:hover { color: #0e5b44 !important; text-decoration: underline !important; }
.rf-intel-card td, .rf-event-row, .co-health-name,
.co-flag-evidence, .co-ratio-explain p {
  color: #34443a !important;
}
.rf-intel-card th, .stApp table th {
  color: #3d6652 !important;
  background: #edf5ef !important;
}
.rf-intel-card table, .stApp table { color: #27352d !important; }
.stApp table td, .stApp table th { border-bottom: 1px solid #e5ebe6 !important; }
.ari-risk-title, .cri-event-title { color: #26362c !important; }
.ari-risk-body, .cri-event-body { color: #46564c !important; }
.cri-hero .cri-sub, .ari-hero .ari-sub, .co-header .co-company-sub {
  color: #5e6d64 !important;
  -webkit-text-fill-color: #5e6d64 !important;
}
.ari-kicker, .cri-kicker { letter-spacing: .1em !important; }
.ari-risk.high, .ari-risk.review, .cri-event.urgent, .cri-event.review, .cri-event.monitor {
  background: #ffffff !important;
}
.rf-flag, .co-flag { background: #ffffff !important; border-color: #e1e8e2 !important; }
.rf-flag-metric, .rf-flag-logic, .rf-flag-text { color: #627168 !important; }
.rf-analyst { background: #edf6f1 !important; color: #385548 !important; }
.rf-analyst b { color: #176c54 !important; }
.rf-pill { color: #40564a !important; background: #f0f5f1 !important; border-color: #dce7df !important; }
.rf-pill.danger { color: #a9323b !important; background: #fff0ef !important; border-color: #f0d1cf !important; }
.rf-pill.warning { color: #87580c !important; background: #fff7e8 !important; border-color: #eeddb9 !important; }
.rf-pill.success { color: #176b4e !important; background: #eaf6ef !important; border-color: #cfe7d8 !important; }
.rf-status.danger { color: #a9323b !important; background: #fff0ef !important; border-color: #f0d1cf !important; }
.rf-status.warning { color: #87580c !important; background: #fff7e8 !important; border-color: #eeddb9 !important; }
.rf-status.success { color: #176b4e !important; background: #eaf6ef !important; border-color: #cfe7d8 !important; }
.rf-status.muted { color: #5f6e64 !important; background: #f1f4f1 !important; border-color: #dfe7e1 !important; }
.rf-section-label { color: #637168 !important; }
.rf-flag.Low { border-left-color: #16856b !important; }
.rf-flag.Medium { border-left-color: #b7791f !important; }
.rf-flag.High, .rf-flag.Critical { border-left-color: #c24145 !important; }
.rf-step small, .rf-event-row .muted { color: #68766d !important; }
.rf-step b { background: #e5f3eb !important; color: #176c54 !important; }

/* Controls, selectors, popovers, tabs and buttons. */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  color: #26342c !important;
  -webkit-text-fill-color: #26342c !important;
  background: #ffffff !important;
  border: 1px solid #d4dfd7 !important;
  border-radius: 8px !important;
  box-shadow: 0 2px 6px rgba(25,45,32,.04) !important;
}
.stButton > button:hover, .stDownloadButton > button:hover,
.stFormSubmitButton > button:hover {
  background: #eff7f2 !important;
  border-color: #83b99e !important;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: #16856b !important;
  border-color: #16856b !important;
  color: #ffffff !important;
  -webkit-text-fill-color: #ffffff !important;
}
.stApp input, .stApp textarea, .stApp [data-baseweb="select"] > div {
  background: #ffffff !important;
  color: #202a25 !important;
  border-color: #d3ded6 !important;
}
.stApp input::placeholder, .stApp textarea::placeholder { color: #849188 !important; }
.stApp [data-baseweb="popover"] > div, .stApp [data-baseweb="menu"],
.stApp [role="option"], .stApp [role="option"] * {
  background: #ffffff !important;
  color: #202a25 !important;
  -webkit-text-fill-color: #202a25 !important;
}
[data-testid="stTabs"] [role="tablist"] {
  gap: .45rem !important; flex-wrap: wrap !important; border-bottom: 1px solid #dce5de !important;
}
[data-testid="stTabs"] button[role="tab"] {
  color: #65746b !important; background: #f8faf8 !important;
  border: 1px solid #e0e7e1 !important; border-radius: 8px 8px 0 0 !important;
}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
  color: #126b54 !important; background: #ffffff !important; border-bottom: 2px solid #16856b !important;
}
div[data-testid="stSegmentedControl"] {
  background: #edf2ee !important; border: 1px solid #dce5de !important;
}
div[data-testid="stSegmentedControl"] button { color: #59685f !important; }
div[data-testid="stSegmentedControl"] button[aria-pressed="true"] {
  background: #ffffff !important; color: #176c54 !important;
  box-shadow: 0 1px 4px rgba(30,55,39,.10) !important;
}
[data-testid="stExpander"] { background: #ffffff !important; }
[data-testid="stMetricLabel"] { color: #65746b !important; }
[data-testid="stMetricValue"] { color: #202a25 !important; }

/* Plotly SVG uses inline trace/layout styles; !important ensures readable labels. */
.js-plotly-plot, .plot-container { background: transparent !important; }
.js-plotly-plot .plotly text, .js-plotly-plot .plotly .gtitle,
.js-plotly-plot .plotly .xtitle, .js-plotly-plot .plotly .ytitle,
.js-plotly-plot .plotly .legendtext,
.js-plotly-plot .plotly .xtick text, .js-plotly-plot .plotly .ytick text {
  fill: #526158 !important; color: #526158 !important;
}
.js-plotly-plot .plotly .gridlayer path { stroke: rgba(80,105,87,.14) !important; }
.js-plotly-plot .plotly .axis path, .js-plotly-plot .plotly .axis line { stroke: rgba(80,105,87,.28) !important; }
.rf-space-stars { display: none !important; }

/* Layout consistency and smaller screens. */
.block-container { padding-top: 1.6rem !important; padding-bottom: 2.8rem !important; }
.rf-section, .rf-intel-title { margin-top: 1.45rem !important; }
@media (max-width: 900px) {
  .rf-grid.c4, .rf-grid.c3, .rf-market-grid, .rf-intel-grid { grid-template-columns: repeat(2,minmax(0,1fr)) !important; }
}
@media (max-width: 640px) {
  .rf-grid.c4, .rf-grid.c3, .rf-grid.c2, .rf-market-grid, .rf-intel-grid, .rf-workflow { grid-template-columns: 1fr !important; }
  .block-container { padding-left: 1rem !important; padding-right: 1rem !important; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; }
}
"""

def inject_css(theme: str | None = None) -> None:
    """Inject the single Premium Institutional Light theme after page-local styles.

    The optional theme argument is retained for backward compatibility. The
    application is intentionally light-theme-only to avoid inconsistent mixed
    colour modes across embedded HTML, Streamlit controls and Plotly charts.
    """
    st.markdown(
        f"<style>{_INSTITUTIONAL_CSS}\n{_LIGHT_THEME_CSS}\n{_MOTION_CSS}\n{_SIDEBAR_NAV_FIX_CSS}</style>",
        unsafe_allow_html=True,
    )
