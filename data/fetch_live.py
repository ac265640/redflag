"""Live company data sourced from Yahoo Finance (yfinance).

The rest of the application consumes a stable ₹ crore financial-statement schema.
Yahoo-only fields that do not exist for a security are left as NaN; they are never
filled with synthetic values.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, wait
from functools import lru_cache
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from core.config import CONFIG
from data.fetch_yahoo import fetch_all

CR = 1e7
MAX_AGE = 24 * 3600


class DataUnavailable(Exception):
    pass


def _normalize_ticker(ticker: str) -> str:
    ticker = str(ticker or "").strip().upper()
    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        return ticker
    return ticker + ".NS"


def _download_statements(ticker: str):
    """Fetch core annual statements concurrently with a hard UI wait budget.

    Each Yahoo endpoint is independent. The dashboard waits at most 10 seconds
    for this group, keeps any completed statement, and cancels unfinished work.
    Network threads may finish later, but they do not hold up the Streamlit page.
    """
    try:
        import yfinance as yf
    except ModuleNotFoundError as e:
        raise DataUnavailable(
            "The Python package 'yfinance' is not installed. "
            "Install project dependencies with: python -m pip install -r requirements.txt"
        ) from e

    normalized = _normalize_ticker(ticker)

    def fetch(attribute: str) -> pd.DataFrame:
        try:
            value = getattr(yf.Ticker(normalized), attribute)
            return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="rfi-yahoo")
    futures = {
        pool.submit(fetch, "income_stmt"): "income",
        pool.submit(fetch, "balance_sheet"): "balance",
        pool.submit(fetch, "cashflow"): "cashflow",
    }
    try:
        done, pending = wait(futures, timeout=10)
        outputs = {"income": pd.DataFrame(), "balance": pd.DataFrame(), "cashflow": pd.DataFrame()}
        for future in done:
            try:
                outputs[futures[future]] = future.result()
            except Exception:
                pass
        for future in pending:
            future.cancel()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    inc, bs, cf = outputs["income"], outputs["balance"], outputs["cashflow"]
    if inc.empty and bs.empty and cf.empty:
        raise DataUnavailable(
            "Yahoo Finance did not return annual statements within 10 seconds. "
            "Retry later or use the last saved local financial cache."
        )
    return inc, bs, cf


def _fy_label(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"FY{ts.year if ts.month <= 3 else ts.year + 1}"


def statements_to_frame(inc: pd.DataFrame, bs: pd.DataFrame, cf: pd.DataFrame) -> pd.DataFrame:
    cols = sorted(set(inc.columns if not inc.empty else []) | set(bs.columns if not bs.empty else []) | set(cf.columns if not cf.empty else []), reverse=True)
    if not cols:
        raise DataUnavailable("Yahoo Finance returned no annual financial statements for this security.")

    def g(df, *labels, scale=CR):
        for l in labels:
            if df is not None and not df.empty and l in df.index:
                return pd.to_numeric(df.loc[l].reindex(cols), errors="coerce") / scale
        return pd.Series(np.nan, index=cols, dtype=float)

    d = pd.DataFrame(index=cols)
    d["revenue"] = g(inc, "Total Revenue", "Operating Revenue")
    d["cogs"] = g(inc, "Cost Of Revenue")
    d["sga"] = g(inc, "Selling General And Administration")
    d["other_income"] = g(inc, "Other Income Expense", "Other Non Operating Income Expenses").fillna(0)
    d["depreciation"] = g(inc, "Reconciled Depreciation").fillna(g(cf, "Depreciation And Amortization", "Depreciation Amortization Depletion")).fillna(0)
    d["interest"] = g(inc, "Interest Expense").abs().fillna(0)
    d["exceptional"] = g(inc, "Special Income Charges").fillna(0)
    d["pbt"] = g(inc, "Pretax Income")
    d["tax"] = g(inc, "Tax Provision").fillna(0)
    d["pat"] = g(inc, "Net Income", "Net Income Common Stockholders")
    d["ebitda"] = g(inc, "EBITDA").fillna(d["pbt"] + d["interest"] + d["depreciation"] - d["other_income"] - d["exceptional"])
    d["receivables"] = g(bs, "Accounts Receivable", "Receivables")
    d["inventory"] = g(bs, "Inventory")
    d["payables"] = g(bs, "Accounts Payable", "Payables")
    d["cash"] = g(bs, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
    d["current_assets"] = g(bs, "Current Assets")
    d["ppe"] = g(bs, "Net PPE")
    d["cwip"] = g(bs, "Construction In Progress").fillna(0)
    d["total_assets"] = g(bs, "Total Assets")
    d["other_nca"] = d["total_assets"] - d["ppe"].fillna(0) - d["cwip"] - d["current_assets"].fillna(0)
    d["long_term_debt"] = g(bs, "Long Term Debt").fillna(0)
    d["short_term_debt"] = g(bs, "Current Debt").fillna(0)
    d["total_debt"] = g(bs, "Total Debt").fillna(d["long_term_debt"] + d["short_term_debt"])
    d["current_liabilities"] = g(bs, "Current Liabilities")
    d["net_worth"] = g(bs, "Stockholders Equity", "Common Stock Equity")
    d["retained_earnings"] = g(bs, "Retained Earnings")
    d["total_liabilities"] = g(bs, "Total Liabilities Net Minority Interest").fillna(d["total_assets"] - d["net_worth"])
    d["cfo"] = g(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    d["capex"] = g(cf, "Capital Expenditure").abs().fillna(0)
    d["fcf"] = d["cfo"] - d["capex"]
    d["contingent_liabilities"] = np.nan
    d["promoter_pledge_pct"] = np.nan
    d["promoter_holding_pct"] = np.nan
    d = d.dropna(subset=["revenue", "total_assets"])
    if len(d) < 2:
        raise DataUnavailable("Yahoo Finance has insufficient annual statements for this security.")
    d.index = [_fy_label(c) for c in d.index]
    d = d[~d.index.duplicated(keep="first")]
    return d.sort_index().round(2)


def _read_financial_cache(path: Path, ticker: str, *, stale: bool = False) -> pd.DataFrame:
    cached = pd.read_csv(path, index_col=0)
    if cached.empty:
        return cached
    label = "stale local cache" if stale else "local cache"
    cached.attrs["source"] = f"Yahoo Finance annual statements ({label})"
    cached.attrs["normalization"] = "Missing source fields preserved as N/A; ₹ crore"
    cached.attrs["retrieved_at"] = pd.Timestamp(path.stat().st_mtime, unit="s", tz="Asia/Kolkata")
    cached.attrs["cache_status"] = "stale" if stale else "fresh"
    return cached


def get_live_financials(ticker: str, force_refresh: bool = False) -> pd.DataFrame:
    """Legacy scoring frame; local data is returned immediately, even when stale.

    This stale-first policy prevents a temporary provider delay from blocking
    company search. Users can force a refresh from the Company Overview page.
    """
    CONFIG.cache_dir.mkdir(parents=True, exist_ok=True)
    ticker = _normalize_ticker(ticker)
    path = CONFIG.cache_dir / f"fin_{ticker}.csv"
    if path.exists() and not force_refresh:
        try:
            age = time.time() - path.stat().st_mtime
            return _read_financial_cache(path, ticker, stale=age >= MAX_AGE)
        except Exception:
            pass
    try:
        inc, bs, cf = _download_statements(ticker)
        df = statements_to_frame(inc, bs, cf)
        tmp = path.with_suffix(path.suffix + ".tmp")
        df.to_csv(tmp)
        tmp.replace(path)
        df.attrs["cache_status"] = "fresh"
        return df
    except DataUnavailable as e:
        if path.exists():
            try:
                return _read_financial_cache(path, ticker, stale=True)
            except Exception:
                pass
        raise e
    except Exception as e:
        if path.exists():
            try:
                return _read_financial_cache(path, ticker, stale=True)
            except Exception:
                pass
        raise DataUnavailable(
            f"Could not retrieve annual statements ({type(e).__name__}). "
            "No substitute values were inserted."
        ) from e


@lru_cache(maxsize=1)
def _names() -> Dict[str, tuple]:
    """Read only the local company-list cache; never make network calls here."""
    path = CONFIG.cache_dir / "listed_companies.csv"
    if not path.exists():
        return {}
    try:
        listing = pd.read_csv(path, dtype=str).fillna("")
        return {
            str(row.get("key", "")).upper(): (str(row.get("name") or row.get("key") or ""), str(row.get("exchange") or "NSE/BSE"))
            for row in listing.to_dict(orient="records")
            if row.get("key")
        }
    except Exception:
        return {}


@lru_cache(maxsize=256)
def _get_live_profile_cached(ticker: str) -> Dict[str, object]:
    """Return instant identity metadata from the local NSE/BSE directory.

    Price, market cap and other live profile fields are intentionally fetched by
    their own market-data view. A profile endpoint must never delay opening a
    company workspace or become a hidden dependency for report/company-name lookup.
    """
    name, exch = _names().get(ticker, (ticker, "NSE/BSE"))
    return {
        "ticker": ticker,
        "name": str(name or ticker),
        "sector": "Unknown",
        "industry": "Unknown",
        "archetype": "listed_company",
        "risk_level": np.nan,
        "market_cap_cr": np.nan,
        "listed_since": None,
        "promoter_group": "Not available from local exchange directory",
        "exchange": exch,
        "data_mode": "local_listing",
        "currency": "INR",
        "website": "",
        "employees": None,
        "profile_source": "Local NSE/BSE company directory",
    }


def get_live_profile(ticker: str) -> Dict[str, object]:
    """Return a cached profile copy so callers cannot mutate shared metadata."""
    return dict(_get_live_profile_cached(str(ticker).strip().upper()))


def clear_live_profile_cache() -> None:
    _get_live_profile_cached.cache_clear()
    _names.cache_clear()


def _source_preserving_statement_frame(inc: pd.DataFrame, bs: pd.DataFrame, cf: pd.DataFrame) -> pd.DataFrame:
    """Normalize annual statements while preserving every unavailable line as NaN.

    Unlike the legacy scoring schema, this function never converts missing
    interest, depreciation, debt, capex or other-income fields to zero.
    It is intended for transparent Company Overview ratios and peer comparisons.
    """
    cols = sorted(
        set(inc.columns if inc is not None and not inc.empty else [])
        | set(bs.columns if bs is not None and not bs.empty else [])
        | set(cf.columns if cf is not None and not cf.empty else []),
        reverse=True,
    )
    if not cols:
        raise DataUnavailable("The provider returned no annual financial statements.")

    def get_row(frame: pd.DataFrame, *labels: str) -> pd.Series:
        if frame is None or frame.empty:
            return pd.Series(np.nan, index=cols, dtype=float)
        for label in labels:
            if label in frame.index:
                value = frame.loc[label]
                if isinstance(value, pd.DataFrame):
                    value = value.iloc[0]
                return pd.to_numeric(value.reindex(cols), errors="coerce") / CR
        return pd.Series(np.nan, index=cols, dtype=float)

    out = pd.DataFrame(index=cols)
    out["revenue"] = get_row(inc, "Total Revenue", "Operating Revenue")
    out["cogs"] = get_row(inc, "Cost Of Revenue")
    out["sga"] = get_row(inc, "Selling General And Administration", "Selling General Administrative")
    out["other_income"] = get_row(inc, "Other Income Expense", "Other Non Operating Income Expenses")
    out["depreciation"] = get_row(inc, "Reconciled Depreciation").combine_first(
        get_row(cf, "Depreciation And Amortization", "Depreciation Amortization Depletion")
    ).abs()
    out["interest"] = get_row(inc, "Interest Expense").abs()
    out["exceptional"] = get_row(inc, "Special Income Charges")
    out["pbt"] = get_row(inc, "Pretax Income", "Income Before Tax")
    out["tax"] = get_row(inc, "Tax Provision")
    out["pat"] = get_row(inc, "Net Income", "Net Income Common Stockholders")
    published_ebitda = get_row(inc, "EBITDA")
    derived_ebitda = out["pbt"] + out["interest"] + out["depreciation"] - out["other_income"] - out["exceptional"]
    out["ebitda"] = published_ebitda.combine_first(derived_ebitda)
    out["receivables"] = get_row(bs, "Accounts Receivable", "Receivables", "Net Receivables")
    out["inventory"] = get_row(bs, "Inventory")
    out["payables"] = get_row(bs, "Accounts Payable", "Payables")
    out["cash"] = get_row(bs, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents")
    out["current_assets"] = get_row(bs, "Current Assets")
    out["ppe"] = get_row(bs, "Net PPE", "Property Plant And Equipment Net")
    out["cwip"] = get_row(bs, "Construction In Progress", "Properties Under Construction")
    out["total_assets"] = get_row(bs, "Total Assets")
    out["long_term_debt"] = get_row(bs, "Long Term Debt", "Long Term Debt And Capital Lease Obligation")
    out["short_term_debt"] = get_row(bs, "Current Debt", "Short Term Debt")
    reported_debt = get_row(bs, "Total Debt")
    component_debt = out["long_term_debt"] + out["short_term_debt"]
    complete_components = out["long_term_debt"].notna() & out["short_term_debt"].notna()
    out["total_debt"] = reported_debt.combine_first(component_debt.where(complete_components))
    out["current_liabilities"] = get_row(bs, "Current Liabilities")
    out["net_worth"] = get_row(bs, "Stockholders Equity", "Common Stock Equity", "Total Stockholder Equity")
    out["retained_earnings"] = get_row(bs, "Retained Earnings")
    reported_liabilities = get_row(bs, "Total Liabilities Net Minority Interest", "Total Liabilities")
    out["total_liabilities"] = reported_liabilities.combine_first(out["total_assets"] - out["net_worth"])
    out["other_nca"] = out["total_assets"] - out["ppe"] - out["cwip"] - out["current_assets"]
    out["cfo"] = get_row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
    out["capex"] = get_row(cf, "Capital Expenditure", "Capital Expenditures").abs()
    out["fcf"] = out["cfo"] - out["capex"]
    out["contingent_liabilities"] = pd.Series(np.nan, index=cols, dtype=float)
    out["promoter_pledge_pct"] = pd.Series(np.nan, index=cols, dtype=float)
    out["promoter_holding_pct"] = pd.Series(np.nan, index=cols, dtype=float)

    out = out.dropna(subset=["revenue"])
    if out.empty:
        raise DataUnavailable("No annual period with reported revenue was returned by the provider.")
    out.index = [_fy_label(c) for c in out.index]
    out = out[~out.index.duplicated(keep="first")].sort_index()
    out.attrs["source"] = "Yahoo Finance annual income statement, balance sheet and cash-flow statement"
    out.attrs["normalization"] = "Missing source fields preserved as N/A; amounts normalized to ₹ crore"
    return out.round(4)


def get_source_preserving_financials(ticker: str, force_refresh: bool = False) -> pd.DataFrame:
    """Return source-preserving annual statements with stale-first cache semantics.

    A local cache is returned immediately for normal page navigation, even when
    older than MAX_AGE. ``force_refresh=True`` is reserved for an explicit user
    refresh action. On a failed refresh, the last known data remains available
    and is clearly tagged stale.
    """
    CONFIG.cache_dir.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_ticker(ticker)
    path = CONFIG.cache_dir / f"source_fin_{normalized}.csv"
    if path.exists() and not force_refresh:
        try:
            age = time.time() - path.stat().st_mtime
            cached = pd.read_csv(path, index_col=0)
            if not cached.empty:
                stale = age >= MAX_AGE
                cached.attrs["source"] = (
                    "Yahoo Finance annual statements (stale local cache)"
                    if stale else "Yahoo Finance annual statements (local cache)"
                )
                cached.attrs["normalization"] = "Missing source fields preserved as N/A; ₹ crore"
                cached.attrs["retrieved_at"] = pd.Timestamp(path.stat().st_mtime, unit="s", tz="Asia/Kolkata")
                cached.attrs["cache_status"] = "stale" if stale else "fresh"
                return cached
        except Exception:
            pass
    try:
        inc, bs, cf = _download_statements(normalized)
        frame = _source_preserving_statement_frame(inc, bs, cf)
        tmp = path.with_suffix(path.suffix + ".tmp")
        frame.to_csv(tmp)
        tmp.replace(path)
        frame.attrs["retrieved_at"] = pd.Timestamp(path.stat().st_mtime, unit="s", tz="Asia/Kolkata")
        frame.attrs["cache_status"] = "fresh"
        return frame.copy()
    except DataUnavailable:
        if path.exists():
            try:
                cached = pd.read_csv(path, index_col=0)
                if not cached.empty:
                    cached.attrs["source"] = "Yahoo Finance annual statements (stale local cache; refresh failed)"
                    cached.attrs["normalization"] = "Missing source fields preserved as N/A; ₹ crore"
                    cached.attrs["retrieved_at"] = pd.Timestamp(path.stat().st_mtime, unit="s", tz="Asia/Kolkata")
                    cached.attrs["cache_status"] = "stale"
                    return cached
            except Exception:
                pass
        raise
    except Exception as exc:
        if path.exists():
            try:
                cached = pd.read_csv(path, index_col=0)
                if not cached.empty:
                    cached.attrs["source"] = "Yahoo Finance annual statements (stale local cache; refresh failed)"
                    cached.attrs["normalization"] = "Missing source fields preserved as N/A; ₹ crore"
                    cached.attrs["retrieved_at"] = pd.Timestamp(path.stat().st_mtime, unit="s", tz="Asia/Kolkata")
                    cached.attrs["cache_status"] = "stale"
                    return cached
            except Exception:
                pass
        raise DataUnavailable(
            f"Could not retrieve annual statements ({type(exc).__name__}). "
            "No substitute values were inserted."
        ) from exc

