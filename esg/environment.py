"""Environment pillar from BRSR Section C Principle 6."""
from __future__ import annotations

from typing import Dict

import numpy as np


def scale(v: float, worst: float, best: float) -> float:
    """Linear 0-100 score between a 'worst' and 'best' value (works in both directions)."""
    return float(np.clip((v - worst) / (best - worst) * 100, 0, 100))


def score_environment(e: Dict[str, float]) -> Dict[str, float]:
    """Sub-scores + pillar score. Benchmarks (worst/best) are illustrative; calibrate per sector with real peer data."""
    sub = {
        "Emissions intensity": scale(e["ghg_intensity_t_per_cr"], 120, 5),
        "Renewable energy": scale(e["renewable_energy_pct"], 0, 50),
        "Water intensity": scale(e["water_intensity_kl_per_cr"], 400, 20),
        "Waste recycled": scale(e["waste_recycled_pct"], 0, 90),
        "Compliance record": scale(e["env_fines_count"], 5, 0),
    }
    sub["Pillar"] = float(np.mean(list(sub.values())))
    return sub
