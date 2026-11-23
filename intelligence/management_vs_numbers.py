"""Phase 3 intelligence: management commentary versus reported numbers.

The module is evidence-first. It extracts short, locating snippets from the latest
NSE annual-report PDF, classifies them into analyst themes, and checks each theme
against the company's reported financial trend. Missing evidence is N/A; no values
are fabricated.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import streamlit as st

from data.annual_report import annual_report_evidence, extract_annual_report_pages


THEMES: Dict[str, Dict[str, Any]] = {
    "Growth / demand": {
        "patterns": [
            r"strong demand", r"robust demand", r"healthy demand", r"demand remained strong",
            r"volume growth", r"volume grew", r"sales growth", r"revenue growth",
            r"strong growth", r"robust growth", r"double[- ]digit growth", r"demand recovery",
        ],
        "negative": [r"weak demand", r"muted demand", r"soft demand", r"demand slowdown", r"volume declined", r"sales declined"],
    },
    "Margins / cost efficiency": {
        "patterns": [
            r"margin improvement", r"margins improved", r"improved margins", r"margin expansion",
            r"cost reduction", r"cost savings", r"operating leverage", r"efficiency improvement",
            r"cost optimisation", r"cost optimization", r"margin remained stable",
        ],
        "negative": [r"margin pressure", r"margin declined", r"margins declined", r"cost pressure", r"cost inflation"],
    },
    "Cash generation / working capital": {
        "patterns": [
            r"strong cash generation", r"cash generation remained strong", r"cash flow improved",
            r"operating cash flow", r"working capital improved", r"working capital management",
            r"better working capital", r"cash conversion improved", r"cash conversion",
        ],
        "negative": [r"working capital increased", r"working capital pressure", r"cash flow declined", r"cash flow pressure", r"cash conversion weakened"],
    },
    "Deleveraging / balance sheet": {
        "patterns": [
            r"deleveraging", r"deleveraged", r"net debt reduced", r"debt reduced", r"debt reduction",
            r"leverage reduced", r"leverage improved", r"balance sheet strengthened", r"strong balance sheet",
        ],
        "negative": [r"debt increased", r"net debt increased", r"higher leverage", r"leverage increased", r"balance sheet pressure"],
    },
    "Capex / expansion": {
        "patterns": [
            r"capital expenditure", r"capex", r"capacity expansion", r"capacity addition",
            r"expansion plan", r"expansion programme", r"expansion program", r"new capacity",
            r"brownfield", r"greenfield",
        ],
        "negative": [r"capex deferred", r"capex delayed", r"expansion delayed", r"project delay"],
    },
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _short_quote(text: str, max_words: int = 28) -> str:
    words = _clean(text).split()
    return " ".join(words[:max_words]).strip()


def _sentences(text: str) -> List[str]:
    text = _clean(text)
    if not text:
        return []
    # PDF extraction frequently loses paragraph breaks. Sentence splitting is
    # intentionally conservative so we do not create long or misleading quotes.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [_clean(x) for x in parts if len(_clean(x).split()) >= 5]


def _classify(sentence: str) -> List[str]:
    low = sentence.lower()
    hits = []
    for theme, cfg in THEMES.items():
        if any(re.search(p, low, re.I) for p in cfg["patterns"] + cfg["negative"]):
            hits.append(theme)
    return hits


def _management_pages(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Locate MD&A / directors' report pages and include a small surrounding window."""
    anchors = []
    for item in pages:
        low = item.get("text", "").lower()
        if re.search(r"management discussion and analysis|management's discussion and analysis|md&a|director'?s report", low):
            anchors.append(int(item["page"]))
    if not anchors:
        return []
    chosen = set()
    for p in anchors:
        # Capture the section heading plus a compact local window. This avoids
        # parsing an entire 300+ page report into the UI.
        for q in range(max(1, p - 1), p + 7):
            chosen.add(q)
    return [p for p in pages if int(p["page"]) in chosen]


@st.cache_data(ttl=86400, show_spinner=False)
def extract_management_commentary(pdf_url: str) -> pd.DataFrame:
    """Extract short management-commentary snippets with annual-report page numbers."""
    if not pdf_url:
        return pd.DataFrame(columns=["Theme", "Tone", "Page", "Statement", "Source"])
    pages = extract_annual_report_pages(pdf_url)
    selected = _management_pages(pages)
    if not selected:
        return pd.DataFrame(columns=["Theme", "Tone", "Page", "Statement", "Source"])

    rows = []
    seen = set()
    for item in selected:
        page = int(item["page"])
        for sentence in _sentences(item.get("text", "")):
            themes = _classify(sentence)
            if not themes:
                continue
            low = sentence.lower()
            for theme in themes:
                tone = "Negative / cautious" if any(re.search(p, low, re.I) for p in THEMES[theme]["negative"]) else "Positive / constructive"
                quote = _short_quote(sentence)
                key = (theme, page, quote.lower())
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"Theme": theme, "Tone": tone, "Page": page, "Statement": quote, "Source": pdf_url})

    if not rows:
        return pd.DataFrame(columns=["Theme", "Tone", "Page", "Statement", "Source"])
    df = pd.DataFrame(rows).drop_duplicates(subset=["Theme", "Page", "Statement"])
    # Keep the evidence layer compact: the strongest few statements per theme.
    df["_priority"] = df["Tone"].eq("Positive / constructive").astype(int)
    df = df.sort_values(["Theme", "_priority", "Page"], ascending=[True, False, True]).drop(columns="_priority")
    return df.groupby("Theme", group_keys=False).head(4).reset_index(drop=True)


def _latest_two(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 2:
        return None, None
    return float(s.iloc[-1]), float(s.iloc[-2])


def _pct_change(series: pd.Series):
    cur, prev = _latest_two(series)
    if cur is None or prev is None or abs(prev) < 1e-12:
        return None
    return (cur / prev - 1.0) * 100.0


def _margin(fin: pd.DataFrame, numerator: str, denominator: str) -> pd.Series:
    den = pd.to_numeric(fin[denominator], errors="coerce").replace(0, np.nan)
    return pd.to_numeric(fin[numerator], errors="coerce") / den * 100.0


def _check(theme: str, fin: pd.DataFrame, ratio: pd.DataFrame) -> Dict[str, Any]:
    """Translate reported numbers into an analyst-friendly validation result."""
    result = {"Theme": theme, "Financial check": "N/A", "Status": "N/A", "Analyst interpretation": "N/A — required financial data is not available."}
    try:
        if theme == "Growth / demand":
            g = _pct_change(fin["revenue"])
            if g is None:
                return result
            result.update({"Financial check": f"Revenue growth YoY: {g:+.1f}%", "Status": "Supports" if g > 5 else ("Mixed" if g >= 0 else "Contradicts"),
                           "Analyst interpretation": "Reported revenue growth supports a positive growth narrative." if g > 5 else ("Revenue is growing, but only modestly; volume/demand claims need supporting operating data." if g >= 0 else "Revenue declined; a strong-growth narrative is not supported by the headline financials.")})
        elif theme == "Margins / cost efficiency":
            m = _margin(fin, "ebitda", "revenue")
            cur, prev = _latest_two(m)
            if cur is None:
                return result
            delta = cur - prev
            result.update({"Financial check": f"EBITDA margin: {cur:.1f}% ({delta:+.1f} pp YoY)", "Status": "Supports" if delta > 0.5 else ("Mixed" if delta >= -0.5 else "Contradicts"),
                           "Analyst interpretation": "EBITDA margin expanded, consistent with cost-efficiency commentary." if delta > 0.5 else ("Margins are broadly stable; commentary should be checked against cost and pricing disclosures." if delta >= -0.5 else "EBITDA margin contracted, so margin-improvement claims need deeper investigation.")})
        elif theme == "Cash generation / working capital":
            if "CFO / PAT" not in ratio.columns:
                return result
            cur, prev = _latest_two(ratio["CFO / PAT"])
            if cur is None:
                return result
            ccc_cur, ccc_prev = _latest_two(ratio["CCC"]) if "CCC" in ratio.columns else (None, None)
            cash_ok = cur >= 1.0
            wc_ok = ccc_cur is not None and ccc_prev is not None and ccc_cur <= ccc_prev
            if cash_ok and (ccc_cur is None or wc_ok):
                status = "Supports"
            elif cur >= 0.8 or wc_ok:
                status = "Mixed"
            else:
                status = "Contradicts"
            wc_text = f"; CCC {ccc_cur:.0f} days ({ccc_cur-ccc_prev:+.0f} days YoY)" if ccc_cur is not None and ccc_prev is not None else ""
            result.update({"Financial check": f"CFO / PAT: {cur:.2f}x{wc_text}", "Status": status,
                           "Analyst interpretation": "Cash conversion supports the management narrative." if status == "Supports" else ("Cash conversion is mixed; verify receivables, inventory and working-capital notes." if status == "Mixed" else "Reported cash conversion does not support a strong cash-generation narrative." )})
        elif theme == "Deleveraging / balance sheet":
            de = fin["total_debt"] / fin["net_worth"].replace(0, np.nan)
            cur, prev = _latest_two(de)
            if cur is None:
                return result
            delta = cur - prev
            status = "Supports" if delta < -0.05 else ("Mixed" if abs(delta) <= 0.05 else "Contradicts")
            result.update({"Financial check": f"Debt / equity: {cur:.2f}x ({delta:+.2f}x YoY)", "Status": status,
                           "Analyst interpretation": "Leverage fell, supporting a deleveraging narrative." if status == "Supports" else ("Leverage is broadly stable; check net debt and cash balances before concluding." if status == "Mixed" else "Debt / equity increased, so a deleveraging narrative is not supported by this measure." )})
        elif theme == "Capex / expansion":
            capex = pd.to_numeric(fin["capex"], errors="coerce")
            revenue = pd.to_numeric(fin["revenue"], errors="coerce").replace(0, np.nan)
            ratio_capex = capex / revenue * 100
            cur, prev = _latest_two(ratio_capex)
            if cur is None:
                return result
            result.update({"Financial check": f"Capex / revenue: {cur:.1f}% ({cur-prev:+.1f} pp YoY)", "Status": "Informational",
                           "Analyst interpretation": "Capex intensity provides context for the expansion narrative; it does not by itself prove project execution or returns."})
    except Exception:
        return result
    return result


@st.cache_data(ttl=86400, show_spinner=False)
def management_vs_numbers(ticker: str, basis: str = "Consolidated") -> Dict[str, Any]:
    """Return annual-report commentary, financial validation and contradictions."""
    ev = annual_report_evidence(ticker, basis)
    url = str(ev.get("latest_url") or "")
    if not url:
        return {"period": ev.get("period", "N/A"), "source": ev.get("source", "N/A"), "commentary": pd.DataFrame(), "checks": pd.DataFrame(), "latest_url": "", "extraction_status": ev.get("extraction_status", "pdf_unavailable")}

    commentary = extract_management_commentary(url)
    if commentary.empty:
        return {"period": ev.get("period", "N/A"), "source": ev.get("source", "N/A"), "commentary": commentary, "checks": pd.DataFrame(), "latest_url": url, "extraction_status": ev.get("extraction_status", "pdf_unavailable")}

    # Reuse the dashboard's cached company analysis so moving between pages does
    # not trigger another Yahoo/company-data download.
    from visualization.components import _analysis
    a = _analysis(ticker)
    checks = []
    for theme in commentary["Theme"].drop_duplicates():
        checks.append(_check(theme, a.financials, a.financial.ratio_table))
    checks_df = pd.DataFrame(checks)
    return {"period": ev.get("period", "N/A"), "source": ev.get("source", "N/A"), "commentary": commentary, "checks": checks_df, "latest_url": url, "extraction_status": ev.get("extraction_status", "pdf_unavailable")}



def extract_management_commitments(commentary: pd.DataFrame) -> pd.DataFrame:
    """Identify candidate forward-looking management commitments from extracted commentary.

    This is deliberately a candidate finder, not a promise-delivery conclusion.
    Each row retains the original annual-report statement, page and source so an
    analyst can verify it. Delivery status is never inferred from the statement.
    """
    columns = [
        "Theme", "Commitment", "Page", "Statement", "Source", "Validation status"
    ]
    if commentary is None or not isinstance(commentary, pd.DataFrame) or commentary.empty:
        return pd.DataFrame(columns=columns)

    # Forward-looking language plus an action/target cue. Avoid treating every
    # optimistic sentence as a commitment.
    forward_cues = re.compile(
        r"\b(?:will|plan(?:s|ned)? to|intend(?:s|ed)? to|aim(?:s|ed)? to|"
        r"target(?:s|ed|ing)?|expect(?:s|ed)? to|committed to|commitment to|"
        r"propose(?:s|d)? to|scheduled to|on track to|by\s+(?:fy|20\d{2}))\b",
        re.I,
    )
    action_cues = re.compile(
        r"\b(?:invest|capex|capital expenditure|expand|expansion|commission|"
        r"complete|launch|construct|build|increase|reduce|improve|achieve|"
        r"capacity|production|renewable|project|debt|emission|net zero|"
        r"digitalis|digitis|modernis|moderniz|roll out|deliver)\w*\b",
        re.I,
    )

    rows = []
    seen = set()
    for _, row in commentary.iterrows():
        statement = str(row.get("Statement", "") or "").strip()
        if not statement or not forward_cues.search(statement) or not action_cues.search(statement):
            continue
        theme = str(row.get("Theme", "General"))
        page = row.get("Page", "N/A")
        source = str(row.get("Source", "") or "")
        key = (theme, str(page), statement.casefold())
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "Theme": theme,
            "Commitment": statement,
            "Page": page,
            "Statement": statement,
            "Source": source,
            "Validation status": "Needs subsequent-period validation",
        })
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).reset_index(drop=True)
