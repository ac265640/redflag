"""Auditor-related governance tests."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, Severity

CAT = "Auditor"


def analyze_auditor(b: Dict[str, object]) -> List[RedFlag]:
    """Mid-term resignation, long tenure, non-audit fee dependence."""
    a, flags = b["auditor"], []
    if a["resigned_midterm"]:
        flags.append(RedFlag("GV_AUDITOR_RESIGN", CAT, "Auditor resigned mid-term", Severity.CRITICAL, "Resignation before term end", "Any",
                             "Auditors quitting early is one of the strongest warning signs in Indian markets; it often follows disagreements over the accounts.", "Auditor resignation disclosures (SEBI circular on resignation reasons)."))
    if a["tenure_years"] > 10:
        flags.append(RedFlag("GV_AUDITOR_TENURE", CAT, "Long auditor tenure", Severity.MEDIUM, f"{a['tenure_years']:.0f} years", "> 10 years",
                             "The same audit firm has served for a long time, which can erode scepticism (statutory rotation is 10 years for firms).", "Years since first appointment."))
    if a["non_audit_fee_pct"] > 25:
        flags.append(RedFlag("GV_AUDITOR_NONAUDIT", CAT, "High non-audit fees to auditor", Severity.MEDIUM, f"{a['non_audit_fee_pct']:.0f}% of total fees", "> 25%",
                             "The auditor earns a lot from other services to the company, which can compromise independence.", "Non-audit fees / total fees paid to audit firm."))
    return flags
