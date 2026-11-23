"""Yahoo Finance data layer.

This module is deliberately defensive: Yahoo Finance does not expose every field
for every security, so each dataset is fetched independently and missing datasets
are returned as empty DataFrames rather than breaking the dashboard.
"""
from __future__ import annotations

from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Dict
import logging
import warnings

import numpy as np
import pandas as pd
import streamlit as st

CR = 1e7

# Keep third-party deprecation chatter out of the Streamlit console. These warnings
# originate inside yfinance/pandas and do not indicate a dashboard failure.
warnings.filterwarnings("ignore", message=r".*The inplace keyword in DataFrame.*deprecated.*")
warnings.filterwarnings("ignore", message=r".*Ticker\\.earnings.*deprecated.*")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _yf(ticker: str):
    import yfinance as yf
    return yf.Ticker(ticker)


def _safe_df(fn, *args, **kwargs) -> pd.DataFrame:
    try:
        x = fn(*args, **kwargs)
        if x is None:
            return pd.DataFrame()
        if isinstance(x, pd.DataFrame):
            return x.copy()
        if isinstance(x, pd.Series):
            return x.to_frame()
        if isinstance(x, dict):
            # Dicts returned by analyst targets/calendar/fast_info become a readable two-column table.
            return pd.DataFrame(list(x.items()), columns=["Field", "Value"])
        if isinstance(x, list):
            return pd.DataFrame(x)
        return pd.DataFrame(x)
    except Exception:
        return pd.DataFrame()


def _safe_dict(fn) -> Dict[str, Any]:
    try:
        x = fn()
        return dict(x) if isinstance(x, dict) else {}
    except Exception:
        return {}


def _jsonable(v):
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(v).isoformat()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def clean_info(info: Dict[str, Any]) -> Dict[str, Any]:
    """Keep Yahoo profile data display-safe and remove huge nested objects."""
    keep = {}
    for k, v in info.items():
        if isinstance(v, (str, int, float, bool, np.integer, np.floating, pd.Timestamp, np.datetime64)) or v is None:
            keep[k] = _jsonable(v)
    return keep


def safe_profile(ticker_obj) -> Dict[str, Any]:
    """Read only Yahoo fast metadata; never fall through to slow quoteSummary info.

    Ticker.info can be unusually slow or return 404 for valid Indian listings.
    Profile enrichment is optional, so a missing result is preferable to holding
    up company navigation.
    """
    fast = _safe_dict(lambda: dict(ticker_obj.fast_info))
    return clean_info(fast) if fast else {}


def arrow_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a Streamlit/PyArrow-safe copy without changing the source data.

    Yahoo tables frequently contain mixed Python types in object columns (for
    example ``Value`` can contain both numbers and ``Yes``).  Streamlit's Arrow
    serializer expects one compatible dtype per column, so display-only tables
    convert object/mixed columns to strings while preserving numeric columns.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == "object":
            out[col] = out[col].map(lambda v: "" if pd.isna(v) else str(v))
    return out


@lru_cache(maxsize=32)
def fetch_all(ticker: str) -> Dict[str, Any]:
    """Fetch the broad Yahoo Finance dataset used by the dashboard."""
    t = _yf(ticker)
    return {
        "info": safe_profile(t),
        "history": _safe_df(t.history, period="max", auto_adjust=False),
        "financials_annual": _safe_df(lambda: t.income_stmt),
        "financials_quarterly": _safe_df(lambda: t.quarterly_income_stmt),
        "balance_annual": _safe_df(lambda: t.balance_sheet),
        "balance_quarterly": _safe_df(lambda: t.quarterly_balance_sheet),
        "cashflow_annual": _safe_df(lambda: t.cashflow),
        "cashflow_quarterly": _safe_df(lambda: t.quarterly_cashflow),
        "actions": _safe_df(lambda: t.actions),
        "dividends": _safe_df(lambda: t.dividends),
        "splits": _safe_df(lambda: t.splits),
        "major_holders": _safe_df(lambda: t.major_holders),
        "institutional_holders": _safe_df(lambda: t.institutional_holders),
        "mutualfund_holders": _safe_df(lambda: t.mutualfund_holders),
        "insider_transactions": _safe_df(lambda: t.insider_transactions),
        "insider_purchases": _safe_df(lambda: t.insider_purchases),
        "recommendations": _safe_df(lambda: t.recommendations),
        "recommendations_summary": _safe_df(lambda: t.recommendations_summary),
        "analyst_targets": _safe_df(lambda: t.analyst_price_targets),
        "earnings_dates": _safe_df(lambda: t.get_earnings_dates(limit=40)),
        "calendar": _safe_df(lambda: t.calendar),
        "sustainability": _safe_df(lambda: t.sustainability),
        "shares_full": _safe_df(lambda: t.get_shares_full(start=pd.Timestamp.now() - pd.DateOffset(years=5))),
        "valuation": _safe_df(lambda: t.valuation),
        "fast_info": _safe_df(lambda: dict(t.fast_info)),
        # Yahoo retired Ticker.earnings/get_earnings; no page depends on this legacy dataset.
        "earnings": pd.DataFrame(),
        "earnings_history": _safe_df(lambda: t.earnings_history),
        "earnings_estimate": _safe_df(lambda: t.earnings_estimate),
        "revenue_estimate": _safe_df(lambda: t.revenue_estimate),
        "growth_estimates": _safe_df(lambda: t.growth_estimates),
        "eps_trend": _safe_df(lambda: t.eps_trend),
        "eps_revisions": _safe_df(lambda: t.eps_revisions),
        "upgrades_downgrades": _safe_df(lambda: t.upgrades_downgrades),
        "insider_roster": _safe_df(lambda: t.insider_roster_holders),
        "news": _safe_df(lambda: t.get_news(count=50)),
        "sec_filings": _safe_df(lambda: t.get_sec_filings()),
    }


YAHOO_GROUP_KEYS = {
    "Profile": ("info",),
    "Price": ("history",),
    "Financials": ("financials_annual", "financials_quarterly"),
    "Balance Sheet": ("balance_annual", "balance_quarterly"),
    "Cash Flow": ("cashflow_annual", "cashflow_quarterly"),
    "Ownership": ("major_holders", "institutional_holders", "mutualfund_holders", "insider_transactions", "insider_purchases"),
    "Corporate Actions": ("actions", "dividends", "splits"),
    "Analysts": ("recommendations", "recommendations_summary", "analyst_targets", "earnings_dates", "earnings_history", "earnings_estimate", "revenue_estimate", "growth_estimates", "eps_trend", "eps_revisions", "upgrades_downgrades"),
    "ESG": ("sustainability",),
    "Other": ("valuation", "fast_info", "shares_full", "calendar", "insider_roster", "news", "sec_filings"),
}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_yahoo_group(ticker: str, group: str) -> Dict[str, Any]:
    """Fetch only one selected Yahoo dataset group for the currently open tab."""
    keys = YAHOO_GROUP_KEYS.get(group)
    if not keys:
        return {}
    t = _yf(ticker)
    loaders = {
        "info": lambda: safe_profile(t),
        "history": lambda: _safe_df(t.history, period="1y", interval="1d", auto_adjust=False, timeout=6),
        "financials_annual": lambda: _safe_df(lambda: t.income_stmt),
        "financials_quarterly": lambda: _safe_df(lambda: t.quarterly_income_stmt),
        "balance_annual": lambda: _safe_df(lambda: t.balance_sheet),
        "balance_quarterly": lambda: _safe_df(lambda: t.quarterly_balance_sheet),
        "cashflow_annual": lambda: _safe_df(lambda: t.cashflow),
        "cashflow_quarterly": lambda: _safe_df(lambda: t.quarterly_cashflow),
        "major_holders": lambda: _safe_df(lambda: t.major_holders),
        "institutional_holders": lambda: _safe_df(lambda: t.institutional_holders),
        "mutualfund_holders": lambda: _safe_df(lambda: t.mutualfund_holders),
        "insider_transactions": lambda: _safe_df(lambda: t.insider_transactions),
        "insider_purchases": lambda: _safe_df(lambda: t.insider_purchases),
        "actions": lambda: _safe_df(lambda: t.actions),
        "dividends": lambda: _safe_df(lambda: t.dividends),
        "splits": lambda: _safe_df(lambda: t.splits),
        "recommendations": lambda: _safe_df(lambda: t.recommendations),
        "recommendations_summary": lambda: _safe_df(lambda: t.recommendations_summary),
        "analyst_targets": lambda: _safe_df(lambda: t.analyst_price_targets),
        "earnings_dates": lambda: _safe_df(lambda: t.get_earnings_dates(limit=40)),
        "earnings_history": lambda: _safe_df(lambda: t.earnings_history),
        "earnings_estimate": lambda: _safe_df(lambda: t.earnings_estimate),
        "revenue_estimate": lambda: _safe_df(lambda: t.revenue_estimate),
        "growth_estimates": lambda: _safe_df(lambda: t.growth_estimates),
        "eps_trend": lambda: _safe_df(lambda: t.eps_trend),
        "eps_revisions": lambda: _safe_df(lambda: t.eps_revisions),
        "upgrades_downgrades": lambda: _safe_df(lambda: t.upgrades_downgrades),
        "sustainability": lambda: _safe_df(lambda: t.sustainability),
        "valuation": lambda: _safe_df(lambda: t.valuation),
        "fast_info": lambda: _safe_df(lambda: dict(t.fast_info)),
        "shares_full": lambda: _safe_df(lambda: t.get_shares_full(start=pd.Timestamp.now() - pd.DateOffset(years=5))),
        "calendar": lambda: _safe_df(lambda: t.calendar),
        "insider_roster": lambda: _safe_df(lambda: t.insider_roster_holders),
        "news": lambda: _safe_df(lambda: t.get_news(count=25)),
        "sec_filings": lambda: _safe_df(lambda: t.get_sec_filings()),
    }
    # Fetch only the selected category. Run its independent provider calls in
    # parallel and cap the UI wait; a slow Yahoo endpoint cannot block the page.
    output = {key: pd.DataFrame() for key in keys}
    pool = ThreadPoolExecutor(max_workers=min(6, len(keys)), thread_name_prefix="rfi-yahoo-group")
    futures = {pool.submit(loaders[key]): key for key in keys}
    try:
        done, pending = wait(futures, timeout=8)
        for future in done:
            key = futures[future]
            try:
                output[key] = future.result()
            except Exception:
                output[key] = pd.DataFrame()
        for future in pending:
            future.cancel()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return output


def refresh(ticker: str) -> None:
    """Clear this ticker from the in-process Yahoo cache."""
    fetch_all.cache_clear()
    fetch_yahoo_group.clear()


def yahoo_profile(ticker: str) -> Dict[str, Any]:
    d = fetch_all(ticker)
    return d["info"]


def yahoo_shareholding(ticker: str) -> pd.DataFrame:
    """Best-effort Yahoo holder table; no invented promoter percentages."""
    d = fetch_yahoo_group(ticker, "Ownership")
    major = d.get("major_holders", pd.DataFrame()).copy()
    if not major.empty:
        major.columns = [str(c) for c in major.columns]
        if major.shape[1] == 2:
            major = major.reset_index(drop=True)
            major.columns = ["Value", "Metric"]
    return major
