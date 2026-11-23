"""Fundamentals fetcher (PLACEHOLDER).

Returns synthetic but internally consistent 5-year financials for a fictional
universe so every module can be exercised end to end. Replace the body of
``get_financials`` / ``get_notes`` / ``get_profile`` with real sources later
(Screener export, XBRL from BSE/NSE, vendor API). Keep the DataFrame schema:

index  : fiscal year labels (FY2022 ... FY2026)
columns: revenue, cogs, sga, ebitda (ex other income), other_income, depreciation,
         interest, exceptional, pbt, tax, pat, receivables, inventory, payables,
         cash, current_assets, ppe, cwip, other_nca, total_assets, long_term_debt,
         short_term_debt, total_debt, current_liabilities, net_worth,
         retained_earnings, total_liabilities, contingent_liabilities, cfo, capex,
         fcf, promoter_pledge_pct, promoter_holding_pct   (₹ Cr unless a pct)
"""
from __future__ import annotations

import zlib
from typing import Dict, List

import numpy as np
import pandas as pd

from core.config import CONFIG

# ticker -> (name, sector, risk profile)
UNIVERSE: Dict[str, tuple] = {}

RISK_LEVEL = {"clean": 0.0, "stretched": 0.5, "manipulated": 1.0}

# Parameters that drive each synthetic archetype (drift = change per year)
_P = {
    "clean": dict(growth=(0.08, 0.14), gm=0.38, gm_d=0.0, sga=0.14, sga_d=0.0, dso=55, dso_d=0, dio=60, dio_d=0,
                  dpo=50, dpo_d=0, oi=0.012, oi_d=0.0, exc=0.0, dep=0.07, dep_d=0.0, tax=0.25, tax_d=0.0,
                  de=0.20, de_d=0.0, cwip=0.04, cwip_d=0.0, cont=0.06, cont_d=0.0, pledge=0, pledge_d=0,
                  hold_d=0.0, hair=0.0),
    "stretched": dict(growth=(0.05, 0.12), gm=0.30, gm_d=-0.004, sga=0.13, sga_d=0.002, dso=70, dso_d=3, dio=80,
                      dio_d=3, dpo=55, dpo_d=0, oi=0.02, oi_d=0.003, exc=0.01, dep=0.07, dep_d=-0.002, tax=0.25,
                      tax_d=0.0, de=0.70, de_d=0.10, cwip=0.08, cwip_d=0.01, cont=0.15, cont_d=0.03, pledge=5,
                      pledge_d=3, hold_d=0.3, hair=0.0),
    "manipulated": dict(growth=(0.15, 0.28), gm=0.30, gm_d=0.012, sga=0.15, sga_d=-0.010, dso=80, dso_d=12,
                        dio=75, dio_d=8, dpo=45, dpo_d=-2, oi=0.015, oi_d=0.012, exc=0.03, dep=0.07, dep_d=-0.006,
                        tax=0.22, tax_d=-0.03, de=0.90, de_d=0.25, cwip=0.12, cwip_d=0.05, cont=0.25,
                        cont_d=0.08, pledge=15, pledge_d=9, hold_d=1.5, hair=0.15),
}


def list_tickers() -> List[str]:
    """Legacy demo-universe hook. The live dashboard uses NSE/BSE listings only."""
    return []


def is_demo(ticker: str) -> bool:
    """Return True only for legacy synthetic tickers; the current dashboard exposes none."""
    return ticker in UNIVERSE


def get_profile(ticker: str) -> Dict[str, object]:
    """Company profile: synthetic for demo tickers, live (listing + Yahoo) otherwise."""
    if not is_demo(ticker):
        from data.fetch_live import get_live_profile
        return get_live_profile(ticker)
    name, sector, prof = UNIVERSE[ticker]
    rng = np.random.default_rng(zlib.crc32(("p" + ticker).encode()))
    return {
        "data_mode": "demo", "ticker": ticker, "name": name, "sector": sector, "archetype": prof,
        "risk_level": RISK_LEVEL[prof],
        "market_cap_cr": float(rng.uniform(4_000, 90_000)),
        "listed_since": int(rng.integers(1995, 2018)),
        "promoter_group": f"{name.split()[0]} Family & Associates",
        "exchange": "NSE / BSE",
    }


def get_financials(ticker: str) -> pd.DataFrame:
    """5 years of financials: synthetic for demo tickers, Yahoo Finance otherwise (schema in module docstring)."""
    if not is_demo(ticker):
        from data.fetch_live import get_live_financials
        return get_live_financials(ticker)
    prof = UNIVERSE[ticker][2]
    p = _P[prof]
    rng = np.random.default_rng(zlib.crc32(ticker.encode()))
    n = 6  # 1 base year (dropped) + 5 reported years, so YoY deltas exist for FY2022
    rev0 = rng.uniform(2_000, 40_000)
    growth = rng.uniform(*p["growth"], n)
    rev = rev0 * np.cumprod(1 + growth)

    rows: List[dict] = []
    nw_prev = rev0 * 0.6
    ppe_prev = rev[0] * 0.55
    prev = None
    for i in range(n):
        cogs = rev[i] * (1 - (p["gm"] + p["gm_d"] * i + rng.normal(0, 0.004)))
        sga = rev[i] * (p["sga"] + p["sga_d"] * i)
        ebitda = rev[i] - cogs - sga
        oi = rev[i] * max(p["oi"] + p["oi_d"] * i, 0)
        dep = ppe_prev * max(p["dep"] + p["dep_d"] * i, 0.02)
        debt = nw_prev * max(p["de"] + p["de_d"] * i, 0.0)
        interest = debt * 0.095
        exc = rev[i] * p["exc"] * (1 if rng.random() < 0.7 else 0)
        pbt = ebitda + oi - dep - interest + exc
        tax = max(pbt, 0) * max(p["tax"] + p["tax_d"] * i, 0.03)
        pat = pbt - tax
        capex = rev[i] * 0.07
        ppe = ppe_prev + capex * 0.85 - dep
        cwip = rev[i] * (p["cwip"] + p["cwip_d"] * i)
        recv = rev[i] * (p["dso"] + p["dso_d"] * i) / 365
        inv = cogs * (p["dio"] + p["dio_d"] * i) / 365
        pay = cogs * (p["dpo"] + p["dpo_d"] * i) / 365
        cash = rev[i] * (0.10 + 0.02 * p["hair"] / 0.15 if p["hair"] else 0.10)
        oca = rev[i] * 0.04
        ca = recv + inv + cash + oca
        other_nca = rev[i] * 0.10
        ta = ppe + cwip + ca + other_nca
        nw = nw_prev + pat * 0.85
        std, ltd = debt * 0.35, debt * 0.65
        cl = pay + std + rev[i] * 0.05
        d_nwc = 0.0 if prev is None else ((recv - prev["receivables"]) + (inv - prev["inventory"]) - (pay - prev["payables"]))
        cfo = (pat + dep - d_nwc) - p["hair"] * max(pat, 0)
        rows.append(dict(
            revenue=rev[i], cogs=cogs, sga=sga, ebitda=ebitda, other_income=oi, depreciation=dep,
            interest=interest, exceptional=exc, pbt=pbt, tax=tax, pat=pat, receivables=recv, inventory=inv,
            payables=pay, cash=cash, current_assets=ca, ppe=ppe, cwip=cwip, other_nca=other_nca,
            total_assets=ta, long_term_debt=ltd, short_term_debt=std, total_debt=debt, current_liabilities=cl,
            net_worth=nw, retained_earnings=nw * 0.8, total_liabilities=ta - nw,
            contingent_liabilities=nw * (p["cont"] + p["cont_d"] * i), cfo=cfo, capex=capex, fcf=cfo - capex,
            promoter_pledge_pct=max(0.0, p["pledge"] + p["pledge_d"] * i),
            promoter_holding_pct=60.0 - p["hold_d"] * i,
        ))
        prev, nw_prev, ppe_prev = rows[-1], nw, ppe
    df = pd.DataFrame(rows).iloc[1:].reset_index(drop=True)
    df.index = CONFIG.years
    return df.round(2)


_KAMS = ["Revenue recognition on long-term contracts", "Valuation of inventory", "Impairment of goodwill and investments",
         "Contingent liabilities and tax litigation", "Related party transactions and loans", "Recoverability of trade receivables",
         "Capitalisation of capital work-in-progress"]


def get_notes(ticker: str) -> Dict[str, object]:
    """Notes-to-accounts / auditor-report extracts (placeholder)."""
    prof = UNIVERSE[ticker][2]
    rng = np.random.default_rng(zlib.crc32(("n" + ticker).encode()))
    k = {"clean": 1, "stretched": 3, "manipulated": 4}[prof]
    kams = list(rng.choice(_KAMS, size=k, replace=False))
    if prof == "manipulated":
        kams.append("Recoverability of trade receivables") if "Recoverability of trade receivables" not in kams else None
    return {
        "audit_opinion": "Qualified" if (prof == "manipulated" and rng.random() < 0.5) else "Unmodified",
        "going_concern_uncertainty": prof == "manipulated" and rng.random() < 0.25,
        "kams": kams,
        "policy_changes": [] if prof == "clean" else [{
            "description": "Change in estimated useful life of plant & machinery" if prof == "manipulated"
            else "Revised revenue recognition for bundled contracts",
            "pat_impact_pct": 9.0 if prof == "manipulated" else 2.0}],
        "caro_adverse_remarks": 0 if prof == "clean" else (3 if prof == "manipulated" else 1),
        "emphasis_of_matter": prof != "clean",
    }
