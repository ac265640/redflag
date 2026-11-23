"""ESG score: pillars (industry weighted) blended with BRSR Core, minus controversies; plus Parivartan (Transition) score."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

from data.fetch_brsr import get_brsr
from esg.controversy import controversy_penalty
from esg.core_brsr import score_core
from esg.environment import scale, score_environment
from esg.governance_esg import score_governance_esg
from esg.industry_weights import get_weights
from esg.social import score_social

BASE_SHARE, CORE_SHARE = 0.7, 0.3


@dataclass
class ESGResult:
    """Full ESG output for one company."""

    total: float
    environment: Dict[str, float]
    social: Dict[str, float]
    governance: Dict[str, float]
    core: Dict[str, float]
    transition_score: float
    controversy_penalty: float
    controversies: List[Dict[str, object]]
    weights: Dict[str, float] = field(default_factory=dict)

    @property
    def grade(self) -> str:
        return "Leader" if self.total >= 70 else ("Average" if self.total >= 50 else "Laggard")


def compute_transition_score(t: Dict[str, object]) -> float:
    """Parivartan (Transition) score: forward-looking readiness, 0-100.

    Defined here as a proprietary composite (NOT an official SEBI metric): net-zero target (20), SBTi validation (15),
    renewable-share trend (20), emission-intensity trend (25), green capex share (20).
    """
    pts = 20 * bool(t["net_zero_target"]) + 15 * bool(t["sbti_validated"])
    pts += 0.20 * scale(t["renewable_trend_pp"], 0, 8)
    pts += 0.25 * scale(t["emissions_intensity_cagr_pct"], 5, -10)
    pts += 0.20 * scale(t["green_capex_pct"], 0, 25)
    return float(np.clip(pts, 0, 100))


def compute_esg(ticker: str, sector: str) -> ESGResult:
    """Score a company. Total = clip((0.7 * weighted E/S/G + 0.3 * Core) - controversy penalty, 0, 100)."""
    d = get_brsr(ticker)
    env, soc, gov = score_environment(d["environment"]), score_social(d["social"]), score_governance_esg(d["governance"])
    core = score_core(d["core"])
    w = get_weights(sector)
    base = w["E"] * env["Pillar"] + w["S"] * soc["Pillar"] + w["G"] * gov["Pillar"]
    pen = controversy_penalty(d["controversies"])
    total = float(np.clip(BASE_SHARE * base + CORE_SHARE * core["Core ESG Score"] - pen, 0, 100))
    return ESGResult(round(total, 1), env, soc, gov, core, round(compute_transition_score(d["transition"]), 1), pen, d["controversies"], w)
