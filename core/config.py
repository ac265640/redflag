"""Application configuration and every tunable threshold in one place.

Thresholds are tuples ``(medium, high)`` unless noted. Direction (higher/lower is
worse) is documented per entry so analysts can tune the model without touching logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppConfig:
    """Runtime settings."""

    app_name: str = "Red Flag Intelligence"
    use_live_data: bool = True                 # flip when real fetchers are wired in
    cache_dir: Path = ROOT / "data" / "cache"
    cache_ttl_seconds: int = 3600
    years: List[str] = field(default_factory=lambda: [f"FY{y}" for y in range(2022, 2027)])
    currency_label: str = "₹ Cr"
    demo_banner: str = "Source-backed values are shown where available; missing fields remain N/A and should be checked against original filings."


CONFIG = AppConfig()

THRESHOLDS: Dict[str, object] = {
    # --- P&L (higher is worse) ---
    "other_income_pbt_pct": (25.0, 40.0),   # other income as % of PBT
    "exceptional_pbt_pct": (10.0, 25.0),    # |exceptional items| as % of |PBT|
    "margin_swing_pp": (5.0, 10.0),         # YoY EBITDA-margin move, percentage points
    "low_tax_rate_pct": 10.0,               # effective tax below this for 2+ years
    "dep_rate_drop_pct": (20.0, 35.0),      # fall in depreciation / opening PPE vs 3 yrs ago
    "interest_cover": (2.0, 1.2),           # LOWER is worse (EBIT / interest)
    # --- Balance sheet ---
    "recv_gap_pp": (10.0, 20.0),            # receivable growth minus sales growth
    "inv_gap_pp": (10.0, 20.0),             # inventory growth minus sales growth
    "cwip_pct_assets": (15.0, 25.0),
    "contingent_pct_nw": (25.0, 50.0),
    "debt_equity": (1.5, 2.5),
    "pledge_pct": (20.0, 40.0),             # promoter shares pledged, % of holding
    "cash_ta_pct": 12.0,                    # cash-rich ...
    "debt_ta_pct": 15.0,                    # ... yet heavily indebted
    # --- Cash flow (LOWER is worse for the two ratios) ---
    "cfo_pat_ratio": (0.7, 0.4),
    "cash_realization": (0.6, 0.4),         # CFO / EBITDA
    "neg_fcf_years": 3,
    # --- Models ---
    "beneish": (-2.22, -1.78),              # M-Score above => likely manipulator (conservative, 8-var)
    "sloan": (0.10, 0.25),                  # (PAT - CFO) / avg total assets
    "altman_em": (5.85, 4.35),              # Z''-EM: grey below 5.85, distress below 4.35 (LOWER worse)
    "ccc_increase_days": (15.0, 30.0),      # cash-conversion-cycle lengthening vs 3 yrs ago
}
