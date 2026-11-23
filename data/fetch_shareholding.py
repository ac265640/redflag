"""Shareholding data.

Demo companies retain their deterministic demo data. Real companies use Yahoo's
major/institutional holder endpoints where available. Promoter ownership is not
fabricated when Yahoo does not provide it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.fetch_fundamentals import is_demo, get_financials
from data.fetch_yahoo import fetch_all


def get_shareholding(ticker: str) -> pd.DataFrame:
    if is_demo(ticker):
        f = get_financials(ticker)
        out = pd.DataFrame({"promoter_pct": f["promoter_holding_pct"], "pledged_pct_of_promoter": f["promoter_pledge_pct"]})
        out["public_pct"] = 100 - out["promoter_pct"]
        return out.round(2)

    d = fetch_all(ticker)
    major = d["major_holders"].copy()
    if major.empty:
        return pd.DataFrame(columns=["Holder metric", "Value"])
    major = major.reset_index(drop=True)
    if major.shape[1] == 2:
        major.columns = ["Value", "Holder metric"]
    else:
        major.columns = [f"Field {i+1}" for i in range(major.shape[1])]
    return major
