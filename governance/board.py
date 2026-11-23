"""Board composition tests (SEBI LODR Reg 17)."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, Severity

CAT = "Board"


def analyze_board(b: Dict[str, object]) -> List[RedFlag]:
    """Independence ratio, women directors, promoter chair.

    LODR: at least 1/2 independent if the chair is an executive/promoter-related, else 1/3; >= 1 woman director.
    """
    flags: List[RedFlag] = []
    ratio = b["independent"] / b["board_size"]
    need = 0.5 if b["chair_is_promoter"] else 1 / 3
    if ratio < need:
        flags.append(RedFlag("GV_BOARD_INDEP", CAT, "Board independence below norm", Severity.HIGH, f"{ratio:.0%} independent", f"< {need:.0%} required",
                             "Too few independent directors means the promoter-led board can pass most decisions without outside challenge.", "Independent directors / board size vs LODR minimum."))
    elif ratio < 0.5:
        flags.append(RedFlag("GV_BOARD_INDEP_LOW", CAT, "Board only minimally independent", Severity.LOW, f"{ratio:.0%} independent", "< 50% (best practice)",
                             "The board meets the legal minimum but not the best-practice level of independence.", "Independent directors / board size."))
    if b["women"] < 1:
        flags.append(RedFlag("GV_BOARD_WOMEN", CAT, "No woman director", Severity.MEDIUM, "0", ">= 1",
                             "The company is missing a mandatory woman director, which also signals weak compliance culture.", "Count of women directors."))
    return flags
