"""Lightweight, cached Indian market and company-news data helpers.

Market quotes are the latest values returned by Yahoo Finance and may be delayed.
News items retain their publisher, timestamp and original URL. No synthetic values
or generated news summaries are returned by this module.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st

INDEX_MAP = {
    "NIFTY 50": "^NSEI",
    "BANK NIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    "INDIA VIX": "^INDIAVIX",
}
PERIODS = {
    "1D": ("1d", "5m"),
    "1W": ("5d", "15m"),
    "1M": ("1mo", "1d"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"),
    "1Y": ("1y", "1d"),
}


def _normalise_history(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["Close"])
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    if "Close" not in frame.columns:
        return pd.DataFrame(columns=["Close"])
    out = frame[["Close"]].copy()
    out["Close"] = pd.to_numeric(out["Close"], errors="coerce")
    out = out.dropna(subset=["Close"])
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_convert("Asia/Kolkata").tz_localize(None)
    return out[~out.index.duplicated(keep="last")].sort_index()


@st.cache_data(ttl=180, show_spinner=False)
def get_index_history(index_name: str, period_label: str = "1M") -> pd.DataFrame:
    """Fetch one index chart series; empty DataFrame means source unavailable."""
    symbol = INDEX_MAP.get(index_name)
    period, interval = PERIODS.get(period_label, PERIODS["1M"])
    if not symbol:
        return pd.DataFrame(columns=["Close"])
    try:
        import yfinance as yf
        raw = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False, actions=False, timeout=5)
        result = _normalise_history(raw)
        if result.empty and period_label in {"1D", "1W"}:
            raw = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False, actions=False, timeout=5)
            result = _normalise_history(raw)
        return result
    except Exception:
        return pd.DataFrame(columns=["Close"])


@st.cache_data(ttl=300, show_spinner=False)
def get_market_snapshot() -> pd.DataFrame:
    """Latest index closes from Yahoo, with a bounded first-load wait.

    All four instruments are requested concurrently. A provider stall cannot
    keep the Welcome page waiting indefinitely; missing rows remain unavailable.
    """
    def fetch_one(name: str, symbol: str) -> dict[str, Any] | None:
        try:
            import yfinance as yf
            hist = _normalise_history(yf.Ticker(symbol).history(
                period="5d", interval="1d", auto_adjust=False, actions=False, timeout=5
            ))
            if hist.empty:
                return None
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else None
            change = last - prev if prev is not None else None
            pct = (change / prev * 100.0) if prev not in (None, 0) else None
            return {"Index": name, "Value": last, "Change": change, "Change %": pct,
                    "As of": hist.index[-1].strftime("%d %b %Y")}
        except Exception:
            return None

    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rfi-market")
    futures = [pool.submit(fetch_one, name, symbol) for name, symbol in INDEX_MAP.items()]
    rows: list[dict[str, Any]] = []
    try:
        done, pending = wait(futures, timeout=7)
        for future in done:
            try:
                row = future.result()
                if row:
                    rows.append(row)
            except Exception:
                continue
        for future in pending:
            future.cancel()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    order = {name: i for i, name in enumerate(INDEX_MAP)}
    rows.sort(key=lambda row: order.get(row["Index"], 99))
    return pd.DataFrame(rows, columns=["Index", "Value", "Change", "Change %", "As of"])


def _parse_yahoo_item(item: dict[str, Any]) -> dict[str, Any] | None:
    content = item.get("content") if isinstance(item.get("content"), dict) else item
    title = str(content.get("title") or "").strip()
    if not title:
        return None
    canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
    url = canonical.get("url") if isinstance(canonical, dict) else canonical
    provider = content.get("provider") or {}
    publisher = provider.get("displayName") if isinstance(provider, dict) else str(provider or "Yahoo Finance")
    pub = content.get("pubDate") or content.get("providerPublishTime")
    published = ""
    try:
        if isinstance(pub, (int, float)):
            published = datetime.fromtimestamp(pub, timezone.utc).astimezone().strftime("%d %b %Y, %I:%M %p")
        elif pub:
            published = parsedate_to_datetime(str(pub)).astimezone().strftime("%d %b %Y, %I:%M %p")
    except Exception:
        published = str(pub or "")
    summary = str(content.get("summary") or content.get("description") or "").strip()
    return {"title": title, "publisher": str(publisher or "Yahoo Finance"), "published": published,
            "summary": summary, "url": str(url or "")}


def _google_news_rss(company_name: str) -> list[dict[str, Any]]:
    query = quote_plus(f'"{company_name}" India company')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ResearchDashboard/1.0)"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = []
        for node in root.findall(".//item")[:12]:
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            source = node.find("source")
            publisher = (source.text or "Google News") if source is not None else "Google News"
            pubdate = node.findtext("pubDate") or ""
            try:
                published = parsedate_to_datetime(pubdate).astimezone().strftime("%d %b %Y, %I:%M %p")
            except Exception:
                published = pubdate
            if title and link:
                items.append({"title": title, "publisher": publisher, "published": published,
                              "summary": "", "url": link})
        return items
    except Exception:
        return []


def _impact_label(title: str, summary: str) -> tuple[str, str]:
    text = f"{title} {summary}".lower()
    negative = ("fraud", "default", "downgrade", "resign", "probe", "penalty", "fine", "regulatory action",
                "insolvency", "bankruptcy", "loss widens", "plant shutdown", "fire at", "accounting irregular")
    positive = ("upgrade", "order win", "contract win", "capacity expansion", "profit rises", "record profit",
                "dividend", "buyback", "debt repaid", "fundraise", "approval for")
    if any(k in text for k in negative):
        return "Negative watch", "Potential risk indicator; verify the underlying filing and financial impact."
    if any(k in text for k in positive):
        return "Potentially positive", "Potential business or financial support; assess execution and valuation impact."
    return "Needs review", "No reliable directional impact can be inferred from the headline alone."


@st.cache_data(ttl=900, show_spinner=False)
def get_company_news(ticker: str, company_name: str, limit: int = 12) -> pd.DataFrame:
    """Fetch company-specific news from Yahoo Finance and Google News RSS."""
    items: list[dict[str, Any]] = []
    try:
        import yfinance as yf
        search = yf.Search(f'"{company_name}"', news_count=max(8, limit), lists=False)
        raw_news = getattr(search, "news", None) or []
        for raw in raw_news:
            parsed = _parse_yahoo_item(raw)
            if parsed:
                items.append(parsed)
    except Exception:
        pass
    # RSS is a fallback and a second independent discovery source.
    items.extend(_google_news_rss(company_name))
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    generic = {"limited", "ltd", "india", "company", "corporation", "corporate", "industries",
               "industry", "private", "public", "bank", "group", "holdings", "services", "the"}
    name_tokens = [x for x in re.findall(r"[A-Za-z0-9]+", company_name.lower())
                   if len(x) > 2 and x not in generic]
    ticker_token = re.sub(r"[^A-Za-z0-9]", "", str(ticker).split(".")[0].lower())
    if len(ticker_token) > 2:
        name_tokens.append(ticker_token)
    current_year = pd.Timestamp.now(tz="Asia/Kolkata").year
    for item in items:
        # Current calendar-year only; undated articles are excluded.
        published_dt = pd.to_datetime(item.get("published"), errors="coerce", utc=True)
        if pd.isna(published_dt) or int(published_dt.year) != current_year:
            continue
        key = re.sub(r"\W+", "", item["title"].lower())
        if not key or key in seen or not item.get("url", "").startswith("http"):
            continue
        # Search providers already search the quoted issuer name; reject obvious unrelated results.
        title_low = item["title"].lower()
        if name_tokens and not any(token in title_low or token in str(item.get("summary", "")).lower()
                                    for token in name_tokens):
            continue
        seen.add(key)
        label, explanation = _impact_label(item["title"], item.get("summary", ""))
        item["impact"] = label
        item["impact_note"] = explanation
        clean.append(item)
        if len(clean) >= limit:
            break
    return pd.DataFrame(clean, columns=["title", "publisher", "published", "summary", "url", "impact", "impact_note"])


@st.cache_data(ttl=900, show_spinner=False)
def get_market_news(limit: int = 5) -> pd.DataFrame:
    """Current-year Indian market headlines with publisher, date and source URL."""
    query = quote_plus('(Nifty OR Sensex OR Indian stock market OR RBI) India')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 ResearchDashboard/1.0"}, timeout=8)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception:
        return pd.DataFrame(columns=["title", "publisher", "published", "url"])
    year = pd.Timestamp.now(tz="Asia/Kolkata").year
    rows, seen = [], set()
    for node in root.findall(".//item"):
        title=(node.findtext("title") or "").strip(); link=(node.findtext("link") or "").strip()
        raw=node.findtext("pubDate") or ""; src=node.find("source")
        publisher=(src.text or "Google News") if src is not None else "Google News"
        try:
            dt=parsedate_to_datetime(raw)
            if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
            dt=dt.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata"))
        except Exception: continue
        key=re.sub(r"\W+","",title.lower())
        if not title or not link.startswith("http") or dt.year != year or key in seen: continue
        seen.add(key); rows.append({"title":title,"publisher":publisher,"published":dt.strftime("%d %b %Y, %I:%M %p"),"url":link})
        if len(rows)>=max(1,min(int(limit),10)): break
    return pd.DataFrame(rows,columns=["title","publisher","published","url"])


# ---------------------------------------------------------------------------
# Welcome-page market intelligence. All functions return empty/N/A on failure;
# no sample figures are ever substituted for missing exchange/provider data.
# ---------------------------------------------------------------------------

NSE_HOME = "https://www.nseindia.com"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    "X-Requested-With": "XMLHttpRequest",
}


def _nse_prime_page(path: str) -> str:
    """Use the relevant NSE section page to establish cookies before its API."""
    p = str(path or "").lower()
    if "integrated-filing" in p or "governance" in p:
        return "https://www.nseindia.com/companies-listing/corporate-integrated-filing?integratedType=integratedfilinggovernance"
    if "share-holdings" in p or "shareholding" in p:
        return "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
    if "bussiness-sustainabilitiy" in p or "brsr" in p:
        return "https://www.nseindia.com/companies-listing/corporate-filings-bussiness-sustainabilitiy-reports"
    if "annual-report" in p:
        return "https://www.nseindia.com/companies-listing/corporate-filings-annual-reports"
    return "https://www.nseindia.com/companies-listing/corporate-filings-announcements"


def _nse_json(path: str, params: dict[str, str] | None = None) -> Any:
    """Fetch an NSE JSON endpoint using a short, section-page-primed session.

    The generic NSE home page is not a reliable cookie primer for every API and
    may return an anti-bot response. The relevant filings page is a better first
    request. This helper deliberately has a small timeout budget and returns
    ``None`` on provider/network failure so a module cannot crash the app.
    """
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        prime = _nse_prime_page(path)
        try:
            session.get(prime, timeout=(2.5, 4.5), allow_redirects=True)
        except requests.RequestException:
            # The JSON endpoint can occasionally work even if the section shell
            # itself is blocked. Continue once, using the same session.
            pass
        endpoint = f"https://www.nseindia.com/api/{str(path).lstrip('/')}"
        response = session.get(endpoint, params=params or {}, timeout=(2.5, 6.5), allow_redirects=True)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None
    finally:
        session.close()


def _as_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "records", "result", "results", "rows", "eventCalendar", "shareholdingData"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
            if isinstance(value, dict):
                nested = _as_records(value)
                if nested:
                    return nested
    return []


@st.cache_data(ttl=1800, show_spinner=False)
def get_sector_rotation() -> pd.DataFrame:
    """Sector-index returns from Yahoo Finance's market-data feed; no estimates."""
    sectors = {
        "Banking": "^NSEBANK", "IT": "^CNXIT", "Auto": "^CNXAUTO",
        "FMCG": "^CNXFMCG", "Pharma": "^CNXPHARMA", "Metal": "^CNXMETAL",
        "Realty": "^CNXREALTY", "Energy": "^CNXENERGY", "Financial Services": "^CNXFIN",
    }
    try:
        import yfinance as yf
        # One batched request is substantially faster than nine sequential ticker calls.
        raw = yf.download(
            tickers=list(sectors.values()), period="6mo", interval="1d",
            auto_adjust=False, group_by="ticker", threads=True,
            progress=False, timeout=15,
        )
    except Exception:
        return pd.DataFrame(columns=["Sector", "1M", "3M", "6M", "As of"])
    rows: list[dict[str, Any]] = []
    for name, ticker in sectors.items():
        try:
            if raw is None or raw.empty:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                if ticker not in raw.columns.get_level_values(0):
                    continue
                frame = raw[ticker]
            else:
                frame = raw
            close = pd.to_numeric(frame.get("Close"), errors="coerce").dropna()
            if len(close) < 2:
                continue
            latest = float(close.iloc[-1])
            if latest <= 0:
                continue
            row: dict[str, Any] = {"Sector": name, "As of": close.index[-1].strftime("%d %b %Y")}
            for label, sessions in (("1M", 21), ("3M", 63), ("6M", 126)):
                base = float(close.iloc[-min(sessions + 1, len(close))])
                row[label] = ((latest / base) - 1) * 100 if base > 0 else float("nan")
            rows.append(row)
        except Exception:
            continue
    return pd.DataFrame(rows, columns=["Sector", "1M", "3M", "6M", "As of"])


@st.cache_data(ttl=900, show_spinner=False)
def get_market_sentiment() -> dict[str, Any]:
    """Transparent risk regime from NIFTY trend and India VIX; not an official score."""
    nifty = get_index_history("NIFTY 50", "6M")
    vix = get_market_snapshot()
    result: dict[str, Any] = {
        "regime": "Unavailable", "nifty_1m": None, "above_50dma": None,
        "vix": None, "as_of": "", "method": "NIFTY 50 trend + India VIX",
    }
    if nifty is None or nifty.empty or "Close" not in nifty:
        return result
    close = pd.to_numeric(nifty["Close"], errors="coerce").dropna()
    if len(close) < 50:
        return result
    latest = float(close.iloc[-1])
    one_month_base = float(close.iloc[-min(22, len(close))])
    dma50 = float(close.tail(50).mean())
    result["nifty_1m"] = ((latest / one_month_base) - 1) * 100 if one_month_base > 0 else None
    result["above_50dma"] = latest > dma50
    result["as_of"] = close.index[-1].strftime("%d %b %Y")
    if isinstance(vix, pd.DataFrame) and not vix.empty:
        vix_row = vix[vix["Index"].astype(str).str.upper().eq("INDIA VIX")]
        if not vix_row.empty and pd.notna(vix_row.iloc[0].get("Value")):
            result["vix"] = float(vix_row.iloc[0]["Value"])
    # Rule-based label; missing VIX or trend is never silently treated as low risk.
    if result["vix"] is None or result["nifty_1m"] is None:
        result["regime"] = "Partial data"
    elif result["vix"] >= 25 or (not result["above_50dma"] and result["nifty_1m"] < 0):
        result["regime"] = "Risk-Off"
    elif result["vix"] < 20 and result["above_50dma"] and result["nifty_1m"] > 0:
        result["regime"] = "Risk-On"
    else:
        result["regime"] = "Neutral"
    return result


@st.cache_data(ttl=3600, show_spinner=False)
def get_nse_institutional_holdings(symbol: str) -> pd.DataFrame:
    """Fetch and parse the latest two NSE SHP XBRL filings for a symbol.

    NSE's corporate-share-holdings-master endpoint returns filing metadata and
    XBRL URLs, not ready-made FII/DII percentage rows. The filing XML is the
    source for the investor-category percentages.
    """
    symbol = re.sub(r"[^A-Za-z0-9&_-]", "", str(symbol).replace(".NS", "").replace(".BO", "")).upper()
    columns = ["Category", "Current %", "Previous %", "Change (pp)", "Quarter", "Filing date", "Source"]
    if not symbol:
        return pd.DataFrame(columns=columns)

    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        # Prime the relevant filing section, not the generic NSE homepage.
        session.get(
            "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
            timeout=(2.5, 4.5),
        )
        response = session.get(
            f"{NSE_HOME.rstrip('/')}/api/corporate-share-holdings-master",
            params={"index": "equities", "symbol": symbol}, timeout=(2.5, 7),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        session.close()
        return pd.DataFrame(columns=columns)

    filings = _as_records(payload)
    # NSE returns a list of filing records containing date and xbrl URL.
    normalised = []
    for filing in filings:
        low = {str(k).lower(): v for k, v in filing.items()}
        xbrl = next((low[k] for k in ("xbrl", "xbrllink", "xbrlfilelink", "fileurl") if low.get(k)), "")
        date = next((low[k] for k in ("date", "period", "ason", "quarterend") if low.get(k)), "")
        submission = next((low[k] for k in ("submission_date", "submissiondate", "broadcastdate", "broadcastdatetime") if low.get(k)), "")
        if not xbrl or str(xbrl).strip() in ("-", "null", "None"):
            continue
        xbrl = str(xbrl).strip()
        if xbrl.startswith("/"):
            xbrl = "https://nsearchives.nseindia.com" + xbrl
        elif not xbrl.startswith("http"):
            xbrl = "https://nsearchives.nseindia.com/corporate/xbrl/" + xbrl.lstrip("/")
        parsed_date = pd.to_datetime(date, errors="coerce", dayfirst=True)
        normalised.append({"date": parsed_date, "date_raw": str(date), "submission": str(submission), "url": xbrl})

    normalised.sort(key=lambda x: x["date"] if pd.notna(x["date"]) else pd.Timestamp.min, reverse=True)
    # Keep only the two latest filing periods; revisions of one period are deduplicated.
    unique = []
    seen_periods = set()
    for item in normalised:
        period_key = item["date"].strftime("%Y-%m-%d") if pd.notna(item["date"]) else item["date_raw"]
        if period_key in seen_periods:
            continue
        seen_periods.add(period_key)
        unique.append(item)
        if len(unique) >= 2:
            break

    category_members = {
        "FII / FPI": "InstitutionsForeignMember",
        "DII": "InstitutionsDomesticMember",
    }

    def parse_filing(item: dict[str, Any]) -> dict[str, float]:
        try:
            xml_response = session.get(item["url"], timeout=18)
            xml_response.raise_for_status()
            root = ET.fromstring(xml_response.content)
        except Exception:
            return {}

        contexts: dict[str, set[str]] = {}
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1].lower() == "context":
                context_id = element.attrib.get("id", "")
                members = set()
                for child in element.iter():
                    if child.tag.rsplit("}", 1)[-1].lower() == "explicitmember":
                        member = (child.text or "").strip().split(":")[-1]
                        if member:
                            members.add(member)
                if context_id:
                    contexts[context_id] = members

        facts: dict[str, float] = {}
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "ShareholdingAsAPercentageOfTotalNumberOfShares":
                continue
            context_id = element.attrib.get("contextRef", "")
            members = contexts.get(context_id, set())
            # Exclude detailed sub-categories; use the top-level FII/DII roll-ups.
            if len(members) > 2:
                continue
            raw = (element.text or "").strip().replace(",", "")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            for label, member_name in category_members.items():
                if member_name in members and label not in facts:
                    facts[label] = value
                    break

        # XBRL V1.1 (late 2025 onward) stores proportions; older taxonomy uses
        # basis-points x 100. Infer the scale only when a promoter/public roll-up
        # is present. If absent, do not guess a scale for the institution values.
        promoter_public = {}
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "ShareholdingAsAPercentageOfTotalNumberOfShares":
                continue
            members = contexts.get(element.attrib.get("contextRef", ""), set())
            label = "promoter" if "ShareholdingOfPromoterAndPromoterGroupMember" in members else (
                "public" if "PublicShareholdingMember" in members else "")
            if label and label not in promoter_public:
                try:
                    promoter_public[label] = float((element.text or "").strip())
                except ValueError:
                    pass
        scale = 1.0
        if len(promoter_public) == 2:
            total = sum(promoter_public.values())
            if total > 1000:
                scale = 0.01
            elif 0 < total < 2:
                scale = 100.0
        return {key: round(value * scale, 4) for key, value in facts.items()}

    try:
        parsed_filings = [(item, parse_filing(item)) for item in unique]
    finally:
        session.close()

    if not parsed_filings:
        return pd.DataFrame(columns=columns)
    current_item, current_values = parsed_filings[0]
    previous_values = parsed_filings[1][1] if len(parsed_filings) > 1 else {}
    rows = []
    for category in ("FII / FPI", "DII"):
        current = current_values.get(category)
        previous = previous_values.get(category)
        if current is None:
            continue
        change = round(current - previous, 4) if previous is not None else None
        rows.append({
            "Category": category, "Current %": current, "Previous %": previous,
            "Change (pp)": change,
            "Quarter": current_item["date"].strftime("%d %b %Y") if pd.notna(current_item["date"]) else current_item["date_raw"],
            "Filing date": current_item["submission"], "Source": current_item["url"],
        })
    return pd.DataFrame(rows, columns=columns)


@st.cache_data(ttl=1800, show_spinner=False)
def get_nse_results_calendar(days: int = 14) -> pd.DataFrame:
    """Upcoming NSE event-calendar rows, restricted to financial-results events."""
    now = pd.Timestamp.now(tz="Asia/Kolkata").normalize()
    end = now + pd.Timedelta(days=max(1, min(int(days), 45)))
    params = {"index": "equities", "from_date": now.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")}
    payload = _nse_json("/api/event-calendar", params)
    records = _as_records(payload)
    rows: list[dict[str, Any]] = []
    for rec in records:
        low = {str(k).lower(): v for k, v in rec.items()}
        symbol = str(next((low[k] for k in ("symbol", "sym") if low.get(k) not in (None, "")), ""))
        company = str(next((low[k] for k in ("company", "companyname", "issuer") if low.get(k) not in (None, "")), ""))
        purpose = str(next((low[k] for k in ("purpose", "event", "meetingtype") if low.get(k) not in (None, "")), ""))
        details = str(next((low[k] for k in ("details", "description", "purpose") if low.get(k) not in (None, "")), ""))
        date_raw = next((low[k] for k in ("date", "meetingdate", "eventdate") if low.get(k) not in (None, "")), None)
        date = pd.to_datetime(date_raw, errors="coerce", dayfirst=True)
        if pd.isna(date) or date.date() < now.date() or date.date() > end.date():
            continue
        if not any(term in f"{purpose} {details}".lower() for term in ("financial result", "results", "quarterly result")):
            continue
        rows.append({"Symbol": symbol, "Company": company, "Event": purpose or "Financial Results", "Date": date.strftime("%d %b %Y"), "_date": date})
    if not rows:
        return pd.DataFrame(columns=["Symbol", "Company", "Event", "Date"])
    return pd.DataFrame(rows).sort_values("_date").drop(columns="_date").drop_duplicates().head(12).reset_index(drop=True)
