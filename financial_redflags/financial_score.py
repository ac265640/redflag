"""Aggregates all financial red flags into a 0-100 Financial Risk Score (higher = worse)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import pandas as pd

from core.constants import FINANCIAL_CATEGORIES, RedFlag, Severity, grade_from_risk, saturating_score
from financial_redflags.balance_sheet_flags import analyze_balance_sheet
from financial_redflags.cashflow_flags import analyze_cashflow
from financial_redflags.notes_flags import analyze_notes
from financial_redflags.pnl_flags import analyze_pnl
from financial_redflags.ratio_flags import analyze_ratios, compute_ratio_table

TOTAL_K = 110.0  # ~110 flag-points => score ~63. Roughly: 3 High + 4 Medium => ~50 (Medium/High boundary)
CATEGORY_K = 45.0


@dataclass
class FinancialScoreResult:
    """Output of the financial red-flag engine."""

    score: float
    grade: str
    flags: List[RedFlag]
    category_scores: Dict[str, float]
    ratio_table: pd.DataFrame
    flag_counts: Dict[str, int] = field(default_factory=dict)


def compute_financial_score(df: pd.DataFrame, notes: Dict[str, object]) -> FinancialScoreResult:
    """Run every financial test, then convert flag points to scores.

    Score = 100 * (1 - exp(-points / K)) so the 1st flags matter most and the scale saturates smoothly.
    """
    if len(df) < 3:
        raise ValueError("Need at least 3 years of financials")
    flags: List[RedFlag] = []
    flags += analyze_pnl(df)
    flags += analyze_balance_sheet(df)
    flags += analyze_cashflow(df)
    flags += analyze_ratios(df)
    flags += analyze_notes(notes, df.index[-1])
    order = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
    flags.sort(key=lambda f: order[f.severity])

    score = saturating_score(sum(f.points for f in flags), TOTAL_K)
    cats = {c: saturating_score(sum(f.points for f in flags if f.category == c), CATEGORY_K) for c in FINANCIAL_CATEGORIES}
    counts = {s.value: sum(1 for f in flags if f.severity == s) for s in Severity}
    return FinancialScoreResult(round(score, 1), grade_from_risk(score), flags, {k: round(v, 1) for k, v in cats.items()},
                                compute_ratio_table(df), counts)
