"""Institutional, sector-aware forensic review page.

The page is intentionally concise: executive summary first, followed by focused
research tabs. Calculations and classifications are supplied by the sector-aware
engine; this module only presents those results and never fabricates values.
"""
from __future__ import annotations

import html
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.constants import Severity
from visualization.components import get_analysis, setup_page


# -----------------------------------------------------------------------------
# Formatting helpers
# -----------------------------------------------------------------------------
def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else "N/A"))


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().upper() in {"", "N/A", "NONE", "NAN"}:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _fmt(value: Any, digits: int = 2) -> str:
    if _is_missing(value):
        return "N/A"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _severity_value(flag: Any) -> str:
    severity = getattr(flag, "severity", None)
    return getattr(severity, "value", str(severity or "N/A"))


def _severity_rank(value: str) -> int:
    return {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}.get(value, 0)


def _status_tone(status: str) -> str:
    return {
        "Triggered": "danger",
        "Not triggered": "success",
        "Unavailable": "warning",
        "Not applicable": "muted",
        "Available": "success",
        "Partial history": "warning",
    }.get(str(status), "muted")


def _pill(text: str, tone: str = "muted") -> str:
    return f'<span class="rf-pill {tone}">{_esc(text)}</span>'


def _records_to_frame(rows: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows).reindex(columns=columns)


def _plotly_layout(fig: go.Figure, height: int = 220) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=6, r=12, t=10, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Arial, sans-serif", color="#526158", size=11),
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(color="#718078"), title=None),
        yaxis=dict(showgrid=False, tickfont=dict(color="#526158"), title=None),
        hoverlabel=dict(bgcolor="#ffffff", font_color="#26342c"),
    )
    return fig


def _flag_row(flag: Any) -> dict[str, str]:
    return {
        "Finding": str(getattr(flag, "title", "N/A")),
        "Research area": str(getattr(flag, "category", "N/A")),
        "Observed result": str(getattr(flag, "metric", "N/A")),
        "Severity": _severity_value(flag),
        "Period": str(getattr(flag, "year", None) or "N/A"),
    }


def _check_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "Test": str(row.get("title", "N/A")),
        "Status": str(row.get("status", "N/A")),
        "Observed result": str(row.get("metric", "N/A")),
        "Threshold": str(row.get("threshold", "N/A")),
        "Period": str(row.get("year", "N/A")),
    }


# -----------------------------------------------------------------------------
# Local visual system: quiet, compact and consistent with the global theme.
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .rf-kicker{font-size:.68rem;letter-spacing:.13em;text-transform:uppercase;color:#55c6dc;font-weight:750;margin:0 0 .35rem}
    .rf-title{font-size:1.72rem;font-weight:760;letter-spacing:-.035em;color:#F1F5F9;line-height:1.12;margin:0}
    .rf-subtitle{font-size:.88rem;color:#9FB2C3;margin-top:.38rem;line-height:1.45}
    .rf-pill{display:inline-block;border:1px solid rgba(110,150,178,.23);background:rgba(45,78,102,.20);border-radius:999px;padding:.18rem .52rem;color:#B9C9D7;font-size:.69rem;margin:.12rem .22rem .08rem 0}
    .rf-pill.danger{background:rgba(207,83,92,.12);border-color:rgba(207,83,92,.25);color:#F29AA1}
    .rf-pill.warning{background:rgba(203,151,62,.12);border-color:rgba(203,151,62,.24);color:#E7C17B}
    .rf-pill.success{background:rgba(54,165,128,.10);border-color:rgba(54,165,128,.22);color:#83D2B2}
    .rf-section-label{font-size:.68rem;letter-spacing:.10em;text-transform:uppercase;color:#7F9AAF;font-weight:750;margin:.15rem 0 .38rem}
    .rf-summary{border:1px solid rgba(88,139,171,.20);background:rgba(15,35,53,.58);border-radius:10px;padding:.72rem .9rem;color:#C2D0DC;font-size:.84rem;line-height:1.48}
    .rf-muted{color:#8FA4B6;font-size:.78rem;line-height:1.45}
    .rf-status{display:inline-block;border-radius:999px;padding:.18rem .52rem;font-size:.69rem;font-weight:700;white-space:nowrap}
    .rf-status.danger{background:rgba(210,82,93,.13);border:1px solid rgba(210,82,93,.26);color:#F29AA1}
    .rf-status.warning{background:rgba(204,154,65,.13);border:1px solid rgba(204,154,65,.24);color:#EAC57E}
    .rf-status.success{background:rgba(50,167,126,.12);border:1px solid rgba(50,167,126,.23);color:#83D2B2}
    .rf-status.muted{background:rgba(132,153,170,.10);border:1px solid rgba(132,153,170,.18);color:#ACBBC8}
    [data-testid="stMetric"]{background:rgba(13,31,48,.70);border:1px solid rgba(89,137,168,.20);padding:.62rem .78rem;border-radius:10px;min-height:88px}
    [data-testid="stMetricLabel"]{color:#9FB2C3!important;font-size:.72rem!important}
    [data-testid="stMetricValue"]{color:#F0F5F9!important;font-size:1.45rem!important;font-weight:740!important}
    [data-testid="stTabs"] button{font-size:.83rem;font-weight:650;padding-top:.45rem;padding-bottom:.45rem}
    /* Separate the five research workspaces instead of running labels together. */
    div[data-testid="stTabs"] [data-baseweb="tab-list"]{
        display:flex!important;flex-wrap:wrap!important;gap:9px!important;
        overflow:visible!important;border-bottom:1px solid rgba(89,137,168,.24)!important;
        padding:0 0 9px!important;align-items:center!important;
    }
    div[data-testid="stTabs"] button[role="tab"]{
        flex:0 0 auto!important;min-height:40px!important;height:auto!important;
        padding:9px 14px!important;margin:0!important;white-space:normal!important;
        border:1px solid rgba(89,137,168,.30)!important;border-radius:10px!important;
        background:rgba(12,34,52,.72)!important;color:#C7D8E6!important;
        line-height:1.25!important;
    }
    div[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{
        background:rgba(8,91,126,.42)!important;border-color:rgba(34,211,238,.72)!important;
        color:#F1FAFF!important;box-shadow:0 0 0 1px rgba(34,211,238,.10) inset;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"]{display:none!important}
    [data-testid="stDataFrame"]{border:1px solid rgba(89,137,168,.20);border-radius:9px;overflow:hidden}
    div[data-testid="stExpander"]{border:1px solid rgba(89,137,168,.20);border-radius:9px;background:rgba(10,26,41,.35)}
    div[data-testid="stVerticalBlock"]>div:has(> div.rf-summary){margin-bottom:.2rem}
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------------------------------------------------------
# Load the existing analysis object; all values remain engine-sourced.
# -----------------------------------------------------------------------------
ticker = setup_page("Forensic Red Flags")
a = get_analysis(ticker)
sector_result = getattr(a, "sector_forensic", None)

if sector_result is None:
    st.error("Sector-aware forensic results are not attached to this company analysis. Clear the cached analysis and reload the company.")
    st.stop()

profile = sector_result.profile
flags = list(sector_result.flags)
checks = list(sector_result.checks)
counts = {
    severity.value: sum(1 for flag in flags if _severity_value(flag) == severity.value)
    for severity in Severity
}
high_critical = counts.get("High", 0) + counts.get("Critical", 0)
priority_flags = sorted(
    flags,
    key=lambda flag: (-_severity_rank(_severity_value(flag)), str(getattr(flag, "year", "")), str(getattr(flag, "title", ""))),
)

# Derived labels are deliberately modest and do not imply fraud or default.
if counts.get("Critical", 0):
    review_status, review_tone = "Critical review", "danger"
elif counts.get("High", 0):
    review_status, review_tone = "Priority review", "danger"
elif counts.get("Medium", 0):
    review_status, review_tone = "Analyst review", "warning"
elif flags:
    review_status, review_tone = "Monitoring", "muted"
else:
    review_status, review_tone = "No triggered checks", "success"

periods = list(getattr(a, "financials", pd.DataFrame()).index) if getattr(a, "financials", None) is not None else []
period_label = f"{periods[0]} – {periods[-1]}" if periods else "Reporting period unavailable"
source = getattr(a, "financials", pd.DataFrame()).attrs.get("source", "Source metadata unavailable") if getattr(a, "financials", None) is not None else "Source metadata unavailable"
normalization = getattr(a, "financials", pd.DataFrame()).attrs.get("normalization", "Normalization details unavailable") if getattr(a, "financials", None) is not None else "Normalization details unavailable"

# -----------------------------------------------------------------------------
# Header and compact executive summary
# -----------------------------------------------------------------------------
st.markdown('<div class="rf-kicker">RED FLAG INTELLIGENCE &nbsp; / &nbsp; COMPANY ANALYSIS &nbsp; / &nbsp; FORENSIC REVIEW</div>', unsafe_allow_html=True)
header_left, header_right = st.columns([5.1, 1.2], vertical_alignment="center")
with header_left:
    st.markdown(f'<h1 class="rf-title">{_esc(a.name)}</h1>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="rf-subtitle">{_esc(a.ticker)} &nbsp;·&nbsp; {_esc(profile.label)} &nbsp;·&nbsp; {_esc(profile.business_model)}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        _pill(profile.confidence)
        + _pill(period_label)
        + _pill("Source-preserving financial statements"),
        unsafe_allow_html=True,
    )
with header_right:
    st.markdown(f'<div style="text-align:right;padding-top:.25rem"> <span class="rf-status {review_tone}">{_esc(review_status)}</span></div>', unsafe_allow_html=True)

if flags:
    top_names = ", ".join(str(getattr(flag, "title", "finding")) for flag in priority_flags[:2])
    summary_text = (
        f"{len(flags)} finding(s) were triggered across {sector_result.applicable_count} executed test(s), "
        f"including {high_critical} high / critical item(s). Start with {top_names}. "
        "These are screening signals for analyst review, not findings of fraud or misconduct."
    )
else:
    summary_text = (
        f"No applicable rule was triggered across {sector_result.applicable_count} executed test(s). "
        "Review unavailable and not-applicable checks before interpreting this as a low-risk result."
    )
st.markdown(f'<div class="rf-summary">{_esc(summary_text)}</div>', unsafe_allow_html=True)

# Three primary metrics only; coverage is shown as a separate compact qualifier.
metric1, metric2, metric3 = st.columns(3)
with metric1:
    st.metric("Triggered findings", len(flags), help="Number of applicable rules that breached their configured review threshold.")
with metric2:
    st.metric("High / critical", high_critical, help="Items that should receive first review; not a fraud conclusion.")
with metric3:
    st.metric("Tests executed", sector_result.applicable_count, help="Applicable tests with the required inputs available for calculation.")
st.markdown(
    f'<div class="rf-muted">Test coverage <b>{sector_result.coverage_pct:.0f}%</b> &nbsp;·&nbsp; '
    f'{sector_result.unavailable_count} unavailable &nbsp;·&nbsp; {sector_result.not_applicable_count} not applicable &nbsp;·&nbsp; '
    f'Sector-screen index: {_fmt(sector_result.score, 1)}/100 (details in Evidence & Methodology)</div>',
    unsafe_allow_html=True,
)

# Tabs replace the very long, continuous page with five focused workflows.
tab_overview, tab_financial, tab_sector, tab_models, tab_evidence = st.tabs([
    "Overview", "Financial Flags", "Sector Checks", "Models", "Evidence & Methodology"
])

# -----------------------------------------------------------------------------
# 1. Overview: short priority queue + a small risk-area chart.
# -----------------------------------------------------------------------------
with tab_overview:
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        st.markdown("#### Priority findings")
        if flags:
            overview_rows = [_flag_row(flag) for flag in priority_flags[:6]]
            st.dataframe(
                pd.DataFrame(overview_rows),
                use_container_width=True,
                hide_index=True,
                height=min(260, 44 + 36 * len(overview_rows)),
            )
            st.caption("The full list, filters and investigation details are in Financial Flags.")
        else:
            st.success("No triggered findings from the tests currently executable for this company.")
    with right:
        st.markdown("#### Findings by area")
        if flags:
            area_counts = pd.Series([getattr(flag, "category", "Other") for flag in flags]).value_counts().sort_values()
            fig = go.Figure(go.Bar(
                x=area_counts.values,
                y=area_counts.index,
                orientation="h",
                marker=dict(color="#50B9CD"),
                text=area_counts.values,
                textposition="outside",
                cliponaxis=False,
                hovertemplate="%{y}: %{x} finding(s)<extra></extra>",
            ))
            fig.update_layout(xaxis=dict(dtick=1, rangemode="tozero"), bargap=.42)
            st.plotly_chart(_plotly_layout(fig, height=max(170, min(235, 38 * len(area_counts)))), use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("Area distribution will appear when an applicable check is triggered.")

    st.markdown("#### Analyst's first read")
    if priority_flags:
        first = priority_flags[0]
        c1, c2 = st.columns([3.4, 1])
        with c1:
            st.markdown(f"**{_esc(getattr(first, 'title', 'Priority finding'))}**")
            st.write(getattr(first, "explanation", "Review the underlying statement and disclosure."))
            st.caption(f"Observed: {getattr(first, 'metric', 'N/A')} · Period: {getattr(first, 'year', None) or 'N/A'}")
        with c2:
            tone = "danger" if _severity_rank(_severity_value(first)) >= 3 else "warning" if _severity_rank(_severity_value(first)) == 2 else "muted"
            st.markdown(f'<div style="text-align:right"><span class="rf-status {tone}">{_esc(_severity_value(first))}</span></div>', unsafe_allow_html=True)
    else:
        st.write("The next step is to review data availability and confirm that all material sector-specific tests are supported by source information.")

    with st.expander("View financial trend context", expanded=False):
        history = sector_result.ratio_history
        trend_candidates = [
            ("Revenue growth (%)", "Revenue growth"),
            ("EBITDA margin (%)", "EBITDA margin"),
            ("ROE (%)", "ROE"),
            ("ROA (%)", "ROA"),
        ]
        valid_trends = [(col, label) for col, label in trend_candidates if col in history and history[col].notna().sum() >= 2]
        cash_candidates = [("CFO / PAT (x)", "CFO / PAT"), ("Sloan accruals (%)", "Sloan accruals")]
        valid_cash = [(col, label) for col, label in cash_candidates if col in history and history[col].notna().sum() >= 2]
        if valid_trends:
            st.markdown("**Growth and returns**")
            fig = go.Figure()
            for col, label in valid_trends:
                fig.add_trace(go.Scatter(x=history.index, y=history[col], name=label, mode="lines+markers"))
            fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.13, x=0), yaxis_title="Percent")
            st.plotly_chart(_plotly_layout(fig, 235), use_container_width=True, config={"displayModeBar": False})
        if valid_cash:
            st.markdown("**Cash conversion and accrual indicators**")
            fig = go.Figure()
            for col, label in valid_cash:
                fig.add_trace(go.Scatter(x=history.index, y=history[col], name=label, mode="lines+markers"))
            fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.13, x=0), yaxis_title="Ratio / percent")
            st.plotly_chart(_plotly_layout(fig, 235), use_container_width=True, config={"displayModeBar": False})
        if not valid_trends and not valid_cash:
            st.info("Not enough comparable historical inputs are available to plot a trend.")

# -----------------------------------------------------------------------------
# 2. Financial flags: compact filters/table; one detailed investigation at a time.
# -----------------------------------------------------------------------------
with tab_financial:
    st.markdown("#### Financial findings")
    st.caption("Filter the findings, select one item, and open its investigation detail only when needed.")
    if not flags:
        st.success("No triggered findings from the currently executable tests.")
    else:
        f1, f2, f3 = st.columns([1.3, 1, 1])
        all_categories = sorted({str(getattr(flag, "category", "Other")) for flag in flags})
        all_severities = [s for s in ["Critical", "High", "Medium", "Low"] if any(_severity_value(flag) == s for flag in flags)]
        all_periods = sorted({str(getattr(flag, "year", "N/A") or "N/A") for flag in flags}, reverse=True)
        with f1:
            selected_categories = st.multiselect("Research area", all_categories, default=all_categories, key="rf_v2_categories")
        with f2:
            selected_severities = st.multiselect("Severity", all_severities, default=all_severities, key="rf_v2_severities")
        with f3:
            selected_periods = st.multiselect("Period", all_periods, default=all_periods, key="rf_v2_periods")

        filtered_flags = [
            flag for flag in priority_flags
            if str(getattr(flag, "category", "Other")) in selected_categories
            and _severity_value(flag) in selected_severities
            and str(getattr(flag, "year", "N/A") or "N/A") in selected_periods
        ]
        st.dataframe(
            pd.DataFrame([_flag_row(flag) for flag in filtered_flags]),
            use_container_width=True,
            hide_index=True,
            height=min(360, 48 + 38 * max(1, len(filtered_flags))),
        )
        if filtered_flags:
            option_labels = [
                f"{_severity_value(flag)} · {getattr(flag, 'title', 'Finding')} · {getattr(flag, 'year', None) or 'N/A'}"
                for flag in filtered_flags
            ]
            selected_label = st.selectbox("Inspect finding", option_labels, key="rf_v2_selected_finding")
            chosen = filtered_flags[option_labels.index(selected_label)]
            sev = _severity_value(chosen)
            tone = "danger" if _severity_rank(sev) >= 3 else "warning" if sev == "Medium" else "muted"
            st.markdown('<div class="rf-section-label">Investigation detail</div>', unsafe_allow_html=True)
            with st.container(border=True):
                title_col, severity_col = st.columns([4, 1], vertical_alignment="center")
                with title_col:
                    st.markdown(f"### {_esc(getattr(chosen, 'title', 'Finding'))}")
                    st.caption(f"{_esc(getattr(chosen, 'category', 'N/A'))} · {_esc(getattr(chosen, 'year', None) or 'N/A')}")
                with severity_col:
                    st.markdown(f'<div style="text-align:right"><span class="rf-status {tone}">{_esc(sev)}</span></div>', unsafe_allow_html=True)
                detail_left, detail_right = st.columns(2)
                with detail_left:
                    st.markdown("**Observed result**")
                    st.write(getattr(chosen, "metric", "N/A"))
                    st.markdown("**Why it matters**")
                    st.write(getattr(chosen, "explanation", "Review the source information and business context."))
                with detail_right:
                    st.markdown("**Review threshold**")
                    st.write(getattr(chosen, "threshold", "N/A"))
                    st.markdown("**How it is tested**")
                    st.write(getattr(chosen, "logic", "Methodology not supplied by the test."))
                followups = {
                    "Working capital": ["Review ageing and subsequent collections.", "Compare customer concentration and credit terms.", "Read the relevant annual-report notes."],
                    "Cash Flow": ["Reconcile PAT with cash from operations.", "Review non-cash adjustments and working-capital movements.", "Compare cash generation over multiple periods."],
                    "Profitability": ["Compare segment margins and input costs.", "Review pricing, volume and product mix.", "Check exceptional items and accounting-policy changes."],
                    "Leverage": ["Review debt maturity, finance cost and covenant headroom.", "Compare debt with operating cash generation.", "Check committed capex and liquidity."],
                    "Earnings": ["Read the related annual-report note.", "Compare earnings with operating cash flow.", "Check whether the item repeats across periods."],
                    "Models": ["Confirm model applicability and all required inputs.", "Compare each input with the original statements.", "Treat model output as a screening indicator only."],
                    "Financial-sector checks": ["Review the applicable regulatory and business disclosures.", "Compare the metric with a consistent historical series.", "Validate capital, asset quality and business-mix context where relevant."],
                }.get(str(getattr(chosen, "category", "")), ["Verify the calculation against the original statement.", "Review the related annual-report note or exchange filing.", "Compare with genuinely comparable business-model peers."])
                with st.expander("Suggested analyst investigation", expanded=False):
                    for item in followups:
                        st.markdown(f"- {item}")
        else:
            st.info("No findings match the selected filters. Adjust the filters to see other findings.")

# -----------------------------------------------------------------------------
# 3. Sector checks: compact results + KPI availability tucked away until needed.
# -----------------------------------------------------------------------------
with tab_sector:
    st.markdown("#### Sector-specific tests")
    st.markdown(
        f'<div class="rf-muted">Business model: <b>{_esc(profile.business_model)}</b> &nbsp;·&nbsp; '
        f'Classification: {_esc(profile.confidence)} &nbsp;·&nbsp; Source: {_esc(profile.classification_source)}</div>',
        unsafe_allow_html=True,
    )
    status_counts = pd.Series([str(row.get("status", "N/A")) for row in checks]).value_counts().to_dict()
    s1, s2, s3 = st.columns(3)
    with s1: st.metric("Triggered", status_counts.get("Triggered", 0))
    with s2: st.metric("Not triggered", status_counts.get("Not triggered", 0))
    with s3: st.metric("Unavailable / N.A.", status_counts.get("Unavailable", 0) + status_counts.get("Not applicable", 0))

    sector_rows = [_check_row(row) for row in checks]
    if sector_rows:
        st.dataframe(
            pd.DataFrame(sector_rows),
            use_container_width=True,
            hide_index=True,
            height=min(420, 56 + 37 * len(sector_rows)),
        )
    else:
        st.info("No sector checks are configured for this classification.")

    metrics = list(getattr(sector_result, "sector_metrics", []) or [])
    available_metrics = [row for row in metrics if str(row.get("Status", "")) == "Available"]
    missing_metrics = [row for row in metrics if str(row.get("Status", "")) != "Available"]
    st.markdown("#### Sector KPI availability")
    if available_metrics:
        available_rows = [{
            "Metric": row.get("Metric", "N/A"),
            "Latest value": _fmt(row.get("Latest value")),
            "Definition": row.get("Definition / required source", "N/A"),
        } for row in available_metrics]
        st.dataframe(pd.DataFrame(available_rows), use_container_width=True, hide_index=True, height=min(240, 50 + 36 * len(available_rows)))
    else:
        st.info("No sector operating KPI has the complete required source inputs in this run.")
    if missing_metrics:
        with st.expander(f"Unavailable sector metrics ({len(missing_metrics)}) — show required data", expanded=False):
            missing_rows = [{
                "Metric": row.get("Metric", "N/A"),
                "Status": row.get("Status", "N/A"),
                "Required source / definition": row.get("Definition / required source", "N/A"),
            } for row in missing_metrics]
            st.dataframe(pd.DataFrame(missing_rows), use_container_width=True, hide_index=True, height=min(320, 48 + 36 * len(missing_rows)))

# -----------------------------------------------------------------------------
# 4. Models: one summary table and historical outputs only where present.
# -----------------------------------------------------------------------------
with tab_models:
    st.markdown("#### Model diagnostics")
    model_rows = [row for row in checks if str(row.get("category", "")) == "Models"]
    if model_rows:
        rows = [{
            "Model / test": row.get("title", "N/A"),
            "Status": row.get("status", "N/A"),
            "Observed result": row.get("metric", "N/A"),
            "Threshold": row.get("threshold", "N/A"),
        } for row in model_rows]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=min(260, 50 + 38 * len(rows)))
        model_names = [str(row.get("title", "Model")) for row in model_rows]
        chosen_model_name = st.selectbox("Model explanation", model_names, key="rf_v2_model_detail")
        selected_model = model_rows[model_names.index(chosen_model_name)]
        with st.container(border=True):
            st.markdown(f"**{_esc(selected_model.get('title', 'Model'))}**")
            tone = _status_tone(str(selected_model.get("status", "N/A")))
            st.markdown(f'<span class="rf-status {tone}">{_esc(selected_model.get("status", "N/A"))}</span>', unsafe_allow_html=True)
            st.write(selected_model.get("explanation", "No explanation was supplied by the model rule."))
            st.caption(f"Method: {selected_model.get('logic', 'N/A')}")
    else:
        st.info("No model diagnostics are relevant and executable for this business model and source coverage.")

    history = sector_result.ratio_history
    model_cols = [column for column in ["Beneish M-Score", "Altman Z''-EM", "Sloan accruals (%)", "CFO / PAT (x)"] if column in history and history[column].notna().any()]
    if model_cols:
        with st.expander("Historical model inputs / outputs", expanded=False):
            st.dataframe(history[model_cols].round(3), use_container_width=True)
    st.caption("Model thresholds are screening conventions, not universal limits. An unavailable or inapplicable model is not a clean result and must not be interpreted as one.")

# -----------------------------------------------------------------------------
# 5. Evidence: source record, limitations and direct links to adjacent modules.
# -----------------------------------------------------------------------------
with tab_evidence:
    st.markdown("#### Source and data quality")
    info_left, info_right = st.columns(2)
    with info_left:
        st.markdown("**Financial statement source**")
        st.write(source)
        st.markdown("**Reporting periods**")
        st.write(", ".join(map(str, periods)) if periods else "N/A")
    with info_right:
        st.markdown("**Normalization**")
        st.write(normalization)
        st.markdown("**Business-model classification**")
        st.write(f"{profile.business_model} · {profile.classification_source} · {profile.confidence}")

    st.markdown("#### Linked findings from Annual Report & Management Intelligence")
    linked_findings = st.session_state.get(f"linked_report_intelligence_{ticker}", [])
    if linked_findings:
        linked_frame = pd.DataFrame(linked_findings)
        keep_cols = [c for c in ["Finding ID", "Disclosure area", "Attention", "Page", "Evidence"] if c in linked_frame.columns]
        if keep_cols:
            st.dataframe(linked_frame[keep_cols], use_container_width=True, hide_index=True, height=min(360, 58 + 42 * len(linked_frame)))
        st.caption("These are linked source disclosures and management-review signals from the combined intelligence page. They are deliberately excluded from the sector forensic score unless independently validated by a configured forensic test, so the same issue is not counted twice.")
    else:
        st.info("No linked annual-report findings are loaded in this session yet. Open Annual Report & Management Intelligence, review its Risk Signals tab, and return here to see the same evidence references.")

    st.markdown("#### Interpretation safeguards")
    safeguards = [
        "Unavailable inputs are not converted into zero or assumed values.",
        "Not-applicable tests are excluded from the sector-screen index.",
        "A triggered rule is an investigation prompt, not a finding of fraud or misconduct.",
        "Sector KPI availability is separate from a sector performance rating.",
        "The current sector-screen index covers the statement-based checks shown here; governance, ESG, credit and regulatory findings remain on their dedicated evidence pages unless explicitly integrated and validated.",
    ]
    for item in safeguards:
        st.markdown(f"- {item}")

    with st.expander("Scoring methodology", expanded=False):
        st.write("The sector-screen index is the severity-weighted share of executed tests. Unavailable and not-applicable tests are excluded from the denominator.")
        st.write("Low = 1, Medium = 2, High = 3, Critical = 4; index = weighted points / (4 × executed tests) × 100.")
        st.write("It is not a probability of fraud, default, manipulation or insolvency, and it should not be compared directly across companies with different sector rule sets.")
        st.metric("Sector-screen index", f"{sector_result.score:.1f}/100")

    warnings = [str(item) for item in getattr(a, "warnings", []) if str(item).strip()]
    if warnings:
        with st.expander(f"Analysis warnings ({len(warnings)})", expanded=False):
            for warning in warnings:
                st.warning(warning)

    st.markdown("#### Continue the investigation")
    nav_cols = st.columns(3)
    nav_items = [
        ("pages/10_Annual_Report_Intelligence.py", "Annual Report & Management Intelligence", ":material/description:"),
        ("pages/4_Governance_DeepDive.py", "Governance Deep Dive", ":material/account_balance:"),
        ("pages/6_Credit_Rating.py", "Credit Rating", ":material/credit_score:"),
        ("pages/5_ESG_Scorecard.py", "ESG Scorecard", ":material/eco:"),
        ("pages/12_Corporate_Regulatory_Intelligence.py", "Corporate & Regulatory Intelligence", ":material/gavel:"),
    ]
    for index, (page_path, label, icon) in enumerate(nav_items):
        with nav_cols[index % 3]:
            st.page_link(page_path, label=label, icon=icon)

# Apply the complete light design system after page-local styles and HTML.
from utils.custom_css import inject_css as _inject_final_light_theme
_inject_final_light_theme()
