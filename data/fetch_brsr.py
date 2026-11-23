"""BRSR / BRSR Core fetcher (PLACEHOLDER). Real source: BSE/NSE BRSR XBRL filings."""
from __future__ import annotations

import zlib
from typing import Dict, List

import numpy as np

from data.fetch_fundamentals import UNIVERSE, RISK_LEVEL

# SEBI BRSR Core: the nine assurance attributes
BRSR_CORE_ATTRIBUTES: List[str] = [
    "GHG footprint", "Water footprint", "Energy footprint", "Embracing circularity",
    "Employee wellbeing & safety", "Gender diversity", "Inclusive development",
    "Fairness with customers & suppliers", "Openness of business",
]


def get_brsr(ticker: str) -> Dict[str, object]:
    """Environment / social / governance disclosures, BRSR Core scores, transition data."""
    s = RISK_LEVEL[UNIVERSE[ticker][2]]
    r = np.random.default_rng(zlib.crc32(("brsr" + ticker).encode()))
    q = 1 - 0.7 * s  # disclosure quality
    return {
        "environment": {
            "ghg_intensity_t_per_cr": float(r.uniform(5, 60) * (1 + s)), "renewable_energy_pct": float(r.uniform(5, 45) * q),
            "water_intensity_kl_per_cr": float(r.uniform(20, 200) * (1 + s)), "waste_recycled_pct": float(r.uniform(20, 90) * q),
            "env_fines_count": int(r.integers(0, 1 + int(4 * s))),
        },
        "social": {
            "women_employees_pct": float(r.uniform(6, 30) * q), "ltifr": float(r.uniform(0.1, 1.0 + 3 * s)),
            "training_hours": float(r.uniform(8, 40) * q), "attrition_pct": float(r.uniform(8, 20 + 20 * s)),
            "csr_spend_vs_prescribed_pct": float(r.uniform(85, 120) - 25 * s),
            "grievances_pending_pct": float(r.uniform(0, 5 + 25 * s)),
        },
        "governance": {
            "complaints_unresolved_pct": float(r.uniform(0, 4 + 20 * s)), "ethics_training_pct": float(r.uniform(50, 100) * q),
            "data_breaches": int(r.integers(0, 1 + int(3 * s))), "supplier_code_pct": float(r.uniform(30, 95) * q),
        },
        "core": {a: float(np.clip(r.normal(72 * q + 15, 12), 5, 100)) for a in BRSR_CORE_ATTRIBUTES},
        "transition": {
            "net_zero_target": bool(r.random() < 0.8 - 0.6 * s), "sbti_validated": bool(r.random() < 0.5 - 0.4 * s),
            "renewable_trend_pp": float(r.normal(4 * q, 2)), "emissions_intensity_cagr_pct": float(r.normal(-5 * q + 4 * s, 3)),
            "green_capex_pct": float(r.uniform(2, 25) * q),
        },
        "controversies": [] if s < 0.5 else [
            {"title": "Pollution-control board notice", "severity": "Medium", "year": 2025},
            {"title": "Labour-safety incident (fatality)", "severity": "High", "year": 2025}][: int(1 + s)],
    }
