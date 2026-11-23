"""Peer benchmarking restricted to the same available business-model cohort."""
from __future__ import annotations

import pandas as pd

METRICS = {"Forensic risk": False, "Governance": True, "ESG": True, "Credit risk": False, "Overall risk": False}  # True = higher is better


def peer_percentiles(summary: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Percentile (0-100, higher = better) of ``ticker`` versus peers for each headline score."""
    company = summary.loc[summary.Ticker == ticker].iloc[0]
    profile_key = company.get("Sector profile key")
    if pd.notna(profile_key) and "Sector profile key" in summary.columns:
        peers = summary[summary["Sector profile key"] == profile_key]
        scope = f"business model: {company.get('Business model', profile_key)}"
    else:
        sector = company["Sector"]
        peers = summary[summary.Sector == sector]
        scope = f"provider sector: {sector}"
    # Never expand a live sector-aware comparison to the broad universe if the
    # like-for-like peer set is small; report the limited sample explicitly.
    rows = []
    is_live = str(company.get("Data mode", "")) == "live"
    metrics = dict(METRICS)
    if is_live and "Sector-screen index" in summary.columns:
        metrics["Sector-screen index"] = False
        metrics.pop("Forensic risk", None)
    for m, higher_better in metrics.items():
        if m not in summary.columns:
            continue
        v = summary.loc[summary.Ticker == ticker, m].iloc[0]
        if pd.isna(v):
            continue
        peer_values = pd.to_numeric(peers[m], errors="coerce").dropna()
        if peer_values.empty:
            continue
        better = (peer_values < v).mean() if higher_better else (peer_values > v).mean()
        percentile = round(better * 100, 0) if len(peer_values) >= 3 else float("nan")
        rows.append({"Metric": m, "Company": v, "Peer median": peer_values.median(), "Percentile (better = higher)": percentile, "Scope": scope, "Peers": len(peer_values)})
    return pd.DataFrame(rows)
