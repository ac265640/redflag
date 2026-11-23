"""Credit-rating risk assessment."""
from __future__ import annotations

from typing import List, Tuple

from core.constants import RedFlag, Severity, saturating_score
from credit_rating.fetch_ratings import SCALE, get_rating_history
from credit_rating.history import add_numeric, latest_by_agency, net_notch_change

CAT = "Credit Rating"
_INV_GRADE_LAST = SCALE.index("BBB-")


def assess_credit_risk(ticker: str) -> Tuple[float, List[RedFlag]]:
    """Return (credit risk 0-100, flags). Higher = worse.

    Inputs: absolute level (notch), net downgrades in 3 yrs, negative outlook / watch, below-investment-grade.
    """
    hist = add_numeric(get_rating_history(ticker))
    latest = latest_by_agency(hist)
    flags: List[RedFlag] = []
    worst = int(latest["notch"].max())
    net = net_notch_change(hist, 3)
    if worst > _INV_GRADE_LAST:
        flags.append(RedFlag("CR_SUB_IG", CAT, "Below investment grade", Severity.CRITICAL, SCALE[worst], "< BBB-",
                             "At least one agency rates the company's debt as speculative, which makes borrowing costly and raises default risk."))
    if net >= 3:
        flags.append(RedFlag("CR_DOWNGRADES", CAT, "Repeated downgrades", Severity.HIGH if net < 6 else Severity.CRITICAL, f"{net} notches in 3 yrs", ">= 3 notches",
                             "Credit agencies have repeatedly cut the rating, a trend that tends to continue until finances stabilise."))
    elif net >= 1:
        flags.append(RedFlag("CR_DOWNGRADE", CAT, "Recent downgrade", Severity.MEDIUM, f"{net} notch(es)", ">= 1",
                             "The company's credit quality has weakened over three years."))
    neg = latest[latest["outlook"].isin(["Negative", "Watch Negative"])]
    if len(neg):
        flags.append(RedFlag("CR_OUTLOOK", CAT, "Negative outlook / watch", Severity.MEDIUM, ", ".join(f"{a}: {o}" for a, o in zip(neg.agency, neg.outlook)), "Negative or Watch Negative",
                             "Agencies signal that another downgrade is more likely than not in the coming year."))
    if latest["notch"].max() - latest["notch"].min() >= 2:
        flags.append(RedFlag("CR_DIVERGENCE", CAT, "Agencies disagree", Severity.LOW, f"{SCALE[int(latest.notch.min())]} to {SCALE[worst]}", "spread >= 2 notches",
                             "Different agencies rate the same company noticeably differently; read each rationale to see why."))
    level = saturating_score(max(worst - 3, 0) * 6, 40)
    return round(min(100.0, 0.5 * level + 0.5 * saturating_score(sum(f.points for f in flags), 40)), 1), flags
