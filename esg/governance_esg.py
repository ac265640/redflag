"""Governance pillar of ESG (BRSR Principles 1, 7, 9). Separate from the forensic Governance score."""
from __future__ import annotations

from typing import Dict

import numpy as np

from esg.environment import scale


def score_governance_esg(g: Dict[str, float]) -> Dict[str, float]:
    """Ethics, complaint handling, data security, supplier conduct."""
    sub = {
        "Complaint resolution": scale(g["complaints_unresolved_pct"], 25, 0),
        "Ethics training": scale(g["ethics_training_pct"], 0, 100),
        "Data security": scale(g["data_breaches"], 4, 0),
        "Supplier code coverage": scale(g["supplier_code_pct"], 0, 100),
    }
    sub["Pillar"] = float(np.mean(list(sub.values())))
    return sub
