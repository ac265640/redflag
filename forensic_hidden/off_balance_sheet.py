"""Off-balance-sheet exposures: guarantees and special-purpose entities."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, flag_if, sev_high

CAT = "Off-Balance-Sheet"


def analyze_off_balance_sheet(inp: Dict[str, float]) -> List[RedFlag]:
    """Corporate guarantees and SPV/structured entities.

    TODO(real data): guarantees note, take-or-pay commitments, factoring/securitisation without recourse disclosure.
    """
    items = [
        flag_if(sev_high(inp["guarantees_pct_networth"], 25, 50), code="FX_GUARANTEES", category=CAT, title="Large guarantees given",
                metric=f"{inp['guarantees_pct_networth']:.0f}% of net worth", threshold="> 25% of net worth",
                explanation="The company has promised to repay other parties' loans if they default. These promises do not show as debt but can become real.",
                logic="Corporate guarantees outstanding / net worth."),
        flag_if(sev_high(inp["spv_count"], 2, 4), code="FX_SPV", category=CAT, title="Special-purpose vehicles",
                metric=f"{inp['spv_count']} SPVs", threshold=">= 2", explanation="Several special-purpose entities may keep debt and losses outside the reported balance sheet.",
                logic="Count of SPVs / structured entities not consolidated."),
    ]
    return [f for f in items if f]
