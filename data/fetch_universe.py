"""Universe of listed companies: every NSE and BSE equity, plus the demo companies.

Sources (downloaded once, cached in data/cache/listed_companies.csv for 7 days):
  * NSE  : https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
  * BSE  : api.bseindia.com ListofScripData (active equity scrips)
If a download is blocked, save NSE's EQUITY_L.csv manually into data/cache/ and it will be used instead.

Key format used everywhere in the app (also the Yahoo Finance ticker):
  NSE symbol -> "RELIANCE.NS"      BSE-only scrip -> "500325.BO"      demo company -> "AARAV"
"""
from __future__ import annotations

import io
import time
from typing import Dict, Optional, Tuple

import pandas as pd
import requests

from core.config import CONFIG
from data.fetch_fundamentals import UNIVERSE

NSE_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CACHE_FILE = CONFIG.cache_dir / "listed_companies.csv"
MANUAL_NSE = CONFIG.cache_dir / "EQUITY_L.csv"
MAX_AGE_SECONDS = 7 * 24 * 3600
COLS = ["key", "symbol", "name", "exchange", "isin", "is_demo"]


def _demo_rows() -> pd.DataFrame:
    return pd.DataFrame([{"key": t, "symbol": t, "name": v[0], "exchange": "Demo", "isin": "", "is_demo": True} for t, v in UNIVERSE.items()])


def _parse_nse(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip().upper() for c in df.columns]
    out = pd.DataFrame({"symbol": df["SYMBOL"].astype(str).str.strip(), "name": df["NAME OF COMPANY"].astype(str).str.strip(),
                        "isin": df.get("ISIN NUMBER", "").astype(str).str.strip()})
    out["key"] = out["symbol"] + ".NS"
    out["exchange"], out["is_demo"] = "NSE", False
    return out[COLS]


def _g(rec: Dict[str, object], *names: str) -> str:
    low = {k.lower(): v for k, v in rec.items()}
    for n in names:
        v = low.get(n.lower())
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _fetch_nse() -> pd.DataFrame:
    r = requests.get(NSE_URL, headers={"User-Agent": _UA, "Referer": "https://www.nseindia.com/"}, timeout=25)
    r.raise_for_status()
    return _parse_nse(r.text)


def _fetch_bse() -> pd.DataFrame:
    r = requests.get(BSE_URL, headers={"User-Agent": _UA, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}, timeout=40)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    rows = []
    for rec in data:
        code = _g(rec, "SCRIP_CD")
        if not code:
            continue
        rows.append({"key": f"{code}.BO", "symbol": _g(rec, "scrip_id") or code, "name": _g(rec, "Scrip_Name", "Issuer_Name") or code,
                     "isin": _g(rec, "ISIN_NUMBER"), "exchange": "BSE", "is_demo": False})
    return pd.DataFrame(rows, columns=COLS)


def _finalize(real: pd.DataFrame) -> pd.DataFrame:
    df = real.sort_values("name").drop_duplicates("key")
    df["label"] = df.apply(lambda r: f"{r['name']} · {r['symbol']} · {'demo' if r['is_demo'] else r['exchange']}", axis=1)
    return df


def build_listing(refresh: bool = False) -> Tuple[pd.DataFrame, str]:
    """Return (listing DataFrame, human-readable source note). Never raises."""
    CONFIG.cache_dir.mkdir(parents=True, exist_ok=True)
    if CACHE_FILE.exists() and not refresh and time.time() - CACHE_FILE.stat().st_mtime < MAX_AGE_SECONDS:
        real = pd.read_csv(CACHE_FILE, dtype=str).fillna("")
        real["is_demo"] = False
        return _finalize(real[COLS]), "NSE + BSE (cached)"

    errors, nse, bse = [], None, None
    try:
        nse = _fetch_nse()
    except Exception as e:  # network blocked, format changed, ...
        errors.append(f"NSE: {type(e).__name__}")
        if MANUAL_NSE.exists():
            try:
                nse = _parse_nse(MANUAL_NSE.read_text(encoding="utf-8", errors="ignore"))
                errors[-1] += " (using manual EQUITY_L.csv)"
            except Exception:
                pass
    try:
        bse = _fetch_bse()
    except Exception as e:
        errors.append(f"BSE: {type(e).__name__}")

    parts = [d for d in (nse, bse) if d is not None and len(d)]
    if not parts:
        if CACHE_FILE.exists():  # stale cache beats nothing
            real = pd.read_csv(CACHE_FILE, dtype=str).fillna("")
            real["is_demo"] = False
            return _finalize(real[COLS]), "NSE + BSE (stale cache; refresh failed)"
        return _finalize(pd.DataFrame(columns=COLS)), "Demo companies only. Could not download listings (" + "; ".join(errors) + ")"

    if nse is not None and bse is not None:  # one row per company: NSE preferred, BSE kept only if not on NSE
        both = set(nse["isin"]) & set(bse["isin"]) - {""}
        nse.loc[nse["isin"].isin(both), "exchange"] = "NSE, BSE"
        bse = bse[~bse["isin"].isin(set(nse["isin"]) - {""})]
    real = pd.concat(parts if nse is None or bse is None else [nse, bse], ignore_index=True)
    real.drop(columns=[], errors="ignore").to_csv(CACHE_FILE, index=False)
    note = ("NSE + BSE" if nse is not None and bse is not None else ("NSE only" if nse is not None else "BSE only"))
    return _finalize(real), note + (f" · partial ({'; '.join(errors)})" if errors else "")
