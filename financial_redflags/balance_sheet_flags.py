"""Balance sheet red flags: working-capital build-up, stuck CWIP, leverage, pledging."""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from core.config import THRESHOLDS as T
from core.constants import RedFlag, Severity, flag_if, pct_growth, safe_div, sev_high

CAT = "Balance Sheet"


def analyze_balance_sheet(df: pd.DataFrame) -> List[RedFlag]:
    """Run all balance-sheet tests."""
    last, prev, y = df.iloc[-1], df.iloc[-2], df.index[-1]
    items: List[RedFlag | None] = []
    sales_g = pct_growth(last.revenue, prev.revenue)

    # 1) Receivables growing faster than sales: revenue booked but cash not collected
    #    (aggressive recognition, channel stuffing or soft credit terms).
    recv_gap = pct_growth(last.receivables, prev.receivables) - sales_g
    items.append(flag_if(
        sev_high(recv_gap, *T["recv_gap_pp"]), code="BS_RECEIVABLES", category=CAT, title="Receivables outgrowing sales",
        metric=f"Receivables +{pct_growth(last.receivables, prev.receivables):.0f}% vs sales +{sales_g:.0f}%",
        threshold=f"gap > {T['recv_gap_pp'][0]:.0f} pp",
        explanation="Customers owe the company a rapidly growing amount compared with sales growth. This can mean revenue is being booked early, "
                    "customers are stretching payments or some sales may never turn into cash.",
        logic="Receivable growth minus sales growth (YoY). Healthy firms keep the two aligned.", year=y))

    # 2) Inventory growing faster than sales: unsold stock, obsolescence risk, or stuffing at dealers' end.
    inv_gap = pct_growth(last.inventory, prev.inventory) - sales_g
    items.append(flag_if(
        sev_high(inv_gap, *T["inv_gap_pp"]), code="BS_INVENTORY", category=CAT, title="Inventory outgrowing sales",
        metric=f"Inventory +{pct_growth(last.inventory, prev.inventory):.0f}% vs sales +{sales_g:.0f}%", threshold=f"gap > {T['inv_gap_pp'][0]:.0f} pp",
        explanation="Stock is piling up faster than sales. That ties up cash and raises the chance of future write-downs.",
        logic="Inventory growth minus sales growth (YoY).", year=y))

    # 3) CWIP: big or ever-growing capital work-in-progress can hide costs that should hit profit
    #    or projects that are stuck and never capitalised (so no depreciation is charged).
    cwip_pct = safe_div(last.cwip, last.total_assets) * 100
    ratio = (df["cwip"] / df["ppe"]).tolist()
    rising = all(ratio[i] < ratio[i + 1] for i in range(len(ratio) - 3, len(ratio) - 1))
    sev = sev_high(cwip_pct, *T["cwip_pct_assets"])
    if sev is None and rising and cwip_pct > 8:
        sev = Severity.LOW
    items.append(flag_if(
        sev, code="BS_CWIP", category=CAT, title="Large or stagnant CWIP", metric=f"{cwip_pct:.0f}% of assets; CWIP/PPE {'rising' if rising else 'stable'}",
        threshold=f"> {T['cwip_pct_assets'][0]:.0f}% of assets", explanation="A big pile of unfinished projects is sitting on the balance sheet. While an asset is 'in progress' "
        "no depreciation is charged, which flatters profit. Stuck projects may later be written off.",
        logic="CWIP / total assets, and 3-year trend in CWIP / net PPE.", year=y))

    # 4) Contingent liabilities relative to net worth: disputed claims that could crystallise.
    cont = safe_div(last.contingent_liabilities, last.net_worth) * 100
    items.append(flag_if(
        sev_high(cont, *T["contingent_pct_nw"]), code="BS_CONTINGENT", category=CAT, title="High contingent liabilities",
        metric=f"{cont:.0f}% of net worth", threshold=f"> {T['contingent_pct_nw'][0]:.0f}% of net worth",
        explanation="Potential obligations (tax disputes, guarantees, litigation) are large relative to what shareholders own. "
                    "If even a part becomes real, it could wipe out a meaningful slice of equity.",
        logic="Contingent liabilities not provided for / net worth.", year=y))

    # 5) Leverage
    de = safe_div(last.total_debt, last.net_worth)
    items.append(flag_if(
        sev_high(de, *T["debt_equity"]), code="BS_LEVERAGE", category=CAT, title="High leverage", metric=f"Debt/Equity {de:.2f}x",
        threshold=f"> {T['debt_equity'][0]:.1f}x", explanation="Borrowings are high compared with shareholder capital, leaving little room for error if profits fall.",
        logic="Total debt / net worth.", year=y))

    # 6) Promoter pledge + debt: pledging is a stress signal; combined with leverage it can trigger forced selling.
    p = last.promoter_pledge_pct
    sev = sev_high(p, *T["pledge_pct"])
    if sev is not None and de > 1.0:
        sev = Severity.CRITICAL if sev == Severity.HIGH else Severity.HIGH
    items.append(flag_if(
        sev, code="BS_PLEDGE_DEBT", category=CAT, title="Promoter pledging with debt", metric=f"{p:.0f}% pledged; D/E {de:.1f}x",
        threshold=f"pledge > {T['pledge_pct'][0]:.0f}%", explanation="Promoters have borrowed against their shares in the company while the company itself is also heavily indebted. "
        "A share-price fall can force lenders to sell pledged shares, hurting all shareholders.", logic="Pledged promoter shares (%) and D/E; combined stress raises severity one notch.", year=y))

    # 7) Cash-rich yet borrowing heavily: cash may not be real / may be parked with related parties.
    cash_ta, debt_ta = safe_div(last.cash, last.total_assets) * 100, safe_div(last.total_debt, last.total_assets) * 100
    if cash_ta >= T["cash_ta_pct"] and debt_ta >= T["debt_ta_pct"]:
        items.append(RedFlag("BS_CASH_DEBT", CAT, "Cash-rich yet borrowing", Severity.MEDIUM, f"Cash {cash_ta:.0f}% and debt {debt_ta:.0f}% of assets",
                             "cash >= 12% and debt >= 15% of assets",
                             "The company reports plenty of cash but still pays interest on large loans. It is worth checking whether the cash is "
                             "freely available or tied up (deposits, related parties).", "Cash/total assets alongside debt/total assets.", y))
    return [f for f in items if f]
