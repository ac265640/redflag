"""Trend analysis on forensic ratios."""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

# metric -> True if a rising trend is bad
_RISING_BAD = {"DSO": True, "DIO": True, "CCC": True, "Beneish M": True, "Sloan accruals": True, "CFO / PAT": False, "Altman Z (EM)": False, "Interest cover": False}


def trend_slopes(ratio_table: pd.DataFrame) -> pd.DataFrame:
    """Linear slope per year for each tracked ratio and whether the direction is adverse."""
    rows = []
    for m, rising_bad in _RISING_BAD.items():
        s = ratio_table[m].dropna()
        if len(s) < 3:
            continue
        slope = float(np.polyfit(np.arange(len(s)), s.values, 1)[0])
        rows.append({"Metric": m, "Slope / yr": round(slope, 2), "Latest": round(float(s.iloc[-1]), 2),
                     "Direction": "Adverse" if (slope > 0) == rising_bad and abs(slope) > 1e-6 else "Favourable"})
    return pd.DataFrame(rows)
