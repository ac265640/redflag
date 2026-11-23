"""Director-level tests: independent director tenure, overboarding, attendance."""
from __future__ import annotations

from typing import Dict, List

from core.constants import RedFlag, Severity

CAT = "Directors"


def analyze_directors(b: Dict[str, object]) -> List[RedFlag]:
    """ID tenure > 10 yrs, directorships beyond the SEBI cap (7 listed boards), poor attendance."""
    flags: List[RedFlag] = []
    ds = b["directors"]
    long_ids = [d for d in ds if d["type"] == "Independent" and d["tenure_years"] > 10]
    if long_ids:
        flags.append(RedFlag("GV_ID_TENURE", CAT, "Long-tenured independent directors", Severity.MEDIUM if len(long_ids) == 1 else Severity.HIGH,
                             f"{len(long_ids)} ID(s) > 10 yrs", "ID tenure > 10 years",
                             "Independent directors who stay for very long can become too close to management, which weakens their independence.",
                             "Tenure of independent directors (law caps IDs at two 5-year terms)."))
    over = [d for d in ds if d["listed_boards"] > 7]
    if over:
        flags.append(RedFlag("GV_OVERBOARD", CAT, "Overboarded directors", Severity.HIGH, f"{len(over)} director(s) on > 7 listed boards", "> 7 listed boards",
                             "Directors with too many board seats cannot give each company enough time.", "Listed-company directorships per director."))
    low_att = [d for d in ds if d["attendance_pct"] < 75]
    if low_att:
        flags.append(RedFlag("GV_ATTENDANCE", CAT, "Poor board attendance", Severity.LOW, f"{len(low_att)} director(s) < 75%", "< 75%",
                             "Some directors attend fewer than three in four meetings, so oversight is thinner than it looks.", "Attendance % per director."))
    return flags
