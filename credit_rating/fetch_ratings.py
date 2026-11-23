"""Credit-rating fetcher (PLACEHOLDER).

Real sources: agency rationale PDFs/pages (CRISIL, ICRA, CARE, India Ratings, Brickwork), the exchange 'Credit Rating'
announcements (Reg 30), and the RBI/SEBI CRA disclosures. Schema: date, agency, instrument, rating, outlook, action,
rationale, source_url (agency home pages only in demo mode, no fabricated deep links).
"""
from __future__ import annotations

import zlib
from typing import List

import numpy as np
import pandas as pd

from data.fetch_fundamentals import UNIVERSE, RISK_LEVEL

SCALE: List[str] = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "C", "D"]
AGENCIES = {"CRISIL": "https://www.crisilratings.com", "ICRA": "https://www.icra.in", "CARE": "https://www.careratings.com",
            "India Ratings": "https://www.indiaratings.co.in", "Brickwork": "https://www.brickworkratings.com"}

_STRENGTHS = ["Established market position", "Healthy liquidity", "Comfortable debt protection metrics", "Diversified customer base"]
_WEAKNESSES = ["Stretched working capital cycle", "Elevated leverage", "Weak cash accruals vs obligations", "Promoter pledge of shares",
               "Exposure to group entities", "Pressure on operating margins", "Large contingent liabilities"]


def get_rating_history(ticker: str) -> pd.DataFrame:
    """Five years of annual rating reviews per agency (newest last)."""
    s = RISK_LEVEL[UNIVERSE[ticker][2]]
    r = np.random.default_rng(zlib.crc32(("cr" + ticker).encode()))
    start = {0.0: 2, 0.5: 4, 1.0: 4}[s]
    agencies = list(r.choice(list(AGENCIES), size=2 if s < 1 else 3, replace=False))
    rows = []
    for ag in agencies:
        idx_prev = start
        for k, yr in enumerate(range(2022, 2027)):
            idx = int(round(start + s * 1.3 * k + (0.4 * k if s == 0.5 else 0)))
            idx = min(idx, len(SCALE) - 3)
            action = "Reaffirmed" if idx == idx_prev else ("Downgraded" if idx > idx_prev else "Upgraded")
            outlook = "Stable" if s == 0 else ("Negative" if action == "Downgraded" or (s == 1 and k >= 3) else ("Watch Negative" if s == 1 and k == 4 else "Stable"))
            weak = list(r.choice(_WEAKNESSES, size=int(1 + 2 * s), replace=False))
            rows.append(dict(date=pd.Timestamp(year=yr, month=int(r.integers(3, 12)), day=15), agency=ag, instrument="Long-term bank facilities",
                             rating=SCALE[idx], outlook=outlook, action=action,
                             rationale=f"Strengths: {r.choice(_STRENGTHS)}. Weaknesses: {'; '.join(weak)}.", source_url=AGENCIES[ag]))
            idx_prev = idx
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
