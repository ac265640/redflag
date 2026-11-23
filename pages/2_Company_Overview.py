"""Institutional Company Overview with sector-aware metrics and traceable peer analysis."""
from __future__ import annotations

import html
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.fetch_live import DataUnavailable, clear_live_profile_cache
from data.market_intelligence import get_company_news
from data.annual_report import discover_annual_reports
from intelligence.corporate_regulatory import fetch_corporate_regulatory_events
from intelligence.sector_intelligence import (
    RATIO_LIBRARY, METRIC_DIRECTION, classify_company,
    calculate_ratio_series, ratio_rows, metric_status, load_peer_statement_frames,
    compare_peers,
)
from visualization.components import setup_page, render, get_company_core_data
from utils.custom_css import inject_css

REGULATED_FINANCIAL_MODELS = {
    "banking", "nbfc_infra", "nbfc_lending", "insurance",
    "insurance_life", "insurance_general", "insurance_health",
}


# ---------------------------------------------------------------------------
# Formatting / display helpers
# ---------------------------------------------------------------------------
def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def is_num(value: Any) -> bool:
    try:
        return value is not None and pd.notna(value) and np.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def number(value: Any, decimals: int = 2, suffix: str = "") -> str:
    if not is_num(value):
        return "N/A"
    return f"{float(value):,.{decimals}f}{suffix}"


def money_cr(value: Any) -> str:
    return f"₹{number(value, 0)} Cr" if is_num(value) else "N/A"


def safe_latest(series: pd.Series | None) -> float | None:
    if series is None or series.empty:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def safe_previous(series: pd.Series | None) -> float | None:
    if series is None or len(series) < 2:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.iloc[-2]) if len(values) >= 2 else None


def panel(title: str, body: str, subtitle: str = "", extra_class: str = "") -> None:
    sub = f'<div class="co-panel-sub">{esc(subtitle)}</div>' if subtitle else ""
    render(f'<section class="co-panel {extra_class}"><div class="co-panel-title">{esc(title)}</div>{sub}{body}</section>')


def status_colour(status: str) -> str:
    if status == "Improving":
        return "good"
    if status == "Deteriorating":
        return "bad"
    if status == "Broadly stable":
        return "stable"
    return "muted"


def metric_card(label: str, value: str, sub: str, tone: str = "neutral") -> str:
    return (
        f'<div class="co-metric-card">'
        f'<div class="co-metric-label">{esc(label)}</div>'
        f'<div class="co-metric-value">{esc(value)}</div>'
        f'<div class="co-metric-sub {esc(tone)}">{esc(sub)}</div></div>'
    )


def _format_yoy(current: Any, previous: Any) -> str:
    if not is_num(current) or not is_num(previous) or float(previous) <= 0 or float(current) <= 0:
        return "YoY: N/A (non-positive or missing base)"
    return f"YoY: {(float(current) / float(previous) - 1) * 100:+.1f}%"


def _headline_metrics(sector_key: str, fin: pd.DataFrame) -> list[tuple[str, str, str]]:
    if fin is None or fin.empty:
        return []
    last = fin.iloc[-1]
    prev = fin.iloc[-2] if len(fin) > 1 else None
    def v(col):
        return last.get(col) if col in last.index else None
    def p(col):
        return prev.get(col) if prev is not None and col in prev.index else None

    if sector_key in REGULATED_FINANCIAL_MODELS:
        fields = [
            ("Total revenue", "revenue"),
            ("Profit after tax", "pat"),
            ("Total assets", "total_assets"),
            ("Shareholders' equity", "net_worth"),
        ]
    else:
        fields = [
            ("Revenue", "revenue"),
            ("EBITDA", "ebitda"),
            ("Profit after tax", "pat"),
            ("Operating cash flow", "cfo"),
        ]
    cards = []
    for label, col in fields:
        val = v(col)
        yoy = _format_yoy(val, p(col))
        if is_num(val):
            display = money_cr(val)
        else:
            display = "N/A"
        cards.append((label, display, yoy))
    return cards


def _executive_observations(fin: pd.DataFrame, sector, metric_map: dict[str, pd.Series]) -> list[tuple[str, str]]:
    """Deterministic, data-led observations; no generated or assumed financial facts."""
    observations: list[tuple[str, str]] = []
    latest_year = str(fin.index[-1]) if fin is not None and not fin.empty else "latest period"
    if fin is None or fin.empty:
        return [("Unavailable", "Annual financial statement data could not be retrieved for this company.")]

    def pair(code):
        series = metric_map.get(code)
        return safe_latest(series), safe_previous(series)

    rev, prev_rev = pair("revenue_growth")
    if rev is not None:
        if rev > 0:
            observations.append(("Observation", f"Reported revenue grew {rev:.1f}% in {latest_year}. Review whether the growth is supported by margins and cash generation."))
        else:
            observations.append(("Monitor", f"Reported revenue declined {abs(rev):.1f}% in {latest_year}; assess demand, pricing and business mix."))

    if sector.key not in REGULATED_FINANCIAL_MODELS:
        margin, prev_margin = pair("ebitda_margin")
        if margin is not None and prev_margin is not None:
            change = margin - prev_margin
            if change <= -2:
                observations.append(("Monitor", f"EBITDA margin contracted by {abs(change):.1f} percentage points year on year. Check input costs, pricing and mix."))
            elif change >= 2:
                observations.append(("Observation", f"EBITDA margin expanded by {change:.1f} percentage points year on year. Verify sustainability and any one-off effects."))
    else:
        pat_growth, prev_pat_growth = pair("pat_growth")
        if pat_growth is not None:
            observations.append(("Observation" if pat_growth >= 0 else "Monitor",
                                 f"Reported PAT growth was {pat_growth:+.1f}% in {latest_year}; assess it alongside asset quality, funding costs and capital disclosures."))

    if sector.key not in REGULATED_FINANCIAL_MODELS:
        cfo_pat, _ = pair("cfo_pat")
        if cfo_pat is not None:
            if cfo_pat < 0.7:
                observations.append(("Monitor", f"Operating cash flow / PAT is {cfo_pat:.2f}x. Review receivables, inventory, payables and non-cash accruals."))
            elif cfo_pat >= 1:
                observations.append(("Observation", f"Operating cash flow is {cfo_pat:.2f}x PAT, indicating cash generation broadly kept pace with reported profit in {latest_year}."))

    if sector.key not in REGULATED_FINANCIAL_MODELS:
        leverage, _ = pair("net_debt_ebitda")
        if leverage is not None:
            observations.append(("Monitor" if leverage > 3.5 else "Observation",
                                 f"Net debt / EBITDA is {leverage:.2f}x. Compare this with the company's debt maturity, cash-flow profile and relevant sector peers."))

    if sector.key in ("banking", "nbfc_infra", "nbfc_lending"):
        roa, prev_roa = pair("roa")
        if roa is not None and prev_roa is not None:
            delta = roa - prev_roa
            if delta < -0.20:
                observations.append(("Monitor", f"Return on average assets declined by {abs(delta):.2f} percentage points. Review asset quality, funding cost and operating efficiency."))
            else:
                observations.append(("Observation", f"Return on average assets was {roa:.2f}% in {latest_year}; compare against institutions with similar lending and funding profiles."))
        observations.append(("Data coverage", "NIM, GNPA, NNPA, capital adequacy and liquidity/ALM measures require dedicated bank/NBFC regulatory or issuer disclosures; they are not inferred from generic financial statements."))
    elif sector.key in ("insurance", "insurance_life", "insurance_general", "insurance_health"):
        observations.append(("Data coverage", "Solvency, VNB/persistency, claims and combined-ratio measures require insurer-specific regulatory and operating disclosures; they are not inferred from generic financial statements."))

    if not observations:
        observations.append(("Data coverage", "The connected statement feed does not contain enough comparable periods for a reliable executive observation."))
    return observations[:5]


def _monitor_flags(fin: pd.DataFrame, sector, metric_map: dict[str, pd.Series]) -> list[dict[str, str]]:
    """Sector-filtered review prompts based on reproducible metrics, not fraud assertions."""
    flags: list[dict[str, str]] = []
    if fin is None or fin.empty:
        return flags

    def pair(code):
        series = metric_map.get(code)
        return safe_latest(series), safe_previous(series)

    finance = sector.key in REGULATED_FINANCIAL_MODELS
    rev_growth, prev_rev_growth = pair("revenue_growth")
    if rev_growth is not None and prev_rev_growth is not None and rev_growth < -5 and prev_rev_growth < 0:
        flags.append({"severity": "Review", "title": "Consecutive revenue contraction",
                      "evidence": f"Revenue growth was {prev_rev_growth:.1f}% and {rev_growth:.1f}% in the latest two reported periods.",
                      "why": "Investigate demand, pricing, portfolio mix and any change in the reporting perimeter."})

    if finance:
        if sector.key in ("banking", "nbfc_infra", "nbfc_lending"):
            roa, prev_roa = pair("roa")
            if roa is not None and prev_roa is not None and roa < prev_roa - 0.25:
                flags.append({"severity": "Monitor", "title": "Return on assets declined",
                              "evidence": f"ROA moved from {prev_roa:.2f}% to {roa:.2f}%.",
                              "why": "Review asset quality, funding cost and operating expenses; this is not an NPA or capital assessment."})
        elif sector.key in ("insurance", "insurance_life", "insurance_general", "insurance_health"):
            pat_growth, prev_pat_growth = pair("pat_growth")
            if pat_growth is not None and prev_pat_growth is not None and pat_growth < -10 and prev_pat_growth < 0:
                flags.append({"severity": "Monitor", "title": "Consecutive PAT contraction",
                              "evidence": f"PAT growth was {prev_pat_growth:.1f}% and {pat_growth:.1f}% in the latest two periods.",
                              "why": "Review claims experience, product mix, investment income and one-off items in insurer disclosures."})
        borrow_cost, prev_borrow_cost = pair("cost_of_borrowings_proxy") if sector.key in ("nbfc_infra", "nbfc_lending") else (None, None)
        if borrow_cost is not None and prev_borrow_cost is not None and borrow_cost > prev_borrow_cost + 0.75:
            flags.append({"severity": "Monitor", "title": "Interest cost proxy increased",
                          "evidence": f"Interest expense / average reported borrowings moved from {prev_borrow_cost:.2f}% to {borrow_cost:.2f}%.",
                          "why": "Check funding mix, repricing and timing effects; this proxy is not regulatory cost of funds."})
    else:
        margin, prev_margin = pair("ebitda_margin")
        if margin is not None and prev_margin is not None and margin < prev_margin - 5:
            flags.append({"severity": "Review", "title": "EBITDA margin contracted",
                          "evidence": f"EBITDA margin moved from {prev_margin:.2f}% to {margin:.2f}%.",
                          "why": "Check pricing, input costs, product mix and one-off operating items."})
        cfo_pat, _ = pair("cfo_pat")
        if cfo_pat is not None and cfo_pat < 0.5:
            flags.append({"severity": "Review", "title": "Cash conversion is weak",
                          "evidence": f"Operating cash flow / PAT is {cfo_pat:.2f}x.",
                          "why": "Reconcile profit with receivables, inventory, payables, non-cash expenses and working-capital movements."})
        net_debt, _ = pair("net_debt_ebitda")
        if net_debt is not None and net_debt > 3.5:
            flags.append({"severity": "Monitor", "title": "Net leverage merits review",
                          "evidence": f"Net debt / EBITDA is {net_debt:.2f}x.",
                          "why": "Assess debt maturities, liquidity, covenant headroom and the stability of operating cash flow."})
        ccc, prev_ccc = pair("ccc")
        if ccc is not None and prev_ccc is not None and ccc > prev_ccc + 30:
            flags.append({"severity": "Monitor", "title": "Cash conversion cycle lengthened",
                          "evidence": f"CCC increased from {prev_ccc:.1f} to {ccc:.1f} days.",
                          "why": "Identify whether the movement comes from receivables, inventory or supplier payment timing."})
    return flags[:5]


def _plot_financial_trend(fin: pd.DataFrame, sector_key: str, metric_map: dict[str, pd.Series] | None = None) -> None:
    """Show revenue, margins and cash flow in separate, unit-consistent charts."""
    if fin is None or fin.empty or len(fin) < 2:
        st.info("At least two comparable annual periods are needed to show financial trends.")
        return

    periods = fin.index.astype(str).tolist()
    revenue = pd.to_numeric(fin.get("revenue", pd.Series(index=fin.index, dtype=float)), errors="coerce")
    ebitda = pd.to_numeric(fin.get("ebitda", pd.Series(index=fin.index, dtype=float)), errors="coerce")
    pat = pd.to_numeric(fin.get("pat", pd.Series(index=fin.index, dtype=float)), errors="coerce")
    cfo = pd.to_numeric(fin.get("cfo", pd.Series(index=fin.index, dtype=float)), errors="coerce")
    capex = pd.to_numeric(fin.get("capex", pd.Series(index=fin.index, dtype=float)), errors="coerce")

    revenue_col, margin_col = st.columns(2, gap="large")
    with revenue_col:
        panel("Revenue Trajectory (₹ crore)", '<div class="co-source">Annual reported revenue; earnings values do not share this axis.</div>')
        if revenue.notna().sum() >= 2:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=periods, y=revenue.values, name="Revenue", marker_color="#16856b",
                                 hovertemplate="%{x}<br>Revenue: ₹%{y:,.2f} Cr<extra></extra>"))
            fig.update_layout(height=290, margin=dict(l=14, r=14, t=8, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font=dict(family="Inter, Segoe UI, sans-serif", color="#526158", size=12), showlegend=False, bargap=.38)
            fig.update_xaxes(showgrid=False, zeroline=False, title=None)
            fig.update_yaxes(title="₹ crore", showgrid=True, gridcolor="rgba(137,170,195,.15)", zeroline=True,
                             zerolinecolor="rgba(137,170,195,.28)", tickformat=",.0f")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False})
        else:
            st.info("Revenue trend is unavailable because fewer than two annual values were returned.")

    with margin_col:
        # Margins are deliberately omitted for regulated financial models when generic
        # income-statement ratios would be misleading substitutes for their core KPIs.
        margin_series = {}
        if sector_key not in REGULATED_FINANCIAL_MODELS and revenue.gt(0).sum() >= 2:
            if "cogs" in fin.columns:
                cogs = pd.to_numeric(fin["cogs"], errors="coerce")
                margin_series["Gross margin"] = (revenue - cogs) / revenue * 100
            if "ebitda" in fin.columns:
                margin_series["EBITDA margin"] = ebitda / revenue * 100
            if "pat" in fin.columns:
                margin_series["PAT margin"] = pat / revenue * 100
        usable = {k: v for k, v in margin_series.items() if v.notna().sum() >= 2}
        if usable:
            panel("Profitability Margin Trend (%)", '<div class="co-source">Margins are calculated from reported line items as a percentage of revenue.</div>')
            fig = go.Figure()
            palette = {"Gross margin": "#4f9b7d", "EBITDA margin": "#16856b", "PAT margin": "#d5ad62"}
            for label, values in usable.items():
                fig.add_trace(go.Scatter(x=periods, y=values.values, mode="lines+markers", name=label,
                                         line=dict(width=2.5, color=palette[label]), marker=dict(size=6), connectgaps=False,
                                         hovertemplate="%{x}<br>" + label + ": %{y:.2f}%<extra></extra>"))
            fig.update_layout(height=290, margin=dict(l=12, r=12, t=8, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font=dict(family="Inter, Segoe UI, sans-serif", color="#526158", size=12),
                              legend=dict(orientation="h", y=1.14, x=0), hovermode="x unified")
            fig.update_xaxes(showgrid=False, zeroline=False, title=None)
            fig.update_yaxes(title="Margin (%)", ticksuffix="%", showgrid=True, gridcolor="rgba(137,170,195,.15)",
                             zeroline=True, zerolinecolor="rgba(137,170,195,.28)")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False})
        else:
            panel("Profitability Margin Trend (%)", '<div class="co-note">Generic operating margins are not shown for this business model. Review the relevant regulatory or operating KPIs (such as NIM, claims, solvency or business-specific measures) where available.</div>')
            if sector_key not in REGULATED_FINANCIAL_MODELS:
                st.info("Comparable revenue and earnings inputs are not available for margin trends.")

    # Financial businesses require their own cash-flow interpretation; do not
    # compare CFO/PAT or industrial free cash flow with non-financial issuers.
    if sector_key in REGULATED_FINANCIAL_MODELS:
        panel("Cash Flow & Earnings Quality", '<div class="co-note">A generic industrial CFO/PAT or free-cash-flow comparison is not applied to banks, NBFCs and insurers because operating cash flows reflect financial assets, deposits, funding and policy activity. Review the entity-specific regulatory disclosures instead.</div>')
        return

    panel("Cash Flow & Earnings Quality (₹ crore)", '<div class="co-source">PAT and operating cash flow are shown separately with a zero baseline; free cash flow appears only when reported capex is available.</div>')
    cash_fields = [("PAT", pat, "#d5ad62"), ("Operating cash flow", cfo, "#4f91ad")]
    if capex.notna().sum() >= 2:
        fcf = cfo - capex
        if fcf.notna().sum() >= 2:
            cash_fields.append(("Free cash flow", fcf, "#56c3a4"))
    if any(values.notna().sum() >= 2 for _, values, _ in cash_fields):
        fig = go.Figure()
        for label, values, colour in cash_fields:
            if values.notna().sum() >= 2:
                fig.add_trace(go.Scatter(x=periods, y=values.values, mode="lines+markers", name=label,
                                         line=dict(width=2.3, color=colour), marker=dict(size=6), connectgaps=False,
                                         hovertemplate="%{x}<br>" + label + ": ₹%{y:,.2f} Cr<extra></extra>"))
        fig.update_layout(height=280, margin=dict(l=12, r=12, t=8, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          font=dict(family="Inter, Segoe UI, sans-serif", color="#526158", size=12),
                          legend=dict(orientation="h", y=1.14, x=0), hovermode="x unified")
        fig.update_xaxes(showgrid=False, zeroline=False, title=None)
        fig.update_yaxes(title="₹ crore", showgrid=True, gridcolor="rgba(137,170,195,.15)",
                         zeroline=True, zerolinecolor="rgba(137,170,195,.55)", tickformat=",.0f")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False})
    else:
        st.info("Comparable PAT and operating cash-flow values are not available for a cash-flow trend.")


def _ratio_display(ratio_rows: list[dict[str, Any]], years: list[str]) -> pd.DataFrame:
    rows = []
    for item in ratio_rows:
        row = {"Ratio / KPI": item["label"], "Unit": item["unit"]}
        for year in years:
            value = item["values"].get(year, np.nan)
            row[year] = number(value, 2) if is_num(value) else "N/A"
        row["Availability"] = "Latest period calculated" if item.get("latest_available", False) else ("Historical only" if item["available"] else "Source input unavailable")
        rows.append(row)
    return pd.DataFrame(rows)


def _input_snapshot(code: str, fin: pd.DataFrame) -> pd.DataFrame:
    input_map = {
        "revenue_growth": ["revenue"], "pat_growth": ["pat"], "asset_growth": ["total_assets"],
        "gross_margin": ["revenue", "cogs"], "ebitda_margin": ["revenue", "ebitda"],
        "ebit_margin": ["revenue", "ebitda", "depreciation"], "pat_margin": ["revenue", "pat"],
        "roa": ["pat", "total_assets"], "roe": ["pat", "net_worth"], "roce": ["ebitda", "depreciation", "total_assets", "current_liabilities"],
        "debt_equity": ["total_debt", "net_worth"], "net_debt_ebitda": ["total_debt", "cash", "ebitda"],
        "interest_coverage": ["ebitda", "depreciation", "interest"], "cfo_pat": ["cfo", "pat"],
        "dso": ["receivables", "revenue"], "dio": ["inventory", "cogs"], "dpo": ["payables", "cogs"],
        "ccc": ["receivables", "inventory", "payables", "revenue", "cogs"],
        "asset_turnover": ["revenue", "total_assets"], "cost_of_borrowings_proxy": ["interest", "total_debt"],
        "capex_revenue": ["capex", "revenue"],
    }
    labels = {
        "revenue":"Revenue (₹ Cr)", "pat":"PAT (₹ Cr)", "asset_growth":"Total assets (₹ Cr)",
        "cogs":"Cost of revenue (₹ Cr)", "ebitda":"EBITDA (₹ Cr)", "depreciation":"Depreciation (₹ Cr)",
        "total_assets":"Total assets (₹ Cr)", "net_worth":"Shareholders' equity (₹ Cr)",
        "total_debt":"Total debt (₹ Cr)", "cash":"Cash and equivalents (₹ Cr)",
        "interest":"Interest expense (₹ Cr)", "cfo":"Operating cash flow (₹ Cr)",
        "receivables":"Receivables (₹ Cr)", "inventory":"Inventory (₹ Cr)",
        "payables":"Payables (₹ Cr)", "current_liabilities":"Current liabilities (₹ Cr)",
        "capex":"Capital expenditure (₹ Cr)",
    }
    fields = input_map.get(code, [])
    if not fields or fin is None or fin.empty:
        return pd.DataFrame()
    latest_year = fin.index[-1]
    previous_year = fin.index[-2] if len(fin) > 1 else None
    rows = []
    for field in fields:
        current = fin.iloc[-1].get(field, np.nan)
        previous = fin.iloc[-2].get(field, np.nan) if previous_year is not None else np.nan
        rows.append({"Input from statement": labels.get(field, field), str(latest_year): number(current, 2), str(previous_year or "Previous period"): number(previous, 2)})
    return pd.DataFrame(rows)


def _valuation_context(profile: dict[str, Any], fin: pd.DataFrame, sector_key: str) -> pd.DataFrame:
    if fin is None or fin.empty:
        return pd.DataFrame()
    last = fin.iloc[-1]
    market_cap = profile.get("market_cap_cr")
    pat = last.get("pat", np.nan)
    equity = last.get("net_worth", np.nan)
    metrics = []
    if is_num(market_cap) and is_num(pat) and float(pat) > 0:
        metrics.append({"Metric": "Market cap / latest FY PAT (P/E)", "Value": f"{float(market_cap)/float(pat):.2f}x"})
    else:
        metrics.append({"Metric": "Market cap / latest FY PAT (P/E)", "Value": "N/A"})
    if is_num(market_cap) and is_num(equity) and float(equity) > 0:
        metrics.append({"Metric": "Market cap / latest FY equity (P/B)", "Value": f"{float(market_cap)/float(equity):.2f}x"})
    else:
        metrics.append({"Metric": "Market cap / latest FY equity (P/B)", "Value": "N/A"})
    if sector_key not in REGULATED_FINANCIAL_MODELS:
        debt, cash, ebitda = last.get("total_debt", np.nan), last.get("cash", np.nan), last.get("ebitda", np.nan)
        if all(is_num(x) for x in (market_cap, debt, cash, ebitda)) and float(ebitda) > 0:
            ev = float(market_cap) + float(debt) - float(cash)
            ev_ebitda = ev / float(ebitda)
            metrics.append({"Metric": "EV / latest FY EBITDA", "Value": f"{ev_ebitda:.2f}x"})
        else:
            metrics.append({"Metric": "EV / latest FY EBITDA", "Value": "N/A"})
    return pd.DataFrame(metrics)


# ---------------------------------------------------------------------------
# Page setup and source-preserving annual statement retrieval
# ---------------------------------------------------------------------------
st.markdown(r"""
<style>
.co-wrap{max-width:1760px;margin:0 auto}
.co-header{border:1px solid rgba(56,189,248,.27);border-radius:16px;padding:18px 22px;background:linear-gradient(110deg,rgba(10,34,52,.96),rgba(7,22,37,.96));margin-bottom:14px}
.co-eyebrow{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#7DD3FC;font-weight:800;margin-bottom:6px}
.co-company-name{font-size:30px;line-height:1.2;font-weight:800;color:#F4F8FC;margin:0 0 6px}
.co-company-sub{font-size:16px;line-height:1.45;color:#C4D2DE}
.co-tags{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.co-tag{display:inline-block;border:1px solid rgba(125,211,252,.22);border-radius:20px;padding:5px 10px;color:#CDEBFA;background:rgba(10,44,65,.6);font-size:13px}
.co-panel{border:1px solid rgba(56,189,248,.24);border-radius:14px;background:linear-gradient(145deg,rgba(10,33,51,.96),rgba(5,20,34,.97));padding:16px 18px;margin:10px 0 14px;min-width:0}
.co-panel-title{font-size:19px;line-height:1.35;font-weight:800;color:#F0F7FC;margin-bottom:8px}
.co-panel-sub{font-size:14px;line-height:1.5;color:#AFC3D2;margin-bottom:10px}
.co-overview-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.co-metrics-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:10px 0 14px}
.co-metric-card{border:1px solid rgba(56,189,248,.22);border-radius:12px;padding:14px 15px;background:rgba(8,27,43,.86);min-height:106px}
.co-metric-label{font-size:14px;color:#B8CAD8;font-weight:650}
.co-metric-value{font-size:25px;line-height:1.3;color:#F8FBFF;font-weight:800;margin:7px 0 2px;overflow-wrap:anywhere}
.co-metric-sub{font-size:13px;line-height:1.4;color:#AFC3D2}
.co-metric-sub.good{color:#67E8A5}.co-metric-sub.bad{color:#FCA5A5}.co-metric-sub.stable{color:#7DD3FC}.co-metric-sub.muted{color:#9CAFC0}
.co-info-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.co-info{padding:9px 10px;border:1px solid rgba(148,163,184,.13);border-radius:8px;background:rgba(4,18,31,.38)}
.co-info-label{font-size:13px;color:#91A9BC;margin-bottom:3px}
.co-info-value{font-size:15px;line-height:1.4;color:#E5EEF5;font-weight:650;overflow-wrap:anywhere}
.co-observation{border-left:3px solid #38BDF8;background:rgba(11,44,64,.55);padding:10px 12px;border-radius:0 9px 9px 0;margin:8px 0;color:#D9E8F2;font-size:15px;line-height:1.5}
.co-observation.monitor{border-left-color:#FBBF24}.co-observation.data{border-left-color:#94A3B8}
.co-health-row{display:flex;justify-content:space-between;gap:14px;align-items:center;padding:10px 0;border-bottom:1px solid rgba(148,163,184,.13);font-size:14px}
.co-health-row:last-child{border-bottom:0}.co-health-name{color:#D7E4ED;font-weight:650}.co-health-status{font-weight:700}
.co-health-status.good{color:#6EE7B7}.co-health-status.bad{color:#FCA5A5}.co-health-status.stable{color:#7DD3FC}.co-health-status.muted{color:#A9BAC8}
.co-flag{border:1px solid rgba(148,163,184,.18);border-left:4px solid #FBBF24;border-radius:10px;padding:13px 14px;margin:9px 0;background:rgba(7,23,38,.72)}
.co-flag.review{border-left-color:#F97316}.co-flag.monitor{border-left-color:#FBBF24}
.co-flag-title{color:#F2F7FB;font-size:16px;font-weight:750;margin-bottom:4px}
.co-flag-evidence{color:#C5D4DF;font-size:14px;line-height:1.45}.co-flag-why{color:#9FB5C5;font-size:14px;line-height:1.45;margin-top:5px}
.co-note{border:1px solid rgba(148,163,184,.18);border-radius:10px;padding:12px 14px;background:rgba(7,22,36,.65);color:#B8C9D6;font-size:14px;line-height:1.5;margin:8px 0}
.co-ratio-explain{border:1px solid rgba(56,189,248,.25);border-radius:12px;background:rgba(7,26,42,.82);padding:16px;margin-top:12px}
.co-ratio-explain h4{font-size:17px;color:#EAF5FC;margin:0 0 10px}
.co-ratio-explain p{font-size:14px;line-height:1.55;color:#C5D6E2;margin:6px 0}
.co-source{color:#91A9BC;font-size:13px;line-height:1.5}
.co-source a{color:#7DD3FC}
.co-table-caption{color:#9FB4C4;font-size:13px;line-height:1.4;margin-top:6px}
.co-news{border:1px solid rgba(148,163,184,.18);border-radius:12px;background:rgba(7,23,38,.78);padding:15px;margin-bottom:10px;height:100%}
.co-news-title{font-size:16px;line-height:1.4;font-weight:700;color:#EAF3F9;margin:7px 0}
.co-news-meta{font-size:13px;color:#9CB1C0;margin-bottom:8px}
.co-news a{font-size:14px;color:#7DD3FC}
div[data-testid="stSegmentedControl"]{margin:16px 0 20px!important;width:100%}
div[data-testid="stSegmentedControl"] [data-baseweb="button-group"]{
    display:flex!important;flex-wrap:wrap!important;gap:9px!important;
    background:transparent!important;border:0!important;overflow:visible!important;
}
div[data-testid="stSegmentedControl"] button{
    flex:0 0 auto!important;min-height:40px!important;height:auto!important;
    padding:9px 15px!important;margin:0!important;border-radius:10px!important;
    border:1px solid rgba(89,137,168,.30)!important;
    font-size:14px!important;font-weight:700!important;white-space:normal!important;
    background:rgba(12,34,52,.72)!important;color:#C7D8E6!important;
}
div[data-testid="stSegmentedControl"] button[aria-pressed="true"]{
    background:rgba(8,91,126,.42)!important;border-color:rgba(34,211,238,.72)!important;color:#F1FAFF!important;
}
[data-testid="stDataFrame"]{font-size:14px!important}
@media(max-width:1100px){.co-overview-grid{grid-template-columns:1fr 1fr}.co-metrics-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.co-overview-grid,.co-info-grid,.co-metrics-grid{grid-template-columns:1fr}.co-company-name{font-size:24px}}
</style>
""", unsafe_allow_html=True)

# Re-apply the shared design system after the page-specific layout rules.
inject_css()

ticker = setup_page("Company Overview")
if not ticker:
    st.stop()

refresh_data = st.button("↻ Refresh company source data", key=f"refresh_company_core_{ticker}", help="Fetch the latest available Yahoo Finance annual statements. Cached data is used during normal navigation for speed.")
if refresh_data:
    clear_live_profile_cache()

try:
    with st.spinner("Loading company profile and annual statements in parallel…"):
        profile, financials = get_company_core_data(ticker, force_refresh=refresh_data)
except DataUnavailable as exc:
    st.error(f"Provider-returned annual statements are unavailable for {ticker}: {exc}")
    st.info("No substitute or synthetic financial figures are shown. Check the ticker, provider access or the company's published statements.")
    st.stop()
except Exception as exc:
    st.error(f"Company Overview could not be loaded ({type(exc).__name__}). No figures have been estimated.")
    st.stop()

sector = classify_company(ticker, profile)
metric_map = calculate_ratio_series(financials)
rows = ratio_rows(financials, sector)
latest_year = str(financials.index[-1])
latest = financials.iloc[-1]
company_name = str(profile.get("name") or ticker)
cache_status = str(financials.attrs.get("cache_status", "unknown"))
if cache_status == "stale":
    st.caption("Showing the last successfully retrieved financial statements to keep this page responsive. Use ‘Refresh company source data’ to request a fresh provider update.")
industry_label = str(profile.get("industry") or sector.industry)
market_cap = profile.get("market_cap_cr")
exchange = str(profile.get("exchange") or "NSE/BSE")

# Header
st.markdown(
    f'<div class="co-header"><div class="co-eyebrow">Company Analysis / Company Overview</div>'
    f'<div class="co-company-name">{esc(company_name)}</div>'
    f'<div class="co-company-sub">{esc(ticker)} &nbsp;|&nbsp; {esc(exchange)} &nbsp;|&nbsp; {esc(sector.label)}'
    f' &nbsp;|&nbsp; {esc(sector.business_model)}</div>'
    f'<div class="co-tags"><span class="co-tag">Financial statements: {esc(latest_year)} latest reported period</span>'
    f'<span class="co-tag">Ratio framework: {esc(sector.label)}</span>'
    f'<span class="co-tag">Classification: {esc(sector.confidence)}</span>'
    f'<span class="co-tag">Market cap: {money_cr(market_cap)}</span></div></div>',
    unsafe_allow_html=True,
)

# Company at a glance and summary
info_items = [
    ("Company", company_name),
    ("NSE/BSE ticker", ticker),
    ("Sector framework", sector.label),
    ("Business model", sector.business_model),
    ("Provider industry", industry_label),
    ("Exchange", exchange),
    ("Market capitalisation", money_cr(market_cap)),
    ("Employees", f'{int(profile["employees"]):,}' if is_num(profile.get("employees")) else "N/A"),
]
glance_body = '<div class="co-info-grid">' + "".join(
    f'<div class="co-info"><div class="co-info-label">{esc(label)}</div><div class="co-info-value">{esc(value)}</div></div>'
    for label, value in info_items
) + '</div>'
classification_body = (
    f'<div class="co-observation">{esc(sector.classification_source)}<br><b>{esc(sector.confidence)}</b></div>'
    '<div class="co-source">The profile is a rules-based starting point. Review the latest annual report and segment disclosures before treating a classification as final, especially for diversified businesses.</div>'
)

observations = _executive_observations(financials, sector, metric_map)
summary_body = "".join(
    f'<div class="co-observation {"monitor" if kind=="Monitor" else "data" if kind=="Data coverage" else ""}"><b>{esc(kind)}:</b> {esc(message)}</div>'
    for kind, message in observations
)
top_cols = st.columns([1.05, 1.15])
with top_cols[0]:
    panel("Company at a Glance", glance_body, "Company identity and business-model classification")
    panel("Classification & Methodology", classification_body)
with top_cols[1]:
    panel("Automated Research Insights · System Generated", summary_body, "Rule-based observations from available statement data; no human analyst is implied and this is not an investment recommendation")

# Key financial highlights
cards = _headline_metrics(sector.key, financials)
st.markdown('<div class="co-panel-title" style="margin-top:12px">Key Financial Highlights · '+esc(latest_year)+'</div>', unsafe_allow_html=True)
st.markdown('<div class="co-metrics-grid">' + "".join(
    metric_card(label, value, yoy, "good" if yoy.startswith("YoY: +") else "bad" if yoy.startswith("YoY: -") else "muted")
    for label, value, yoy in cards
) + '</div>', unsafe_allow_html=True)

views = ["Overview", "Financial Analysis", "Peer Benchmarking", "Updates & Evidence"]
view = st.segmented_control("Company research workspace", options=views, default="Overview", key=f"company_view_{ticker}")
view = view or "Overview"

if view == "Overview":
    left, right = st.columns([1.12, 1])
    with left:
        panel("How to Read the Indicators", '<div class="co-note">The status compares the latest reported period with the prior period using a sector-aware direction rule. It is a trend cue, not a universal score or a recommendation. Missing source inputs remain unavailable and are not treated as zero.</div>', "Research framework")
    with right:
        # Health indicators are trends, not an unsupported 0–100 composite score.
        health_codes = []
        preferred = {
            "banking": ("roa","roe","pat_growth"),
            "nbfc_infra": ("roa","roe","debt_equity","cost_of_borrowings_proxy"),
            "nbfc_lending": ("roa","roe","debt_equity","cost_of_borrowings_proxy"),
            "insurance": ("roe","pat_growth"),
            "cement": ("ebitda_margin","roce","net_debt_ebitda","cfo_pat"),
            "it_services": ("ebit_margin","roce","cfo_pat","revenue_growth"),
            "automobile": ("ebitda_margin","roce","net_debt_ebitda","cfo_pat"),
            "fmcg": ("gross_margin","ebitda_margin","roce","ccc"),
            "pharma": ("ebitda_margin","roce","cfo_pat","net_debt_ebitda"),
            "real_estate": ("ebitda_margin","roce","debt_equity","cfo_pat"),
            "capital_markets": ("ebitda_margin","roe","pat_growth","cfo_pat"),
            "utilities": ("ebitda_margin","roce","net_debt_ebitda","interest_coverage"),
            "epc": ("ebitda_margin","roce","debt_equity","cfo_pat"),
            "insurance_life": ("roe","pat_growth"),
            "insurance_general": ("roe","pat_growth"),
            "insurance_health": ("roe","pat_growth"),
            "depository": ("ebitda_margin","roe","pat_growth"),
            "exchange": ("ebitda_margin","roe","pat_growth"),
            "brokerage": ("ebitda_margin","roe","pat_growth"),
            "registrar": ("ebitda_margin","roe","pat_growth"),
            "oil_upstream": ("ebitda_margin","roce","net_debt_ebitda","interest_coverage"),
            "oil_downstream": ("ebitda_margin","roce","net_debt_ebitda","interest_coverage"),
            "gas_distribution": ("ebitda_margin","roce","net_debt_ebitda","interest_coverage"),
            "metals": ("ebitda_margin","roce","net_debt_ebitda","interest_coverage"),
            "telecom": ("ebitda_margin","roce","net_debt_ebitda"),
            "logistics": ("ebitda_margin","roce","asset_turnover"),
            "qsr": ("revenue_growth","ebitda_margin","roce"),
            "consumer_durables": ("gross_margin","ebitda_margin","roce"),
            "chemicals": ("ebitda_margin","roce","net_debt_ebitda"),
        }
        for code in preferred.get(sector.key, ("revenue_growth","pat_margin","roe")):
            series = metric_map.get(code)
            current, previous = safe_latest(series), safe_previous(series)
            if current is None:
                continue
            status = metric_status(current, previous, METRIC_DIRECTION.get(code))
            health_codes.append((RATIO_LIBRARY.get(code, {}).get("label", code), number(current,2) + RATIO_LIBRARY.get(code,{}).get("unit",""), status))
        health_body = "".join(
            f'<div class="co-health-row"><span class="co-health-name">{esc(label)}</span><span>{esc(value)}</span><span class="co-health-status {status_colour(status)}">{esc(status)}</span></div>'
            for label, value, status in health_codes
        ) or '<div class="co-note">Not enough source inputs to populate sector-specific health indicators.</div>'
        panel("Sector Health Indicators", health_body, "The status reflects direction of change in reported inputs, not a composite risk score.")

    # Keep unavailable segment disclosures as a subdued data-coverage note, not a large empty panel.
    st.caption("Segment performance is not displayed because segment revenue and profit are not yet parsed from the original company filing; no company-wide totals are allocated to segments.")

    st.markdown("### Financial Trend Analysis")
    _plot_financial_trend(financials, sector.key, metric_map)

    flags = _monitor_flags(financials, sector, metric_map)
    if flags:
        body = "".join(
            f'<div class="co-flag {"review" if item["severity"]=="Review" else "monitor"}"><div class="co-flag-title">{esc(item["title"])} <span style="color:#FBBF24;font-size:13px">· {esc(item["severity"])}</span></div>'
            f'<div class="co-flag-evidence">{esc(item["evidence"])}</div><div class="co-flag-why">{esc(item["why"])}</div></div>'
            for item in flags
        )
    else:
        body = '<div class="co-note">No monitoring trigger was identified from the available sector-relevant statement metrics. This is not an assurance that the company has no risk; unavailable regulatory and operating KPIs are not scored.</div>'
    panel("Financial Monitoring Points", body, "Rule-based prompts for analyst review, not evidence of fraud or a credit rating")
    source_stamp = financials.attrs.get("retrieved_at")
    source_time = source_stamp.strftime("%d %b %Y, %I:%M %p IST") if isinstance(source_stamp, pd.Timestamp) else "timestamp unavailable"
    st.markdown('<div class="co-source">Financial source: '+esc(financials.attrs.get("source","Yahoo Finance annual statements"))+'. Retrieved/cache timestamp: '+esc(source_time)+'. Amounts normalized to ₹ crore. Reporting basis is the provider-returned statement basis; confirm consolidated/standalone status in the original filing before peer or valuation decisions.</div>', unsafe_allow_html=True)

elif view == "Financial Analysis":
    years = list(financials.index.astype(str))[-5:]
    ratio_frame = _ratio_display(rows, years)
    panel("Sector-Specific Financial Ratios & KPIs",
          '<div class="co-note">The ratio set is selected from the classified business model. Calculated values require all stated inputs; unsupported regulatory and operating KPIs remain N/A. Balance-sheet ratios that require average balances start only when an opening period is available.</div>',
          f"Framework: {sector.label} · Reporting periods: {', '.join(years)}")
    st.dataframe(ratio_frame, use_container_width=True, hide_index=True, height=min(540, 46 + 42*len(ratio_frame)))

    selectable = [x for x in rows]
    default_code = next((x["code"] for x in selectable if x["available"]), selectable[0]["code"] if selectable else "")
    options = [x["code"] for x in selectable]
    labels = {x["code"]: x["label"] for x in selectable}
    if options:
        chosen = st.selectbox("Inspect ratio methodology", options, index=options.index(default_code), format_func=lambda x: labels[x], key=f"ratio_explain_{ticker}")
        item = next(x for x in selectable if x["code"] == chosen)
        current_value = safe_latest(item["values"])
        prior_value = safe_previous(item["values"])
        current_period = str(financials.index[-1])
        prior_period = str(financials.index[-2]) if len(financials)>1 else "N/A"
        status = ("Calculated for latest period" if item.get("latest_available", False)
                  else "Historical value only; latest period input unavailable" if item["available"]
                  else "Not available from connected statements")
        ratio_html = (
            f'<div class="co-ratio-explain"><h4>{esc(item["label"])} · {esc(item["unit"])}</h4>'
            f'<p><b>What it measures:</b> {esc(item["definition"])}</p>'
            f'<p><b>Formula:</b> {esc(item["formula"])}</p>'
            f'<p><b>How to interpret:</b> {esc(item["interpretation"])}</p>'
            f'<p><b>Required inputs:</b> {esc(item["inputs"])}</p>'
            f'<p><b>Calculation limitation:</b> {esc(item["caveat"])}</p>'
            f'<p><b>Status:</b> {esc(status)} · {esc(current_period)}: {number(current_value,2)} · {esc(prior_period)}: {number(prior_value,2)}</p>'
            f'<p class="co-source">Source: {esc(financials.attrs.get("source","Yahoo Finance annual statements"))}. Provider-returned annual statement fields; amounts normalized to ₹ crore.</p></div>'
        )
        st.markdown(ratio_html, unsafe_allow_html=True)
        if item["available"] and item["values"].notna().sum() >= 2:
            fig = go.Figure(go.Scatter(x=item["values"].index, y=item["values"].values, mode="lines+markers", name=item["label"]))
            fig.update_layout(height=290, margin=dict(l=12,r=12,t=18,b=12), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#526158",size=13), showlegend=False)
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(showgrid=True,gridcolor="rgba(148,163,184,.14)",title=item["unit"])
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
        else:
            st.info("A historical trend is not shown because fewer than two valid observations are available.")
        inputs = _input_snapshot(chosen, financials)
        if not inputs.empty:
            st.markdown("**Underlying statement inputs used for the latest calculation**")
            st.dataframe(inputs, use_container_width=True, hide_index=True)
    st.markdown("### Cash Flow & Earnings Quality")
    if sector.key in REGULATED_FINANCIAL_MODELS:
        st.info("Operating cash-flow movements for banks, NBFCs and insurers reflect financial-asset, deposit, policy and funding flows. CFO/PAT and industrial cash-conversion comparisons are not used as a sector benchmark here.")
    else:
        cashflow = pd.DataFrame(index=financials.index)
        pat_values = pd.to_numeric(financials["pat"], errors="coerce") if "pat" in financials.columns else pd.Series(np.nan,index=financials.index)
        cfo_values = pd.to_numeric(financials["cfo"], errors="coerce") if "cfo" in financials.columns else pd.Series(np.nan,index=financials.index)
        comparable_cash_period = (pat_values.notna() & cfo_values.notna()).any()
        if comparable_cash_period:
            cashflow["PAT (₹ Cr)"] = pat_values
            cashflow["Operating cash flow (₹ Cr)"] = cfo_values
            if "capex" in financials.columns:
                capex_values = pd.to_numeric(financials["capex"], errors="coerce")
                if capex_values.notna().any():
                    cashflow["Capex (₹ Cr)"] = capex_values
                    cashflow["Free cash flow (₹ Cr)"] = cfo_values - capex_values
            cashflow["CFO / PAT (x)"] = cfo_values.where(pat_values > 0) / pat_values.where(pat_values > 0)
            st.dataframe(cashflow.round(2), use_container_width=True)
            cfo_pat_value = safe_latest(metric_map.get("cfo_pat"))
            sloan_value = safe_latest(metric_map.get("sloan_accruals"))
            cash_cols = st.columns(2)
            with cash_cols[0]:
                st.metric("Latest CFO / PAT", number(cfo_pat_value,2)+"x" if cfo_pat_value is not None else "N/A")
            with cash_cols[1]:
                st.metric("Latest Sloan accrual ratio", number(sloan_value,2)+"%" if sloan_value is not None else "N/A")
            st.caption("These are earnings-quality screening measures. Reconcile working capital, non-cash expenses and exceptional items; neither measure proves misstatement. Free cash flow is shown only when reported capex is available.")
        else:
            st.info("PAT and operating cash flow are not both available in the same reported period, so no cash-conversion ratio is calculated.")
    if sector.key in ("banking","nbfc_infra","nbfc_lending"):
        st.warning("For banks and NBFCs, NIM, GNPA, NNPA, CRAR, credit cost and ALM measures must be taken from issuer/regulatory disclosures. They are not derived from generic annual statements.")
    elif sector.key in ("insurance_life","insurance_general","insurance_health","insurance"):
        st.warning("For insurers, solvency, VNB/persistency, claims and combined-ratio measures must be taken from insurer/regulatory disclosures. They are not derived from generic annual statements.")
    st.markdown('<div class="co-source">Formula definitions are displayed for transparency. For peer comparisons, ensure consistent statement basis and reporting periods. The application does not silently substitute zero for a missing input in this workspace.</div>', unsafe_allow_html=True)

elif view == "Peer Benchmarking":
    panel("Sector-Matched Peer Benchmarking",
          f'<div class="co-note">Peer candidates are a starting universe for the <b>{esc(sector.label)}</b> business model, not a certified comparable set. Review business mix, revenue segments, geography and scale before using the comparison. The app compares only metrics calculated with the same formulas and a common fiscal year.</div>',
          sector.peer_note)
    if not sector.peers:
        st.info("A peer group has not been assigned because the business model is unclassified. Review the sector classification before selecting peers.")
    else:
        from visualization.components import load_listing_cached
        listing, listing_source = load_listing_cached()
        names = {}
        if listing is not None and not listing.empty:
            names = {str(r["key"]): str(r["name"]) for _, r in listing.iterrows() if "key" in r and "name" in r}
        candidates = [p for p in sector.peers if p != ticker and p in names]
        if not candidates:
            candidates = [p for p in sector.peers if p != ticker]
        default_peers = candidates[:min(4, len(candidates))]
        format_peer = lambda p: f'{names.get(p, p.replace(".NS",""))} ({p})'
        selected_peers = st.multiselect("Select comparable listed companies", options=candidates, default=default_peers,
                                        format_func=format_peer, key=f"peer_selection_{ticker}")
        st.caption(f"Peer universe source: {listing_source}. Only peers present in the current listing universe are selectable where listing metadata is available.")
        if st.button("Load peer financials", type="primary", key=f"load_peer_financials_{ticker}", disabled=not selected_peers):
            with st.spinner("Retrieving peer annual statements and validating common reporting periods..."):
                peer_frames = load_peer_statement_frames(tuple(selected_peers))
                peer_frame, common_period = compare_peers(ticker, financials, peer_frames, sector)
            st.session_state[f"peer_result_{ticker}"] = peer_frame
            st.session_state[f"peer_period_{ticker}"] = common_period
            st.session_state[f"peer_loaded_tickers_{ticker}"] = tuple(selected_peers)
        peer_frame = st.session_state.get(f"peer_result_{ticker}")
        common_period = st.session_state.get(f"peer_period_{ticker}")
        loaded_peers = st.session_state.get(f"peer_loaded_tickers_{ticker}", ())
        peer_selection_changed = tuple(selected_peers) != tuple(loaded_peers)
        if peer_selection_changed:
            peer_frame = None
        if peer_frame is not None and not peer_frame.empty:
            peer_frame = peer_frame.copy()
            peer_frame["Company / ticker"] = peer_frame["Company / ticker"].map(lambda x: f"{names.get(x, x)} ({x})")
            display = peer_frame.copy()
            metric_cols = [c for c in display.columns if c not in ("Company / ticker","Period")]
            for col in metric_cols:
                display[col] = display[col].map(lambda x: number(x,2) if is_num(x) else "N/A")
            st.markdown(f"**Common reporting period: {esc(common_period)}**")
            st.dataframe(display, use_container_width=True, hide_index=True, height=min(420, 48+42*len(display)))
            median_rows = {}
            for col in metric_cols:
                values = pd.to_numeric(peer_frame.iloc[1:][col], errors="coerce").dropna()
                median_rows[col] = number(values.median(),2) if len(values) >= 2 else "N/A (need 2 peers)"
            median_line = {"Company / ticker":"Peer median (minimum 2 valid peers)", "Period":common_period, **median_rows}
            st.dataframe(pd.DataFrame([median_line]), use_container_width=True, hide_index=True)
            st.caption("Peer medians exclude the selected company and require at least two peers with a valid value for the same metric and fiscal year.")
            st.caption("Source: Yahoo Finance annual statement feed for the selected company and peers; compare the original consolidated/standalone filings before relying on relative rankings.")
        elif not peer_selection_changed and st.session_state.get(f"peer_result_{ticker}") is not None:
            st.warning("A common reporting period could not be established across the selected company and loaded peers. No mixed-period peer median has been calculated.")
        elif peer_selection_changed and loaded_peers:
            st.info("The peer selection has changed. Select “Load peer financials” to refresh the comparison for the current peer set.")
        else:
            st.info("Choose the comparable companies and select “Load peer financials”. Peer data is retrieved only on request to keep the overview responsive.")
    # Valuation context from current market capitalisation and reported annual statements.
    valuation = _valuation_context(profile, financials, sector.key)
    panel("Valuation Context", '<div class="co-note">Multiples use the provider-returned latest available market capitalisation and latest reported FY financials. These are indicative FY multiples, not TTM multiples, price targets or intrinsic-value estimates.</div>')
    if not valuation.empty:
        st.dataframe(valuation, use_container_width=True, hide_index=True)
    st.caption("P/E and P/B are displayed only when market capitalisation and positive PAT/equity are available. EV/EBITDA is omitted for banks, NBFCs and insurers.")

elif view == "Updates & Evidence":
    # Annual report catalogue and company news are deliberately loaded only in this view.
    st.markdown("### Annual report and filing evidence")
    try:
        with st.spinner("Checking NSE annual-report attachments..."):
            annual_reports, annual_source = discover_annual_reports(ticker)
        if annual_reports is not None and not annual_reports.empty:
            report = annual_reports.iloc[0]
            period = f"FY{report.get('From Year','')}-{report.get('To Year','')}"
            attachment = str(report.get("Attachment") or "")
            st.markdown(f"**Latest indexed annual report:** {esc(period or 'Latest available')}")
            if attachment.startswith("http"):
                st.markdown(f"[Open original NSE annual-report attachment]({attachment})")
            else:
                st.info("The NSE filing record was returned, but the original attachment URL was not available.")
        else:
            st.info(f"{annual_source}. Annual-report attachment not verified in this run.")
    except Exception as exc:
        st.warning(f"Annual-report lookup unavailable ({type(exc).__name__}).")

    st.markdown("### Latest company news & developments")
    st.caption("Only items published in the current calendar year are shown. News is separate from official exchange disclosures.")
    try:
        news = get_company_news(ticker, company_name, limit=10)
    except Exception:
        news = pd.DataFrame()
    if news is None or news.empty:
        st.info("No company-specific current-year news item could be verified from the connected feed.")
    else:
        for start in range(0, min(len(news), 10), 2):
            cols = st.columns(2)
            for col, (_, item) in zip(cols, news.iloc[start:start+2].iterrows()):
                with col:
                    title = esc(item.get("title","Untitled"))
                    publisher = esc(item.get("publisher","News source"))
                    published = esc(item.get("published","Date unavailable"))
                    url = str(item.get("url",""))
                    impact = esc(item.get("impact","Needs review"))
                    tone = "good" if "positive" in impact.lower() else "bad" if "negative" in impact.lower() else "stable"
                    st.markdown(f'<div class="co-news"><div class="co-news-meta">{publisher} · {published} · {impact}</div><div class="co-news-title">{title}</div><a href="{esc(url)}" target="_blank" rel="noopener">Open original article ↗</a></div>', unsafe_allow_html=True)

    st.markdown("### Recent NSE corporate disclosures")
    try:
        events, event_source = fetch_corporate_regulatory_events(ticker, years=1)
    except Exception as exc:
        events, event_source = pd.DataFrame(), f"Disclosure lookup failed: {type(exc).__name__}"
    if events is None or events.empty:
        st.info(f"{event_source}. No exchange disclosure rows were verified in this run.")
    else:
        for _, ev in events.head(10).iterrows():
            date = esc(ev.get("Date","N/A"))
            title = esc(ev.get("Type","Corporate announcement"))
            category = esc(ev.get("Category","Disclosure"))
            detail = esc(ev.get("Details",""))
            url = str(ev.get("Source",""))
            link = f'<a href="{esc(url)}" target="_blank" rel="noopener">Open original exchange filing ↗</a>' if url.startswith("http") else '<span class="co-source">Attachment link unavailable</span>'
            st.markdown(f'<div class="co-flag monitor"><div class="co-flag-title">{title} <span style="color:#9FC7DD;font-size:13px">· {date} · {category}</span></div><div class="co-flag-evidence">{detail}</div><div style="margin-top:7px">{link}</div></div>', unsafe_allow_html=True)

    st.markdown("### Source coverage & data quality")
    source_rows = [
        {"Dataset":"Annual financial statements","Status":"Retrieved" if not financials.empty else "Unavailable","Source":financials.attrs.get("source","Yahoo Finance annual statements"),"Period":f"{financials.index[0]}–{financials.index[-1]}" if len(financials)>0 else "N/A"},
        {"Dataset":"Sector classification","Status":sector.confidence,"Source":sector.classification_source,"Period":"Current profile"},
        {"Dataset":"Promoter / FII / DII holdings","Status":"Not retrieved in this page","Source":"Use official quarterly NSE/BSE shareholding-pattern filings","Period":"Quarterly"},
        {"Dataset":"Bank/NBFC regulatory metrics","Status":"Not available in standardized statement feed","Source":"Issuer / exchange / regulator filings required","Period":"Latest filing"},
    ]
    st.dataframe(pd.DataFrame(source_rows), use_container_width=True, hide_index=True)

st.markdown('<div class="co-source" style="margin-top:16px">No artificial or sample company figures are inserted in this page. All ratios are either calculated from the displayed provider-returned statement inputs or marked N/A when inputs are missing. Provider data should be checked against original annual reports and exchange filings before investment decisions.</div>', unsafe_allow_html=True)
