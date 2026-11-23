"""Rating history utilities."""
from __future__ import annotations

import pandas as pd

from credit_rating.fetch_ratings import SCALE


def add_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Add 'notch' column: 0 = AAA ... 17 = D (higher is worse)."""
    out = df.copy()
    out["notch"] = out["rating"].map({r: i for i, r in enumerate(SCALE)})
    return out


def latest_by_agency(df: pd.DataFrame) -> pd.DataFrame:
    """Latest review per agency."""
    return df.sort_values("date").groupby("agency").tail(1).reset_index(drop=True)


def net_notch_change(df: pd.DataFrame, years: int = 3) -> int:
    """Net notches moved (positive = downgrade) summing per-agency change over the last ``years`` years."""
    d = add_numeric(df)
    cutoff = d["date"].max() - pd.DateOffset(years=years)
    total = 0
    for _, g in d.groupby("agency"):
        g = g.sort_values("date")
        before = g[g["date"] <= cutoff]
        start = before["notch"].iloc[-1] if len(before) else g["notch"].iloc[0]
        total += int(g["notch"].iloc[-1] - start)
    return total
