"""Social pillar from BRSR Principles 3, 5 and 8."""
from __future__ import annotations

from typing import Dict

import numpy as np

from esg.environment import scale


def score_social(s: Dict[str, float]) -> Dict[str, float]:
    """Sub-scores + pillar score for workforce, safety, community and grievance handling."""
    sub = {
        "Gender diversity": scale(s["women_employees_pct"], 0, 30),
        "Workplace safety": scale(s["ltifr"], 4.0, 0.1),
        "Training": scale(s["training_hours"], 0, 40),
        "Retention": scale(s["attrition_pct"], 40, 8),
        "CSR delivery": scale(s["csr_spend_vs_prescribed_pct"], 50, 120),
        "Grievance handling": scale(s["grievances_pending_pct"], 30, 0),
    }
    sub["Pillar"] = float(np.mean(list(sub.values())))
    return sub
