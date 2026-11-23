"""Regulatory track record."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, Severity

CAT = "Regulatory"


def analyze_sebi_actions(b: Dict[str, object]) -> List[RedFlag]:
    """Count SEBI / exchange actions in the last 5 years.

    TODO(real data): scrape SEBI orders database, BSE/NSE penalty notices, fraud/forfeiture records.
    """
    n = len(b["sebi_actions"])
    if n == 0:
        return []
    return [RedFlag("GV_SEBI", CAT, "Regulatory actions", Severity.CRITICAL if n >= 3 else (Severity.HIGH if n == 2 else Severity.MEDIUM), f"{n} action(s)", ">= 1",
                    "The company or its people have faced regulator action. Repeat actions point to weak compliance.", "Count of SEBI orders / exchange penalties over five years.")]
