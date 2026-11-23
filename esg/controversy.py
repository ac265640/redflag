"""Controversy adjustment: penalises ESG scores for live incidents."""
from __future__ import annotations

from typing import Dict, List

_PTS = {"Low": 2.0, "Medium": 5.0, "High": 10.0, "Critical": 18.0}
MAX_PENALTY = 25.0


def controversy_penalty(items: List[Dict[str, object]]) -> float:
    """Sum severity points, capped at 25. TODO(real data): news / NGT / DGMS / court feeds, with recency decay."""
    return min(MAX_PENALTY, sum(_PTS.get(str(i.get("severity")), 0.0) for i in items))
