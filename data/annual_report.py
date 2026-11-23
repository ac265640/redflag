"""Annual-report evidence layer for Phase 2.

Primary source: NSE Corporate Filings -> Annual Reports.
The module is deliberately evidence-first:
    discover -> download -> extract pages -> classify -> cite.

No financial value is fabricated here. If the NSE annual-report attachment cannot
be reached or a topic cannot be located, the result is marked N/A.
"""
from __future__ import annotations

import io
import re
import tempfile
import zipfile
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import quote_plus, urljoin

import pandas as pd
import requests
import streamlit as st

NSE_HOME = "https://www.nseindia.com/"
NSE_ANNUAL_REPORTS_URL = (
    "https://www.nseindia.com/companies-listing/corporate-filings-annual-reports"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0 Safari/537.36"
)

# Topic -> search phrases. We use multiple phrases because report layouts vary.
TOPIC_PATTERNS: Dict[str, List[str]] = {
    "Consolidated financial statements": [
        r"consolidated statement of profit and loss",
        r"consolidated balance sheet",
        r"consolidated cash flow statement",
        r"consolidated financial statements",
    ],
    "Standalone financial statements": [
        r"standalone statement of profit and loss",
        r"standalone balance sheet",
        r"standalone cash flow statement",
        r"standalone financial statements",
    ],
    "Notes to accounts": [
        r"notes to the consolidated financial statements",
        r"notes forming part of the consolidated financial statements",
        r"notes to accounts",
    ],
    "Related parties": [
        r"related party transactions",
        r"related parties",
    ],
    "Contingent liabilities": [
        r"contingent liabilities",
        r"contingencies",
    ],
    "Exceptional items": [
        r"exceptional items",
        r"exceptional item",
    ],
    "Accounting policies": [
        r"significant accounting policies",
        r"accounting policies",
        r"basis of preparation",
    ],
    "Segments": [
        r"segment information",
        r"operating segments",
        r"reportable segments",
    ],
    "Subsidiaries / JVs": [
        r"subsidiaries",
        r"joint ventures",
        r"associate companies",
        r"investment in subsidiaries",
    ],
    "Guarantees": [
        r"guarantees",
        r"corporate guarantees",
        r"guarantee given",
    ],
    "Loans / advances": [
        r"loans and advances",
        r"loans, advances",
        r"loans to related parties",
    ],
    "Auditor observations": [
        r"independent auditor's report",
        r"independent auditors' report",
        r"key audit matters",
        r"material uncertainty",
        r"qualified opinion",
        r"internal financial controls",
    ],
    "Management commentary": [
        r"management discussion and analysis",
        r"management's discussion and analysis",
        r"md&a",
        r"director's report",
    ],
}

# Financial red-flag area -> annual-report topic to verify.
FLAG_TOPIC_MAP = {
    "P&L": "Consolidated financial statements",
    "Balance Sheet": "Notes to accounts",
    "Cash Flow": "Consolidated financial statements",
    "Ratios": "Consolidated financial statements",
    "Notes": "Auditor observations",
    "Governance": "Management commentary",
    "Hidden Forensic": "Related parties",
}


BSE_LIST_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=Active"
BSE_ANNUAL_URLS = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w",
    "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport/w",
)
BSE_LOOKUP_URL = "https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w"


def _bse_json_records(payload: Any):
    """Yield dict records from the many wrapper shapes used by BSE APIs."""
    if isinstance(payload, list):
        for x in payload:
            if isinstance(x, dict):
                yield x
    elif isinstance(payload, dict):
        for key in ("Table", "Table1", "data", "Data", "result", "results", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                for x in value:
                    if isinstance(x, dict):
                        yield x
        for value in payload.values():
            if isinstance(value, dict):
                yield from _bse_json_records(value)


def _bse_value(d: Dict[str, Any], *names: str) -> str:
    lower={str(k).lower():v for k,v in d.items()}
    for name in names:
        if name in d and d[name] not in (None, ""):
            return str(d[name])
        if name.lower() in lower and lower[name.lower()] not in (None, ""):
            return str(lower[name.lower()])
    return ""


def _find_urls(obj: Any) -> List[str]:
    urls=[]
    if isinstance(obj, str):
        urls.extend(re.findall(r'https?://[^\s"\'<>]+', obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            urls.extend(_find_urls(v))
    elif isinstance(obj, list):
        for v in obj:
            urls.extend(_find_urls(v))
    return list(dict.fromkeys(u.rstrip("'\"),;]") for u in urls))


def _bse_headers() -> Dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Origin": "https://www.bseindia.com",
        "Referer": "https://www.bseindia.com/",
        "Connection": "keep-alive",
    }


@st.cache_data(ttl=86400, show_spinner=False)
def _lookup_bse_scrip_code(query: str) -> str:
    """Resolve an NSE symbol/company name through BSE's official quick search."""
    text = str(query or "").strip()
    if not text:
        return ""
    try:
        response = requests.get(
            BSE_LOOKUP_URL,
            params={"Type": "SS", "text": text},
            headers=_bse_headers(),
            timeout=(3, 7),
        )
        response.raise_for_status()
        raw = response.text or ""
        # BSE's quick-search HTML places the matching security label before
        # its ISIN and numeric scrip code. Match the exact symbol/name token;
        # never accept an arbitrary six-digit number from an unrelated row.
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw, "html.parser")
        target = re.sub(r"[^a-z0-9]+", "", text.lower())
        for tag in soup.find_all(["strong", "b", "span"]):
            label = re.sub(r"[^a-z0-9]+", "", tag.get_text(" ", strip=True).lower())
            if not label or (label != target and not (len(target) >= 6 and target in label)):
                continue
            parent = tag.parent
            blob = parent.get_text(" ", strip=True) if parent else tag.get_text(" ", strip=True)
            codes = re.findall(r"(?<!\d)(\d{6})(?!\d)", blob)
            if codes:
                return codes[-1]
        # Fallback for the documented inline response: <strong>SYMBOL</strong> ISIN 500000.
        for match in re.finditer(r"<(?:strong|b|span)\b[^>]*>(.*?)</(?:strong|b|span)>((?:(?!<(?:strong|b|span)\b).){0,180})", raw, re.I | re.S):
            label = re.sub(r"[^a-z0-9]+", "", BeautifulSoup(match.group(1), "html.parser").get_text(" ", strip=True).lower())
            if label != target and not (len(target) >= 6 and target in label):
                continue
            tail = BeautifulSoup(match.group(2), "html.parser").get_text(" ", strip=True)
            codes = re.findall(r"(?<!\d)(\d{6})(?!\d)", tail)
            if codes:
                return codes[-1]
    except Exception:
        return ""
    return ""


@st.cache_data(ttl=86400, show_spinner=False)
def _load_bse_scrip_rows() -> List[Dict[str, Any]]:
    """Load the official BSE scrip directory once per day."""
    try:
        r = requests.get(
            BSE_LIST_URL,
            headers=_bse_headers(),
            timeout=(3, 7),
        )
        r.raise_for_status()
        return list(_bse_json_records(r.json()))
    except Exception:
        return []


def _bse_scrip_code(symbol: str) -> str:
    """Resolve a ticker to a BSE numeric code using local listing data first.

    A BSE ticker already ending in ``.BO`` is itself the scrip code. For NSE
    tickers, resolve by exact NSE symbol, ISIN, then conservative legal-name
    matching against the cached exchange directory. This avoids a repeated
    list request and does not guess a code from an unrelated substring.
    """
    raw = str(symbol or "").strip().upper()
    if raw.endswith(".BO"):
        direct = raw[:-3]
        return direct if direct.isdigit() else ""
    sym = raw[:-3] if raw.endswith(".NS") else raw
    if sym.isdigit():
        return sym

    isin = ""
    company = ""
    try:
        cache = Path(__file__).resolve().parent / "cache" / "listed_companies.csv"
        if cache.exists():
            df = pd.read_csv(cache, dtype=str).fillna("")
            if "key" in df.columns:
                exact = df[df["key"].astype(str).str.upper().eq(raw)]
                if not exact.empty:
                    key = str(exact.iloc[0]["key"]).upper()
                    if key.endswith(".BO") and key[:-3].isdigit():
                        return key[:-3]
            if "symbol" in df.columns:
                hit = df[df["symbol"].astype(str).str.upper().eq(sym)]
                if not hit.empty:
                    isin = str(hit.iloc[0].get("isin") or "").strip().upper()
                    company = str(hit.iloc[0].get("name") or "").strip()
    except Exception:
        pass

    rows = _load_bse_scrip_rows()

    # Direct BSE Quick Search must still run when the full BSE scrip directory
    # is blocked. Returning early here used to make the advertised fallback
    # unreachable for exactly those cases.
    if not rows:
        for query in (sym, company, isin):
            code = _lookup_bse_scrip_code(query)
            if code:
                return code
        return ""

    def code_of(record: Dict[str, Any]) -> str:
        code = _bse_value(record, "SCRIP_CD", "scrip_id", "Scripcode", "Scrip Code", "scripcode")
        return code.strip() if code.strip().isdigit() else ""

    # Highest-confidence match: BSE record explicitly maps the NSE trading symbol.
    for record in rows:
        nse_symbol = _bse_value(record, "NSE_SYMBOL", "NSESymbol", "symbol", "NSE Symbol").upper().strip()
        code = code_of(record)
        if code and nse_symbol == sym:
            return code

    # Exchange ISIN is stable across NSE/BSE listings and outranks fuzzy names.
    if isin:
        for record in rows:
            rec_isin = _bse_value(record, "ISIN_NUMBER", "ISIN", "isin").upper().strip()
            code = code_of(record)
            if code and rec_isin == isin:
                return code

    # Finally use normalized legal name, but reject weak substring-only matches.
    if company:
        import re
        target = re.sub(r"[^a-z0-9]+", " ", company.lower()).strip()
        target = re.sub(r"\b(limited|ltd|company|co)\b", "", target).strip()
        best = []
        for record in rows:
            name = _bse_value(record, "Scrip_Name", "Issuer_Name", "Company_Name", "companyName")
            norm = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
            norm = re.sub(r"\b(limited|ltd|company|co)\b", "", norm).strip()
            code = code_of(record)
            if not code or not target or not norm:
                continue
            if norm == target:
                return code
            if min(len(norm), len(target)) >= 8 and (norm in target or target in norm):
                best.append((min(len(norm), len(target)) / max(len(norm), len(target)), code))
        if best:
            best.sort(reverse=True)
            if best[0][0] >= 0.85 and (len(best) == 1 or best[0][0] > best[1][0]):
                return best[0][1]

    # Direct BSE quick-search endpoint is a better fallback than guessing from
    # a partial local listing row. It accepts the exact NSE symbol/company name.
    for query in (sym, company, isin):
        code = _lookup_bse_scrip_code(query)
        if code:
            return code
    return ""


def _fetch_bse_annual_reports(symbol: str) -> Tuple[List[Dict[str, str]], str]:
    """BSE fallback using the current AnnualReport_New API response shape."""
    code = _bse_scrip_code(symbol)
    if not code:
        return [], "BSE annual reports: BSE scrip code could not be resolved by BSE quick search"

    headers = _bse_headers()
    errors = []
    for endpoint in BSE_ANNUAL_URLS:
        try:
            response = requests.get(
                endpoint, params={"scripcode": code}, headers=headers, timeout=(3, 6)
            )
            if not response.ok:
                errors.append(f"{endpoint.rsplit('/', 1)[-1]} HTTP {response.status_code}")
                continue
            payload = response.json()
            rows = []
            for record in _bse_json_records(payload):
                pdf = _bse_value(
                    record, "PDFDownload", "PDFDownloadLink", "Attachment", "attachment",
                    "FileName", "fileName", "FILE_NAME", "pdfLink", "PDFLink", "url",
                ).strip()
                if pdf.startswith("//"):
                    pdf = "https:" + pdf
                elif pdf.startswith("/"):
                    pdf = "https://www.bseindia.com" + pdf
                urls = [pdf] if pdf.startswith("http") else []
                urls.extend(u for u in _find_urls(record) if u not in urls)
                urls = [u for u in urls if ("attachhis" in u.lower() or "attachlive" in u.lower() or re.search(r"\.(?:pdf|zip)(?:\?|$)", u, re.I))]
                if not urls:
                    continue
                year_text = _bse_value(record, "Year", "FinancialYear", "FY", "year", "fromYr", "FromYear")
                years = re.findall(r"20\d{2}", year_text or "")
                if not years:
                    years = re.findall(r"20\d{2}", " ".join(str(v) for v in record.values() if v is not None))
                from_y = years[0] if len(years) > 1 else ""
                to_y = years[-1] if years else ""
                rows.append({
                    "Company": _bse_value(record, "CompanyName", "companyName", "Company_Name", "Scrip_Name") or symbol,
                    "From Year": from_y,
                    "To Year": to_y,
                    "Attachment": urls[0],
                    "Type": _bse_value(record, "SubmissionType", "submission_type", "Type"),
                    "Date": _bse_value(record, "BroadcastDate", "broadcast_dttm", "Date", "date"),
                    "File Size": _bse_value(record, "FileSize", "attFileSize", "size"),
                    "Source": "BSE Annual Reports",
                })
            if rows:
                return rows, "BSE AnnualReport_New API fallback" if "AnnualReport_New" in endpoint else "BSE annual reports API fallback"
            errors.append(f"{endpoint.rsplit('/', 1)[-1]} returned no PDFDownload rows")
        except Exception as exc:
            errors.append(f"{endpoint.rsplit('/', 1)[-1]}:{type(exc).__name__}")
    return [], "BSE annual reports unavailable: " + "; ".join(errors[-2:])


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": NSE_HOME,
        "Connection": "keep-alive",
    })
    return s


def _absolute(url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return ""
    return urljoin(NSE_HOME, u)


def _valid_pdf_url(url: str) -> bool:
    """Allow only official NSE/BSE attachment hosts and plausible report URLs."""
    from urllib.parse import urlparse

    value = str(url or "").strip()
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
    except Exception:
        return False
    official_host = (host == "nseindia.com" or host.endswith(".nseindia.com") or host == "bseindia.com" or host.endswith(".bseindia.com"))
    path = (parsed.path or "").lower()
    plausible_attachment = (
        path.endswith(".pdf") or path.endswith(".zip")
        or ".pdf" in path or ".zip" in path
        or "annual" in path or "attachhis" in path or "corporate" in path
    )
    return parsed.scheme == "https" and official_host and plausible_attachment


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_date(value: Any):
    return pd.to_datetime(str(value or ""), errors="coerce", dayfirst=True)


def _rows_from_html(html: str, symbol: str) -> List[Dict[str, str]]:
    """Parse annual-report rows from the NSE rendered page.

    The attachment control is often rendered by Angular and the visible table
    can contain a row even when the PDF URL is not present in the initial HTML.
    This parser therefore extracts URLs from normal attributes, data attributes
    and inline javascript instead of relying on a single href pattern.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    rows: List[Dict[str, str]] = []

    def urls_from_node(node) -> List[str]:
        found: List[str] = []
        for attr in (
            "href", "data-href", "data-url", "data-link", "data-file",
            "data-file-url", "data-attachment", "data-attachment-url", "onclick",
        ):
            value = node.get(attr)
            if not value:
                continue
            text = str(value).replace("&amp;", "&")
            # Accept any NSE archive/corporate URL first; then normal .pdf URLs.
            patterns = [
                r'https?://[^\s"\'<>]+(?:nsearchives\.nseindia\.com|nseindia\.com)[^\s"\'<>]*',
                r'(?:https?:)?//[^\s"\'<>]+(?:nsearchives\.nseindia\.com|nseindia\.com)[^\s"\'<>]*',
                r'[^\s"\'<>]*(?:\.pdf)(?:\?[^\s"\'<>]*)?',
            ]
            for pat in patterns:
                for m in re.findall(pat, text, flags=re.I):
                    href = _absolute(m.strip("'\"(),;"))
                    if _valid_pdf_url(href):
                        found.append(href)
        return found

    for tr in soup.find_all("tr"):
        text = _clean_text(tr.get_text(" ", strip=True))
        years = re.findall(r"\b(20\d{2})\b", text)
        if len(years) < 1:
            continue

        links: List[str] = []
        for node in tr.find_all(["a", "button", "div", "span", "img"]):
            links.extend(urls_from_node(node))

        lower = text.lower()
        rows.append({
            "Company": text,
            "From Year": years[0],
            "To Year": years[1] if len(years) > 1 else "",
            "Attachment": next(iter(dict.fromkeys(links)), ""),
            "Type": "Revised" if "revised" in lower else ("New" if re.search(r"\bnew\b", lower) else ""),
            "Date": "",
            "Source": f"{NSE_ANNUAL_REPORTS_URL}?symbol={quote_plus(symbol)}&tabIndex=equity",
        })
    return rows


def _api_rows_from_payload(payload: Any, symbol: str) -> List[Dict[str, str]]:
    """Normalize NSE /api/annual-reports JSON into our internal schema.

    NSE has changed the wrapper around this endpoint over time. We therefore
    accept the documented field names (fromYr, toYr, fileName, attFileSize,
    submission_type, broadcast_dttm) as well as common casing variants.
    """
    if not isinstance(payload, (dict, list)):
        return []

    def records(obj: Any):
        if isinstance(obj, list):
            for x in obj:
                if isinstance(x, dict):
                    yield x
        elif isinstance(obj, dict):
            for key in ("data", "annualReports", "annual_reports", "records", "result", "results"):
                value = obj.get(key)
                if isinstance(value, list):
                    for x in value:
                        if isinstance(x, dict):
                            yield x
                    return
            # Some responses put the list one level deeper.
            for value in obj.values():
                if isinstance(value, list) and any(isinstance(x, dict) for x in value):
                    for x in value:
                        if isinstance(x, dict):
                            yield x
                    return

    def get(d: Dict[str, Any], *names: str) -> Any:
        lower = {str(k).lower(): v for k, v in d.items()}
        for name in names:
            if name in d:
                return d[name]
            if name.lower() in lower:
                return lower[name.lower()]
        return ""

    out: List[Dict[str, str]] = []
    for d in records(payload):
        from_year = str(get(d, "fromYr", "fromYear", "from_year", "From Year") or "")
        to_year = str(get(d, "toYr", "toYear", "to_year", "To Year") or "")
        file_name = str(get(d, "fileName", "filename", "attachment", "attFile", "attchmntFile", "attachmentFile") or "").strip()
        file_name = _absolute(file_name) if file_name else ""
        company = str(get(d, "companyName", "company", "Company") or symbol).strip()
        submission = str(get(d, "submission_type", "submissionType", "type", "Type") or "").strip()
        broadcast = str(get(d, "broadcast_dttm", "broadcastDateTime", "broadcastDate", "Date") or "").strip()
        size = str(get(d, "attFileSize", "fileSize", "size") or "").strip()
        if not from_year and not to_year and not file_name:
            continue
        # Keep only actual annual-report records, not unrelated API metadata.
        if file_name and not _valid_pdf_url(file_name):
            file_name = ""
        out.append({
            "Company": company,
            "From Year": re.search(r"20\d{2}", from_year).group(0) if re.search(r"20\d{2}", from_year) else from_year,
            "To Year": re.search(r"20\d{2}", to_year).group(0) if re.search(r"20\d{2}", to_year) else to_year,
            "Attachment": file_name,
            "Type": submission,
            "Date": broadcast,
            "File Size": size,
            "Source": f"{NSE_ANNUAL_REPORTS_URL}?symbol={quote_plus(symbol)}&tabIndex=equity",
        })
    return out


def _fetch_nse_annual_api(symbol: str) -> Tuple[List[Dict[str, str]], str]:
    """Fetch the dedicated NSE annual-reports endpoint using a primed session."""
    api_url = f"https://www.nseindia.com/api/annual-reports?index=equities&symbol={quote_plus(symbol)}"
    s = _session()
    try:
        # Prime the exact annual-report section, not only the generic homepage.
        # NSE's API may issue the required cookies from this section URL.
        page_url = f"{NSE_ANNUAL_REPORTS_URL}?symbol={quote_plus(symbol)}&tabIndex=equity"
        page = s.get(page_url, timeout=(3.5, 8))
        if not page.ok:
            return [], f"NSE annual-report page HTTP {page.status_code}"
        headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": page_url,
        }
        r = s.get(api_url, headers=headers, timeout=(3.5, 12))
        if not r.ok:
            return [], f"NSE annual API HTTP {r.status_code}"
        try:
            payload = r.json()
        except ValueError:
            return [], "NSE annual API returned non-JSON"
        return _api_rows_from_payload(payload, symbol), "NSE annual reports API"
    except Exception as exc:
        return [], f"NSE annual API {type(exc).__name__}"


def _fetch_nse_annual_via_browser(symbol: str) -> List[Dict[str, str]]:
    """Render NSE's page and extract attachment URLs from the live DOM."""
    page_url = f"{NSE_ANNUAL_REPORTS_URL}?symbol={quote_plus(symbol)}&tabIndex=equity"
    rows: List[Dict[str, str]] = []
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        import time

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        driver = webdriver.Chrome(options=opts)
        try:
            driver.get(page_url)
            time.sleep(3.0)
            elements = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for tr in elements:
                text = _clean_text(tr.text)
                years = re.findall(r"\b(20\d{2})\b", text)
                if not years:
                    continue
                links: List[str] = []
                candidates = tr.find_elements(By.CSS_SELECTOR, "a,button,[role='button'],[onclick],img")
                for el in candidates:
                    for attr in ("href", "data-href", "data-url", "data-link", "data-file", "data-file-url", "data-attachment", "data-attachment-url", "onclick", "src"):
                        try:
                            value = el.get_attribute(attr)
                        except Exception:
                            value = None
                        if not value:
                            continue
                        text_value = str(value).replace("&amp;", "&")
                        # Pull complete URL tokens rather than stopping at the first
                        # occurrence of .pdf; NSE archive filenames contain many underscores.
                        for m in re.findall(r'https?://[^\s"\'<>]+', text_value):
                            candidate = m.strip("'\"(),;")
                            if _valid_pdf_url(candidate):
                                links.append(candidate)
                        # onclick/data attributes sometimes contain a relative archive path.
                        for m in re.findall(r'(?:(?:nsearchives\.nseindia\.com)|(?:nseindia\.com))[^\s"\'<>]+', text_value, flags=re.I):
                            candidate = _absolute(m.strip("'\"(),;"))
                            if _valid_pdf_url(candidate):
                                links.append(candidate)
                lower = text.lower()
                rows.append({
                    "Company": text,
                    "From Year": years[0],
                    "To Year": years[1] if len(years) > 1 else "",
                    "Attachment": next(iter(dict.fromkeys(links)), ""),
                    "Type": "Revised" if "revised" in lower else ("New" if re.search(r"\bnew\b", lower) else ""),
                    "Date": "",
                    "Source": page_url,
                })
        finally:
            driver.quit()
    except Exception:
        return []
    return rows


@st.cache_data(ttl=21600, show_spinner=False)
def discover_annual_reports(ticker: str, use_browser_fallback: bool = False) -> Tuple[pd.DataFrame, str]:
    """Discover NSE annual-report metadata for a ticker.

    Retrieval order:
      1. NSE's dedicated annual-reports API (section-page-primed session)
      2. NSE rendered HTML page
      3. BSE annual-report API fallback
      4. Optional headless-browser DOM extraction when explicitly requested

    The previous implementation stopped after finding HTML rows, even when
    those rows contained no attachment URL. That was the direct cause of the
    N/A shown for companies such as NHPC.
    """
    symbol = str(ticker).split(".")[0].upper()
    page_url = f"{NSE_ANNUAL_REPORTS_URL}?symbol={quote_plus(symbol)}&tabIndex=equity"
    rows: List[Dict[str, str]] = []
    messages: List[str] = []

    api_rows, api_status = _fetch_nse_annual_api(symbol)
    if api_rows:
        rows = api_rows
        source = "NSE annual reports API"
    else:
        messages.append(api_status)
        source = "NSE Annual Reports"
        try:
            r = _session().get(page_url, timeout=(3.5, 8))
            if r.ok and len(r.text) > 500:
                rows = _rows_from_html(r.text, symbol)
        except Exception as exc:
            messages.append(f"requests:{type(exc).__name__}")

        # IMPORTANT: do not require rows == empty here. The table may exist but
        # the attachment URL may be hidden behind JS. Retry if no usable file URL.
    if not rows or not any(_valid_pdf_url(str(x.get("Attachment") or "")) for x in rows):
        # Selenium starts Chrome and can add 10–30 seconds. It is an explicit
        # fallback only, never part of normal company search/page loading.
        if use_browser_fallback:
            browser_rows = _fetch_nse_annual_via_browser(symbol)
            if browser_rows and any(_valid_pdf_url(str(x.get("Attachment") or "")) for x in browser_rows):
                rows = browser_rows
        if not rows or not any(_valid_pdf_url(str(x.get("Attachment") or "")) for x in rows):
            bse_rows, bse_status = _fetch_bse_annual_reports(symbol)
            if bse_rows:
                rows = bse_rows
                source = bse_status
            else:
                messages.append(bse_status)

    if not rows or not any(_valid_pdf_url(str(x.get("Attachment") or "")) for x in rows):
        detail = "; ".join(messages[-3:]) if messages else "no filing record"
        return pd.DataFrame(columns=[
            "Company", "From Year", "To Year", "Attachment", "Type", "Date", "File Size", "Source"
        ]), f"Annual report unavailable from NSE/BSE automatically: {detail}"

    df = pd.DataFrame(rows)
    for col in ("Company", "From Year", "To Year", "Attachment", "Type", "Date", "Source"):
        if col not in df.columns:
            df[col] = ""
    df = df.drop_duplicates(subset=["From Year", "To Year", "Attachment", "Type"])
    df["_dt"] = df["Date"].map(_parse_date)
    df["_has_pdf"] = df["Attachment"].map(_valid_pdf_url)
    df["_to"] = pd.to_numeric(df["To Year"], errors="coerce")
    # Latest year first; among same-year submissions prefer revised, then a
    # real attachment. This also handles the duplicate rows shown by NSE.
    df["_revised"] = df["Type"].astype(str).str.contains("revised", case=False, na=False)
    df = df.sort_values(
        ["_has_pdf", "_to", "_revised", "_dt"],
        ascending=[False, False, False, False],
        na_position="last",
    ).drop(columns=["_dt", "_has_pdf", "_to", "_revised"])
    return df.reset_index(drop=True), source


def _valid_pdf_bytes(data: bytes) -> bool:
    """Return True only when bytes are plausibly a readable PDF."""
    if not data or len(data) < 100:
        return False
    if data[:4] == b"%PDF":
        return True
    # A few NSE archive responses omit the signature in the first bytes while
    # still being a valid PDF stream. pypdf is the final authority below.
    return b"%PDF-" in data[:1024]


def _download_pdf_via_browser(url: str) -> bytes:
    """Fallback downloader using the user's installed Chrome/Selenium session.

    NSE archive files can be reachable in Chrome while a plain requests session
    receives an HTML challenge/403. We borrow Chrome's cookies and request the
    exact same archive URL, then validate the bytes as a PDF.
    """
    if not _valid_pdf_url(url):
        return b""
    driver = None
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        import time

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        driver = webdriver.Chrome(options=opts)
        driver.get(NSE_ANNUAL_REPORTS_URL)
        time.sleep(1.0)
        cookies = driver.get_cookies()
        sess = _session()
        for c in cookies:
            try:
                sess.cookies.set(c.get("name"), c.get("value"), domain=c.get("domain"))
            except Exception:
                pass
        sess.headers.update({
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Referer": f"{NSE_ANNUAL_REPORTS_URL}",
        })
        r = sess.get(url, timeout=60, allow_redirects=True)
        if r.ok and _valid_pdf_bytes(r.content):
            return r.content
    except Exception:
        pass
    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass
    return b""


@st.cache_data(ttl=86400, show_spinner=False)
def _download_pdf(url: str, use_browser_fallback: bool = False) -> bytes:
    """Download one official annual-report PDF with request + Chrome fallback."""
    if not _valid_pdf_url(url):
        return b""
    # 1) Fast path: normal NSE/BSE archive request.
    try:
        s = _session()
        r = s.get(url, timeout=(4, 18), allow_redirects=True, headers={
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Referer": NSE_ANNUAL_REPORTS_URL,
        })
        if r.ok and _valid_pdf_bytes(r.content):
            return r.content
        if r.ok and r.content[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(r.content)) as archive:
                    pdf_names = [n for n in archive.namelist() if n.lower().endswith(".pdf")]
                    if pdf_names:
                        return archive.read(pdf_names[0])
            except Exception:
                pass
    except Exception:
        pass
    # Browser-cookie retrieval is deliberately opt-in; do not block search.
    return _download_pdf_via_browser(url) if use_browser_fallback else b""


@st.cache_data(ttl=86400, show_spinner=False)
def extract_annual_report_pages(pdf_url: str, use_browser_fallback: bool = False) -> List[Dict[str, Any]]:
    """Extract text page-by-page from an annual-report PDF.

    pypdf is primary; pdfplumber is a second extractor for PDFs whose text
    layer is present but not handled well by pypdf.
    """
    data = _download_pdf(pdf_url, use_browser_fallback=use_browser_fallback)
    if not data:
        return []
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = _clean_text(page.extract_text() or "")
            except Exception:
                text = ""
            pages.append({"page": i, "text": text})
        if any(str(x.get("text") or "").strip() for x in pages):
            return pages
    except Exception:
        pass

    # Secondary extractor. This does not create data; it only reads the PDF's
    # existing text layer using a different parser.
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                try:
                    text = _clean_text(page.extract_text() or "")
                except Exception:
                    text = ""
                pages.append({"page": i, "text": text})
        return pages
    except Exception:
        return []


def _snippet(text: str, start: int, width: int = 150) -> str:
    lo = max(0, start - 40)
    hi = min(len(text), start + width)
    snippet = _clean_text(text[lo:hi])
    # Keep the displayed locating quote deliberately short.
    words = snippet.split()
    return " ".join(words[:18]).strip()


def _find_topic_page(pages: List[Dict[str, Any]], patterns: List[str], prefer: str = "") -> Dict[str, Any] | None:
    candidates = []
    for item in pages:
        text = item["text"]
        low = text.lower()
        for pattern in patterns:
            m = re.search(pattern, low, re.I)
            if m:
                score = 1
                if prefer and prefer.lower() in low:
                    score += 2
                # Headings are generally early/short; reward occurrences near start.
                if m.start() < 500:
                    score += 1
                candidates.append((score, item["page"], m.start(), pattern))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (-x[0], x[1]))
    _, page_no, pos, pattern = candidates[0]
    text = next(p["text"] for p in pages if p["page"] == page_no)
    return {
        "page": page_no,
        "pattern": pattern,
        "quote": _snippet(text, pos),
    }


@st.cache_data(ttl=86400, show_spinner=False)
def build_evidence_index(pdf_url: str, basis: str = "Consolidated", use_browser_fallback: bool = False) -> pd.DataFrame:
    """Build a topic-to-page evidence map from one annual-report PDF."""
    pages = extract_annual_report_pages(pdf_url, use_browser_fallback=use_browser_fallback)
    if not pages:
        return pd.DataFrame(columns=[
            "Topic", "Status", "Page", "Basis", "Evidence quote", "Source"
        ])

    records = []
    for topic, patterns in TOPIC_PATTERNS.items():
        prefer = "consolidated" if basis.lower().startswith("con") else "standalone"
        found = _find_topic_page(pages, patterns, prefer=prefer)
        if found is None:
            # For a topic not explicitly basis-specific, retry without a basis preference.
            found = _find_topic_page(pages, patterns)
        if found:
            records.append({
                "Topic": topic,
                "Status": "Found",
                "Page": int(found["page"]),
                "Basis": basis,
                "Evidence quote": f'"{found["quote"]}"',
                "Source": pdf_url,
            })
        else:
            records.append({
                "Topic": topic,
                "Status": "N/A",
                "Page": "N/A",
                "Basis": basis,
                "Evidence quote": "N/A — topic not located in extracted report text.",
                "Source": pdf_url,
            })
    return pd.DataFrame(records)


@st.cache_data(ttl=21600, show_spinner=False)
def annual_report_evidence(ticker: str, basis: str = "Consolidated", use_browser_fallback: bool = False) -> Dict[str, Any]:
    """Return latest report metadata + page-level evidence index."""
    reports, source = discover_annual_reports(ticker, use_browser_fallback=use_browser_fallback)
    if reports.empty:
        return {
            "reports": reports,
            "source": source,
            "latest_url": "",
            "period": "N/A",
            "evidence": pd.DataFrame(),
        }

    work = reports.copy()
    # Prefer rows with attachments, then the latest To Year.
    work["_has_pdf"] = work["Attachment"].astype(str).str.startswith("http")
    work["_to"] = pd.to_numeric(work["To Year"], errors="coerce")
    work = work.sort_values(["_has_pdf", "_to"], ascending=[False, False], na_position="last")
    row = work.iloc[0]
    url = str(row.get("Attachment") or "")
    evidence = build_evidence_index(url, basis, use_browser_fallback=use_browser_fallback) if url else pd.DataFrame()
    period = f"FY{row.get('From Year', '')}-{row.get('To Year', '')}".strip("-")
    extracted_pages = extract_annual_report_pages(url, use_browser_fallback=use_browser_fallback) if url else []
    extraction_status = (
        "text_extracted" if any(str(x.get("text") or "").strip() for x in extracted_pages)
        else ("pdf_retrieved_but_text_unavailable" if url else "pdf_unavailable")
    )
    return {
        "reports": reports,
        "source": source,
        "latest_url": url,
        "period": period or "N/A",
        "type": str(row.get("Type") or "N/A"),
        "evidence": evidence,
        "extraction_status": extraction_status,
        "pages": extracted_pages,
    }


REPORT_SIGNAL_PATTERNS = [
    ("Auditor qualification / control weakness", "High attention", [r"qualified opinion", r"modified opinion", r"material weakness(?:es)?", r"material uncertainty related to going concern", r"ineffective internal financial controls"]),
    ("Borrowing default / covenant", "High attention", [r"default in repayment", r"defaulted in repayment", r"breach of covenant", r"covenant breach", r"loan.*overdue.*\d+ days"]),
    ("Statutory dues / regulatory exposure", "Review", [r"undisputed statutory dues.*outstanding", r"disputed statutory dues", r"show cause notice", r"regulatory penalty"]),
    ("Contingencies / litigation", "Review", [r"contingent liabilities", r"claims not acknowledged as debt", r"pending litigations?", r"tax demands? under dispute"]),
    ("Related-party transactions", "Review", [r"related party transactions", r"related party balances", r"loans and advances to related parties"]),
    ("Impairment / asset valuation", "Review", [r"impairment loss", r"impairment of goodwill", r"impairment of property", r"recoverable amount"]),
    ("Exceptional / non-recurring items", "Review", [r"exceptional items?", r"one[- ]off items?", r"non[- ]recurring items?"]),
]


@st.cache_data(ttl=86400, show_spinner=False)
def annual_report_risk_signals(pdf_url: str, use_browser_fallback: bool = False) -> pd.DataFrame:
    """Extract disclosure-led review signals with source pages; never infer fraud.

    These are evidence pointers, not confirmed red flags. They are intentionally
    kept outside the forensic score until independently validated.
    """
    columns = ["Finding ID", "Disclosure area", "Attention", "Page", "Evidence", "Interpretation", "Source"]
    if not pdf_url:
        return pd.DataFrame(columns=columns)
    pages = extract_annual_report_pages(pdf_url, use_browser_fallback=use_browser_fallback)
    rows: List[Dict[str, Any]] = []
    for category, attention, patterns in REPORT_SIGNAL_PATTERNS:
        found = None
        for page in pages:
            text = _clean_text(page.get("text", ""))
            low = text.lower()
            for pattern in patterns:
                match = re.search(pattern, low, re.I)
                if not match:
                    continue
                # Avoid treating a plain negative assurance as an issue.
                context = low[max(0, match.start() - 90):min(len(low), match.end() + 110)]
                if re.search(r"no (?:instances? of |evidence of |such )?(?:qualified opinion|material weakness|default|covenant breach)", context):
                    continue
                start = max(0, match.start() - 90)
                end = min(len(text), match.end() + 130)
                quote = " ".join(text[start:end].split()[:28])
                # Skip a bare contents-page hit where a later page may contain the disclosure.
                if int(page.get("page", 0)) <= 2 and len(quote) < 70:
                    continue
                found = (int(page.get("page", 0)), quote, pattern)
                break
            if found:
                break
        if not found:
            continue
        page_no, quote, pattern = found
        digest = hashlib.sha1(f"{pdf_url}|{category}|{page_no}|{pattern}".encode("utf-8")).hexdigest()[:12].upper()
        rows.append({
            "Finding ID": f"AR-{digest}",
            "Disclosure area": category,
            "Attention": attention,
            "Page": page_no,
            "Evidence": quote,
            "Interpretation": "Disclosure located; assess materiality, trend and financial impact before classifying as a red flag.",
            "Source": pdf_url,
        })
    return pd.DataFrame(rows, columns=columns)


def evidence_for_flag_category(evidence_df: pd.DataFrame, category: str) -> Dict[str, Any]:
    """Return the most relevant annual-report evidence for a red-flag category."""
    topic = FLAG_TOPIC_MAP.get(category, "Notes to accounts")
    if evidence_df is None or evidence_df.empty or "Topic" not in evidence_df.columns:
        return {"topic": topic, "page": "N/A", "quote": "N/A"}
    rows = evidence_df[evidence_df["Topic"].astype(str).eq(topic)]
    if rows.empty:
        return {"topic": topic, "page": "N/A", "quote": "N/A"}
    r = rows.iloc[0]
    return {
        "topic": topic,
        "page": r.get("Page", "N/A"),
        "quote": r.get("Evidence quote", "N/A"),
    }
