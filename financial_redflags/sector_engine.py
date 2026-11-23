"""Sector-aware forensic screening for live listed-company financial statements.

The engine separates executable tests from unavailable sector KPIs and tests that
are not suitable for a business model. Missing provider fields are never imputed.
A triggered signal is a review prompt, not a finding of fraud or misconduct.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core.constants import RedFlag, Severity
from intelligence.sector_intelligence import SectorProfile, classify_company, calculate_ratio_series, ratio_rows

SEVERITY_POINTS = {Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}

FINANCIAL_SECTORS = {
    "banking", "nbfc_infra", "nbfc_lending", "insurance", "insurance_life",
    "insurance_general", "insurance_health", "brokerage", "depository", "exchange", "registrar",
}
CASH_FLOW_SECTORS = {
    "cement", "it_services", "automobile", "fmcg", "pharma", "real_estate", "utilities",
    "epc", "metals", "oil_upstream", "oil_downstream", "gas_distribution", "oil_gas",
    "telecom", "logistics", "qsr", "consumer_durables", "chemicals", "depository",
    "exchange", "brokerage", "registrar", "generic",
}
INVENTORY_SECTORS = {
    "cement", "automobile", "fmcg", "pharma", "metals", "oil_downstream", "oil_gas",
    "qsr", "consumer_durables", "chemicals",
}
WORKING_CAPITAL_SECTORS = {
    "cement", "it_services", "automobile", "fmcg", "pharma", "utilities", "epc", "metals",
    "oil_upstream", "oil_downstream", "gas_distribution", "oil_gas", "telecom", "logistics",
    "qsr", "consumer_durables", "chemicals",
}

# These are only review thresholds for a first-pass screen, not universal
# regulatory or accounting limits. Sector-specific thresholds are explicit.
NET_DEBT_EBITDA_LIMITS = {
    "cement": (4.0, 5.5), "metals": (4.0, 5.5), "utilities": (5.0, 7.0),
    "telecom": (4.5, 6.0), "epc": (3.5, 5.0), "real_estate": (4.0, 6.0),
    "automobile": (2.5, 3.5), "fmcg": (2.5, 3.5), "pharma": (3.0, 4.0),
    "it_services": (2.0, 3.0), "qsr": (3.0, 4.0), "consumer_durables": (2.5, 3.5),
    "chemicals": (3.5, 5.0), "logistics": (3.5, 5.0),
}

UNAVAILABLE_BY_SECTOR = {
    "banking": {
        "GNPA / NNPA / PCR": "Requires bank regulatory asset-quality disclosures.",
        "NIM / CASA": "Requires interest income, interest expense, average earning assets and deposit mix from bank filings.",
        "CRAR / CET1": "Requires regulatory capital and risk-weighted assets.",
        "Credit cost": "Requires loan-loss provisions and average advances on a consistent definition.",
        "ALM maturity gaps": "Requires contractual asset-liability maturity buckets.",
    },
    "nbfc_infra": {
        "GNPA / NNPA": "Requires NBFC asset-quality and provisioning disclosures.",
        "CRAR": "Requires regulatory capital and risk-weighted assets.",
        "ALM maturity gaps": "Requires asset-liability maturity buckets.",
        "Project / borrower concentration": "Requires lender portfolio and counterparty disclosures.",
    },
    "nbfc_lending": {
        "GNPA / NNPA": "Requires NBFC asset-quality and provisioning disclosures.",
        "Credit cost": "Requires impairment charge and average loan book.",
        "CRAR": "Requires regulatory capital and risk-weighted assets.",
        "Collection efficiency": "Requires collection and overdue-bucket disclosures.",
    },
    "brokerage": {
        "Active clients / client concentration": "Requires exchange and issuer client disclosures by period.",
        "AUM and wealth mix": "Requires AUM, net flows and product-mix disclosures.",
        "Broking / wealth / distribution revenue mix": "Requires segment revenue disclosures on a consistent basis.",
        "Margin funding book": "Requires funding book and collateral disclosures.",
        "Regulatory net worth / liquid capital": "Requires exchange or regulator capital disclosures.",
    },
    "depository": {
        "Beneficial owner accounts / transaction volumes": "Requires depository operating statistics.",
        "Issuer services / transaction revenue mix": "Requires segment and operating disclosures.",
    },
    "exchange": {
        "Market turnover / segment volume": "Requires exchange trading-volume and market-turnover disclosures.",
        "Regulatory capital / settlement guarantee exposure": "Requires exchange regulatory and risk disclosures.",
    },
    "registrar": {
        "Assets serviced / folios / transaction volumes": "Requires issuer operating statistics.",
        "Client concentration": "Requires client-level revenue or AUM-serviced disclosures.",
    },
    "insurance_life": {
        "Solvency ratio": "Requires regulatory available solvency margin and required solvency margin.",
        "VNB margin / APE growth": "Requires value-of-new-business and annualised-premium-equivalent disclosures.",
        "Persistency": "Requires policy persistency by cohort.",
    },
    "insurance_general": {
        "Solvency ratio": "Requires regulatory available and required solvency margin.",
        "Combined ratio / claims ratio": "Requires incurred claims, expenses and earned premium.",
    },
    "insurance_health": {
        "Solvency ratio": "Requires regulatory available and required solvency margin.",
        "Claims ratio": "Requires claims and premium disclosures.",
        "Renewal / persistency": "Requires policy renewal and persistency data.",
    },
}

@dataclass
class SectorForensicResult:
    profile: SectorProfile
    flags: list[RedFlag]
    checks: list[dict[str, Any]]
    sector_metrics: list[dict[str, Any]]
    ratio_history: pd.DataFrame
    score: float
    grade: str
    applicable_count: int
    unavailable_count: int
    not_applicable_count: int

    @property
    def triggered_count(self) -> int:
        return len(self.flags)

    @property
    def coverage_pct(self) -> float:
        total = self.applicable_count + self.unavailable_count
        return 100.0 * self.applicable_count / total if total else 0.0


def _series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], np.nan)


def _pct_growth(cur: float, prev: float) -> float:
    if not np.isfinite(cur) or not np.isfinite(prev) or prev <= 0:
        return np.nan
    return (cur / prev - 1.0) * 100.0


def _ratio(n: float, d: float) -> float:
    if not np.isfinite(n) or not np.isfinite(d) or d == 0:
        return np.nan
    return n / d


def _beneish_strict(df: pd.DataFrame) -> pd.Series:
    """Beneish eight-variable M-Score; any missing required input => NaN, never neutral-filled."""
    required = ["revenue", "receivables", "cogs", "current_assets", "ppe", "total_assets",
                "depreciation", "sga", "current_liabilities", "long_term_debt", "pat", "cfo"]
    out = pd.Series(np.nan, index=df.index, dtype=float)
    if not set(required).issubset(df.columns):
        return out
    d = df[required].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    for i in range(1, len(d)):
        c, p = d.iloc[i], d.iloc[i - 1]
        if c.isna().any() or p.isna().any():
            continue
        if min(c.revenue, p.revenue, c.total_assets, p.total_assets) <= 0:
            continue
        prior_leverage_base = (p.current_liabilities + p.long_term_debt) / p.total_assets
        if prior_leverage_base == 0:
            continue
        if c.cogs <= 0 or p.cogs <= 0 or c.depreciation + c.ppe <= 0 or p.depreciation + p.ppe <= 0 or c.depreciation == 0:
            continue
        if (1 - (c.current_assets + c.ppe) / c.total_assets) == 0 or (1 - (p.current_assets + p.ppe) / p.total_assets) == 0:
            continue
        gm_c, gm_p = (c.revenue - c.cogs) / c.revenue, (p.revenue - p.cogs) / p.revenue
        if gm_c == 0 or gm_p == 0:
            continue
        dsri = (c.receivables / c.revenue) / (p.receivables / p.revenue) if p.receivables != 0 else np.nan
        gmi = gm_p / gm_c
        aqi = (1 - (c.current_assets + c.ppe) / c.total_assets) / (1 - (p.current_assets + p.ppe) / p.total_assets)
        sgi = c.revenue / p.revenue
        depi = (p.depreciation / (p.depreciation + p.ppe)) / (c.depreciation / (c.depreciation + c.ppe))
        sgai = (c.sga / c.revenue) / (p.sga / p.revenue) if p.sga != 0 else np.nan
        lvgi = ((c.current_liabilities + c.long_term_debt) / c.total_assets) / prior_leverage_base
        tata = (c.pat - c.cfo) / c.total_assets
        vals = [dsri, gmi, aqi, sgi, depi, sgai, lvgi, tata]
        if not all(np.isfinite(v) for v in vals):
            continue
        out.iloc[i] = -4.84 + 0.920*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi + 0.115*depi - 0.172*sgai + 4.679*tata - 0.327*lvgi
    return out


def _altman_em_strict(df: pd.DataFrame) -> pd.Series:
    """Altman Z''-EM diagnostic for non-financial firms; missing inputs remain NaN."""
    out = pd.Series(np.nan, index=df.index, dtype=float)
    required = ["current_assets", "current_liabilities", "total_assets", "retained_earnings", "ebitda", "depreciation", "net_worth", "total_liabilities"]
    if not set(required).issubset(df.columns):
        return out
    d = df[required].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    for ix, row in d.iterrows():
        if row.isna().any() or row.total_assets <= 0 or row.total_liabilities <= 0:
            continue
        x1 = (row.current_assets - row.current_liabilities) / row.total_assets
        x2 = row.retained_earnings / row.total_assets
        x3 = (row.ebitda - row.depreciation) / row.total_assets
        x4 = row.net_worth / row.total_liabilities
        out.loc[ix] = 3.25 + 6.56*x1 + 3.26*x2 + 6.72*x3 + 1.05*x4
    return out


def evaluate_sector_forensics(ticker: str, profile: dict[str, Any], financials: pd.DataFrame) -> SectorForensicResult:
    """Evaluate only business-model-relevant tests with complete inputs."""
    if financials is None or financials.empty:
        raise ValueError("Sector forensic analysis requires at least one annual financial statement period.")
    df = financials.copy().sort_index()
    sector = classify_company(ticker, profile or {})
    key = sector.key
    financial_company = key in FINANCIAL_SECTORS
    checks: list[dict[str, Any]] = []
    flags: list[RedFlag] = []

    def record(code: str, title: str, category: str, status: str, metric: str, threshold: str,
               explanation: str, logic: str, severity: Severity | None = None, year: str | None = None):
        row = {"code": code, "title": title, "category": category, "status": status,
               "metric": metric or "N/A", "threshold": threshold or "—", "severity": severity.value if severity else "—",
               "explanation": explanation, "logic": logic, "year": str(year or df.index[-1])}
        checks.append(row)
        if status == "Triggered" and severity is not None:
            flags.append(RedFlag(code, category, title, severity, row["metric"], row["threshold"], explanation, logic, row["year"]))

    def add_rule(code, title, category, required, metric, threshold, explain, logic, evaluator, not_applicable_reason=None):
        if not_applicable_reason:
            record(code, title, category, "Not applicable", "—", "—", not_applicable_reason, logic)
            return
        missing = [c for c in required if c not in df.columns or _series(df, c).isna().all() or pd.isna(_series(df, c).iloc[-1])]
        if missing:
            record(code, title, category, "Unavailable", "N/A", "Required current-period inputs: " + ", ".join(missing),
                   "The source feed does not contain all required current-period fields. No value has been estimated.", logic)
            return
        status, severity, observed = evaluator()
        record(code, title, category, status, metric(observed), threshold, explain, logic, severity)

    # Universal checks with broad relevance and transparent statement inputs.
    if len(df) >= 2:
        rev, pat = _series(df, "revenue"), _series(df, "pat")
        last, prev = df.iloc[-1], df.iloc[-2]
        rev_g, pat_g = _pct_growth(float(rev.iloc[-1]), float(rev.iloc[-2])), _pct_growth(float(pat.iloc[-1]), float(pat.iloc[-2]))
    else:
        rev = _series(df, "revenue"); pat = _series(df, "pat")
        last = df.iloc[-1]; prev = None; rev_g = pat_g = np.nan

    def pat_loss():
        v = float(pat.iloc[-1])
        if v < 0: return "Triggered", Severity.HIGH, v
        return "Not triggered", None, v
    add_rule("GEN_PAT_LOSS", "Latest-year loss", "Earnings", ["pat"], lambda v: f"PAT ₹{v:,.2f} Cr", "PAT < 0", "A reported loss needs to be assessed against the company's business cycle, exceptional items and capital position.", "Latest reported PAT.", pat_loss)

    def revenue_drop():
        if not np.isfinite(rev_g): return "Unavailable", None, np.nan
        if rev_g <= -15: return "Triggered", Severity.HIGH, rev_g
        if rev_g <= -8: return "Triggered", Severity.MEDIUM, rev_g
        return "Not triggered", None, rev_g
    add_rule("GEN_REVENUE_DECLINE", "Revenue contraction", "Earnings", ["revenue"], lambda v: f"Revenue growth {v:+.1f}% YoY", "≤ -8% review; ≤ -15% high", "A material revenue decline can indicate weaker demand, lost customers or a change in business mix; compare with sector conditions.", "(Current revenue / prior-year revenue − 1) × 100.", revenue_drop,
             "At least two positive revenue periods are required." if len(df)<2 else None)

    def earnings_divergence():
        if not np.isfinite(rev_g) or not np.isfinite(pat_g): return "Unavailable", None, np.nan
        if rev_g >= 5 and pat_g <= -10: return "Triggered", Severity.HIGH, pat_g
        if rev_g >= 10 and pat_g < 0: return "Triggered", Severity.MEDIUM, pat_g
        return "Not triggered", None, pat_g
    add_rule("GEN_REVENUE_PAT_DIVERGENCE", "Profit weakening while revenue grows", "Earnings", ["revenue", "pat"], lambda v: f"Revenue {rev_g:+.1f}% vs PAT {v:+.1f}%", "Revenue ≥ +5%; PAT ≤ -10%", "Revenue is growing while reported profit is falling. Investigate margins, finance costs, one-offs and operating mix.", "Compare latest YoY revenue growth with PAT growth.", earnings_divergence,
             "At least two comparable annual periods are required." if len(df)<2 else None)

    def exception_test():
        pbt=float(_series(df,"pbt").iloc[-1]); exc=float(_series(df,"exceptional").iloc[-1])
        share=abs(exc)/abs(pbt)*100 if pbt!=0 else (100.0 if exc!=0 else 0.0)
        if share>=25: return "Triggered", Severity.HIGH, share
        if share>=10: return "Triggered", Severity.MEDIUM, share
        return "Not triggered", None, share
    add_rule("GEN_EXCEPTIONAL_ITEMS", "Material exceptional items", "Earnings", ["exceptional","pbt"], lambda v: f"Exceptional items / PBT {v:.1f}%", "≥ 10% review; ≥ 25% high", "Material exceptional items can distort the recurring earnings picture. Read the note and determine whether the item is genuinely non-recurring.", "Absolute exceptional item / absolute PBT × 100.", exception_test)

    # Financial-sector-specific checks: do not apply industrial working-capital or
    # manufacturing leverage rules to banks, lenders, insurers or market infrastructure.
    if financial_company:
        roa_series = calculate_ratio_series(df).get("roa", pd.Series(np.nan, index=df.index))
        # Return-on-equity deterioration is a broad financial-sector trend check.
        # It is not a substitute for the regulatory profitability metrics listed as unavailable.
        roe_series = calculate_ratio_series(df).get("roe", pd.Series(np.nan, index=df.index))
        def roe_deterioration():
            if len(roe_series)<2 or not np.isfinite(roe_series.iloc[-1]) or not np.isfinite(roe_series.iloc[-2]):
                return "Unavailable", None, np.nan
            current=float(roe_series.iloc[-1]); prior=float(roe_series.iloc[-2]); change=current-prior
            if current<0: return "Triggered", Severity.HIGH, change
            if change<=-10: return "Triggered", Severity.HIGH, change
            if change<=-5: return "Triggered", Severity.MEDIUM, change
            return "Not triggered", None, change
        add_rule("FI_ROE_TREND", "Return on equity deterioration", "Financial-sector checks", ["pat","net_worth"],
                 lambda v:f"ROE change {v:+.2f} pp YoY", "≤ -5 pp review; ≤ -10 pp high", 
                 "Return on equity has weakened materially. Review profitability drivers, capital changes and business mix; for insurers, also verify insurer-specific operating metrics.",
                 "PAT / average equity × 100; compare latest year with prior year.", roe_deterioration,
                 "Two periods of PAT and equity are required to calculate ROE trend." if len(df)<2 else None)

        if key in {"banking", "nbfc_infra", "nbfc_lending"}:
            def low_roa():
                v=float(roa_series.iloc[-1])
                if not np.isfinite(v): return "Unavailable", None, np.nan
                floor=0.5 if key=="banking" else 1.0
                if v<0: return "Triggered", Severity.HIGH, v
                if v<floor: return "Triggered", Severity.MEDIUM, v
                return "Not triggered", None, v
            add_rule("FI_LOW_ROA", "Low return on average assets", "Financial-sector checks", ["pat","total_assets"], lambda v: f"ROA {v:.2f}%", f"Below {0.5 if key=='banking' else 1.0:.1f}% review", "Low asset profitability can be a warning sign for a bank or lender; validate with asset quality, provisioning and business mix before concluding.", "PAT / average total assets × 100.", low_roa,
                     "Two periods of total assets are required to calculate average-asset ROA." if len(df)<2 else None)
        else:
            record("FI_ROA_NOT_APPLICABLE", "Return on average assets", "Financial-sector checks", "Not applicable", "—", "—",
                   "ROA is not used as a standalone trigger for this business model; insurer-specific operating metrics are required.", "PAT / average total assets is not an adequate standalone insurer-quality test.")

        def asset_earnings_divergence():
            asset_g=_pct_growth(float(_series(df,"total_assets").iloc[-1]),float(_series(df,"total_assets").iloc[-2]))
            if not np.isfinite(asset_g) or not np.isfinite(pat_g): return "Unavailable", None, np.nan
            if asset_g>=20 and pat_g<0: return "Triggered", Severity.HIGH, asset_g
            if asset_g>=25 and pat_g<5: return "Triggered", Severity.MEDIUM, asset_g
            return "Not triggered", None, asset_g
        add_rule("FI_ASSET_EARNINGS_DIVERGENCE", "Asset growth outpacing earnings", "Financial-sector checks", ["total_assets","pat"], lambda v: f"Assets {v:+.1f}% vs PAT {pat_g:+.1f}%", "Assets ≥ +20% with falling PAT; ≥ +25% with PAT growth < +5%", "Rapid balance-sheet expansion without a corresponding improvement in earnings deserves review of asset quality, funding and provisioning.", "Compare total-assets growth with PAT growth.", asset_earnings_divergence,
                 "At least two annual periods are required." if len(df)<2 else None)

        # Accounting manipulation / industrial distress models are deliberately
        # excluded for financial institutions unless separately validated for the
        # relevant business model and reporting data.
        record("MODEL_BENEISH_NA", "Beneish M-Score", "Models", "Not applicable", "—", "—",
               "The standard Beneish formulation is not used as a generic trigger for this financial business model. Its input ratios can be distorted by financial-institution balance sheets and income statements.",
               "Do not interpret a standard Beneish threshold as a validated banking / lending / insurance / market-infrastructure signal.")
        record("MODEL_ALTMAN_NA", "Altman Z''-EM", "Models", "Not applicable", "—", "—",
               "The Altman Z''-EM model is designed for non-financial companies and is not applied to this financial business model.",
               "Altman Z''-EM is not calculated for banks, NBFCs, insurers or market infrastructure companies.")
        record("IND_RECEIVABLES_NA", "Trade receivables vs revenue growth", "Working capital", "Not applicable", "—", "—",
               "Standardized balance-sheet receivable fields may represent loans, settlements or other financial balances rather than industrial trade debtors.",
               "Not applied to financial institutions without a validated trade-receivable definition.")
        record("IND_INVENTORY_NA", "Inventory growth test", "Working capital", "Not applicable", "—", "—",
               "An industrial inventory build-up test is not relevant to the core balance-sheet model of this financial company.",
               "Not applied to financial institutions.")
        record("IND_CCC_NA", "Industrial cash conversion cycle", "Working capital", "Not applicable", "—", "—",
               "A conventional DSO + DIO − DPO cash conversion cycle is not comparable for this financial business model.",
               "Not applied to financial institutions.")
        record("IND_NET_DEBT_NA", "Industrial net debt / EBITDA", "Leverage", "Not applicable", "—", "—",
               "Debt and liquid balances are core funding / operating balances for many financial institutions, so industrial net-debt / EBITDA thresholds are unsuitable.",
               "Not applied to financial institutions.")
        record("IND_INTEREST_COVER_NA", "Industrial interest coverage", "Leverage", "Not applicable", "—", "—",
               "Interest is an operating cost or core financial line for many financial institutions, so industrial EBIT / interest thresholds are unsuitable.",
               "Not applied to financial institutions.")

        # Operating cash flow comparisons are not used for deposit-taking banks,
        # lending NBFCs or insurers; cash-flow statement classification is different.
        if key in {"brokerage","depository","exchange","registrar"}:
            _add_cash_conversion_checks(add_rule, df)
            _add_sloan_check(record, df)
        else:
            record("FI_CFO_PAT_NA", "CFO / PAT conversion", "Financial-sector checks", "Not applicable", "—", "—",
                   "Operating cash flow / PAT is not used as a primary earnings-quality trigger for deposit-taking banks, lending NBFCs or insurers because operating cash-flow classification is not directly comparable with an industrial business.",
                   "Not applied to this financial business model.")
    elif key == "generic" or "needs analyst review" in sector.confidence.lower():
        # An unverified or diversified issuer must not inherit manufacturing rules
        # merely because provider metadata is vague. Require analyst classification.
        for code,title,category,reason in [
            ("GEN_MARGIN_NA","EBITDA margin compression","Profitability","Business model is not sufficiently classified to apply a sector-calibrated margin threshold."),
            ("GEN_RECEIVABLES_NA","Trade receivables vs revenue growth","Working capital","The balance-sheet receivable field may not represent trade debtors for an unclassified or diversified issuer."),
            ("GEN_INVENTORY_NA","Inventory growth test","Working capital","Inventory may not be a comparable operating asset until the business model is verified."),
            ("GEN_CCC_NA","Industrial cash conversion cycle","Working capital","A conventional inventory-based cash conversion cycle requires a verified operating business model."),
            ("GEN_LEVERAGE_NA","Net debt / EBITDA","Leverage","A calibrated leverage threshold is not assigned to an unclassified / diversified business model."),
            ("GEN_INTEREST_COVER_NA","Interest coverage","Leverage","A sector-appropriate interest coverage interpretation cannot be assigned until the business model is verified."),
            ("GEN_BENEISH_NA","Beneish M-Score","Models","The company classification is not sufficiently confident to apply this model as an automated trigger."),
            ("GEN_ALTMAN_NA","Altman Z''-EM","Models","The company classification is not sufficiently confident to apply this model as an automated trigger."),
        ]:
            record(code,title,category,"Not applicable","—","—",reason,"Deferred pending analyst verification of the issuer's business model.")
    else:
        # Non-financial operating-company tests.
        def margin_compression():
            e=_series(df,"ebitda")/_series(df,"revenue")*100
            if len(e)<2 or not np.isfinite(e.iloc[-1]) or not np.isfinite(e.iloc[-2]): return "Unavailable", None, np.nan
            change=float(e.iloc[-1]-e.iloc[-2])
            if change<=-10: return "Triggered", Severity.HIGH, change
            if change<=-5: return "Triggered", Severity.MEDIUM, change
            return "Not triggered", None, change
        add_rule("IND_MARGIN_COMPRESSION", "EBITDA margin compression", "Profitability", ["ebitda","revenue"], lambda v: f"Margin change {v:+.1f} pp", "≤ -5 pp review; ≤ -10 pp high", "A sharp fall in operating margin can reflect input-cost pressure, weaker pricing, poor mix or cost inefficiency. Compare with segment and peer disclosures.", "Current EBITDA margin minus prior-year EBITDA margin, in percentage points.", margin_compression,
                 "Two periods with reported revenue and EBITDA are required." if len(df)<2 else None)

        def receivable_gap():
            rg=_pct_growth(float(_series(df,"receivables").iloc[-1]),float(_series(df,"receivables").iloc[-2]))
            if not np.isfinite(rg) or not np.isfinite(rev_g): return "Unavailable", None, np.nan
            gap=rg-rev_g
            if gap>=20: return "Triggered", Severity.HIGH, gap
            if gap>=10: return "Triggered", Severity.MEDIUM, gap
            return "Not triggered", None, gap
        add_rule("IND_RECEIVABLES_GAP", "Receivables outgrowing revenue", "Working capital", ["receivables","revenue"], lambda v: f"Receivables growth gap {v:+.1f} pp", "≥ 10 pp review; ≥ 20 pp high", "Trade receivables are growing faster than revenue. Review ageing, customer concentration, credit terms and subsequent collections.", "Receivables YoY growth minus revenue YoY growth.", receivable_gap,
                 "Receivables are not treated as trade debtors for all industries; use only after business-model classification." if key in FINANCIAL_SECTORS else ("Two periods are required." if len(df)<2 else None))

        if key in INVENTORY_SECTORS:
            def inventory_gap():
                ig=_pct_growth(float(_series(df,"inventory").iloc[-1]),float(_series(df,"inventory").iloc[-2]))
                if not np.isfinite(ig) or not np.isfinite(rev_g): return "Unavailable", None, np.nan
                gap=ig-rev_g
                if gap>=20: return "Triggered", Severity.HIGH, gap
                if gap>=10: return "Triggered", Severity.MEDIUM, gap
                return "Not triggered", None, gap
            add_rule("IND_INVENTORY_GAP", "Inventory outgrowing revenue", "Working capital", ["inventory","revenue"], lambda v: f"Inventory growth gap {v:+.1f} pp", "≥ 10 pp review; ≥ 20 pp high", "Inventory is growing faster than revenue. Examine ageing, slow-moving stock, provisioning and demand assumptions.", "Inventory YoY growth minus revenue YoY growth.", inventory_gap,
                     "Two periods are required." if len(df)<2 else None)
        else:
            record("IND_INVENTORY_NA", "Inventory growth test", "Working capital", "Not applicable", "—", "—",
                   "This business model does not use an industrial inventory-growth screen by default. Apply only if inventory is a meaningful operating asset.", "Not applied to this business model.")

        _add_cash_conversion_checks(add_rule, df)

        if key in WORKING_CAPITAL_SECTORS:
            def ccc_change():
                dso=_series(df,"receivables")/_series(df,"revenue")*365
                dio=_series(df,"inventory")/_series(df,"cogs")*365
                dpo=_series(df,"payables")/_series(df,"cogs")*365
                ccc=dso+dio-dpo
                if ccc.notna().sum()<2: return "Unavailable", None, np.nan
                base=ccc.iloc[max(0,len(ccc)-4)] if len(ccc)>=4 else ccc.iloc[0]
                if not np.isfinite(base) or not np.isfinite(ccc.iloc[-1]): return "Unavailable", None, np.nan
                delta=float(ccc.iloc[-1]-base)
                if delta>=30: return "Triggered", Severity.HIGH, delta
                if delta>=15: return "Triggered", Severity.MEDIUM, delta
                return "Not triggered", None, delta
            add_rule("IND_CCC_LENGTHENING", "Cash conversion cycle lengthening", "Working capital", ["receivables","inventory","payables","revenue","cogs"], lambda v: f"CCC change {v:+.1f} days", "≥ +15 days review; ≥ +30 days high", "More cash is being tied up in the operating cycle. Confirm that receivables, inventory and payables are consistently classified.", "DSO + DIO − DPO; latest period compared with up to three years earlier.", ccc_change)
        else:
            record("IND_CCC_NA", "Industrial cash conversion cycle", "Working capital", "Not applicable", "—", "—",
                   "A conventional inventory-based cash conversion cycle is not suitable for this business model.", "Not applied to this business model.")

        if key in NET_DEBT_EBITDA_LIMITS:
            low, high=NET_DEBT_EBITDA_LIMITS[key]
            def leverage_test():
                netdebt=float(_series(df,"total_debt").iloc[-1]-_series(df,"cash").iloc[-1])
                ebitda=float(_series(df,"ebitda").iloc[-1])
                v=_ratio(netdebt,ebitda)
                if not np.isfinite(v) or ebitda<=0: return "Unavailable", None, v
                if v>=high: return "Triggered", Severity.HIGH, v
                if v>=low: return "Triggered", Severity.MEDIUM, v
                return "Not triggered", None, v
            add_rule("IND_NET_DEBT_EBITDA", "Elevated net debt / EBITDA", "Leverage", ["total_debt","cash","ebitda"], lambda v: f"Net debt / EBITDA {v:.2f}x", f"≥ {low:.1f}x review; ≥ {high:.1f}x high", "Leverage is high relative to operating earnings. Review debt maturities, interest cost, liquidity and committed capex.", "(Total debt − cash) / EBITDA; latest annual period.", leverage_test)
        else:
            record("IND_NET_DEBT_NA", "Net debt / EBITDA", "Leverage", "Not applicable", "—", "—",
                   "No calibrated leverage trigger is configured for this sector profile; do not apply a universal industrial threshold.", "Not applied to this business model.")

        def interest_cover():
            pbt=float(_series(df,"pbt").iloc[-1]); interest=float(_series(df,"interest").iloc[-1])
            other=float(_series(df,"other_income").iloc[-1])
            exceptional=float(_series(df,"exceptional").iloc[-1])
            if not all(np.isfinite(v) for v in [pbt,interest,other,exceptional]) or interest<=0: return "Unavailable", None, np.nan
            ebit=pbt+interest-other-exceptional
            v=ebit/interest
            if v<1.2: return "Triggered", Severity.HIGH, v
            if v<2.0: return "Triggered", Severity.MEDIUM, v
            return "Not triggered", None, v
        add_rule("IND_INTEREST_COVER", "Thin interest coverage", "Leverage", ["pbt","interest","other_income","exceptional"], lambda v: f"Core EBIT / interest {v:.2f}x", "< 2.0x review; < 1.2x high", "Operating earnings may not provide sufficient headroom to service interest. Reconcile finance costs and non-operating income.", "(PBT + interest − other income − exceptional items) / interest.", interest_cover)

        # M-Score and Altman are explicitly restricted to non-financial companies,
        # and are marked unavailable unless all required fields are present.
        beneish=_beneish_strict(df)
        bm=float(beneish.iloc[-1]) if len(beneish) else np.nan
        if np.isfinite(bm):
            sev=Severity.HIGH if bm>-1.78 else (Severity.MEDIUM if bm>-2.22 else None)
            record("MODEL_BENEISH", "Beneish M-Score screening", "Models", "Triggered" if sev else "Not triggered", f"M-Score {bm:.2f}", "> -2.22 watch; > -1.78 elevated", "The Beneish model flags an accounting-pattern resemblance that warrants document-level review; it is not proof of manipulation.", "Beneish (1999), eight-variable M-Score; all required inputs must be populated.", sev)
        else:
            record("MODEL_BENEISH", "Beneish M-Score screening", "Models", "Unavailable", "N/A", "All eight inputs required", "At least two comparable periods and every required model input are not available. No missing component is replaced with a neutral value.", "Beneish (1999), eight-variable M-Score.")

        altman=_altman_em_strict(df)
        az=float(altman.iloc[-1]) if len(altman) else np.nan
        if np.isfinite(az):
            sev=Severity.HIGH if az<4.35 else (Severity.MEDIUM if az<5.85 else None)
            record("MODEL_ALTMAN_EM", "Altman Z''-EM screen", "Models", "Triggered" if sev else "Not triggered", f"Z'' {az:.2f}", "< 5.85 grey; < 4.35 distress zone", "The model is a screening indicator and can be distorted by industry accounting and balance-sheet structure. Verify its assumptions before interpreting it.", "Altman Z''-EM: 3.25 + 6.56×WC/TA + 3.26×RE/TA + 6.72×EBIT/TA + 1.05×Equity/TL; EBIT approximated as EBITDA less depreciation.", sev)
        else:
            record("MODEL_ALTMAN_EM", "Altman Z''-EM screen", "Models", "Unavailable", "N/A", "Working capital, retained earnings, EBIT, equity and liabilities required", "Required inputs are incomplete or denominators are invalid; the model is not calculated.", "Altman Z''-EM; EBIT is approximated as EBITDA less depreciation; non-financial companies only.")

        # Sloan accruals: use only when CFO, PAT and average assets are all present.
        metrics=calculate_ratio_series(df)
        sloan=metrics.get("sloan_accruals",pd.Series(np.nan,index=df.index))
        sv=float(sloan.iloc[-1]) if len(sloan) else np.nan
        if np.isfinite(sv):
            sev=Severity.HIGH if sv>=25 else (Severity.MEDIUM if sv>=10 else None)
            record("MODEL_SLOAN", "High accruals (Sloan ratio)", "Models", "Triggered" if sev else "Not triggered", f"{sv:.2f}%", "≥ 10% review; ≥ 25% high", "A high share of earnings is represented by accruals rather than operating cash. Review persistence and working-capital movements.", "(PAT − CFO) / average total assets × 100.", sev)
        else:
            record("MODEL_SLOAN", "Sloan accrual ratio", "Models", "Unavailable", "N/A", "PAT, CFO and average total assets required", "The required cash-flow or balance-sheet inputs are missing; the ratio is not inferred.", "(PAT − CFO) / average total assets × 100.")

    # Sector KPI library provides explicit availability based on sector profile.
    try:
        metrics = ratio_rows(df, sector)
    except Exception:
        metrics = []
    sector_metric_rows=[]
    for item in metrics:
        vals=item.get("values")
        latest = None
        if isinstance(vals,pd.Series) and len(vals) and pd.notna(vals.iloc[-1]):
            latest=float(vals.iloc[-1])
        sector_metric_rows.append({
            "Metric": item.get("label",item.get("code","Metric")),
            "Latest value": latest if latest is not None else "N/A",
            "Status": "Available" if item.get("latest_available") else ("Partial history" if item.get("available") else "Unavailable"),
            "Definition / required source": item.get("definition",item.get("caveat","")),
            "Formula": item.get("formula","—"),
            "Code": item.get("code",""),
        })

    # Add explicit sector-specific unavailable source modules that the standardized
    # annual statement feed cannot substantiate.
    unavailable_custom=UNAVAILABLE_BY_SECTOR.get(key,{})
    for name,reason in unavailable_custom.items():
        sector_metric_rows.append({"Metric":name,"Latest value":"N/A","Status":"Unavailable","Definition / required source":reason,"Formula":"Dedicated disclosure required","Code":name.lower().replace(" ","_")})

    # Include a warning for generic or uncertain issuer mappings.
    if "review" in sector.confidence.lower() or sector.key=="generic":
        record("CLASSIFICATION_REVIEW", "Business-model classification needs review", "Data quality", "Unavailable", "Needs analyst confirmation", "Verify against latest annual report segment disclosures", "The current provider or mapping information is not sufficient to select a narrow business model confidently. Sector-specific tests are therefore restricted to broad statement checks.", sector.classification_source)

    # Score only tests actually evaluated. Unavailable and not-applicable tests do not
    # enter the denominator. The index is not a fraud probability or peer rating.
    executed=[r for r in checks if r["status"] in {"Triggered","Not triggered"}]
    total_points=sum(SEVERITY_POINTS[f.severity] for f in flags)
    score=round(100.0*total_points/(4.0*max(len(executed),1)),1) if executed else 0.0
    score=min(100.0,score)
    if any(f.severity==Severity.CRITICAL for f in flags) or sum(f.severity==Severity.HIGH for f in flags)>=3:
        grade="Critical" if any(f.severity==Severity.CRITICAL for f in flags) else "High"
    elif any(f.severity==Severity.HIGH for f in flags): grade="High"
    elif any(f.severity==Severity.MEDIUM for f in flags): grade="Medium"
    elif flags: grade="Low"
    else: grade="Low"

    ratio_series=calculate_ratio_series(df)
    history=pd.DataFrame(index=df.index)
    if ratio_series:
        for source_col,target_col in [("revenue_growth","Revenue growth (%)"),("pat_growth","PAT growth (%)"),
                                      ("ebitda_margin","EBITDA margin (%)"),("roa","ROA (%)"),("roe","ROE (%)"),
                                      ("cfo_pat","CFO / PAT (x)"),("net_debt_ebitda","Net debt / EBITDA (x)"),
                                      ("sloan_accruals","Sloan accruals (%)"),("dso","DSO"),("dio","DIO"),("dpo","DPO"),
                                      ("ccc","CCC"),("interest_coverage","Interest cover")]:
            if source_col in ratio_series:
                history[target_col]=ratio_series[source_col]
    beneish_series=_beneish_strict(df)
    altman_series=_altman_em_strict(df) if not financial_company else pd.Series(np.nan,index=df.index)
    history["Beneish M-Score"] = beneish_series
    history["Altman Z''-EM"] = altman_series
    history["CFO / PAT (x)"] = ratio_series.get("cfo_pat",pd.Series(np.nan,index=df.index))

    return SectorForensicResult(
        profile=sector, flags=flags, checks=checks, sector_metrics=sector_metric_rows,
        ratio_history=history.replace([np.inf,-np.inf],np.nan), score=score, grade=grade,
        applicable_count=len(executed), unavailable_count=sum(r["status"]=="Unavailable" for r in checks),
        not_applicable_count=sum(r["status"]=="Not applicable" for r in checks),
    )



def _add_sloan_check(record, df: pd.DataFrame) -> None:
    """Add Sloan accrual screen to capital-market service businesses where CFO/PAT is used."""
    metrics=calculate_ratio_series(df)
    series=metrics.get("sloan_accruals",pd.Series(np.nan,index=df.index))
    value=float(series.iloc[-1]) if len(series) else np.nan
    if not np.isfinite(value):
        record("MODEL_SLOAN", "Sloan accrual ratio", "Models", "Unavailable", "N/A", "PAT, CFO and average total assets required",
               "Required cash-flow or balance-sheet inputs are missing; the ratio is not inferred.", "(PAT − CFO) / average total assets × 100.")
    else:
        severity=Severity.HIGH if value>=25 else (Severity.MEDIUM if value>=10 else None)
        record("MODEL_SLOAN", "High accruals (Sloan ratio)", "Models", "Triggered" if severity else "Not triggered", f"{value:.2f}%", "≥ 10% review; ≥ 25% high",
               "A high share of earnings is represented by accruals rather than operating cash. Review persistence and working-capital movements.",
               "(PAT − CFO) / average total assets × 100.", severity)



def _add_cash_conversion_checks(add_rule, df: pd.DataFrame) -> None:
    if len(df)<2:
        add_rule("CF_CFO_PAT", "Operating cash conversion", "Cash Flow", ["cfo","pat"], lambda v:f"CFO / PAT {v:.2f}x", "< 0.7x review; < 0.4x high", "Reported profit is not translating into operating cash. Review working capital, collections and non-cash earnings.", "Sum of CFO / sum of PAT over available periods.", lambda: ("Unavailable",None,np.nan), "At least two periods are required.")
        return
    def cfo_pat_test():
        cfo=_series(df,"cfo"); pat=_series(df,"pat")
        valid=cfo.notna()&pat.notna()
        cfo_sum=float(cfo[valid].sum()); pat_sum=float(pat[valid].sum())
        if valid.sum()<2 or pat_sum<=0: return "Unavailable",None,np.nan
        v=cfo_sum/pat_sum
        if v<0.4: return "Triggered",Severity.HIGH,v
        if v<0.7: return "Triggered",Severity.MEDIUM,v
        return "Not triggered",None,v
    add_rule("CF_CFO_PAT", "Operating cash conversion", "Cash Flow", ["cfo","pat"], lambda v:f"CFO / PAT {v:.2f}x", "< 0.7x review; < 0.4x high", "Reported profit is not translating into operating cash. Review working capital, collections and non-cash earnings.", "Sum of CFO / sum of PAT over periods with both inputs available; at least two periods.", cfo_pat_test,
             "At least two periods with CFO and PAT are required." if len(df)<2 else None)

    def negative_cfo_test():
        cfo=float(_series(df,"cfo").iloc[-1]); pat=float(_series(df,"pat").iloc[-1])
        if cfo<0<pat:return "Triggered",Severity.HIGH,cfo
        return "Not triggered",None,cfo
    add_rule("CF_NEGATIVE_CFO", "Negative operating cash flow with profit", "Cash Flow", ["cfo","pat"], lambda v:f"CFO ₹{v:,.2f} Cr", "CFO < 0 while PAT > 0", "The company reports accounting profit while operating activities consume cash. Review collection timing, inventory and accrued expenses.", "Latest annual CFO < 0 and PAT > 0.", negative_cfo_test)


def as_financial_score(result: SectorForensicResult):
    """Adapt sector result to the existing score-result contract used elsewhere."""
    from financial_redflags.financial_score import FinancialScoreResult
    counts={s.value:sum(1 for f in result.flags if f.severity==s) for s in Severity}
    categories={}
    for cat in sorted({f.category for f in result.flags}):
        pts=sum(SEVERITY_POINTS[f.severity] for f in result.flags if f.category==cat)
        categories[cat]=round(100*pts/(4*max(len([r for r in result.checks if r['category']==cat and r['status'] in {'Triggered','Not triggered'}]),1)),1)
    # Keep legacy ratio column labels available to downstream modules.
    hist=result.ratio_history.copy()
    aliases={"Cash conversion cycle (days)":"CCC","CFO / PAT (x)":"CFO / PAT","Sloan accruals (%)":"Sloan accruals","Beneish M-Score":"Beneish M","Altman Z''-EM":"Altman Z (EM)"}
    for src,dst in aliases.items():
        if src in hist.columns: hist[dst]=hist[src]
    if "Interest coverage" not in hist.columns:
        hist["Interest cover"]=np.nan
    return FinancialScoreResult(result.score,result.grade,result.flags,categories,hist,counts)
