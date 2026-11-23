"""Early-warning engine: forward-looking alerts from trend + flag combinations."""
from __future__ import annotations

from typing import Dict, List

from core.constants import Severity
from intelligence.trend_analysis import trend_slopes


def generate_alerts(a) -> List[Dict[str, str]]:
    """Return alerts [{severity, title, message}] ordered by urgency. ``a`` is a CompanyAnalysis."""
    alerts: List[Dict[str, str]] = []
    slopes = trend_slopes(a.financial.ratio_table).set_index("Metric")
    adverse = [m for m in slopes.index if slopes.loc[m, "Direction"] == "Adverse"]
    if len(adverse) >= 4:
        alerts.append({"severity": "High", "title": "Broad deterioration in earnings-quality ratios", "message": f"{len(adverse)} of {len(slopes)} tracked ratios are trending the wrong way: {', '.join(adverse[:4])}."})
    codes = {f.code for f in a.all_flags}
    if {"BS_PLEDGE_DEBT", "CR_OUTLOOK"} <= codes:
        alerts.append({"severity": "Critical", "title": "Pledging plus negative rating outlook", "message": "Promoter share pledges and a negative credit outlook together raise the risk of a forced-selling spiral."})
    if {"CF_CFO_PAT", "BS_RECEIVABLES"} <= codes:
        alerts.append({"severity": "High", "title": "Profit growth without cash", "message": "Receivables are building while operating cash flow lags profit: classic early sign of aggressive revenue recognition."})
    if "GV_AUDITOR_RESIGN" in codes or "NT_GOING_CONCERN" in codes:
        alerts.append({"severity": "Critical", "title": "Auditor-level distress signal", "message": "An auditor resignation or going-concern note needs immediate review of the latest filings."})
    if a.credit_risk is not None and a.credit_risk >= 50:
        alerts.append({"severity": "Medium", "title": "Credit trajectory weakening", "message": "Rating history shows downgrades; watch for further action at the next review."})
    return alerts
