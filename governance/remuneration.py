"""Executive pay vs performance."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, Severity

CAT = "Remuneration"


def analyze_remuneration(b: Dict[str, object]) -> List[RedFlag]:
    """Pay growth outpacing profit growth; extreme pay vs median employee."""
    r, flags = b["remuneration"], []
    gap = r["pay_growth_pct"] - r["pat_growth_pct"]
    if gap > 25:
        flags.append(RedFlag("GV_PAY_GAP", CAT, "Promoter pay outpacing profit", Severity.HIGH if gap > 40 else Severity.MEDIUM,
                             f"Pay +{r['pay_growth_pct']:.0f}% vs PAT {r['pat_growth_pct']:+.0f}%", "gap > 25 pp",
                             "Top executives' pay is rising much faster than profit, a sign of weak pay discipline.", "Growth in promoter-executive remuneration minus PAT growth."))
    if r["ratio_to_median"] > 250:
        flags.append(RedFlag("GV_PAY_RATIO", CAT, "Very high pay ratio", Severity.LOW, f"{r['ratio_to_median']:.0f}x median employee", "> 250x",
                             "The top executive earns far more than a typical employee, which can hurt morale and signals skewed pay culture.", "CEO/MD pay / median employee pay."))
    return flags
