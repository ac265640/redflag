"""Notes-to-accounts and auditor-report red flags (text signals)."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, Severity

CAT = "Notes"

# KAM topics that historically coincide with accounting disputes
_RISKY_KAM_TERMS = ["revenue recognition", "receivable", "related party", "impairment", "contingent", "capitalisation", "going concern", "litigation"]


def analyze_notes(notes: Dict[str, object], year: str = "") -> List[RedFlag]:
    """Evaluate audit opinion, going-concern language, KAMs, policy changes and CARO remarks."""
    flags: List[RedFlag] = []

    # Audit opinion: anything other than unmodified is rare and serious.
    op = notes.get("audit_opinion", "Unmodified")
    if op != "Unmodified":
        sev = Severity.CRITICAL if op in ("Adverse", "Disclaimer") else Severity.HIGH
        flags.append(RedFlag("NT_QUALIFIED", CAT, f"{op} audit opinion", sev, op, "Opinion != Unmodified",
                             "The auditor could not give a clean sign-off on the accounts. That means at least part of the numbers may be wrong or unverifiable.",
                             "Audit opinion type from the independent auditor's report.", year))

    if notes.get("going_concern_uncertainty"):
        flags.append(RedFlag("NT_GOING_CONCERN", CAT, "Going-concern uncertainty", Severity.CRITICAL, "Material uncertainty reported", "Any",
                             "The auditor doubts the company can keep operating for the next 12 months without fresh funding or restructuring.",
                             "Material-uncertainty paragraph related to going concern.", year))

    kams = [str(k) for k in notes.get("kams", [])]
    risky = [k for k in kams if any(t in k.lower() for t in _RISKY_KAM_TERMS)]
    if len(risky) >= 3:
        flags.append(RedFlag("NT_KAMS", CAT, "Many high-risk key audit matters", Severity.MEDIUM if len(risky) == 3 else Severity.HIGH,
                             f"{len(risky)} risky KAMs", ">= 3 KAMs on revenue / receivables / related parties / impairment",
                             "The auditor flagged several areas where management judgement can easily distort profit. More judgement areas means more room for error or bias.",
                             "Keyword screen of Key Audit Matters; judgement-heavy topics are weighted as risky.", year))

    for ch in notes.get("policy_changes", []):
        impact = float(ch.get("pat_impact_pct", 0))
        flags.append(RedFlag("NT_POLICY_CHANGE", CAT, "Accounting policy / estimate change", Severity.HIGH if impact >= 5 else Severity.LOW,
                             f"{ch.get('description', 'n/a')} (PAT impact {impact:.0f}%)", "Impact >= 5% of PAT = High",
                             "The company changed how it accounts for something. If the change raises profit, it can make results look better without any real improvement.",
                             "Policy/estimate changes disclosed in notes, weighted by their effect on PAT.", year))

    caro = int(notes.get("caro_adverse_remarks", 0))
    if caro >= 2:
        flags.append(RedFlag("NT_CARO", CAT, "Adverse CARO remarks", Severity.MEDIUM, f"{caro} remarks", ">= 2",
                             "The auditor noted several lapses in basic compliance and internal controls (statutory dues, loans to related parties, etc.).",
                             "Count of adverse remarks in the Companies (Auditor's Report) Order annexure.", year))
    return flags
