"""Company analysis orchestration for demo and live listed-company workflows.

The demo path retains the legacy multi-module composite score. The live path uses
source-preserving financial statements and a sector-aware financial screening
index only. Governance, ESG, credit and regulatory layers are not silently
assumed to be complete when their source feeds are unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from core.constants import (FORENSIC_WEIGHTS, GRADE_BANDS, OVERALL_WEIGHTS, RedFlag, Severity, grade_from_risk, saturating_score)
from credit_rating.rating_risk import assess_credit_risk
from data.fetch_fundamentals import get_financials, get_notes, get_profile, is_demo, list_tickers
from data.fetch_filings import get_board_data, get_forensic_inputs
from esg.esg_score import ESGResult, compute_esg
from financial_redflags.financial_score import FinancialScoreResult, compute_financial_score
from forensic_hidden.channel_stuffing import analyze_channel_stuffing
from forensic_hidden.management_behaviour import analyze_management
from forensic_hidden.off_balance_sheet import analyze_off_balance_sheet
from forensic_hidden.ownership_structure import analyze_ownership
from forensic_hidden.related_parties import analyze_related_parties
from governance.auditor import analyze_auditor
from governance.board import analyze_board
from governance.directors import analyze_directors
from governance.remuneration import analyze_remuneration
from governance.sebi_actions import analyze_sebi_actions
from governance.voting import analyze_voting

HIDDEN_K, GOV_K = 70.0, 60.0
_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


@dataclass
class CompanyAnalysis:
    """Everything the UI needs for one company."""

    ticker: str
    profile: Dict[str, object]
    financials: pd.DataFrame
    financial: FinancialScoreResult
    hidden_flags: List[RedFlag]
    governance_flags: List[RedFlag]
    credit_flags: List[RedFlag]
    esg: Optional[ESGResult]
    board: Optional[Dict[str, object]]
    forensic_score: float
    hidden_score: Optional[float]
    governance_score: Optional[float]
    credit_risk: Optional[float]
    overall_risk: float
    grade: str
    explanations: List[str] = field(default_factory=list)
    data_mode: str = "demo"          # 'demo' (synthetic, all modules) or 'live' (real statements only)
    warnings: List[str] = field(default_factory=list)
    sector_forensic: Optional[object] = None

    @property
    def name(self) -> str:
        return str(self.profile["name"])

    @property
    def esg_score(self) -> Optional[float]:
        return self.esg.total if self.esg else None

    @property
    def all_flags(self) -> List[RedFlag]:
        fl = self.financial.flags + self.hidden_flags + self.governance_flags + self.credit_flags
        return sorted(fl, key=lambda f: _ORDER[f.severity])

    def count(self, sev: Severity) -> int:
        return sum(1 for f in self.all_flags if f.severity == sev)


def explain(a: CompanyAnalysis) -> List[str]:
    """Plain-English narrative: headline, top drivers, and what is going well."""
    head = {
        "Low": "Few warning signs. Reported numbers, governance and credit profile look consistent.",
        "Medium": "Some warning signs worth monitoring. Nothing alarming alone, but several items together deserve a closer look.",
        "High": "Multiple red flags across the numbers and governance. Treat reported profit with caution and dig into the details below.",
        "Critical": "Serious, overlapping red flags. Earnings quality, governance and credit signals all point to elevated risk of surprises.",
    }[a.grade]
    if a.data_mode == "live":
        live_head = {
            "Low": "No high-priority signal was triggered by the sector-appropriate statement checks that could be executed. Unavailable tests still need review.",
            "Medium": "One or more medium-priority sector-aware financial signals need follow-up against the original statements and disclosures.",
            "High": "One or more high-priority sector-aware financial signals need detailed investigation; this is not a conclusion of misconduct.",
            "Critical": "At least one critical sector-aware financial signal needs immediate source-level investigation; this is not a conclusion of misconduct.",
        }[a.financial.grade]
        out = [live_head]
        out.append("This is a sector-aware financial-statement screening index, not a fraud probability or a complete assessment of governance, ESG, credit or regulatory risk.")
        if a.sector_forensic is not None:
            out.append(f"Business model: {a.sector_forensic.profile.business_model}. Classification: {a.sector_forensic.profile.confidence}.")
    else:
        out = [head]
    for f in a.all_flags[:3]:
        out.append(f"{f.title}: {f.explanation}")
    good = []
    if not any(f.category == "Notes" and f.severity in (Severity.HIGH, Severity.CRITICAL) for f in a.financial.flags):
        good.append("the auditor's report has no serious issues")
    if a.esg_score is not None and a.esg_score >= 65:
        good.append("ESG disclosures are strong")
    if a.credit_risk is not None and not a.credit_flags:
        good.append("credit ratings are stable")
    if good:
        out.append("In its favour: " + ", ".join(good) + ".")
    return out


def _apply_floor(a: CompanyAnalysis) -> None:
    """Stacked critical flags override a benign blended average."""
    crit = a.count(Severity.CRITICAL)
    floor = "Critical" if crit >= 3 else ("High" if crit >= 2 else None)
    names = [b[1] for b in GRADE_BANDS]
    if floor and names.index(floor) > names.index(a.grade):
        a.grade = floor


def _analyze_live(ticker: str) -> CompanyAnalysis:
    """Live company path: source-preserving statements + sector-aware screening.

    Regulatory, operating and hidden-forensic signals are not inferred from generic
    statement fields. Unsupported checks remain explicitly unavailable/not applicable.
    """
    from data.fetch_live import get_source_preserving_financials
    from financial_redflags.sector_engine import evaluate_sector_forensics, as_financial_score

    profile = get_profile(ticker)
    fin = get_source_preserving_financials(ticker)
    sector_result = evaluate_sector_forensics(ticker, profile, fin)
    financial = as_financial_score(sector_result)
    coverage_note = (
        f"Sector profile: {sector_result.profile.label} / {sector_result.profile.business_model}. "
        f"{sector_result.applicable_count} tests executed; {sector_result.unavailable_count} unavailable items; "
        f"{sector_result.not_applicable_count} not-applicable checks."
    )
    warnings = [
        "Live financial statements use the source-preserving Yahoo Finance normalization. Missing statement fields are not filled with zero or estimates.",
        f"{len(fin)} annual statement periods available ({fin.index[0]} to {fin.index[-1]}). Verify the reporting basis and original annual report before relying on a signal.",
        coverage_note,
        "Sector-specific regulatory and operating metrics are shown as unavailable until the relevant official filing data is retrieved and validated.",
    ]
    a = CompanyAnalysis(
        ticker, profile, fin, financial, [], [], [], None, None,
        financial.score, None, None, None, float("nan"), financial.grade,
        data_mode="live", warnings=warnings, sector_forensic=sector_result,
    )
    _apply_floor(a)
    a.explanations = explain(a)
    return a


def analyze_company(ticker: str) -> CompanyAnalysis:
    """Run the full pipeline for one ticker (demo = all modules, live = financial statements only)."""
    if not is_demo(ticker):
        return _analyze_live(ticker)
    profile = get_profile(ticker)
    fin = get_financials(ticker)
    financial = compute_financial_score(fin, get_notes(ticker))

    inp = get_forensic_inputs(ticker)
    hidden = (analyze_related_parties(inp) + analyze_ownership(inp) + analyze_management(inp)
              + analyze_off_balance_sheet(inp) + analyze_channel_stuffing(inp))
    board = get_board_data(ticker)
    gov = (analyze_board(board) + analyze_directors(board) + analyze_auditor(board) + analyze_remuneration(board)
           + analyze_sebi_actions(board) + analyze_voting(board))
    credit_risk, credit_flags = assess_credit_risk(ticker)
    esg = compute_esg(ticker, str(profile["sector"]))

    hidden_score = saturating_score(sum(f.points for f in hidden), HIDDEN_K)
    forensic = FORENSIC_WEIGHTS["financial"] * financial.score + FORENSIC_WEIGHTS["hidden"] * hidden_score
    gov_score = 100 - saturating_score(sum(f.points for f in gov), GOV_K)
    w = OVERALL_WEIGHTS
    overall = w["forensic"] * forensic + w["governance"] * (100 - gov_score) + w["esg"] * (100 - esg.total) + w["credit"] * credit_risk
    grade = grade_from_risk(overall)

    a = CompanyAnalysis(ticker, profile, fin, financial, hidden, gov, credit_flags, esg, board, round(forensic, 1), round(hidden_score, 1),
                        round(gov_score, 1), credit_risk, round(overall, 1), grade)
    _apply_floor(a)
    a.explanations = explain(a)
    return a


def analyze_universe() -> List[CompanyAnalysis]:
    """Analyze every ticker in the universe (cache this in the UI layer)."""
    return [analyze_company(t) for t in list_tickers()]


def summary_row(a: CompanyAnalysis) -> Dict[str, object]:
    """One flat row per company (NaN where a module has no data)."""
    nan = lambda v: np.nan if v is None else v
    sector_profile = getattr(a, "sector_forensic", None)
    return {"Ticker": a.ticker, "Company": a.name, "Sector": a.profile["sector"],
            "Business model": sector_profile.profile.business_model if sector_profile is not None else "Demo / composite model",
            "Sector profile key": sector_profile.profile.key if sector_profile is not None else None,
            "Sector-screen index": a.financial.score if a.data_mode == "live" else np.nan,
            "Data mode": a.data_mode,
            "Market cap (₹ Cr)": a.profile["market_cap_cr"],
            "Forensic risk": a.forensic_score, "Governance": nan(a.governance_score), "ESG": nan(a.esg_score), "Credit risk": nan(a.credit_risk),
            "Overall risk": a.overall_risk, "Grade": a.grade, "Critical": a.count(Severity.CRITICAL), "High": a.count(Severity.HIGH),
            "Flags": len(a.all_flags), "Data": a.data_mode}


def summary_frame(analyses: List[CompanyAnalysis]) -> pd.DataFrame:
    """One row per company for tables, heatmaps and peer ranking."""
    return pd.DataFrame([summary_row(a) for a in analyses])
