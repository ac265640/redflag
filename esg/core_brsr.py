"""BRSR Core: the nine SEBI assurance attributes (reasonable-assurance KPIs)."""
from __future__ import annotations

from typing import Dict

import numpy as np


def score_core(core: Dict[str, float]) -> Dict[str, float]:
    """Average of the nine attribute scores = Core ESG Score.

    TODO(real data): compute each attribute from the BRSR Core KPI formulas (e.g. GHG per rupee of turnover, PPP-adjusted).
    """
    out = dict(core)
    out["Core ESG Score"] = float(np.mean(list(core.values())))
    return out
