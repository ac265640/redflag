"""Profit & Loss red flags.

Core idea: reported profit can be inflated by items that are not repeatable
(other income, exceptional gains), by softer accounting (lower depreciation) or
can simply be unstable. Each test returns an explainable ``RedFlag``.
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from core.config import THRESHOLDS as T
from core.constants import RedFlag, Severity, fmt, flag_if, safe_div, sev_high, sev_low

CAT = "P&L"


def analyze_pnl(df: pd.DataFrame) -> List[RedFlag]:
    """Run all P&L tests on a financials DataFrame (rows = fiscal years)."""
    last, prev, y = df.iloc[-1], df.iloc[-2], df.index[-1]
    items: List[RedFlag | None] = []

    # 1) Unusual other income: profit that does not come from the core business.
    #    If PBT <= 0 but other income > 0, the entire profit pool is non-core.
    oi_pct = safe_div(last.other_income, last.pbt) * 100 if last.pbt > 0 else (100.0 if last.other_income > 0 else 0.0)
    items.append(flag_if(
        sev_high(oi_pct, *T["other_income_pbt_pct"]), code="PNL_OTHER_INCOME", category=CAT,
        title="Unusual other income", metric=f"{oi_pct:.0f}% of PBT", threshold=f"> {T['other_income_pbt_pct'][0]:.0f}% of PBT",
        explanation="A large share of pre-tax profit comes from treasury gains, asset sales or write-backs rather than selling products. "
                    "That income is rarely repeatable and is a classic way to dress up earnings.",
        logic="Other income / PBT. Core earnings power is EBITDA; anything above it is 'below the line'.", year=y))

    # 2) Exceptional items: recurring "one-offs" are not one-off.
    exc_pct = safe_div(abs(last.exceptional), abs(last.pbt)) * 100
    recurring = int((df["exceptional"].abs() > 0).sum())
    sev = sev_high(exc_pct, *T["exceptional_pbt_pct"])
    if sev is None and recurring >= 4:
        sev = Severity.LOW
    items.append(flag_if(
        sev, code="PNL_EXCEPTIONAL", category=CAT, title="Exceptional items", metric=f"{exc_pct:.0f}% of PBT; present in {recurring}/5 yrs",
        threshold=f"> {T['exceptional_pbt_pct'][0]:.0f}% of PBT or recurring",
        explanation="Items labelled 'exceptional' keep showing up. When one-offs repeat every year they are part of the business, "
                    "and management may be using them to smooth or boost profit.", logic="|Exceptional| / |PBT| and count of years with exceptional items.", year=y))

    # 3) Margin anomalies: sudden EBITDA-margin jumps vs prior year.
    m, mp = safe_div(last.ebitda, last.revenue) * 100, safe_div(prev.ebitda, prev.revenue) * 100
    swing = abs(m - mp)
    direction = "expanded" if m > mp else "compressed"
    items.append(flag_if(
        sev_high(swing, *T["margin_swing_pp"]), code="PNL_MARGIN_SWING", category=CAT, title="Margin anomaly",
        metric=f"EBITDA margin {direction} {swing:.1f} pp to {m:.1f}%", threshold=f"> {T['margin_swing_pp'][0]:.0f} pp YoY",
        explanation="Operating margin moved sharply in one year. Stable businesses rarely change margins this fast; "
                    "check for cost deferral, capitalisation of expenses or pricing shocks.", logic="|EBITDA margin(t) - EBITDA margin(t-1)| in percentage points.", year=y))

    #    Margin expansion funded by shrinking SG&A while gross margin also rises -> cost capitalisation smell.
    gm, gmp = (1 - safe_div(last.cogs, last.revenue)) * 100, (1 - safe_div(prev.cogs, prev.revenue)) * 100
    sga, sgap = safe_div(last.sga, last.revenue) * 100, safe_div(prev.sga, prev.revenue) * 100
    first_sga = safe_div(df.iloc[0].sga, df.iloc[0].revenue) * 100
    if gm - gmp > 1.0 and first_sga - sga > 3.0:
        items.append(RedFlag("PNL_SGA_SQUEEZE", CAT, "Margins rising while overheads shrink", Severity.MEDIUM,
                             f"Gross margin +{gm - gmp:.1f} pp; SG&A/sales down {first_sga - sga:.1f} pp in 4 yrs", "SG&A/sales down > 3 pp",
                             "Both gross margin and overhead ratio improved together. This is unusual and can indicate expenses being "
                             "parked on the balance sheet (capitalised) instead of charged to profit.",
                             "Compare gross-margin change with SG&A/sales change; both favourable = scrutinise capitalisation.", y))

    # 4) Persistently low effective tax rate while PBT is positive.
    etr = (df["tax"] / df["pbt"].where(df["pbt"] > 0)) * 100
    low_years = int((etr < T["low_tax_rate_pct"]).sum())
    if low_years >= 2:
        items.append(RedFlag("PNL_LOW_TAX", CAT, "Low effective tax rate", Severity.LOW, f"{etr.iloc[-1]:.0f}% latest; <10% in {low_years} yrs",
                             f"< {T['low_tax_rate_pct']:.0f}% for 2+ yrs",
                             "The company pays very little tax relative to profit. This may be a legitimate holiday or deferred-tax benefit, "
                             "but it can also mean profits are partly booked in low-tax or non-taxable ways.", "Tax / PBT across years.", y))

    # 5) Depreciation rate drop: lengthening useful lives lifts profit with no cash effect.
    rate = df["depreciation"] / df["ppe"].shift(1)
    if rate.notna().sum() >= 3:
        base, now = rate.dropna().iloc[0], rate.iloc[-1]
        drop = (1 - safe_div(now, base)) * 100
        items.append(flag_if(
            sev_high(drop, *T["dep_rate_drop_pct"]), code="PNL_DEP_RATE", category=CAT, title="Falling depreciation rate",
            metric=f"Depreciation/opening PPE down {drop:.0f}%", threshold=f"> {T['dep_rate_drop_pct'][0]:.0f}% decline",
            explanation="The company is charging less depreciation on its assets than before. Stretching asset lives is a quiet way to raise profit "
                        "without any extra cash coming in.", logic="Depreciation / opening net PPE, first available year vs latest.", year=y))

    # 6) Interest coverage: can operating profit service debt?
    ebit = last.pbt + last.interest - last.other_income - last.exceptional
    icr = safe_div(ebit, last.interest, default=np.inf)
    items.append(flag_if(
        sev_low(icr, *T["interest_cover"]), code="PNL_INTEREST_COVER", category=CAT, title="Thin interest coverage",
        metric=f"{fmt(icr, 1)}x", threshold=f"< {T['interest_cover'][0]:.1f}x",
        explanation="Operating profit barely covers the interest bill. A small earnings dip could make it hard to service debt.",
        logic="Core EBIT (ex other income & exceptionals) / interest expense.", year=y))

    return [f for f in items if f]
