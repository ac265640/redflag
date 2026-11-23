"""Management behaviour: KMP exits, insider selling."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, flag_if, sev_high

CAT = "Management"


def analyze_management(inp: Dict[str, float]) -> List[RedFlag]:
    """Senior exits and insider trading patterns.

    TODO(real data): SEBI PIT disclosures (Reg 7), BSE announcements for CFO / CS / auditor resignations.
    """
    items = [
        flag_if(sev_high(inp["kmp_exits_24m"], 2, 3), code="FX_KMP_EXIT", category=CAT, title="Key management exits",
                metric=f"{inp['kmp_exits_24m']} exits in 24 months", threshold=">= 2",
                explanation="Several senior executives (CFO, CEO, company secretary) left recently. Finance-chief exits before bad news are a well-known warning pattern.",
                logic="Count of KMP resignations in trailing 24 months."),
        flag_if(sev_high(inp["insider_net_sell_pct"], 2, 4), code="FX_INSIDER_SELL", category=CAT, title="Insider selling",
                metric=f"{inp['insider_net_sell_pct']:.1f}% of equity net sold", threshold="> 2% of equity",
                explanation="Promoters and insiders have been net sellers. They know the business best, so heavy selling can signal reduced confidence.",
                logic="Net insider sales / shares outstanding (trailing 12 months)."),
    ]
    return [f for f in items if f]
