"""Shareholder voting patterns: where minority investors push back."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, Severity

CAT = "Voting"


def analyze_voting(b: Dict[str, object]) -> List[RedFlag]:
    """Dissent on related-party and remuneration resolutions (non-promoter votes against).

    TODO(real data): voting results (Reg 44) + proxy-advisor recommendations (IiAS, SES, InGovern).
    """
    v, flags = b["voting"], []
    if v["rpt_dissent_pct"] > 20:
        flags.append(RedFlag("GV_VOTE_RPT", CAT, "High dissent on related-party votes", Severity.HIGH, f"{v['rpt_dissent_pct']:.0f}% against", "> 20% of public votes",
                             "Outside shareholders are voting against related-party deals in large numbers, a clear sign they distrust them.", "Public-shareholder votes against / votes cast."))
    if v["remuneration_dissent_pct"] > 20:
        flags.append(RedFlag("GV_VOTE_PAY", CAT, "High dissent on pay votes", Severity.MEDIUM, f"{v['remuneration_dissent_pct']:.0f}% against", "> 20%",
                             "Minority shareholders object to executive pay proposals.", "Public-shareholder votes against pay resolutions."))
    return flags
