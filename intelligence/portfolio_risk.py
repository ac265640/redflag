"""Portfolio-level risk aggregation and heatmap data."""
from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

HEAT_COLUMNS = ["Forensic risk", "Governance", "ESG", "Credit risk", "Overall risk"]


def portfolio_table(summary: pd.DataFrame, weights: Dict[str, float]) -> pd.DataFrame:
    """Holdings with normalised weights (sum = 100%) joined to company scores."""
    w = pd.Series(weights, name="Weight").clip(lower=0)
    w = (w / w.sum() * 100).rename_axis("Ticker").reset_index() if w.sum() > 0 else pd.DataFrame(columns=["Ticker", "Weight"])
    return w.merge(summary, on="Ticker", how="left")


def weighted_scores(table: pd.DataFrame) -> Dict[str, float]:
    """Weight-averaged headline scores (companies without a score are skipped for that metric) + share in High/Critical names."""
    out: Dict[str, float] = {}
    for c in HEAT_COLUMNS:
        m = table[c].notna()
        w = table.loc[m, "Weight"]
        out[c] = float((table.loc[m, c] * w).sum() / w.sum()) if w.sum() > 0 else float("nan")
    out["Share in High/Critical"] = float(table.loc[table["Grade"].isin(["High", "Critical"]), "Weight"].sum())
    return out
