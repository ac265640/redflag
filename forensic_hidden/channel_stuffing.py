"""Channel-stuffing detector: pushing goods to distributors to book sales early."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, flag_if, sev_high

CAT = "Channel Stuffing"


def analyze_channel_stuffing(inp: Dict[str, float]) -> List[RedFlag]:
    """Q4 loading, year-end receivable spikes and rising dealer inventory.

    Logic: if a quarter holds an outsized share of annual sales AND receivables spike at year-end,
    sales were probably pulled forward on credit. TODO(real data): quarterly results + receivable ageing.
    """
    items = [
        flag_if(sev_high(inp["q4_sales_share_pct"] - 25, 3, 7), code="FX_Q4_LOADING", category=CAT, title="Year-end sales loading",
                metric=f"Q4 = {inp['q4_sales_share_pct']:.0f}% of annual sales", threshold="> 28% (even split = 25%)",
                explanation="An unusually large share of the year's sales landed in the final quarter, a typical pattern when targets are met by pushing goods to dealers.",
                logic="Q4 sales / annual sales vs 25% baseline."),
        flag_if(sev_high(inp["yearend_receivable_spike_pct"], 15, 30), code="FX_RECV_SPIKE", category=CAT, title="Year-end receivable spike",
                metric=f"+{inp['yearend_receivable_spike_pct']:.0f}% vs Q3", threshold="> 15%",
                explanation="Amounts owed by customers jump at year-end. Sales booked but not paid for are the usual footprint of stuffing.", logic="Receivables(Q4) / Receivables(Q3) - 1."),
        flag_if(sev_high(inp["dealer_inventory_days_rise"], 10, 20), code="FX_DEALER_INV", category=CAT, title="Rising dealer inventory",
                metric=f"+{inp['dealer_inventory_days_rise']:.0f} days", threshold="> 10 days", explanation="Goods are sitting longer with distributors, so reported sales may run ahead of real consumer demand.",
                logic="Change in channel inventory days (industry data / management commentary)."),
    ]
    return [f for f in items if f]
