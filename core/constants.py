"""Shared constants and primitives: palette, severities, the RedFlag model and helpers.

Every analysis module (financial, forensic, governance, credit) emits ``RedFlag``
objects so the scoring engine and the UI can treat them uniformly.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

# --------------------------------------------------------------------------- #
# Design tokens (Institutional Premium palette)
# --------------------------------------------------------------------------- #
COLORS = {
    "bg": "#07111D",
    "bg_secondary": "#0B1928",
    "card": "#0E2031",
    "border": "#2A4054",
    "text": "#EDF4F8",
    "text_secondary": "#A5B6C4",
    "blue": "#55A9CB",
    "green": "#45C49A",
    "amber": "#E8B65A",
    "red": "#E47E83",
}


class Severity(str, Enum):
    """Severity of a single red flag."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


# Points each flag adds to a risk pool (see scoring: saturating transform).
SEVERITY_POINTS = {
    Severity.LOW: 3.0,
    Severity.MEDIUM: 8.0,
    Severity.HIGH: 15.0,
    Severity.CRITICAL: 25.0,
}

SEVERITY_COLORS = {
    Severity.LOW: COLORS["blue"],
    Severity.MEDIUM: COLORS["amber"],
    Severity.HIGH: COLORS["red"],
    Severity.CRITICAL: "#B3001B",
}

# Overall risk index (0-100, higher = worse) -> grade
GRADE_BANDS = [(25.0, "Low"), (45.0, "Medium"), (65.0, "High"), (101.0, "Critical")]
GRADE_COLORS = {
    "Low": COLORS["green"],
    "Medium": COLORS["amber"],
    "High": COLORS["red"],
    "Critical": "#C45461",
}

# Weights for the overall risk index. Each input is expressed as "risk" (0-100, higher = worse).
OVERALL_WEIGHTS = {"forensic": 0.45, "governance": 0.25, "esg": 0.15, "credit": 0.15}
# Forensic score = financial red flags + hidden forensic flags
FORENSIC_WEIGHTS = {"financial": 0.65, "hidden": 0.35}

FINANCIAL_CATEGORIES = ["P&L", "Balance Sheet", "Cash Flow", "Ratios", "Notes"]


# --------------------------------------------------------------------------- #
# RedFlag model
# --------------------------------------------------------------------------- #
@dataclass
class RedFlag:
    """A single detected risk signal with plain-English explainability."""

    code: str
    category: str
    title: str
    severity: Severity
    metric: str            # observed value, formatted for display
    threshold: str         # rule that triggered it, formatted for display
    explanation: str       # plain-English "why this matters"
    logic: str = ""        # the financial logic behind the test
    year: Optional[str] = None

    @property
    def points(self) -> float:
        return SEVERITY_POINTS[self.severity]


def flag_if(sev: Optional[Severity], **kwargs) -> Optional[RedFlag]:
    """Build a RedFlag only when ``sev`` is not None (keeps rule code declarative)."""
    return RedFlag(severity=sev, **kwargs) if sev is not None else None


# --------------------------------------------------------------------------- #
# Numeric helpers
# --------------------------------------------------------------------------- #
def safe_div(a: float, b: float, default: float = np.nan) -> float:
    """a / b that returns ``default`` for zero / NaN denominators."""
    try:
        if b is None or b == 0 or np.isnan(b):
            return default
        return float(a) / float(b)
    except (TypeError, ValueError):
        return default


def pct_growth(cur: float, prev: float) -> float:
    """Percentage growth cur vs prev (NaN if prev <= 0)."""
    return safe_div(cur - prev, prev) * 100 if prev and prev > 0 else np.nan


def sev_high(value: float, med: float, high: float, crit: Optional[float] = None) -> Optional[Severity]:
    """Severity when a HIGHER value is worse."""
    if value is None or np.isnan(value):
        return None
    if crit is not None and value >= crit:
        return Severity.CRITICAL
    if value >= high:
        return Severity.HIGH
    if value >= med:
        return Severity.MEDIUM
    return None


def sev_low(value: float, med: float, high: float, crit: Optional[float] = None) -> Optional[Severity]:
    """Severity when a LOWER value is worse (med > high > crit)."""
    if value is None or np.isnan(value):
        return None
    if crit is not None and value <= crit:
        return Severity.CRITICAL
    if value <= high:
        return Severity.HIGH
    if value <= med:
        return Severity.MEDIUM
    return None


def saturating_score(points: float, k: float) -> float:
    """Map unbounded risk points to 0-100 with diminishing returns: 100*(1-exp(-p/k)).

    Why: ten medium flags are worse than one, but the score should not blow past 100
    and the 1st flag should matter more than the 20th.
    """
    return float(100.0 * (1.0 - np.exp(-max(points, 0.0) / k)))


def grade_from_risk(risk: float) -> str:
    """Convert a 0-100 risk index to Low / Medium / High / Critical."""
    for upper, label in GRADE_BANDS:
        if risk < upper:
            return label
    return "Critical"


def fmt(x: float, nd: int = 1, suffix: str = "") -> str:
    """Format a number for display; '–' for NaN."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:,.{nd}f}{suffix}"
