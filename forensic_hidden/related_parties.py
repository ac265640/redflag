"""Related-party red flags: money and value leaking to promoters / group entities."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, flag_if, sev_high

CAT = "Related Parties"


def analyze_related_parties(inp: Dict[str, float]) -> List[RedFlag]:
    """RPT intensity, loans to related parties, royalty paid to promoters.

    TODO(real data): parse AS-24 / Ind AS 24 note; split revenue-side vs expense-side RPTs; flag
    arm's-length pricing disclosures from the audit committee.
    """
    items = [
        flag_if(sev_high(inp["rpt_pct_revenue"], 15, 30), code="FX_RPT_INTENSITY", category=CAT, title="High related-party intensity",
                metric=f"{inp['rpt_pct_revenue']:.0f}% of revenue", threshold="> 15% of revenue",
                explanation="A big share of business is done with entities connected to the promoters. Prices may not be market-based and value can quietly move out of the listed company.",
                logic="Total RPT value / revenue."),
        flag_if(sev_high(inp["rpt_loans_pct_networth"], 10, 25), code="FX_RPT_LOANS", category=CAT, title="Loans & advances to related parties",
                metric=f"{inp['rpt_loans_pct_networth']:.0f}% of net worth", threshold="> 10% of net worth",
                explanation="The company has lent a notable amount to group entities. If those entities cannot repay, shareholders bear the loss.",
                logic="Loans/advances/guarantees to related parties / net worth."),
        flag_if(sev_high(inp["royalty_pct_pat"], 5, 10), code="FX_ROYALTY", category=CAT, title="Royalty to promoters / group",
                metric=f"{inp['royalty_pct_pat']:.1f}% of PAT", threshold="> 5% of PAT (SEBI RPT limit: higher of 5% of turnover / 2% of net worth)",
                explanation="Large royalty or brand-fee payments to promoter entities transfer profit from public shareholders to the promoter family.",
                logic="Royalty and brand fees paid to promoters / PAT."),
    ]
    return [f for f in items if f]
