"""Filings fetcher (PLACEHOLDER): board / governance / forensic inputs.

Real sources: Corporate Governance report (BSE/NSE), annual report, SEBI orders,
SAST/PIT disclosures, MCA filings. Each function documents the dict it returns so
real parsers can be dropped in without touching the analysis modules.
"""
from __future__ import annotations

import zlib
from typing import Dict

import numpy as np

from data.fetch_fundamentals import UNIVERSE, RISK_LEVEL


def _rng(ticker: str, salt: str) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32((salt + ticker).encode()))


def get_board_data(ticker: str) -> Dict[str, object]:
    """Board composition, directors, auditor, remuneration, SEBI actions, voting."""
    s = RISK_LEVEL[UNIVERSE[ticker][2]]
    r = _rng(ticker, "board")
    size = int(r.integers(7, 12))
    indep = max(2, int(round(size * (0.55 - 0.25 * s))))
    directors = []
    for i in range(size):
        is_id = i < indep
        directors.append({
            "name": f"Director {i + 1}", "type": "Independent" if is_id else ("Promoter" if i % 2 else "Executive"),
            "tenure_years": float(r.uniform(1, 8 + 7 * s)) if is_id else float(r.uniform(3, 25)),
            "listed_boards": int(r.integers(1, 4 + int(5 * s))),
            "attendance_pct": float(r.uniform(70 + 20 * (1 - s), 100)),
        })
    return {
        "board_size": size, "independent": indep, "women": int(r.integers(1 if s < 1 else 0, 3)),
        "chair_is_promoter": bool(r.random() < 0.4 + 0.5 * s), "directors": directors,
        "auditor": {"name": "Demo & Co. LLP", "tenure_years": float(r.uniform(2, 8 + 12 * s)),
                    "non_audit_fee_pct": float(r.uniform(3, 15 + 40 * s)), "resigned_midterm": bool(r.random() < 0.5 * s)},
        "remuneration": {"promoter_pay_cr": float(r.uniform(5, 30 + 40 * s)), "pay_growth_pct": float(r.uniform(5, 15 + 40 * s)),
                         "pat_growth_pct": float(r.uniform(5, 18) - 12 * s), "ratio_to_median": float(r.uniform(30, 120 + 250 * s))},
        "sebi_actions": [{"year": 2024, "type": "Adjudication order", "summary": "Delay in disclosure under LODR"}] * int(round(2 * s * r.random() * 2)),
        "voting": {"rpt_dissent_pct": float(r.uniform(1, 8 + 30 * s)), "remuneration_dissent_pct": float(r.uniform(1, 6 + 25 * s))},
    }


def get_forensic_inputs(ticker: str) -> Dict[str, float]:
    """Hidden-forensic inputs parsed from annual report notes and disclosures."""
    s = RISK_LEVEL[UNIVERSE[ticker][2]]
    r = _rng(ticker, "forensic")
    return {
        "rpt_pct_revenue": float(r.uniform(2, 10 + 35 * s)), "rpt_loans_pct_networth": float(r.uniform(0, 5 + 35 * s)),
        "royalty_pct_pat": float(r.uniform(0, 3 + 12 * s)), "subsidiaries": int(r.integers(3, 12 + int(40 * s))),
        "ownership_layers": int(r.integers(1, 3 + int(4 * s))), "cross_holdings": int(r.integers(0, 1 + int(5 * s))),
        "kmp_exits_24m": int(r.integers(0, 1 + int(4 * s * 1.5))), "insider_net_sell_pct": float(r.uniform(0, 1 + 6 * s)),
        "guarantees_pct_networth": float(r.uniform(2, 10 + 50 * s)), "spv_count": int(r.integers(0, 1 + int(6 * s))),
        "q4_sales_share_pct": float(r.uniform(24, 27 + 12 * s)), "yearend_receivable_spike_pct": float(r.uniform(0, 8 + 40 * s)),
        "dealer_inventory_days_rise": float(r.uniform(0, 5 + 30 * s)),
    }
