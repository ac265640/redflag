"""Ownership-structure red flags: complex subsidiary webs and circular holdings."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, flag_if, sev_high

CAT = "Ownership"


def analyze_ownership(inp: Dict[str, float]) -> List[RedFlag]:
    """Subsidiary count, ownership layers and cross-holdings.

    TODO(real data): MCA subsidiary list, layering depth from SHP, shell-company screen (CIN / address overlaps).
    """
    items = [
        flag_if(sev_high(inp["subsidiaries"], 20, 35), code="FX_SUBS", category=CAT, title="Complex subsidiary structure",
                metric=f"{inp['subsidiaries']} subsidiaries", threshold="> 20",
                explanation="A sprawling web of subsidiaries makes it hard to see where profit and debt really sit, and is a common hiding place for related-party flows.",
                logic="Count of subsidiaries, associates and JVs."),
        flag_if(sev_high(inp["ownership_layers"], 3, 5), code="FX_LAYERS", category=CAT, title="Deep ownership layering",
                metric=f"{inp['ownership_layers']} layers", threshold=">= 3",
                explanation="Promoters hold the company through multiple layers of entities. Layering obscures who ultimately controls and benefits.",
                logic="Number of intermediate holding entities between promoters and the listed company."),
        flag_if(sev_high(inp["cross_holdings"], 2, 4), code="FX_CROSS", category=CAT, title="Cross-holdings within group",
                metric=f"{inp['cross_holdings']} cross-holdings", threshold=">= 2",
                explanation="Group companies hold each other's shares, which can inflate apparent capital and prop up share prices.", logic="Count of circular shareholdings."),
    ]
    return [f for f in items if f]
