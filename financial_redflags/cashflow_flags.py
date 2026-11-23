"""Cash-flow red flags: does profit turn into cash?"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from core.config import THRESHOLDS as T
from core.constants import RedFlag, Severity, flag_if, pct_growth, safe_div, sev_low

CAT = "Cash Flow"


def analyze_cashflow(df: pd.DataFrame) -> List[RedFlag]:
    """Run all cash-flow tests."""
    last, prev, y = df.iloc[-1], df.iloc[-2], df.index[-1]
    items: List[RedFlag | None] = []

    # 1) Cumulative CFO vs cumulative PAT. Over several years profit must convert to cash.
    cum = safe_div(df["cfo"].sum(), df["pat"].sum())
    items.append(flag_if(
        sev_low(cum, *T["cfo_pat_ratio"]), code="CF_CFO_PAT", category=CAT, title="Profit not converting to cash", metric=f"5-yr CFO/PAT {cum:.2f}x",
        threshold=f"< {T['cfo_pat_ratio'][0]:.1f}x", explanation="Over five years, much less cash came in from operations than profit reported. "
        "Profit that never becomes cash is a core warning sign of aggressive accounting.", logic="Sum of operating cash flow / sum of PAT over the window (a ratio near or above 1 is healthy).", year=y))

    # 2) Cash realization ratio = CFO / EBITDA (how much operating profit is real cash).
    crr = safe_div(last.cfo, last.ebitda)
    items.append(flag_if(
        sev_low(crr, *T["cash_realization"]), code="CF_CASH_REALIZATION", category=CAT, title="Low cash realization", metric=f"CFO/EBITDA {crr:.2f}x",
        threshold=f"< {T['cash_realization'][0]:.1f}x", explanation="Only a small portion of operating profit is arriving as cash this year.", logic="CFO / EBITDA for the latest year.", year=y))

    # 3) Negative CFO despite positive PAT
    if last.cfo < 0 < last.pat:
        items.append(RedFlag("CF_NEGATIVE_CFO", CAT, "Negative operating cash flow with profit", Severity.HIGH, f"CFO {last.cfo:,.0f} vs PAT {last.pat:,.0f}", "CFO < 0 and PAT > 0",
                             "The business reports a profit but burned cash in operations. This usually means sales are on credit or costs are deferred.", "Sign test of CFO vs PAT.", y))

    # 4) Divergence: PAT up, CFO down
    pg, cg = pct_growth(last.pat, prev.pat), pct_growth(last.cfo, prev.cfo) if prev.cfo > 0 else np.nan
    if pg > 10 and (cg < -10 or last.cfo < prev.cfo):
        items.append(RedFlag("CF_DIVERGENCE", CAT, "Profit and cash flow diverging", Severity.MEDIUM, f"PAT {pg:+.0f}% while CFO fell", "PAT growth > 10% and CFO falling",
                             "Reported profit rose but operating cash flow went the other way. The two should move together over time.", "YoY growth comparison of PAT and CFO.", y))

    # 5) Persistent negative FCF: growth funded by external capital.
    neg = int((df["fcf"] < 0).sum())
    if neg >= T["neg_fcf_years"]:
        items.append(RedFlag("CF_NEG_FCF", CAT, "Persistent negative free cash flow", Severity.MEDIUM if neg == 3 else Severity.HIGH, f"FCF negative in {neg}/5 yrs",
                             f">= {T['neg_fcf_years']} yrs", "After capex, the business keeps consuming cash. It depends on new debt or equity to keep running.", "FCF = CFO - capex across the window.", y))
    return [f for f in items if f]
