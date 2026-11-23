"""Model-based tests: Beneish M-Score, Sloan accruals, Altman Z (EM), working-capital cycle."""
from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from core.config import THRESHOLDS as T
from core.constants import RedFlag, Severity, flag_if, safe_div, sev_high, sev_low

CAT = "Ratios"


def compute_beneish(df: pd.DataFrame) -> pd.DataFrame:
    """Beneish eight-variable M-Score; never replace missing inputs with neutral values.

    A year receives an M-Score only when all required current/prior inputs are
    available and the relevant denominators are valid. Partial data remains NaN.
    The model is a screening indicator for non-financial companies, not proof.
    """
    columns = ["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI", "TATA", "M_Score"]
    result = pd.DataFrame(np.nan, index=df.index, columns=columns, dtype=float)
    required = ["revenue", "receivables", "cogs", "current_assets", "ppe", "total_assets",
                "depreciation", "sga", "current_liabilities", "long_term_debt", "pat", "cfo"]
    if not set(required).issubset(df.columns):
        return result
    d = df[required].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    for i in range(1, len(d)):
        c, p = d.iloc[i], d.iloc[i - 1]
        if c.isna().any() or p.isna().any():
            continue
        if min(c.revenue, p.revenue, c.total_assets, p.total_assets) <= 0:
            continue
        gm_c = (c.revenue - c.cogs) / c.revenue
        gm_p = (p.revenue - p.cogs) / p.revenue
        asset_quality_c = 1 - (c.current_assets + c.ppe) / c.total_assets
        asset_quality_p = 1 - (p.current_assets + p.ppe) / p.total_assets
        dep_denom_c, dep_denom_p = c.depreciation + c.ppe, p.depreciation + p.ppe
        lev_p = (p.current_liabilities + p.long_term_debt) / p.total_assets
        if gm_c == 0 or gm_p == 0 or asset_quality_c == 0 or asset_quality_p == 0 or dep_denom_c <= 0 or dep_denom_p <= 0 or lev_p == 0 or p.receivables == 0 or p.sga == 0:
            continue
        values = {
            "DSRI": (c.receivables / c.revenue) / (p.receivables / p.revenue),
            "GMI": gm_p / gm_c,
            "AQI": asset_quality_c / asset_quality_p,
            "SGI": c.revenue / p.revenue,
            "DEPI": (p.depreciation / dep_denom_p) / (c.depreciation / dep_denom_c),
            "SGAI": (c.sga / c.revenue) / (p.sga / p.revenue),
            "LVGI": ((c.current_liabilities + c.long_term_debt) / c.total_assets) / lev_p,
            "TATA": (c.pat - c.cfo) / c.total_assets,
        }
        if not all(np.isfinite(v) for v in values.values()):
            continue
        m = (-4.84 + 0.920 * values["DSRI"] + 0.528 * values["GMI"] + 0.404 * values["AQI"]
             + 0.892 * values["SGI"] + 0.115 * values["DEPI"] - 0.172 * values["SGAI"]
             + 4.679 * values["TATA"] - 0.327 * values["LVGI"])
        for name, value in values.items():
            result.loc[df.index[i], name] = value
        result.loc[df.index[i], "M_Score"] = m
    return result


def compute_sloan(df: pd.DataFrame) -> pd.Series:
    """Sloan accrual ratio = (PAT - CFO) / average total assets.

    High positive values mean earnings are driven by accruals (non-cash) rather than cash, and Sloan (1996)
    showed such earnings are less persistent.
    """
    avg_ta = (df["total_assets"] + df["total_assets"].shift(1)) / 2
    return ((df["pat"] - df["cfo"]) / avg_ta).dropna()


def compute_altman_em(df: pd.DataFrame) -> pd.Series:
    """Altman Z''-score for emerging markets: 3.25 + 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4.

    X1 working capital / TA, X2 retained earnings / TA, X3 EBIT / TA, X4 book equity / total liabilities.
    Zones: > 5.85 safe, 4.35-5.85 grey, < 4.35 distress. Non-financial companies only.
    """
    ebit = df["pbt"] + df["interest"]
    x1 = (df["current_assets"] - df["current_liabilities"]) / df["total_assets"]
    x2 = df["retained_earnings"] / df["total_assets"]
    x3 = ebit / df["total_assets"]
    x4 = df["net_worth"] / df["total_liabilities"]
    return 3.25 + 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4


def compute_working_capital(df: pd.DataFrame) -> pd.DataFrame:
    """DSO, DIO, DPO and Cash Conversion Cycle (days).

    DSO = receivables / revenue * 365; DIO = inventory / COGS * 365; DPO = payables / COGS * 365;
    CCC = DSO + DIO - DPO. A lengthening CCC means more cash is locked in operations.
    """
    out = pd.DataFrame(index=df.index)
    out["DSO"] = df["receivables"] / df["revenue"] * 365
    out["DIO"] = df["inventory"] / df["cogs"] * 365
    out["DPO"] = df["payables"] / df["cogs"] * 365
    out["CCC"] = out["DSO"] + out["DIO"] - out["DPO"]
    return out


def compute_ratio_table(df: pd.DataFrame) -> pd.DataFrame:
    """Per-year analytics table used by the UI and trend analysis."""
    t = compute_working_capital(df)
    t["Beneish M"] = compute_beneish(df)["M_Score"]
    t["Sloan accruals"] = compute_sloan(df)
    t["Altman Z (EM)"] = compute_altman_em(df)
    t["CFO / PAT"] = df["cfo"] / df["pat"]
    t["Interest cover"] = (df["pbt"] + df["interest"] - df["other_income"]) / df["interest"]
    return t.round(2)


def analyze_ratios(df: pd.DataFrame) -> List[RedFlag]:
    """Flags from the model-based tests."""
    y = df.index[-1]
    items: List[RedFlag | None] = []

    m = compute_beneish(df)["M_Score"].iloc[-1]
    if pd.notna(m):
        items.append(flag_if(
            sev_high(float(m), *T["beneish"]), code="RT_BENEISH", category=CAT, title="Beneish M-Score signals manipulation risk", metric=f"M = {m:.2f}",
            threshold=f"> {T['beneish'][1]} (high) / > {T['beneish'][0]} (watch)",
            explanation="A statistical model built on eight accounting ratios says this company's numbers resemble patterns associated with earnings manipulation in the model's development sample. "
                        "It is a prompt to investigate, not proof.", logic=compute_beneish.__doc__.split("\n")[0], year=y))

    s = compute_sloan(df).iloc[-1]
    items.append(flag_if(
        sev_high(s, *T["sloan"]), code="RT_SLOAN", category=CAT, title="High accruals (Sloan ratio)", metric=f"{s:.2f}", threshold=f"> {T['sloan'][0]:.2f}",
        explanation="A large share of earnings is accounting accruals rather than cash. Such earnings tend to fade in later years.", logic="(PAT - CFO) / average total assets.", year=y))

    z = compute_altman_em(df).iloc[-1]
    sev = sev_low(z, T["altman_em"][0], T["altman_em"][1])
    if sev == Severity.HIGH:
        sev = Severity.CRITICAL
    items.append(flag_if(
        sev, code="RT_ALTMAN", category=CAT, title="Altman Z-score distress zone" if sev == Severity.CRITICAL else "Altman Z-score in grey zone",
        metric=f"Z'' = {z:.2f}", threshold=f"< {T['altman_em'][0]} grey / < {T['altman_em'][1]} distress",
        explanation="The bankruptcy-prediction score is below the safe level. Liquidity, retained profits, earnings and equity cushion together look weak.",
        logic=compute_altman_em.__doc__.split("\n")[0], year=y))

    wc = compute_working_capital(df)
    inc = wc["CCC"].iloc[-1] - wc["CCC"].iloc[max(-4, -len(wc))]  # vs 3 years ago (or earliest year available)
    items.append(flag_if(
        sev_high(inc, *T["ccc_increase_days"]), code="RT_CCC", category=CAT, title="Working-capital cycle lengthening",
        metric=f"CCC {wc['CCC'].iloc[-1]:.0f} days (+{inc:.0f} vs 3 yrs ago)", threshold=f"> +{T['ccc_increase_days'][0]:.0f} days",
        explanation="It now takes noticeably longer to turn spending on inventory into collected cash. More money is locked in day-to-day operations, "
                    "which strains funding.", logic="CCC = DSO + DIO - DPO; compare latest with three years earlier.", year=y))
    return [f for f in items if f]
