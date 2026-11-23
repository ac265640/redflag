"""Public Indian-market filing connectors used by Governance, ESG and Credit pages.

Primary source priority:
1) NSE corporate filings / announcements
2) Yahoo Finance sustainability data as a supplemental ESG source
3) Rating-agency websites are linked as primary sources when an NSE rating announcement
   is found; the dashboard never invents a rating when no public rating is found.

NSE can occasionally block automated requests. All functions therefore return an
empty result plus a human-readable error instead of crashing the dashboard.
"""
from __future__ import annotations

import re
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import time
from urllib.parse import quote_plus, urljoin
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st

NSE_HOME = "https://www.nseindia.com/"
NSE_API = "https://www.nseindia.com/api"
NSE_GOV_URL = "https://www.nseindia.com/companies-listing/corporate-filings-governance"
NSE_INTEGRATED_URL = "https://www.nseindia.com/companies-listing/corporate-integrated-filing?integratedType=integratedfilinggovernance"
NSE_BRSR_URL = "https://www.nseindia.com/companies-listing/corporate-filings-bussiness-sustainabilitiy-reports"
NSE_ANN_URL = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"

# Verified NSE-published Integrated Filing – Governance iXBRL fallbacks for
# companies whose NSE listing tables are sometimes not exposed to automated
# clients. These are source URLs only; the values are still parsed from NSE.

NSE_GOV_TAXONOMY_URL = "https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Taxonomy_Integrated%20Governance_0.zip"

@st.cache_data(ttl=86400, show_spinner=False)
def _load_governance_taxonomy_labels() -> Dict[str, str]:
    """Load NSE's official Integrated Governance taxonomy labels.

    The raw filing is an XBRL instance and its element names are not guaranteed
    to be human-readable. The taxonomy maps those element names/ids to labels
    such as 'Independent Directors', 'Audit Committee' and 'Compliance status'.
    """
    labels: Dict[str, str] = {}
    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
            "Accept": "application/zip,application/octet-stream,*/*",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": NSE_HOME,
        })
        r = sess.get(NSE_GOV_TAXONOMY_URL, timeout=(2.5, 6))
        if not r.ok or len(r.content) < 1000:
            return labels
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(('.xml','.xsd'))]
            element_names: Dict[str, str] = {}
            for name in xml_names:
                try:
                    root = ET.fromstring(zf.read(name))
                except Exception:
                    continue
                for e in root.iter():
                    local = str(e.tag).rsplit('}',1)[-1]
                    if local == 'element':
                        en = e.attrib.get('name') or ''
                        eid = e.attrib.get('id') or ''
                        if en:
                            element_names[en] = en
                        if eid:
                            element_names[eid] = en or eid
            # XBRL label linkbases use labelArcs to connect locators to label resources.
            for name in xml_names:
                try:
                    root = ET.fromstring(zf.read(name))
                except Exception:
                    continue
                resources: Dict[str, str] = {}
                locs: Dict[str, str] = {}
                arcs: List[Tuple[str,str]] = []
                for e in root.iter():
                    local = str(e.tag).rsplit('}',1)[-1]
                    attrs = {str(k).rsplit('}',1)[-1]: v for k,v in e.attrib.items()}
                    if local == 'loc':
                        lab = attrs.get('label')
                        href = attrs.get('href') or attrs.get('resource') or ''
                        if lab:
                            locs[lab] = href.split('#')[-1]
                    elif local == 'label':
                        lab = attrs.get('label')
                        txt = ' '.join((e.itertext())) if e is not None else ''
                        txt = re.sub(r'\s+', ' ', txt).strip()
                        if lab and txt:
                            resources[lab] = txt
                    elif local == 'labelArc':
                        fr = attrs.get('from'); to = attrs.get('to')
                        if fr and to:
                            arcs.append((fr,to))
                for fr,to in arcs:
                    concept_id = locs.get(fr)
                    label = resources.get(to)
                    if concept_id and label:
                        labels[concept_id] = label
                        short = concept_id.split(':')[-1]
                        labels[short] = label
            # Fallback: element name itself is still useful when no label resource
            # is present in a particular taxonomy file.
            for key,val in element_names.items():
                labels.setdefault(key.split(':')[-1], val)
    except Exception:
        return labels
    return labels

def _taxonomy_aware_governance_facts(payload: bytes) -> Dict[str, Any]:
    """Extract governance facts from XBRL using the official NSE taxonomy.

    This supplements the heuristic parser. It uses labels + context dimensions
    instead of assuming the XBRL element names contain words like 'committee'.
    """
    out = {
        "board_total": None, "independent_directors": None,
        "audit_members": None, "nrc_members": None, "stakeholder_members": None,
        "risk_members": None, "committee_meetings": None, "committee_quorum_yes": None,
        "board_meetings": None, "board_quorum_yes": None,
        "affirmations_yes": None, "affirmations_no": None, "affirmations_na": None,
        "cyber_security_count": None, "investor_grievance_unresolved": None,
        "investor_grievance_pending": None, "investor_grievance_received": None,
        "investor_grievance_disposed": None,
    }
    try:
        root=ET.fromstring(payload)
    except Exception:
        return out
    label_map=_load_governance_taxonomy_labels()
    contexts: Dict[str, Dict[str, Any]] = {}
    for e in root.iter():
        if str(e.tag).rsplit('}',1)[-1] != 'context':
            continue
        cid=e.attrib.get('id')
        if not cid: continue
        members=[]
        for c in e.iter():
            if str(c.tag).rsplit('}',1)[-1] in {'explicitMember','typedMember'}:
                txt=(c.text or '').strip()
                if txt: members.append(txt.rsplit(':',1)[-1])
        contexts[cid]={"members":members}

    facts=[]
    for e in root.iter():
        tag=str(e.tag).rsplit('}',1)[-1]
        txt=(e.text or '').strip()
        if not txt: continue
        cref=e.attrib.get('contextRef')
        label=label_map.get(tag) or label_map.get(tag.split(':')[-1]) or tag
        facts.append({"tag":tag,"label":label,"text":txt,"context":contexts.get(cref,{})})

    def norm(x): return re.sub(r'[^a-z0-9]+',' ',str(x).lower()).strip()
    def num(x):
        m=re.search(r'-?\d+(?:\.\d+)?',str(x).replace(',',''))
        return float(m.group()) if m else None
    # IMPORTANT: context cardinality is NOT a committee/member count. One
    # director can generate multiple XBRL contexts and one context can represent
    # a whole dimensional row. We therefore never infer committee membership or
    # meeting counts from the number of contexts. Those fields must come from an
    # actual filing table (iXBRL/PDF) or remain N/A.

    # Numeric fact candidates. Labels are much more stable than raw concept names.
    for f in facts:
        l=norm(f['label']); v=num(f['text'])
        if v is None: continue
        if out['board_total'] is None and re.search(r'number of directors|total number of directors|no of directors',l) and 'committee' not in l:
            if v <= 100: out['board_total']=int(v)
        if out['independent_directors'] is None and re.search(r'(number|no) of independent director|independent directors',l) and not re.search(r'listed entit|percentage|%',l):
            if v <= 100: out['independent_directors']=int(v)
        if out['cyber_security_count'] is None and 'number of cyber' in l:
            if v <= 1000: out['cyber_security_count']=int(v)
        if out['investor_grievance_pending'] is None and 'investor complaint' in l and 'pending at the beginning' in l: out['investor_grievance_pending']=int(v)
        if out['investor_grievance_received'] is None and 'investor complaint' in l and 'received during' in l: out['investor_grievance_received']=int(v)
        if out['investor_grievance_disposed'] is None and 'investor complaint' in l and 'disposed' in l: out['investor_grievance_disposed']=int(v)
        if out['investor_grievance_unresolved'] is None and 'investor complaint' in l and 'unresolved' in l: out['investor_grievance_unresolved']=int(v)

    # Committee membership and meeting counts intentionally remain unset here.
    # They are populated only by row-aware iXBRL/PDF parsers below.

    # Do not aggregate repeated dimensional status facts as counts. XBRL can
    # repeat a label across periods/sections; only a row-aware HTML/PDF parser
    # can safely count affirmation and quorum records.
    return out

KNOWN_GOVERNANCE_XBRL = {
    # Exact official NSE iXBRL documents verified to exist. These are lower-
    # priority, period-labelled fallbacks only; no values are hard-coded.
    "ULTRACEMCO": [
        "https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_GOVERNANCE_152848_25042026111939_iXBRL_WEB.html",
    ],
    "RAJESHEXPO": [
        "https://nsearchives.nseindia.com/corporate/ixbrl/INTEGRATED_FILING_GOVERNANCE_152286_23042026135612_iXBRL_WEB.html",
    ],
}

RATING_AGENCY_URLS = {
    "CRISIL": "https://www.crisilratings.com/",
    "ICRA": "https://www.icra.in/",
    "CARE Ratings": "https://www.careratings.com/",
    "India Ratings": "https://www.indiaratings.co.in/",
    "Acuité": "https://www.acuite.in/",
    "Brickwork": "https://www.brickworkratings.com/",
}

RATING_RATIONALE_URLS = {
    "CRISIL": "https://www.crisilratings.com/en/home/our-business/ratings/rating-rationale.html",
    "ICRA": "https://www.icra.in/Rating",
    "CARE Ratings": "https://www.careratings.com/report/find-ratings",
    "India Ratings": "https://www.indiaratings.co.in/",
    "Acuité": "https://www.acuite.in/",
    "Brickwork": "https://www.brickworkratings.com/",
}



def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain,*/*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": NSE_HOME,
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
    })
    return s


def _nse_prime_page(path: str) -> str:
    """Choose the filings page associated with an NSE API family."""
    p = str(path or "").lower()
    if "integrated-filing" in p:
        return NSE_INTEGRATED_URL
    if "share-holdings" in p or "shareholding" in p:
        return "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
    if "annual-report" in p:
        return "https://www.nseindia.com/companies-listing/corporate-filings-annual-reports"
    if "bussiness-sustainabilitiy" in p or "brsr" in p:
        return NSE_BRSR_URL
    return NSE_ANN_URL


def _nse_json(path: str, params: Dict[str, Any], timeout: int = 7) -> Any:
    """Fetch a public NSE JSON endpoint with a section-page-primed session.

    NSE's home page is a poor universal cookie primer and can time out while the
    corresponding filings page/API is reachable. Keep both the prime and API
    timeout bounded; callers can then show a clear source-unavailable state.
    """
    s = _session()
    try:
        try:
            s.get(_nse_prime_page(path), timeout=(2.5, 4.5), allow_redirects=True)
        except requests.RequestException:
            # Continue once with this session: some NSE API responses work even
            # when the page shell is blocked by an anti-bot layer.
            pass
        endpoint = f"{NSE_API}/{str(path).lstrip('/')}"
        r = s.get(endpoint, params=params, timeout=(2.5, timeout), allow_redirects=True)
        r.raise_for_status()
        return r.json()
    finally:
        s.close()


def _rows(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "results", "records", "rows", "result"):
        val = payload.get(key)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
        if isinstance(val, dict):
            nested = _rows(val)
            if nested:
                return nested
    return []


def _first(d: Dict[str, Any], *names: str) -> Any:
    low = {str(k).lower().replace(" ", "").replace("_", ""): v for k, v in d.items()}
    for n in names:
        k = n.lower().replace(" ", "").replace("_", "")
        if k in low:
            return low[k]
    return None


def _link(v: Any) -> str:
    """Return the first usable URL from NSE's inconsistent attachment/XBRL structures."""
    if not v:
        return ""
    if isinstance(v, dict):
        preferred = ("url", "link", "file", "fileLink", "attachment", "attachmentLink", "xbrl", "xbrlLink", "href", "path")
        for k in preferred:
            if k in v:
                got = _link(v.get(k))
                if got:
                    return got
        for val in v.values():
            got = _link(val)
            if got:
                return got
        return ""
    if isinstance(v, (list, tuple)):
        for item in v:
            got = _link(item)
            if got:
                return got
        return ""
    text = str(v).strip()
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("/"):
        return "https://www.nseindia.com" + text
    return ""


def _normalize_records(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    out = []
    for r in rows:
        out.append({
            "Company Name": _first(r, "companyName", "company", "company_name", "name"),
            "Date": _first(r, "broadcastDateTime", "broadcastDate", "date", "submissionDate", "originalSubmissionDate"),
            "Quarter / Period": _first(r, "quarterEndDate", "periodEnded", "quarterEnd", "period"),
            "Type": _first(r, "typeOfSubmission", "filingType", "type", "subject", "desc", "category"),
            "Details": _first(r, "details", "description", "subject", "remarks", "attchmntText", "attachmentText", "text"),
            "Attachment": _link(_first(r,
                "attachment", "attachmentLink", "attachmentFile", "attchmntFile",
                "attchmntFileLink", "fileLink", "file", "document", "documentLink")),
            "XBRL": _link(_first(r,
                "xbrl", "xbrlFileLink", "xbrlLink", "xbrlFile", "xbrlFilePath",
                "xbrlUrl", "xbrlURL")),
            "iXBRL": _link(_first(r,
                "ixbrl", "ixbrlFileLink", "ixbrlLink", "ixbrlFile", "ixbrlFilePath",
                "ixbrlUrl", "ixbrlURL", "htmlFileLink", "htmlUrl")),
            "Source": _link(_first(r, "source", "url", "link", "sourceUrl", "sourceURL")),
        })
    df = pd.DataFrame(out)
    if not df.empty:
        for c in ("Date", "Quarter / Period"):
            df[c] = df[c].astype(str).replace({"None": "", "nan": ""})
    return df


def _selenium_nse_page_source(url: str, wait_texts: tuple[str, ...], timeout: int = 35) -> str:
    """Load an NSE client-rendered page in local Chrome and return its DOM."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        options.add_argument("--window-size=1920,1400")
        options.add_argument("--lang=en-US")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
        driver = webdriver.Chrome(options=options)
        try:
            driver.get(url)
            WebDriverWait(driver, timeout).until(
                lambda d: any(text.lower() in d.page_source.lower() for text in wait_texts)
            )
            # Give NSE's client-side tables a moment to finish populating.
            time.sleep(1.5)
            return driver.page_source
        finally:
            driver.quit()
    except Exception:
        return ""


def _parse_integrated_governance_html(html: str, symbol: str) -> pd.DataFrame:
    """Parse the client-rendered NSE Integrated Filing – Governance table."""
    if not html:
        return pd.DataFrame()
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        records = []
        for table in soup.find_all("table"):
            headers = [re.sub(r"\s+", " ", x.get_text(" ", strip=True)).strip().lower() for x in table.find_all("th")]
            header_blob = " | ".join(headers)
            if not ("symbol" in header_blob and "company name" in header_blob and "quarter end date" in header_blob and "xbrl" in header_blob):
                continue
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if len(cells) < 5:
                    continue
                texts = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in cells]
                row_blob = " | ".join(texts)
                if symbol.upper() not in row_blob.upper():
                    continue
                links = []
                for c in cells:
                    a = c.find("a", href=True)
                    links.append(_absolute_nse_url(a.get("href")) if a else "")
                # Find columns by header position; NSE occasionally adds/removes
                # descriptive columns, so do not rely on fixed indexes.
                def idx(patterns, default):
                    for i, h in enumerate(headers):
                        if any(p in h for p in patterns):
                            return i
                    return default
                si = idx(("symbol",), 0)
                ci = idx(("company name",), 1)
                qi = idx(("quarter end",), 2)
                ti = idx(("type of submission",), 3)
                di = idx(("details",), 4)
                ai = idx(("attachment",), 5)
                xi = idx(("xbrl",), 6)
                bi = idx(("broadcast date",), 7)
                ri = idx(("revised date",), 8)
                rmi = idx(("revision remarks",), 9)
                records.append({
                    "Date": texts[bi] if bi < len(texts) else "",
                    "Quarter / Period": texts[qi] if qi < len(texts) else "",
                    "Type": texts[ti] if ti < len(texts) else "",
                    "Details": texts[di] if di < len(texts) else "",
                    "Attachment": links[ai] if ai < len(links) else "",
                    "XBRL": links[xi] if xi < len(links) else "",
                    "Source": f"{NSE_INTEGRATED_URL}&symbol={quote_plus(symbol)}",
                    "Revised Date": texts[ri] if ri < len(texts) else "",
                    "Revision Remarks": texts[rmi] if rmi < len(texts) else "",
                })
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        return df.drop_duplicates(subset=["Date", "Quarter / Period", "Type", "Details", "XBRL"]).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def _fetch_governance_filings_with_browser(symbol: str) -> pd.DataFrame:
    url = f"{NSE_INTEGRATED_URL}&symbol={quote_plus(symbol)}"
    html = _selenium_nse_page_source(url, ("Integrated Filing- Governance", "Quarter End Date", "Convert XBRL into Excel"), timeout=15)
    return _parse_integrated_governance_html(html, symbol)


def _governance_detail_html_has_rows(html: str) -> Tuple[bool, int, str]:
    """Return True only when the page contains an actual populated Board table.

    Generic NSE page shells contain the words 'Audit Committee', 'Yes' and
    'No' even when no company has been selected. Requiring multiple distinct
    director DINs in a Board table avoids treating that empty shell as data.
    """
    if not html:
        return False, 0, "empty_html"
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        return False, 0, f"html_parse:{type(exc).__name__}"

    best = 0
    for table in soup.find_all("table"):
        text = re.sub(r"\s+", " ", table.get_text(" ", strip=True)).lower()
        if not ("name of the director" in text or ("category 1 of directors" in text and "din" in text)):
            continue
        dins = set(re.findall(r"\b\d{8}\b", table.get_text(" ", strip=True)))
        # NSE board tables have at least three directors for an operating listed
        # company; unique DINs prove rows are present, unlike generic labels.
        best = max(best, len(dins))
    if best >= 3:
        return True, best, "populated_board_table"
    # Fallback for NSE's occasional div-based rendering: require director IDs
    # across the page and the board and committee section labels.
    full = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).lower()
    dins = set(re.findall(r"\b\d{8}\b", full))
    if len(dins) >= 3 and "composition of board of directors" in full and "audit committee" in full:
        return True, len(dins), "populated_dom_rows"
    return False, max(best, len(dins) if 'dins' in locals() else 0), "no_populated_governance_rows"


def _fetch_governance_detail_html_verified(symbol: str, browser_fallback: bool = False) -> Tuple[str, List[str]]:
    """Fetch a genuinely populated NSE Governance detail page.

    The page's query string does not reliably pre-select the company. This
    function therefore verifies the actual table rows and, in Chrome, uses the
    input labelled 'Company Name or Symbol' rather than NSE's global search.
    An unpopulated HTML shell is never returned as a data source.
    """
    messages: List[str] = []
    sym = str(symbol or "").split(".")[0].strip().upper()
    if not sym:
        return "", ["detail_page:no_symbol"]

    static_url = f"{NSE_GOV_URL}?symbol={quote_plus(sym)}&tabIndex=equity"
    try:
        r = _session().get(static_url, timeout=(3, 7))
        if r.ok and len(r.text) > 5000:
            populated, n_dins, why = _governance_detail_html_has_rows(r.text)
            if populated:
                messages.append(f"detail_page:requests_populated:{n_dins}_unique_DINs")
                return r.text, messages
            messages.append(f"detail_page:requests_shell_only:{why}:{n_dins}_DINs")
        else:
            messages.append(f"detail_page:requests_http:{r.status_code}:{len(r.text)}")
    except Exception as exc:
        messages.append(f"detail_page:requests:{type(exc).__name__}")

    if not browser_fallback:
        messages.append("detail_page:browser_fallback_not_run")
        return "", messages

    # Selenium fallback: explicitly locate the NSE governance selector. The
    # prior implementation matched the first input containing 'symbol', which
    # could be the global market-wide search box and leave the Governance panel
    # empty while still returning its shell HTML.
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait, Select

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        options.add_argument("--window-size=1920,1800")
        options.add_argument("--lang=en-IN")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")
        options.page_load_strategy = "eager"
        driver = webdriver.Chrome(options=options)
        try:
            driver.set_page_load_timeout(20)
            # Load the generic page so the query parameter does not get mistaken
            # for evidence that the selected company has actually loaded.
            try:
                driver.get(f"{NSE_GOV_URL}?tabIndex=equity")
            except Exception as exc:
                messages.append(f"detail_page:selenium_navigation:{type(exc).__name__}")

            wait = WebDriverWait(driver, 10)
            try:
                wait.until(lambda d: "Corporate Governance" in d.page_source)
            except Exception:
                messages.append("detail_page:selenium_shell_not_ready")

            # Prefer exact label/placeholder selectors and rank visible inputs.
            company_input = None
            try_selectors = (
                "input[placeholder*='Company Name or Symbol' i]",
                "input[aria-label*='Company Name or Symbol' i]",
                "input[placeholder*='Company Name' i]",
                "input[aria-label*='Company Name' i]",
            )
            for selector in try_selectors:
                try:
                    visible = [el for el in driver.find_elements(By.CSS_SELECTOR, selector)
                               if el.is_displayed() and el.is_enabled()]
                    if visible:
                        company_input = visible[-1]
                        break
                except Exception:
                    continue

            # Attribute-based fallback, with hard exclusions for global search.
            if company_input is None:
                scored = []
                for el in driver.find_elements(By.CSS_SELECTOR, "input"):
                    try:
                        if not el.is_displayed() or not el.is_enabled():
                            continue
                        attrs = " ".join(str(el.get_attribute(a) or "") for a in
                                          ("placeholder", "aria-label", "name", "id", "class")).lower()
                        if "search by company name, index" in attrs or "index, symbol" in attrs or "global-search" in attrs:
                            continue
                        score = 0
                        if "company name or symbol" in attrs: score += 100
                        elif "company name" in attrs and "symbol" in attrs: score += 80
                        elif "company" in attrs and "symbol" in attrs: score += 50
                        elif "symbol" in attrs and "search" not in attrs: score += 20
                        if score:
                            scored.append((score, el))
                    except Exception:
                        continue
                if scored:
                    scored.sort(key=lambda pair: pair[0], reverse=True)
                    company_input = scored[0][1]

            if company_input is None:
                messages.append("detail_page:governance_company_selector_not_found")
            else:
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", company_input)
                    company_input.click()
                    company_input.send_keys(Keys.CONTROL, "a")
                    company_input.send_keys(sym)
                    time.sleep(1.2)

                    # Select the suggestion matching the exact ticker token.
                    clicked = False
                    for _ in range(3):
                        suggestions = driver.find_elements(
                            By.CSS_SELECTOR,
                            "[role='option'], li, .autocomplete-item, .suggestion-item, [class*='suggestion']"
                        )
                        for item in suggestions:
                            try:
                                if not item.is_displayed():
                                    continue
                                tx = re.sub(r"\s+", " ", item.text or "").strip().upper()
                                if tx and re.search(rf"(?<![A-Z0-9]){re.escape(sym)}(?![A-Z0-9])", tx):
                                    driver.execute_script("arguments[0].click();", item)
                                    clicked = True
                                    break
                            except Exception:
                                continue
                        if clicked:
                            break
                        time.sleep(0.5)
                    if not clicked:
                        company_input.send_keys(Keys.ENTER)
                    messages.append("detail_page:company_selector_submitted" if clicked else "detail_page:company_enter_submitted")
                except Exception as exc:
                    messages.append(f"detail_page:company_selection:{type(exc).__name__}")

            # First wait for actual Board rows. Do not accept a symbol visible in
            # an input or a generic 'Yes/No' label as proof of a loaded filing.
            try:
                wait.until(lambda d: _governance_detail_html_has_rows(d.page_source)[0])
            except Exception:
                # NSE sometimes loads rows only after the quarter selector fires.
                # Locate the selector whose nearby DOM text actually says
                # 'For Quarter Ending'; do not change an unrelated date filter.
                try:
                    quarter_selects = []
                    for sel in driver.find_elements(By.TAG_NAME, "select"):
                        try:
                            context = driver.execute_script(
                                "let n=arguments[0], t=''; for(let i=0;i<5 && n;i++,n=n.parentElement){t+=' '+(n.innerText||'');} return t;", sel
                            ).lower()
                            opts = sel.find_elements(By.TAG_NAME, "option")
                            date_opts = []
                            for opt in opts:
                                tx = (opt.text or "").strip()
                                dt = pd.to_datetime(tx, errors="coerce", dayfirst=True)
                                if not pd.isna(dt):
                                    date_opts.append((dt, opt.get_attribute("value"), tx))
                            if "quarter ending" in context and date_opts:
                                quarter_selects.append((sel, date_opts))
                        except Exception:
                            continue
                    if quarter_selects:
                        sel, date_opts = quarter_selects[0]
                        newest = sorted(date_opts, key=lambda x: x[0], reverse=True)[0]
                        value = newest[1]
                        try:
                            Select(sel).select_by_value(value)
                        except Exception:
                            driver.execute_script(
                                "arguments[0].value=arguments[1]; arguments[0].dispatchEvent(new Event('input',{bubbles:true})); arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                                sel, value
                            )
                        messages.append(f"detail_page:quarter_selected:{newest[2]}")
                        try:
                            wait.until(lambda d: _governance_detail_html_has_rows(d.page_source)[0])
                        except Exception:
                            pass
                except Exception as exc:
                    messages.append(f"detail_page:quarter_selector:{type(exc).__name__}")

            html = driver.page_source
            populated, n_dins, why = _governance_detail_html_has_rows(html)
            if populated:
                messages.append(f"detail_page:selenium_populated:{n_dins}_unique_DINs")
                return html, messages

            # Include a small sample of browser API resources in the diagnostics;
            # this helps identify future NSE frontend endpoint changes without
            # displaying or persisting company cookies/session tokens.
            try:
                resources = driver.execute_script("return performance.getEntriesByType('resource').map(x=>x.name).filter(x=>x.includes('/api/'))")
                resources = list(dict.fromkeys(str(x).split('?')[0] for x in (resources or [])))[:8]
                if resources:
                    messages.append("detail_page:api_resources:" + ",".join(resources))
            except Exception:
                pass
            messages.append(f"detail_page:selenium_no_rows:{why}:{n_dins}_DINs")
        finally:
            driver.quit()
    except Exception as exc:
        messages.append(f"detail_page:selenium_error:{type(exc).__name__}:{str(exc)[:160]}")

    return "", messages


def _fetch_governance_detail_html(symbol: str) -> str:
    """Backward-compatible wrapper; only returns actual populated governance HTML."""
    html, _messages = _fetch_governance_detail_html_verified(symbol)
    return html

def _extract_governance_detail_page_html(html: str, source_url: str = "") -> Dict[str, Any]:
    """Parse the populated NSE Corporate Governance detail page.

    This is a separate parser from the iXBRL parser because NSE's public
    governance page has different HTML/table structure. It reads only visible
    filing fields. Missing values remain None.
    """
    result = {
        "source_url": source_url,
        "board_total": None, "independent_directors": None,
        "chairperson_regular": None, "chairperson_related_to_md_ceo": None,
        "audit_members": None, "nrc_members": None, "stakeholder_members": None,
        "risk_members": None, "committee_meetings": None, "board_meetings": None,
        "committee_quorum_yes": None, "board_quorum_yes": None,
        "affirmations_yes": None, "affirmations_no": None, "affirmations_na": None,
        "cyber_security_count": None, "cyber_security_text": None,
        "investor_grievance_pending": None, "investor_grievance_received": None,
        "investor_grievance_disposed": None, "investor_grievance_unresolved": None,
        "investor_grievance_text": None, "signatory": None,
        "errors": [], "parse_status": "failed", "retrieval_stage": "detail_page_parser",
    }
    if not html:
        return result
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        result["errors"].append(f"detail_html:{type(exc).__name__}")
        return result

    def clean(x):
        return re.sub(r"\s+", " ", str(x or "")).strip()

    tables = soup.find_all("table")
    parsed_tables = []
    for table in tables:
        rows=[]
        for tr in table.find_all("tr"):
            cells=[clean(c.get_text(" ", strip=True)) for c in tr.find_all(["th","td"])]
            if cells:
                rows.append(cells)
        if rows:
            parsed_tables.append((table, rows))

    def blob(rows):
        return " ".join(" | ".join(r) for r in rows).lower()

    def active_row(cells):
        low=" | ".join(cells).lower()
        if not re.search(r"\b\d{5,9}\b", low):
            return False
        # Current governance tables expose status/cessation columns. Do not
        # count a director/member whose cessation date is populated.
        dates=re.findall(r"\b\d{1,2}[-/]\w{3}[-/]\d{4}\b", low)
        if len(dates)>=2 and "cessation" in low:
            # In a generic row, appointment + cessation means the final date is
            # normally cessation. If the row says active/current, keep it.
            if not re.search(r"\bactive\b|\bcurrent\b", low):
                return False
        return True

    # Board table: header names vary slightly between NSE revisions.
    for table, rows in parsed_tables:
        b=blob(rows)
        if not ("name of the director" in b or ("din" in b and "category 1 of directors" in b)):
            continue
        header=next((r for r in rows if any("name of the director" in c.lower() for c in r)), None)
        if header:
            h=[c.lower() for c in header]
            cat_i=next((i for i,c in enumerate(h) if "category 1" in c), None)
            status_i=next((i for i,c in enumerate(h) if "current status" in c), None)
            cess_i=next((i for i,c in enumerate(h) if "date of cessation" in c), None)
            din_i=next((i for i,c in enumerate(h) if c == "din" or c.endswith(" din") or "din number" in c), None)
            name_i=next((i for i,c in enumerate(h) if "name of the director" in c), None)
            identities=set(); independent_ids=set()
            for r in rows:
                if not active_row(r): continue
                status=r[status_i].lower() if status_i is not None and status_i < len(r) else ""
                cess=r[cess_i].strip().lower() if cess_i is not None and cess_i < len(r) else ""
                if status and status not in {"active","current"}: continue
                if cess and cess not in {"na","n/a","-","none"}: continue
                din = r[din_i].strip() if din_i is not None and din_i < len(r) else ""
                name = r[name_i].strip().lower() if name_i is not None and name_i < len(r) else ""
                identity = ("din:" + din) if re.fullmatch(r"\d{5,9}", din) and set(din) != {"0"} else ("name:" + name if name else "")
                if not identity or identity in identities: continue
                identities.add(identity)
                cat=r[cat_i].lower() if cat_i is not None and cat_i < len(r) else ""
                if "independent director" in cat:
                    independent_ids.add(identity)
            if identities:
                result["board_total"]=len(identities)
                result["independent_directors"]=len(independent_ids)
        break

    # Committee tables. NSE standard header is:
    # Sr | DIN Number | Name of Committee members | Category 1 | Category 2 |
    # Date of Appointment | Date of Cessation | Remarks
    committee_targets=(
        ("audit_members", ("audit committee details", "audit committee")),
        ("nrc_members", ("nomination and remuneration committee", "nomination & remuneration committee")),
        ("stakeholder_members", ("stakeholders relationship committee", "stakeholder relationship committee", "stakeholders committee")),
        ("risk_members", ("risk management committee",)),
    )
    for table, rows in parsed_tables:
        b=blob(rows)
        if "name of committee members" not in b or "din number" not in b:
            continue
        # Determine the section for THIS exact DOM table. The old implementation
        # re-found a table by comparing its first row, which is identical across
        # Audit/NRC/Stakeholder/Risk tables and caused wrong or missing mappings.
        section = ""
        target_terms = [term for _key, terms in committee_targets for term in terms]
        for h in table.find_all_previous(["h1", "h2", "h3", "h4", "h5", "h6"], limit=20):
            tx = clean(h.get_text(" ", strip=True)).lower()
            if tx and any(term in tx for term in target_terms):
                section = tx
                break
        if not section:
            # Some NSE revisions use paragraphs/divs for section headings.
            for node in table.find_all_previous(["p", "div", "span", "strong", "b"], limit=80):
                tx = clean(node.get_text(" ", strip=True)).lower()
                if 4 < len(tx) < 140 and any(term in tx for term in target_terms):
                    section = tx
                    break
        key = None
        for k, labels in committee_targets:
            if any(label in section for label in labels):
                key = k
                break
        # If the title is rendered as a table caption/heading in the table itself,
        # permit that explicit label; never infer from person rows or XBRL contexts.
        if key is None:
            for k, labels in committee_targets:
                if any(label in b for label in labels) and "name of committee members" in b:
                    key = k
                    break
        if not key: continue
        header=next((r for r in rows if "name of committee members" in " | ".join(r).lower()), None)
        h=[c.lower() for c in (header or [])]
        din_i=next((i for i,c in enumerate(h) if "din number" in c or c == "din" or c.endswith(" din")), None)
        name_i=next((i for i,c in enumerate(h) if "name of committee members" in c), None)
        cess_i=next((i for i,c in enumerate(h) if "date of cessation" in c), None)
        identities=set()
        for r in rows:
            if header and r==header: continue
            if not re.search(r"\b\d{5,9}\b", " | ".join(r)): continue
            cess=r[cess_i].strip().lower() if cess_i is not None and cess_i < len(r) else ""
            if cess and cess not in {"na","n/a","-","none"}: continue
            din=r[din_i].strip() if din_i is not None and din_i < len(r) else ""
            name=r[name_i].strip().lower() if name_i is not None and name_i < len(r) else ""
            identity=("din:"+din) if re.fullmatch(r"\d{5,9}",din) and set(din)!={"0"} else ("name:"+name if name else "")
            if identity: identities.add(identity)
        if identities:
            result[key]=len(identities)

    # Chairperson flags.
    alltxt=clean(soup.get_text(" ",strip=True))
    for pat,key in [
        (r"whether (?:the )?listed entity has a regular chairperson\s*[:|]?\s*(yes|no)","chairperson_regular"),
        (r"whether chairperson is related to md or ceo\s*[:|]?\s*(yes|no)","chairperson_related_to_md_ceo"),
    ]:
        m=re.search(pat, alltxt, re.I)
        if m: result[key]=m.group(1).title()

    # Meetings: count distinct disclosed meeting rows and read the exact quorum column.
    board_dates=set(); board_quorum_dates=set()
    committee_keys=set(); committee_quorum_keys=set()
    for table, rows in parsed_tables:
        b=blob(rows)
        header=next((r for r in rows if "date(s) of meeting" in " | ".join(r).lower()), None)
        if header is None:
            continue
        h=[c.lower() for c in header]
        date_i=next((i for i,c in enumerate(h) if "date(s) of meeting" in c or "date of meeting" in c), None)
        quorum_i=next((i for i,c in enumerate(h) if "quorum met" in c), None)
        name_i=next((i for i,c in enumerate(h) if "name of committee" in c), None)
        total_i=next((i for i,c in enumerate(h) if "total number of directors" in c), None)
        for r in rows:
            if r==header or date_i is None or date_i>=len(r):
                continue
            date=clean(r[date_i])
            if not re.search(r"\b\d{1,2}[-/]\w{3}[-/]\d{4}\b", date):
                continue
            quorum = quorum_i is not None and quorum_i < len(r) and r[quorum_i].strip().lower()=="yes"
            if total_i is not None or "total number of directors" in b:
                board_dates.add(date)
                if quorum: board_quorum_dates.add(date)
            elif name_i is not None or "name of committee" in b:
                name = r[name_i].strip().lower() if name_i is not None and name_i < len(r) else "committee"
                key=(name,date)
                committee_keys.add(key)
                if quorum: committee_quorum_keys.add(key)
    if board_dates:
        result["board_meetings"]=len(board_dates)
        result["board_quorum_yes"]=len(board_quorum_dates)
    if committee_keys:
        result["committee_meetings"]=len(committee_keys)
        result["committee_quorum_yes"]=len(committee_quorum_keys)

    # Compliance / annual affirmations.
    yes=no=na=0
    for table, rows in parsed_tables:
        b=blob(rows)
        if "compliance status" not in b: continue
        for r in rows:
            status=next((c.strip().lower() for c in reversed(r) if c.strip().lower() in {"yes","no","na","n/a"}),None)
            if status=="yes": yes+=1
            elif status=="no": no+=1
            elif status in {"na","n/a"}: na+=1
    if yes or no or na:
        result["affirmations_yes"]=yes; result["affirmations_no"]=no; result["affirmations_na"]=na

    # Cyber-security: parse the value only when it is attached to the specific
    # NSE question, not the word 'cyber' elsewhere in the page.
    m=re.search(r"Whether as per Regulation 27\(2\)\(ba\).*?(?:\|\s*|:\s*|\s+)(Yes|No)", alltxt, re.I)
    if m:
        result["cyber_security_text"]=m.group(1).title()
    m2=re.search(r"Number of cyber security incidence or breaches or loss of data event (?:occured|occurred) during the quarter\s*(?:\|\s*|:\s*|\s+)(\d+)", alltxt, re.I)
    if m2: result["cyber_security_count"]=int(m2.group(1))

    # Investor grievance fields.
    inv_patterns={
        "investor_grievance_pending": r"No\. of investor complaints pending at the beginning of Quarter\s*(?:\|\s*|:\s*|\s+)(\d+)",
        "investor_grievance_received": r"No\. of investor complaints received during the Quarter\s*(?:\|\s*|:\s*|\s+)(\d+)",
        "investor_grievance_disposed": r"No\. of investor complaints disposed off during the Quarter\s*(?:\|\s*|:\s*|\s+)(\d+)",
        "investor_grievance_unresolved": r"No\. of investor complaints those remaining unresolved at the end of the Quarter\s*(?:\|\s*|:\s*|\s+)(\d+)",
    }
    for k,pat in inv_patterns.items():
        m=re.search(pat,alltxt,re.I)
        if m: result[k]=int(m.group(1))

    # Signatory / compliance officer.
    m=re.search(r"Name of signatory\s*(?:\|\s*|:\s*|\s+)([^|]+?)(?= Designation| Place| Date|$)", alltxt, re.I)
    if m: result["signatory"]=clean(m.group(1))

    useful=("board_total","independent_directors","audit_members","nrc_members","stakeholder_members","risk_members","committee_meetings","board_meetings","affirmations_yes","affirmations_no","cyber_security_count","investor_grievance_unresolved")
    n=sum(result.get(k) is not None for k in useful)
    result["parse_status"]="parsed" if n>=2 else ("partial" if n else "failed")
    return result


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_governance_filings(ticker: str, use_browser_fallback: bool = False) -> Tuple[pd.DataFrame, str]:
    """Fetch NSE Integrated Filing – Governance metadata using two complementary routes.

    The API is the fast catalog route, while the Chrome-rendered NSE page is used
    as a second catalog route because the browser table exposes the *actual*
    Attachment/XBRL hrefs.  We MERGE both instead of returning as soon as one
    route succeeds; this fixes the common case where the API returns the XBRL
    URL but omits the PDF attachment.
    """
    symbol = ticker.split(".")[0].upper()
    errors = []
    frames = []

    api_params = (
        {"index": "equities", "symbol": symbol, "type": "Integrated Filing- Governance", "page": 1, "size": 50},
        {"index": "equities", "symbol": symbol, "type": "Integrated Filing - Governance", "page": 1, "size": 50},
    )
    for params in api_params:
        try:
            data = _nse_json("/integrated-filing-results", params)
            rows = _rows(data)
            df = _normalize_records(rows)
            if not df.empty:
                frames.append(df)
                break
        except Exception as e:
            errors.append(f"api:{type(e).__name__}")

    # Chrome/Selenium is intentionally opt-in. Starting a local browser during
    # every page visit made company navigation slow and could stall on driver
    # setup. The primary API and source-linked records remain available first.
    if use_browser_fallback:
        try:
            browser_df = _fetch_governance_filings_with_browser(symbol)
            if not browser_df.empty:
                frames.append(browser_df)
        except Exception as e:
            errors.append(f"browser:{type(e).__name__}")
    elif not frames:
        errors.append("browser fallback not run (use the page's browser retry control)")

    if frames:
        df = pd.concat(frames, ignore_index=True, sort=False)
        # Normalize common URL columns once more after the merge.
        for col in ("Attachment", "XBRL", "iXBRL", "Source"):
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].map(_absolute_nse_url)
        # Keep the newest representation of each filing. Prefer rows that have
        # an attachment and/or XBRL link when otherwise identical.
        df["_has_attachment"] = df["Attachment"].astype(str).str.startswith("http")
        df["_has_xbrl"] = df["XBRL"].astype(str).str.startswith("http")
        df["_date_sort"] = pd.to_datetime(df.get("Date", ""), errors="coerce", dayfirst=True)
        df = (df.sort_values(["_date_sort", "_has_attachment", "_has_xbrl"],
                             ascending=[False, False, False], na_position="last")
                .drop_duplicates(subset=["Date", "Quarter / Period", "Type", "Details", "XBRL", "iXBRL", "Attachment"], keep="first")
                .drop(columns=["_has_attachment", "_has_xbrl", "_date_sort"], errors="ignore")
                .reset_index(drop=True))
        return df, "NSE Integrated Filing – Governance (API + browser catalog)"

    return pd.DataFrame(), "NSE unavailable: " + ", ".join(errors or ["no records"])


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_governance_announcements(ticker: str, days: int = 730) -> Tuple[pd.DataFrame, str]:
    symbol = ticker.split(".")[0].upper()
    end = datetime.now().date()
    start = end - timedelta(days=days)
    try:
        data = _nse_json("/corporate-announcements", {
            "index": "equities", "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y"),
        })
        rows = _rows(data)
        df = _normalize_records(rows)
        if not df.empty:
            text = (df["Type"].astype(str) + " " + df["Details"].astype(str)).str.lower()
            mask = text.str.contains("governance|board|director|auditor|related party|compliance|investor grievance|committee|agm|appointment|resignation", regex=True, na=False)
            df = df.loc[mask].reset_index(drop=True)
        return df, "NSE Corporate Announcements"
    except Exception as e:
        return pd.DataFrame(), f"NSE unavailable: {type(e).__name__}"


def _absolute_nse_url(href: str) -> str:
    href = str(href or '').strip()
    if not href:
        return ''
    return urljoin('https://www.nseindia.com/', href)


def _parse_brsr_html(html: str, symbol: str = '') -> pd.DataFrame:
    """Parse the rendered NSE BRSR table and preserve the actual attachment/XBRL hrefs."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')
        tables = soup.find_all('table')
        records = []
        for table in tables:
            headers = [re.sub(r'\s+', ' ', th.get_text(' ', strip=True)).strip().lower() for th in table.find_all('th')]
            if not headers or not any('company' in h for h in headers):
                continue
            for tr in table.find_all('tr'):
                cells = tr.find_all(['td', 'th'])
                if not cells or len(cells) < 4:
                    continue
                texts = [re.sub(r'\s+', ' ', c.get_text(' ', strip=True)).strip() for c in cells]
                blob = ' '.join(texts).lower()
                if 'company' in blob and 'from year' in blob:
                    continue
                # NSE columns: Company, From Year, To Year, Attachment, XBRL, Original Submission Date, Latest Revision Date
                def idx(name, default):
                    for i,h in enumerate(headers):
                        if name in h: return i
                    return default
                ci, fi, ti, ai, xi, oi, ri = [idx(x, d) for x,d in [
                    ('company',0), ('from year',1), ('to year',2), ('attachment',3), ('xbrl',4), ('original submission',5), ('latest revision',6)]]
                company = texts[ci] if ci < len(texts) else ''
                if not company or company.lower() == 'company':
                    continue
                links = []
                for c in cells:
                    a = c.find('a', href=True)
                    links.append(_absolute_nse_url(a.get('href')) if a else '')
                records.append({
                    'Company': company,
                    'From Year': texts[fi] if fi < len(texts) else '',
                    'To Year': texts[ti] if ti < len(texts) else '',
                    'Attachment': links[ai] if ai < len(links) else '',
                    'XBRL': links[xi] if xi < len(links) else '',
                    'Original Submission Date': texts[oi] if oi < len(texts) else '',
                    'Latest Revision Date': texts[ri] if ri < len(texts) else '',
                    'Source': NSE_BRSR_URL + '?symbol=' + quote_plus(symbol),
                })
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        # The table may contain multiple pages. Prefer the selected company if it was rendered.
        return df
    except Exception:
        return pd.DataFrame()


def _parse_quote_brsr_html(html: str, symbol: str = '') -> pd.DataFrame:
    """Parse BRSR attachment links rendered inside NSE's company quote page.

    NSE's dedicated BRSR page is a client-rendered grid and frequently returns the
    shell without rows to automation. The NSE quote page, however, also publishes
    the company's BRSR history and is considerably more stable for browser clients.
    We only retain actual NSE archive links found in the rendered DOM.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')
        heading = None
        for node in soup.find_all(string=re.compile(r'Business Responsibility\s*&\s*Sustainability Report', re.I)):
            heading = node.parent
            break
        if heading is None:
            return pd.DataFrame()

        # Start from a reasonably large ancestor containing the BRSR cards.
        container = heading
        for _ in range(7):
            if container.parent is None:
                break
            container = container.parent
            txt = re.sub(r'\s+', ' ', container.get_text(' ', strip=True))
            if len(txt) > 1500 and 'Business Responsibility' in txt:
                break

        anchors = container.find_all('a', href=True)
        records = []
        seen = set()
        current_year = ''
        for a in anchors:
            href = _absolute_nse_url(a.get('href'))
            if not href or 'nseindia.com' not in href.lower():
                continue
            atxt = re.sub(r'\s+', ' ', a.get_text(' ', strip=True))
            # Find the closest useful card/row text. This catches the From Year,
            # submission date and attachment size that NSE renders beside the link.
            parent = a
            context = ''
            for _ in range(6):
                if parent.parent is None:
                    break
                parent = parent.parent
                context = re.sub(r'\s+', ' ', parent.get_text(' ', strip=True))
                if re.search(r'From Year\s*:\s*20\d{2}\s*.*?To Year\s*:\s*20\d{2}', context, re.I):
                    break
            years = re.search(r'From Year\s*:\s*(20\d{2})\s*To Year\s*:\s*(20\d{2})', context, re.I)
            if years:
                fy_from, fy_to = years.group(1), years.group(2)
                current_year = f'{fy_from}-{fy_to}'
            elif current_year:
                fy_from, fy_to = current_year.split('-', 1)
            else:
                fy_from = fy_to = ''

            if href in seen:
                continue
            seen.add(href)
            low = href.lower()
            # Keep only actual filing/archive links, not page navigation assets.
            if not any(x in low for x in ('nsearchives.nseindia.com', '/corporate/', '/annual_reports/')):
                continue
            # Classify by actual file target first; text/size second.
            is_xbrl = bool(re.search(r'\.(xml|xbrl|zip)(?:\?|$)', low)) or 'xbrl' in low or 'xbrl' in atxt.lower()
            is_attachment = bool(re.search(r'\.pdf(?:\?|$)', low)) or not is_xbrl
            records.append({
                'Company': '',
                'From Year': fy_from,
                'To Year': fy_to,
                'Attachment': href if is_attachment else '',
                'XBRL': href if is_xbrl else '',
                'Original Submission Date': (re.search(r'Original Submission Date\s*:\s*([^|]+?)(?=\s+Image:|\s+From Year:|$)', context, re.I).group(1).strip()
                    if re.search(r'Original Submission Date\s*:', context, re.I) else ''),
                'Latest Revision Date': '',
                'Source': f'{NSE_BRSR_URL}?symbol={quote_plus(symbol)}',
            })

        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df['Company'] = df['Company'].replace('', symbol)
        # Combine PDF and XBRL links for the same FY into one filing row.
        grouped = []
        for (fy_from, fy_to), g in df.groupby(['From Year', 'To Year'], dropna=False, sort=False):
            row = g.iloc[0].copy()
            row['Attachment'] = next((x for x in g['Attachment'].astype(str) if x and x != 'nan'), '')
            row['XBRL'] = next((x for x in g['XBRL'].astype(str) if x and x != 'nan'), '')
            grouped.append(row)
        return pd.DataFrame(grouped).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()



def _brsr_rows_from_payload(payload: Any, symbol: str) -> List[Dict[str, Any]]:
    """Recursively find BRSR filing rows inside an NSE API response."""
    found: List[Dict[str, Any]] = []
    def walk(obj: Any):
        if isinstance(obj, dict):
            keys = {re.sub(r'[^a-z0-9]', '', str(k).lower()) for k in obj.keys()}
            filingish = bool(keys & {'attachment', 'attachmentlink', 'xbrl', 'xbrllink', 'xbrlfilelink'}) and bool(
                keys & {'fromyear', 'toyear', 'originalsubmissiondate', 'companyname', 'company'}
            )
            if filingish:
                found.append(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
    walk(payload)
    # De-duplicate by the combination of period and links.
    out=[]; seen=set()
    for r in found:
        frm=_first(r,'fromYear','from_year','from')
        to=_first(r,'toYear','to_year','to')
        att=_link(_first(r,'attachment','attachmentLink','fileLink','file','attachmentUrl'))
        xbrl=_link(_first(r,'xbrl','xbrlFileLink','xbrlLink','xbrlUrl'))
        company=_first(r,'companyName','company','name') or symbol
        orig=_first(r,'originalSubmissionDate','submissionDate','originalDate') or ''
        rev=_first(r,'latestRevisionDate','revisionDate','latestRevision') or ''
        key=(str(frm),str(to),att,xbrl,str(orig),str(rev))
        if key in seen or not (att or xbrl):
            continue
        seen.add(key)
        out.append({
            'Company': str(company), 'From Year': str(frm or ''), 'To Year': str(to or ''),
            'Attachment': att, 'XBRL': xbrl,
            'Original Submission Date': str(orig), 'Latest Revision Date': str(rev),
            'Source': f'{NSE_BRSR_URL}?symbol={quote_plus(symbol)}',
        })
    return out


def _parse_network_brsr_response(body: str, symbol: str) -> pd.DataFrame:
    """Parse a JSON response captured from NSE's own browser network calls."""
    if not body:
        return pd.DataFrame()
    try:
        payload=json.loads(body)
    except Exception:
        return pd.DataFrame()
    rows=_brsr_rows_from_payload(payload, symbol)
    if not rows:
        # Some NSE responses wrap the row list under an arbitrary key. _rows handles
        # the common data/results/records/rows/result wrappers.
        rows2=_rows(payload)
        if rows2:
            rows=[]
            for r in rows2:
                att=_link(_first(r,'attachment','attachmentLink','fileLink','file'))
                xbrl=_link(_first(r,'xbrl','xbrlFileLink','xbrlLink'))
                if not (att or xbrl):
                    continue
                rows.append({
                    'Company': str(_first(r,'companyName','company','name') or symbol),
                    'From Year': str(_first(r,'fromYear','from_year','from') or ''),
                    'To Year': str(_first(r,'toYear','to_year','to') or ''),
                    'Attachment': att, 'XBRL': xbrl,
                    'Original Submission Date': str(_first(r,'originalSubmissionDate','submissionDate','originalDate') or ''),
                    'Latest Revision Date': str(_first(r,'latestRevisionDate','revisionDate','latestRevision') or ''),
                    'Source': f'{NSE_BRSR_URL}?symbol={quote_plus(symbol)}',
                })
    return pd.DataFrame(rows)


def _capture_brsr_from_browser_network(driver, symbol: str) -> pd.DataFrame:
    """Capture the exact NSE API responses used by the public BRSR web app.

    This avoids hard-coding an internal NSE endpoint, which has changed over time.
    Chrome itself requests the correct endpoint; we simply inspect those responses.
    """
    try:
        logs=driver.get_log('performance')
    except Exception:
        return pd.DataFrame()
    candidates=[]
    for item in logs:
        try:
            msg=json.loads(item['message'])['message']
            if msg.get('method') != 'Network.responseReceived':
                continue
            params=msg.get('params',{})
            resp=params.get('response',{})
            url=str(resp.get('url') or '')
            low=url.lower()
            if 'nseindia.com' not in low:
                continue
            if not re.search(r'brsr|business.?responsibility|sustainab|corporate-filings', low):
                continue
            req_id=params.get('requestId')
            mime=str(resp.get('mimeType') or '').lower()
            candidates.append((req_id,url,mime))
        except Exception:
            continue
    # Newest responses first; avoid requesting the same URL repeatedly.
    seen_urls=set()
    for req_id,url,mime in reversed(candidates):
        if not req_id or url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            body_obj=driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': req_id})
            body=body_obj.get('body','') if isinstance(body_obj,dict) else ''
            df=_parse_network_brsr_response(body, symbol)
            if not df.empty:
                return df
        except Exception:
            continue
    return pd.DataFrame()


def _fetch_brsr_with_selenium(symbol: str, company_name: str = "") -> Tuple[pd.DataFrame, str]:
    """Use Chrome to execute NSE's own BRSR page and capture its live API response."""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
    except Exception:
        return pd.DataFrame(), 'Selenium not installed'

    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-features=Translate,BackForwardCache')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154 Safari/537.36')
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd('Network.enable', {})

        # First load the official BRSR page. Do not wait for a fragile DOM label;
        # the grid is populated asynchronously and may use a different component tree.
        brsr_url=NSE_BRSR_URL + '?symbol=' + quote_plus(symbol) + '&tabIndex=equity'
        driver.get(brsr_url)
        WebDriverWait(driver, 15).until(lambda d: d.execute_script('return document.readyState') in ('interactive','complete'))
        time.sleep(5)
        # Trigger lazy-loaded grids and pagination components.
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        time.sleep(4)
        driver.execute_script('window.scrollTo(0, 0);')
        time.sleep(1)

        # Best path: capture the exact API response the NSE page itself used.
        df=_capture_brsr_from_browser_network(driver, symbol)
        if not df.empty:
            return df, 'NSE BRSR page (official browser network response)'

        # Second path: inspect the rendered DOM after scrolling. This handles cases
        # where the API response is embedded as HTML rather than JSON.
        html=driver.page_source
        df=_parse_brsr_html(html, symbol)
        if not df.empty:
            return df, 'NSE BRSR public page (Chrome-rendered)'

        # Final path: company quote page. The quote page can expose the same BRSR
        # attachments even when the standalone BRSR grid does not render to Selenium.
        quote_url=f'https://www.nseindia.com/get-quotes/equity?symbol={quote_plus(symbol)}'
        driver.get(quote_url)
        WebDriverWait(driver, 25).until(lambda d: d.execute_script('return document.readyState') in ('interactive','complete'))
        time.sleep(6)
        for _ in range(3):
            driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            time.sleep(3)
        df=_capture_brsr_from_browser_network(driver, symbol)
        if not df.empty:
            return df, 'NSE company quote page (official browser network response)'
        df=_parse_quote_brsr_html(driver.page_source, symbol)
        if not df.empty:
            return df, 'NSE company quote page (Chrome-rendered BRSR filing links)'

        return pd.DataFrame(), 'NSE BRSR page loaded but its filing grid/API did not return rows to Chrome'
    except Exception as e:
        return pd.DataFrame(), f'NSE Chrome fallback failed: {type(e).__name__}: {e}'
    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_brsr_filings(ticker: str, use_browser_fallback: bool = False) -> Tuple[pd.DataFrame, str]:
    """Fetch the actual NSE BRSR filing table, including PDF and XBRL links.

    NSE's BRSR page is a JavaScript application and its internal API route changes.
    We therefore try normal HTML first and then use the installed Chrome browser to
    render the public page. No BRSR values are fabricated when NSE is unavailable.
    """
    symbol = ticker.split('.')[0].upper()
    errors = []

    # 1) Prime the relevant section page and make a small number of bounded
    # requests. The previous implementation could spend >90 seconds on three
    # sequential page attempts before starting Chrome.
    try:
        s = _session()
        try:
            s.get(NSE_BRSR_URL, timeout=(2.5, 4.5))
        except requests.RequestException as prime_exc:
            errors.append(f'prime:{type(prime_exc).__name__}')
        url = NSE_BRSR_URL + '?symbol=' + quote_plus(symbol) + '&tabIndex=equity'
        r = s.get(url, timeout=(2.5, 7))
        if r.ok:
            df = _parse_brsr_html(r.text, symbol)
            if not df.empty:
                mask = df['Company'].astype(str).str.contains(symbol, case=False, na=False)
                if mask.any():
                    df = pd.concat([df.loc[mask], df.loc[~mask]], ignore_index=True)
                return df, 'NSE BRSR public page'
        errors.append(f'HTML {r.status_code}')
        s.close()
    except Exception as e:
        errors.append(type(e).__name__)

    # Browser rendering is opt-in from the page because Selenium startup is
    # environment-dependent and should not block other modules after search.
    if use_browser_fallback:
        company_name = ''
        try:
            from data.fetch_live import get_live_profile
            company_name = str(get_live_profile(ticker).get('name') or '')
        except Exception:
            pass
        df, browser_source = _fetch_brsr_with_selenium(symbol, company_name)
        if not df.empty:
            return df, browser_source
        errors.append(browser_source)
    else:
        errors.append('browser fallback not run (use the page retry control)')

    # 3) Evidence-grade fallback: the BRSR is also part of the company's annual
    # report for applicable listed entities. If the NSE BRSR grid is blocked,
    # expose the original annual-report attachment rather than reporting that no
    # BRSR exists. This does not fabricate any ESG values.
    try:
        from data.annual_report import discover_annual_reports
        reports, report_source = discover_annual_reports(ticker)
        if not reports.empty:
            candidate = reports[reports["Attachment"].astype(str).str.startswith("http")].copy()
            if not candidate.empty:
                row=candidate.iloc[0]
                fallback=pd.DataFrame([{
                    "Company": row.get("Company", symbol),
                    "From Year": row.get("From Year", ""),
                    "To Year": row.get("To Year", ""),
                    "Attachment": row.get("Attachment", ""),
                    "XBRL": "",
                    "Original Submission Date": row.get("Date", ""),
                    "Latest Revision Date": "",
                    "Source": row.get("Source", ""),
                }])
                return fallback, f"NSE BRSR grid unavailable; official annual-report BRSR fallback ({report_source})"
    except Exception as exc:
        errors.append(f"annual-report fallback:{type(exc).__name__}")

    return pd.DataFrame(), 'NSE BRSR public page unavailable to the Python/Chrome client: ' + '; '.join(errors[-5:])




# ---------------------------------------------------------------------------
# Integrated Filing – Governance XBRL/HTML parser
# ---------------------------------------------------------------------------
def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_blank(value: Any) -> bool:
    t = _norm_text(value).lower()
    return t in {"", "nan", "none", "nat", "na", "n/a", "-"}


def _find_table_containing(tables: List[pd.DataFrame], *needles: str) -> Optional[pd.DataFrame]:
    needles = [n.lower() for n in needles]
    for table in tables:
        if table is None or table.empty:
            continue
        blob = " ".join(_norm_text(c).lower() for c in table.columns) + " " + " ".join(
            _norm_text(v).lower() for v in table.astype(str).fillna("").values.flatten()[:2000]
        )
        if all(n in blob for n in needles):
            return table
    return None



def _governance_ixbrl_candidates(url: str) -> List[str]:
    """Return the NSE human-readable iXBRL rendering corresponding to a raw XBRL URL.

    NSE's Integrated Filing table often exposes a *_WEB.xml instance document.
    The same filing is also published by NSE's archive as an iXBRL HTML rendering,
    which contains the section/table labels an analyst sees.  We derive only the
    archive URL pattern; the content is still fetched from NSE and never invented.
    """
    u = _norm_text(url)
    if not u:
        return []
    out = []
    if '/corporate/xbrl/' in u and u.lower().endswith('.xml'):
        base = u.rsplit('/', 1)[-1]
        stem = re.sub(r'_WEB\.xml$', '', base, flags=re.I)
        stem = re.sub(r'_WEB$', '', stem, flags=re.I)
        for name in (f'{stem}_iXBRL_WEB.html', f'{stem}_WEB.html'):
            out.append(u.replace('/corporate/xbrl/', '/corporate/ixbrl/').rsplit('/',1)[0] + '/' + name)
    elif '/corporate/ixbrl/' in u and u.lower().endswith('.html'):
        out.append(u)
    return list(dict.fromkeys(out))


def _extract_governance_pdf(url: str) -> Dict[str, Any]:
    """Extract governance facts from the actual NSE Integrated Filing PDF.

    This is a source-backed fallback for NSE clients that can see the filing
    metadata/XBRL URL but cannot render the XBRL instance locally. The PDF is
    the company's submitted governance filing, so values are extracted from
    the filing text rather than inferred.
    """
    result = {
        'source_url': url, 'board_total': None, 'independent_directors': None,
        'chairperson_regular': None, 'chairperson_related_to_md_ceo': None,
        'audit_members': None, 'nrc_members': None, 'stakeholder_members': None,
        'risk_members': None, 'committee_meetings': None, 'committee_quorum_yes': None,
        'board_meetings': None, 'board_quorum_yes': None, 'affirmations_yes': None,
        'affirmations_no': None, 'affirmations_na': None, 'related_party_status': None,
        'cyber_security_text': None, 'cyber_security_count': None,
        'investor_grievance_text': None, 'investor_grievance_pending': None,
        'investor_grievance_received': None, 'investor_grievance_disposed': None,
        'investor_grievance_unresolved': None, 'signatory': None, 'period_end': None,
        'reporting_quarter': None, 'errors': [], 'parse_status': 'not_attempted',
        'retrieval_stage': ''
    }
    if not url:
        return result
    try:
        # V4: the NSE filing catalog sometimes exposes the attachment only
        # through a browser click. The browser helper may therefore hand us a
        # local downloaded PDF. It is still the official NSE filing bytes.
        if str(url).startswith("file://") or os.path.isfile(str(url)):
            local_path = str(url)[7:] if str(url).startswith("file://") else str(url)
            with open(local_path, "rb") as fh:
                pdf_bytes = fh.read()
            result["retrieval_stage"] = f"pdf_local:{len(pdf_bytes)}"
        else:
            if not str(url).lower().endswith('.pdf'):
                return result
            r = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
                "Accept": "application/pdf,*/*", "Referer": NSE_HOME,
            }, timeout=12)
            r.raise_for_status()
            pdf_bytes = r.content
            result["retrieval_stage"] = f"pdf_http:{r.status_code}:{len(pdf_bytes)}"
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = '\n'.join((page.extract_text() or '') for page in reader.pages)
        text = re.sub(r'\r', '\n', text)
        text = re.sub(r'[ \t]+', ' ', text)

        # Some NSE-generated PDFs have table text that pypdf cannot reconstruct
        # reliably. Use pdfplumber as an optional second extraction engine. It
        # still reads the submitted NSE PDF; it does not generate any values.
        if len(text.strip()) < 300 or not re.search(r'Composition of Board|Audit Committee|Risk Management Committee', text, re.I):
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                    alt = '\n'.join((page.extract_text() or '') for page in pdf.pages)
                if len(alt.strip()) > len(text.strip()):
                    text = alt
                    result['retrieval_stage'] += ':pdfplumber'
            except Exception as exc:
                result['errors'].append(f'pdfplumber:{type(exc).__name__}')

        if len(text.strip()) < 300:
            result['errors'].append('pdf_text_empty')
            return result

        def segment(start, ends):
            low=text.lower(); a=low.find(start.lower())
            if a<0: return ''
            b=len(text)
            for end in ends:
                x=low.find(end.lower(), a+len(start))
                if x>=0: b=min(b,x)
            return text[a:b]
        def dins(seg):
            return list(dict.fromkeys(re.findall(r'\b\d{8}\b', seg)))

        bm0=re.search(r'I\.\s*Composition of Board of Directors', text, re.I)
        board=''
        if bm0:
            b=len(text)
            for ep in (r'II\.\s*Composition of Committees', r'(?:###\s*)?Audit Committee Details'):
                me=re.search(ep, text[bm0.end():], re.I)
                if me:
                    b=min(b, bm0.end()+me.start())
            board=text[bm0.start():b]
        if board:
            ds=dins(board)
            if ds:
                # If the PDF explicitly labels a director as ceased, exclude that DIN.
                active=[]
                for d in ds:
                    pos=board.find(d); w=board[max(0,pos-250):pos+900]
                    if re.search(r'(date of cessation|cessation)', w, re.I) and not re.search(r'(current status\s*[:|]?\s*active|active\s*[:|]?)', w, re.I):
                        # Only exclude when a populated date is visible near the row.
                        if re.search(r'\b\d{1,2}[-/]?[A-Za-z]{3}[-/]?\d{4}\b', w):
                            continue
                    active.append(d)
                if active:
                    result['board_total']=len(active)
                    result['independent_directors']=sum('independent director' in board[max(0,board.find(d)-250):board.find(d)+700].lower() for d in active)
            m=re.search(r'Whether.*regular chairperson\s*[:|]?\s*(Yes|No)', board, re.I)
            if m: result['chairperson_regular']=m.group(1).title()
            m=re.search(r'Whether.*chairperson.*related.*MD.*CEO\s*[:|]?\s*(Yes|No)', board, re.I)
            if m: result['chairperson_related_to_md_ceo']=m.group(1).title()

        # PDF text extraction is not consistent about markdown-style headings.
        # Use the section titles themselves as anchors and cut at the next
        # governance section. This keeps committee membership tied to actual
        # DINs in the submitted filing rather than counting XBRL contexts.
        section_specs=[
            ('audit_members', r'(?:###\s*)?Audit Committee Details',
             (r'(?:###\s*)?Nomination and remuneration committee', r'(?:###\s*)?Stakeholders? Relationship Committee', r'(?:###\s*)?Risk Management Committee', r'III\.\s*Meeting of Board of Directors')),
            ('nrc_members', r'(?:###\s*)?Nomination and remuneration committee',
             (r'(?:###\s*)?Stakeholders? Relationship Committee', r'(?:###\s*)?Risk Management Committee', r'III\.\s*Meeting of Board of Directors')),
            ('stakeholder_members', r'(?:###\s*)?Stakeholders? Relationship Committee',
             (r'(?:###\s*)?Risk Management Committee', r'III\.\s*Meeting of Board of Directors')),
            ('risk_members', r'(?:###\s*)?Risk Management Committee',
             (r'III\.\s*Meeting of Board of Directors', r'IV\.\s*Meeting of Committees')),
        ]
        for key,start_pat,end_pats in section_specs:
            m0=re.search(start_pat, text, re.I)
            if not m0:
                continue
            a=m0.start()
            b=len(text)
            for ep in end_pats:
                me=re.search(ep, text[m0.end():], re.I)
                if me:
                    b=min(b, m0.end()+me.start())
            seg=text[a:b]
            ds=dins(seg)
            if ds:
                # De-duplicate DINs: one committee member may appear more than
                # once because the PDF repeats headers or wrapped rows.
                result[key]=len(set(ds))

        bm=segment('III. Meeting of Board of Directors',('IV. Meeting of Committees','V. Related Party Transactions','VI. Affirmations'))
        dates=re.findall(r'\b\d{1,2}[-/]?[A-Za-z]{3}[-/]?\d{4}\b',bm)
        if dates:
            result['board_meetings']=len(dates)
            result['board_quorum_yes']=len(re.findall(r'\bYes\b',bm,re.I)) if 'quorum' in bm.lower() else None

        cm=segment('IV. Meeting of Committees',('V. Related Party Transactions','VI. Affirmations'))
        dates=re.findall(r'\b\d{1,2}[-/]?[A-Za-z]{3}[-/]?\d{4}\b',cm)
        if dates:
            result['committee_meetings']=len(dates)
            # Count rows/occurrences explicitly associated with quorum = Yes.
            result['committee_quorum_yes']=len(re.findall(r'quorum[^\n]{0,180}?\bYes\b',cm,re.I)) or None

        af=segment('VI. Affirmations',('Signatory Details','Details of Cyber security incidence','Investor Grievance Details'))
        if af:
            # The affirmation table uses one Yes/No/NA per numbered disclosure.
            result['affirmations_yes']=len(re.findall(r'\bYes\b',af,re.I))
            result['affirmations_no']=len(re.findall(r'\bNo\b',af,re.I))
            result['affirmations_na']=len(re.findall(r'\b(?:N/?A|Not Applicable)\b',af,re.I))

        cyber=segment('Details of Cyber security incidence',('Signatory Details','Investor Grievance Details'))
        if cyber:
            result['cyber_security_text']=_norm_text(cyber)[:700]
            m=re.search(r'number of cyber security[^\n|:]*[|:]\s*(\d+)',cyber,re.I)
            if m: result['cyber_security_count']=int(m.group(1))

        gr=segment('Investor Grievance Details',('Disclosure of Acquisition','Disclosure of Imposition','Signatory Details'))
        if gr:
            pats={
              'investor_grievance_pending':r'pending at the beginning of Quarter[^\d]{0,30}(\d+)',
              'investor_grievance_received':r'received during the Quarter[^\d]{0,30}(\d+)',
              'investor_grievance_disposed':r'disposed off during the Quarter[^\d]{0,30}(\d+)',
              'investor_grievance_unresolved':r'remaining unresolved at the end of the Quarter[^\d]{0,30}(\d+)',
            }
            for k,pat in pats.items():
                m=re.search(pat,gr,re.I)
                if m: result[k]=int(m.group(1))
            if any(result.get(k) is not None for k in pats): result['investor_grievance_text']='Investor grievance disclosure retrieved from NSE Integrated Filing – Governance PDF.'

        m=re.search(r'Name of signatory\s*[:|]?\s*([^\n|]+)',text,re.I)
        if m: result['signatory']=_norm_text(m.group(1))
        useful=('board_total','independent_directors','audit_members','nrc_members','stakeholder_members','risk_members','committee_meetings','board_meetings','affirmations_yes','affirmations_no','investor_grievance_unresolved')
        extracted=sum(result.get(k) is not None for k in useful)
        result['parse_status']='parsed' if extracted>=2 else ('partial' if extracted else 'failed')
        return result
    except Exception as exc:
        result['errors'].append(f'pdf:{type(exc).__name__}:{exc}')
        result['parse_status']='failed'
        return result

def _extract_governance_raw_xbrl(url: str) -> Dict[str, Any]:
    """Parse the raw NSE Integrated Filing-Governance XBRL/XML instance.

    V20 treats the URL supplied by NSE as the source of truth.  The previous
    versions tried to manufacture an iXBRL HTML URL from the XML filename;
    NSE does not guarantee that the two archive paths share the same file id.
    This parser therefore reads the actual XML instance first and uses
    taxonomy-like element names/context text where possible.  It is deliberately
    conservative: uncertain fields stay None rather than becoming zero.
    """
    result = {
        "source_url": url, "board_total": None, "independent_directors": None,
        "audit_members": None, "nrc_members": None, "stakeholder_members": None,
        "risk_members": None, "committee_meetings": None, "committee_quorum_yes": None,
        "board_meetings": None, "board_quorum_yes": None, "affirmations_yes": None,
        "affirmations_no": None, "affirmations_na": None, "cyber_security_count": None,
        "investor_grievance_unresolved": None, "investor_grievance_pending": None,
        "investor_grievance_received": None, "investor_grievance_disposed": None,
        "errors": [], "parse_status": "not_attempted", "retrieval_stage": "", "taxonomy_parser": "not_attempted"
    }
    if not url or not url.lower().endswith(('.xml', '.xbrl')):
        return result

    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
            "Accept": "application/xml,text/xml,*/*",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": NSE_HOME,
        })
        r = sess.get(url, timeout=6, allow_redirects=True)
        result["retrieval_stage"] = f"raw_xbrl_http:{r.status_code}:{len(r.content)}"
        if not r.ok or len(r.content) < 200:
            result["errors"].append(f"raw_xbrl_http:{r.status_code}:{len(r.content)}")
            return result
        payload = r.content
        if payload[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                names=[n for n in zf.namelist() if n.lower().endswith(('.xml','.xbrl'))]
                payload = zf.read(names[0]) if names else payload
        root = ET.fromstring(payload)
        # First use the official NSE taxonomy to interpret opaque XBRL concepts.
        # The heuristic parser below remains as a fallback for filings whose taxonomy
        # is unavailable or partially revised.
        tax = _taxonomy_aware_governance_facts(payload)
        result['taxonomy_parser'] = 'enabled'
        for _k, _v in tax.items():
            if _v is not None:
                result[_k] = _v
        elems=[]
        for e in root.iter():
            tag=str(e.tag).split('}')[-1]
            txt=(e.text or '').strip()
            attrs={str(k).split('}')[-1]:str(v) for k,v in e.attrib.items()}
            if txt or attrs:
                elems.append((tag, txt, attrs))
        lowtags=[(t.lower(),txt,a) for t,txt,a in elems]

        def vals(*patterns):
            out=[]
            for t,txt,a in lowtags:
                if any(re.search(p,t,re.I) for p in patterns) and txt:
                    out.append(txt.strip())
            return out
        def ints(*patterns):
            out=[]
            for v in vals(*patterns):
                m=re.fullmatch(r"[-+]?\d+(?:\.0+)?", v.replace(',',''))
                if m: out.append(int(float(v)))
            return out
        def unique_nonblank(items):
            return list(dict.fromkeys(x for x in items if x and x.lower() not in {'na','n/a','not applicable','none','null','-'}))

        # Raw XBRL is used only for explicitly tagged scalar facts. Do NOT count
        # DINs, names, contexts, or repeated tags here: those are dimensional
        # rows and cannot safely be converted into committee/member totals.
        explicit_board = ints(r'^(?:numberofdirectors|totalnumberofdirectors|noofdirectors)$')
        if explicit_board and result.get('board_total') is None:
            result['board_total']=explicit_board[0]
        explicit_independent = ints(r'^(?:numberofindependentdirectors|noofindependentdirectors)$')
        if explicit_independent and result.get('independent_directors') is None:
            result['independent_directors']=explicit_independent[0]

        # Committee membership and meeting counts intentionally remain unset in
        # the raw-XBRL parser. They must be reconstructed from an actual filing
        # table by the iXBRL/PDF parsers.
        # Quorum and compliance are table-row metrics. Do not count raw XML
        # elements without uniquely identifying the corresponding meeting or
        # affirmation row; that produced the misleading 'Quorum met = 2'.

        cyber=ints(r'number.*cyber.*security.*inciden', r'cyber.*security.*inciden.*number')
        if cyber:
            result['cyber_security_count']=cyber[-1]

        for key, pats in {
            'investor_grievance_pending': (r'pending.*beginning.*quarter',),
            'investor_grievance_received': (r'received.*during.*quarter',),
            'investor_grievance_disposed': (r'disposed.*during.*quarter', r'disposed.*off.*quarter'),
            'investor_grievance_unresolved': (r'unresolved.*end.*quarter', r'remaining.*unresolved'),
        }.items():
            vv=ints(*pats)
            if vv: result[key]=vv[-1]

        useful=('board_total','independent_directors','audit_members','nrc_members','stakeholder_members','risk_members','committee_meetings','board_meetings','affirmations_yes','affirmations_no','cyber_security_count','investor_grievance_unresolved')
        n=sum(result.get(k) is not None for k in useful)
        result['parse_status']='parsed' if n>=2 else ('partial' if n else 'failed')
        if not n:
            result['errors'].append('raw_xbrl_schema_names_not_recognised')
        return result
    except ET.ParseError as exc:
        result['errors'].append(f'raw_xbrl_xml:{type(exc).__name__}')
        result['parse_status']='failed'
        return result
    except Exception as exc:
        result['errors'].append(f'raw_xbrl:{type(exc).__name__}:{exc}')
        result['parse_status']='failed'
        return result

def _extract_governance_xbrl_html(url: str, html_override: str = "", browser_fallback: bool = False) -> Dict[str, Any]:
    """Extract governance facts from an NSE Integrated Filing – Governance iXBRL page.

    NSE publishes these filings as HTML/iXBRL.  The visible report has section
    headings outside the individual HTML tables, so parsing a table in isolation
    is unreliable.  This parser therefore works from the rendered row text and
    identifies tables by their column headers.  It also excludes ceased committee
    members from current committee counts where a cessation date is supplied.
    Missing fields remain None/N/A; nothing is inferred as zero.
    """
    result: Dict[str, Any] = {
        "source_url": url,
        "board_total": None,
        "independent_directors": None,
        "chairperson_regular": None,
        "chairperson_related_to_md_ceo": None,
        "audit_members": None,
        "nrc_members": None,
        "stakeholder_members": None,
        "risk_members": None,
        "committee_meetings": None,
        "committee_quorum_yes": None,
        "board_meetings": None,
        "board_quorum_yes": None,
        "affirmations_yes": None,
        "affirmations_no": None,
        "affirmations_na": None,
        "related_party_status": None,
        "cyber_security_text": None,
        "cyber_security_count": None,
        "investor_grievance_text": None,
        "investor_grievance_pending": None,
        "investor_grievance_received": None,
        "investor_grievance_disposed": None,
        "investor_grievance_unresolved": None,
        "signatory": None,
        "period_end": None,
        "reporting_quarter": None,
        "errors": [],
        "parse_status": "not_attempted",
        "retrieval_stage": "",
    }
    if not url or not url.startswith("http"):
        return result

    html = html_override or ""

    def _fetch_archive_html(target_url: str) -> tuple[str, str]:
        """Fetch an NSE archive/iXBRL page with archive-safe headers.

        NSE archive files are hosted separately from www.nseindia.com. The
        normal NSE API session adds X-Requested-With, which is useful for API
        calls but can cause archive HTML requests to be rejected or served an
        incomplete response. Use a clean browser-like session here.
        """
        try:
            sess = requests.Session()
            sess.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
                "Referer": "https://www.nseindia.com/",
                "Cache-Control": "no-cache",
            })
            resp = sess.get(target_url, timeout=8, allow_redirects=True)
            ctype = str(resp.headers.get("Content-Type", ""))
            if resp.ok and len(resp.text) > 1000:
                return resp.text, f"archive_http:{resp.status_code}:{len(resp.text)}"
            return "", f"archive_http:{resp.status_code}:{len(resp.text)}:{ctype}"
        except Exception as exc:
            return "", f"archive_http_error:{type(exc).__name__}"

    # Primary route: direct NSE archive request.  If NSE serves the archive
    # through a browser-only session / anti-bot layer, fall back to Selenium
    # and parse the exact rendered iXBRL page.  This is important because the
    # filing table can expose a valid XBRL link even when a plain requests
    # client cannot retrieve its contents.
    if not html:
        html, stage = _fetch_archive_html(url)
        result["retrieval_stage"] = stage
        if not html:
            result["errors"].append(stage)

    if (not html or ("Composition of Board" not in html and "Integrated Filing" not in html)) and browser_fallback:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.common.by import By

            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1600,1200")
            options.add_argument("--lang=en-US")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/154 Safari/537.36")
            options.page_load_strategy = "eager"
            driver = webdriver.Chrome(options=options)
            try:
                driver.set_page_load_timeout(8)
                try:
                    driver.get(url)
                except Exception as load_exc:
                    result["errors"].append(f"selenium_load:{type(load_exc).__name__}")
                try:
                    WebDriverWait(driver, 5).until(
                        lambda d: "Integrated Filing" in d.page_source
                        or "Composition of Board" in d.page_source
                    )
                except Exception:
                    pass
                html = driver.page_source
                # A few NSE archive wrappers expose the actual iXBRL document
                # inside an iframe. Inspect those frames before giving up.
                if html and ("Composition of Board" not in html and "Integrated Filing" not in html):
                    try:
                        frames = driver.find_elements(By.TAG_NAME, "iframe")
                        for frame in frames[:3]:
                            try:
                                driver.switch_to.frame(frame)
                                candidate = driver.page_source
                                if candidate and ("Composition of Board" in candidate or "Integrated Filing" in candidate):
                                    html = candidate
                                    break
                            except Exception:
                                pass
                            finally:
                                try:
                                    driver.switch_to.default_content()
                                except Exception:
                                    pass
                    except Exception:
                        pass
                if html:
                    result["retrieval_stage"] = "selenium_xbrl"
            finally:
                driver.quit()
        except Exception as exc:
            result["errors"].append(f"selenium:{type(exc).__name__}")

    if not html:
        return result

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        result["errors"].append(type(exc).__name__)
        return result

    def clean(v: Any) -> str:
        return _norm_text(v)

    def row_cells(tr) -> List[str]:
        return [clean(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]

    def table_rows(table) -> List[List[str]]:
        return [cells for tr in table.find_all("tr") if (cells := row_cells(tr))]

    tables = soup.find_all("table")

    # General information is a two-column table.  These fields are useful for
    # showing the actual reporting period rather than only the NSE broadcast date.
    all_text = clean(soup.get_text(" ", strip=True))
    m = re.search(r"Reporting Quarter\s+([^|]+?)\s+Date of Quarter Ending\s+([0-9]{1,2}-[A-Za-z]{3}-[0-9]{4})", all_text, re.I)
    if m:
        result["reporting_quarter"] = clean(m.group(1))
        result["period_end"] = clean(m.group(2))

    def table_matching(*required: str):
        req = [x.lower() for x in required]
        for table in tables:
            rows = table_rows(table)
            blob = " ".join(" | ".join(r) for r in rows).lower()
            if all(x in blob for x in req):
                return rows
        return None

    # ------------------------------------------------------------------
    # I. Composition of Board of Directors
    # ------------------------------------------------------------------
    board_rows = table_matching("name of the director", "din", "category 1 of directors")
    if board_rows:
        active = []
        independent = 0
        # Locate the header row so Date of cessation / Current status can be
        # interpreted by column position instead of guessing from row text.
        header = next((r for r in board_rows if any("name of the director" in c.lower() for c in r)), None)
        hmap = {c.strip().lower(): i for i, c in enumerate(header or [])}
        status_i = next((i for k, i in hmap.items() if k == "current status"), None)
        cessation_i = next((i for k, i in hmap.items() if k == "date of cessation"), None)
        cat1_i = next((i for k, i in hmap.items() if k == "category 1 of directors"), None)
        for cells in board_rows:
            rt = " | ".join(cells)
            low = rt.lower()
            # Skip header / separator rows.
            if not re.search(r"\b\d{5,9}\b", rt):
                continue
            status = cells[status_i].strip().lower() if status_i is not None and status_i < len(cells) else ""
            cessation = cells[cessation_i].strip() if cessation_i is not None and cessation_i < len(cells) else ""
            # A populated cessation date means the director is no longer current.
            if cessation and cessation.lower() not in {"na", "n/a", "-"}:
                continue
            if status and status not in {"active", "current"}:
                continue
            active.append(cells)
            cat1 = cells[cat1_i].lower() if cat1_i is not None and cat1_i < len(cells) else low
            if "independent director" in cat1:
                independent += 1
        if active:
            result["board_total"] = len(active)
            result["independent_directors"] = independent

        # Chairperson disclosures are generally in the row immediately before
        # the director table, but searching all table text is more robust.
        bblob = " | ".join(" | ".join(x) for x in board_rows)
        if re.search(r"whether (?:the )?listed entity has a regular chairperson\s*\|\s*yes", bblob, re.I):
            result["chairperson_regular"] = "Yes"
        elif re.search(r"whether (?:the )?listed entity has a regular chairperson\s*\|\s*no", bblob, re.I):
            result["chairperson_regular"] = "No"
        if re.search(r"whether chairperson is related to md or ceo\s*\|\s*yes", bblob, re.I):
            result["chairperson_related_to_md_ceo"] = "Yes"
        elif re.search(r"whether chairperson is related to md or ceo\s*\|\s*no", bblob, re.I):
            result["chairperson_related_to_md_ceo"] = "No"

    # ------------------------------------------------------------------
    # II. Composition of Committees
    # ------------------------------------------------------------------
    def committee_members(label_patterns: List[str]) -> Optional[int]:
        for table in tables:
            rows = table_rows(table)
            blob = " ".join(" | ".join(r) for r in rows).lower()
            if not ("name of committee members" in blob and any(p.lower() in blob for p in label_patterns)):
                continue
            count = 0
            for cells in rows:
                rt = " | ".join(cells)
                low = rt.lower()
                if not re.search(r"\b\d{5,9}\b", rt):
                    continue
                # Last/second-last field in NSE's standard committee table is
                # Date of Cessation.  If populated, the member is no longer current.
                if re.search(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}\b", low):
                    # There is also an appointment date, so inspect the row from
                    # the right: a trailing date after the role is the cessation date.
                    dates = re.findall(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}\b", rt)
                    if len(dates) >= 2 and dates[-1] != dates[0]:
                        # Rows with appointment + cessation have >=2 dates.
                        # Keep only if the row explicitly contains a populated
                        # cessation value after the appointment.
                        # If the final date is followed by remarks, it is still cessation.
                        count -= 0
                        continue
                count += 1
            return count or None
        return None

    # A more precise committee parser based on the standard 7-column table.
    def _table_section_hint(table) -> str:
        # NSE's iXBRL HTML puts section titles (e.g. "Audit Committee Details")
        # immediately before the member table rather than inside its <table>.
        # Walk backwards through nearby elements and collect the nearest useful
        # heading/strong text. This makes the parser independent of exact HTML tags.
        texts = []
        node = table
        for _ in range(18):
            node = node.find_previous()
            if node is None:
                break
            if getattr(node, "name", "") in {"script", "style"}:
                continue
            txt = clean(node.get_text(" ", strip=True))
            if not txt or len(txt) > 180:
                continue
            if any(k in txt.lower() for k in (
                "audit committee", "nomination and remuneration committee",
                "stakeholders relationship committee", "risk management committee",
            )):
                texts.append(txt.lower())
                if len(texts) >= 2:
                    break
        return " | ".join(reversed(texts))

    def committee_members_precise(label: str) -> Optional[int]:
        label_low = label.lower()
        for table in tables:
            rows = table_rows(table)
            blob = " ".join(" | ".join(r) for r in rows).lower()
            hint = _table_section_hint(table)
            if "name of committee members" not in blob:
                continue
            if label_low not in blob and label_low not in hint:
                continue
            header = next((r for r in rows if "name of committee members" in " | ".join(r).lower()), None)
            h = [c.lower() for c in (header or [])]
            din_i = next((i for i,c in enumerate(h) if "din number" in c or c == "din" or c.endswith(" din")), None)
            name_i = next((i for i,c in enumerate(h) if "name of committee members" in c), None)
            cessation_i = next((i for i,c in enumerate(h) if "date of cessation" in c), None)
            identities = set()
            for cells in rows:
                if header and cells == header:
                    continue
                rowtext = " | ".join(cells)
                if not re.search(r"\b\d{5,9}\b", rowtext):
                    continue
                cessation = cells[cessation_i].strip().lower() if cessation_i is not None and cessation_i < len(cells) else ""
                if cessation and cessation not in {"na", "n/a", "-", "none"}:
                    continue
                din = cells[din_i].strip() if din_i is not None and din_i < len(cells) else ""
                name = cells[name_i].strip().lower() if name_i is not None and name_i < len(cells) else ""
                identity = ("din:" + din) if re.fullmatch(r"\d{5,9}", din) and set(din) != {"0"} else ("name:" + name if name else "")
                if identity:
                    identities.add(identity)
            return len(identities) or None
        return None

    result["audit_members"] = committee_members_precise("audit committee details") or committee_members_precise("audit committee")
    result["nrc_members"] = committee_members_precise("nomination and remuneration committee")
    result["stakeholder_members"] = committee_members_precise("stakeholders relationship committee")
    result["risk_members"] = committee_members_precise("risk management committee")

    # ------------------------------------------------------------------
    # III / IV. Meeting tables: match the header row robustly and count unique
    # dated rows. NSE revisions use both "No. of Independent Directors" and
    # "Number of Independent Directors"; requiring the latter exact phrase was
    # the reason Board Meeting counts silently remained N/A for some filings.
    # ------------------------------------------------------------------
    board_date_keys = set()
    board_quorum_keys = set()
    committee_date_keys = set()
    committee_quorum_keys = set()
    for table in tables:
        rows = table_rows(table)
        header = next((r for r in rows if any("date(s) of meeting" in c.lower() or "date of meeting" in c.lower() for c in r)), None)
        if not header:
            continue
        h = [re.sub(r"\s+", " ", c.lower()).strip() for c in header]
        header_text = " | ".join(h)
        date_i = next((i for i,c in enumerate(h) if "date(s) of meeting" in c or "date of meeting" in c), None)
        quorum_i = next((i for i,c in enumerate(h) if "quorum met" in c), None)
        committee_i = next((i for i,c in enumerate(h) if "name of committee" in c), None)
        total_i = next((i for i,c in enumerate(h) if "total number of directors" in c), None)
        if date_i is None:
            continue
        if committee_i is None and total_i is not None and "independent directors attending" in header_text:
            # Board meeting table
            for row in rows:
                if row == header or date_i >= len(row):
                    continue
                date = clean(row[date_i])
                if not re.search(r"\b\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}\b", date):
                    continue
                board_date_keys.add(date)
                quorum = quorum_i is not None and quorum_i < len(row) and row[quorum_i].strip().lower() == "yes"
                if quorum:
                    board_quorum_keys.add(date)
        elif committee_i is not None and any("total number of directors in the committee" in c for c in h):
            # Committee meetings use (committee name, date) as identity: more
            # than one committee may meet on the same date.
            for row in rows:
                if row == header or date_i >= len(row) or committee_i >= len(row):
                    continue
                date = clean(row[date_i])
                name = clean(row[committee_i]).lower()
                if not name or not re.search(r"\b\d{1,2}[-/][A-Za-z]{3}[-/]\d{4}\b", date):
                    continue
                key = (name, date)
                committee_date_keys.add(key)
                quorum = quorum_i is not None and quorum_i < len(row) and row[quorum_i].strip().lower() == "yes"
                if quorum:
                    committee_quorum_keys.add(key)
    if board_date_keys:
        result["board_meetings"] = len(board_date_keys)
        result["board_quorum_yes"] = len(board_quorum_keys)
    if committee_date_keys:
        result["committee_meetings"] = len(committee_date_keys)
        result["committee_quorum_yes"] = len(committee_quorum_keys)

    # ------------------------------------------------------------------
    # VI. Affirmations
    # ------------------------------------------------------------------
    for table in tables:
        rows = table_rows(table)
        blob = " ".join(" | ".join(r) for r in rows).lower()
        if "compliance status" not in blob:
            continue
        # Do not require 'board composition' in the table header: NSE's actual
        # table has generic headers and puts the subject text in each row.
        yes = no = na = 0
        related = None
        for cells in rows:
            rt = " | ".join(cells)
            low = rt.lower()
            if "compliance status" in low and len(cells) <= 3:
                continue
            if not any(re.search(r"\b(?:yes|no|na|n/a)\b", c, re.I) for c in cells):
                continue
            # In the standard NSE table, the last cell is the status.
            status = next((c.strip().lower() for c in reversed(cells) if c.strip().lower() in {"yes", "no", "na", "n/a"}), None)
            if status == "yes": yes += 1
            elif status == "no": no += 1
            elif status in {"na", "n/a"}: na += 1
            if "related party" in low and status:
                related = status.upper().replace("/", "")
        if yes or no or na:
            result["affirmations_yes"] = yes
            result["affirmations_no"] = no
            result["affirmations_na"] = na
            result["related_party_status"] = related
            break

    # ------------------------------------------------------------------
    # Cyber-security disclosure
    # ------------------------------------------------------------------
    cyber_table = None
    for table in tables:
        rows = table_rows(table)
        blob = " ".join(" | ".join(r) for r in rows).lower()
        if "cyber security" in blob and "number of cyber security" in blob:
            cyber_table = rows
            break
    if cyber_table:
        cblob = " | ".join(" | ".join(x) for x in cyber_table)
        result["cyber_security_text"] = cblob[:700]
        m = re.search(r"number of cyber security[^|]*\|\s*(\d+)", cblob, re.I)
        if m:
            result["cyber_security_count"] = int(m.group(1))

    # ------------------------------------------------------------------
    # Investor grievance disclosure
    # ------------------------------------------------------------------
    for table in tables:
        rows = table_rows(table)
        blob = " ".join(" | ".join(r) for r in rows).lower()
        if "investor complaints pending" not in blob:
            continue
        vals = {}
        for cells in rows:
            rt = " | ".join(cells)
            m = re.search(r"(pending at the beginning of quarter|received during the quarter|disposed off during the quarter|remaining unresolved at the end of the quarter)[^|]*\|\s*(\d+)", rt, re.I)
            if m:
                vals[m.group(1).lower()] = int(m.group(2))
        result["investor_grievance_pending"] = vals.get("pending at the beginning of quarter")
        result["investor_grievance_received"] = vals.get("received during the quarter")
        result["investor_grievance_disposed"] = vals.get("disposed off during the quarter")
        result["investor_grievance_unresolved"] = vals.get("remaining unresolved at the end of the quarter")
        result["investor_grievance_text"] = "Investor grievance disclosure retrieved from NSE Integrated Filing – Governance."
        break

    # ------------------------------------------------------------------
    # Body-text fallback for NSE iXBRL pages
    # ------------------------------------------------------------------
    # Some Chrome/NSE combinations expose the filing as accessible text but
    # not as normal HTML tables. In that case the section structure is still
    # deterministic, so extract facts from the published filing text. This is
    # a parser fallback only; no values are invented.
    if not any(result.get(k) is not None for k in (
        "board_total", "audit_members", "nrc_members", "stakeholder_members",
        "risk_members", "committee_meetings", "board_meetings",
        "affirmations_yes", "affirmations_no"
    )):
        try:
            body_lines = [clean(x) for x in soup.get_text("\n", strip=True).splitlines() if clean(x)]
            body = "\n".join(body_lines)
            low_body = body.lower()

            def _segment(start_text: str, end_texts: tuple[str, ...]) -> str:
                low = body.lower()
                a = low.find(start_text.lower())
                if a < 0:
                    return ""
                b = len(body)
                for end_text in end_texts:
                    x = low.find(end_text.lower(), a + len(start_text))
                    if x >= 0:
                        b = min(b, x)
                return body[a:b]

            def _unique_dins(text: str) -> list[str]:
                # DINs are normally 8 digits; allow 5-9 for compatibility with
                # older/edge filings, while avoiding ordinary quantities.
                return list(dict.fromkeys(re.findall(r"\b\d{5,9}\b", text)))

            board_seg = _segment(
                "I. Composition of Board of Directors",
                ("II. Composition of Committees", "### II. Composition of Committees"),
            )
            if board_seg:
                dins = _unique_dins(board_seg)
                # The board table has a DIN per current/ceased director. Remove
                # directors whose row explicitly carries a cessation date/status.
                active_dins = []
                for din in dins:
                    pos = board_seg.find(din)
                    window = board_seg[pos:pos + 900]
                    wlow = window.lower()
                    if "current status" in wlow:
                        wlow = wlow[wlow.find("current status"):]
                    if re.search(r"\b(active|current)\b", wlow) or not re.search(r"date of cessation\s*[^\n|]+", wlow):
                        active_dins.append(din)
                if active_dins:
                    result["board_total"] = len(active_dins)
                    independent = 0
                    for din in active_dins:
                        pos = board_seg.find(din)
                        window = board_seg[max(0, pos-120):pos + 700].lower()
                        if "independent director" in window:
                            independent += 1
                    result["independent_directors"] = independent

                def _committee_text(title: str, next_titles: tuple[str, ...]) -> str:
                    return _segment(title, next_titles)

                committee_sections = [
                    ("audit_members", "### Audit Committee Details", ("### Nomination and remuneration committee", "### Stakeholders Relationship Committee", "### Risk Management Committee")),
                    ("nrc_members", "### Nomination and remuneration committee", ("### Stakeholders Relationship Committee", "### Risk Management Committee", "III. Meeting of Board of Directors")),
                    ("stakeholder_members", "### Stakeholders Relationship Committee", ("### Risk Management Committee", "III. Meeting of Board of Directors")),
                    ("risk_members", "### Risk Management Committee", ("III. Meeting of Board of Directors", "IV. Meeting of Committees")),
                ]
                for key, title, ends in committee_sections:
                    seg = _committee_text(title, ends)
                    if seg:
                        cdins = _unique_dins(seg)
                        if cdins:
                            result[key] = len(cdins)

            board_meeting_seg = _segment("III. Meeting of Board of Directors", ("IV. Meeting of Committees", "VI. Affirmations"))
            if board_meeting_seg:
                dates = list(dict.fromkeys(re.findall(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}\b", board_meeting_seg)))
                if dates:
                    result["board_meetings"] = len(dates)
                    result["board_quorum_yes"] = sum(
                        1 for d in dates if re.search(re.escape(d) + r"[^\n]{0,250}\bYes\b", board_meeting_seg, re.I)
                    )

            committee_meeting_seg = _segment("IV. Meeting of Committees", ("VI. Affirmations", "VI. Affirmation"))
            if committee_meeting_seg:
                dates = list(dict.fromkeys(re.findall(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}\b", committee_meeting_seg)))
                if dates:
                    result["committee_meetings"] = len(dates)
                    result["committee_quorum_yes"] = sum(
                        1 for d in dates if re.search(re.escape(d) + r"[^\n]{0,250}\bYes\b", committee_meeting_seg, re.I)
                    )

            affirm_seg = _segment("VI. Affirmations", ("Signatory Details", "Details of Cyber security incidence"))
            if affirm_seg:
                status_part = affirm_seg[affirm_seg.lower().find("compliance status"):] if "compliance status" in affirm_seg.lower() else affirm_seg
                yes = len(re.findall(r"\bYes\b", status_part, re.I))
                no = len(re.findall(r"\bNo\b", status_part, re.I))
                na = len(re.findall(r"\bN/?A\b", status_part, re.I))
                if yes or no or na:
                    result["affirmations_yes"] = yes
                    result["affirmations_no"] = no
                    result["affirmations_na"] = na

            cyber_seg = _segment("Details of Cyber security incidence", ("Signatory Details", "Investor Grievance Details"))
            if cyber_seg:
                result["cyber_security_text"] = _norm_text(cyber_seg)[:700]
                m = re.search(r"number of cyber security[^\n|]*[|:]\s*(\d+)", cyber_seg, re.I)
                if m:
                    result["cyber_security_count"] = int(m.group(1))

            grievance_seg = _segment("Investor Grievance Details", ("Disclosure of Acquisition", "Disclosure of Imposition"))
            if grievance_seg:
                patterns = {
                    "investor_grievance_pending": r"pending at the beginning of Quarter\s*[|:]\s*(\d+)",
                    "investor_grievance_received": r"received during the Quarter\s*[|:]\s*(\d+)",
                    "investor_grievance_disposed": r"disposed off during the Quarter\s*[|:]\s*(\d+)",
                    "investor_grievance_unresolved": r"remaining unresolved at the end of the Quarter\s*[|:]\s*(\d+)",
                }
                for key, pat in patterns.items():
                    m = re.search(pat, grievance_seg, re.I)
                    if m:
                        result[key] = int(m.group(1))
                if any(result.get(k) is not None for k in patterns):
                    result["investor_grievance_text"] = "Investor grievance disclosure retrieved from NSE Integrated Filing – Governance."
        except Exception as exc:
            result["errors"].append(f"body_text:{type(exc).__name__}")

    # ------------------------------------------------------------------
    # Robust pandas/read_html fallback
    # ------------------------------------------------------------------
    # NSE iXBRL pages can be rendered with nested tables / repeated headers.
    # BeautifulSoup parsing above is intentionally conservative, but pandas'
    # HTML table parser is often able to recover the logical columns even when
    # the DOM structure is slightly different. Use it only to fill fields that
    # are still missing; never overwrite a successfully parsed value.
    try:
        html_tables = pd.read_html(io.StringIO(html))
    except Exception as exc:
        html_tables = []
        result["errors"].append(f"read_html:{type(exc).__name__}")

    def _norm_col(v: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(v).lower()).strip()

    # NSE iXBRL tables can be returned by pandas with numeric / tuple / mixed
    # column labels.  Normalize every parsed table once so later checks such as
    # `"compliance status" in column` never raise `TypeError` when `column` is
    # an int.  Keep the cell values unchanged; only column labels are normalized.
    normalized_tables = []
    for _df in html_tables:
        try:
            _df = _df.copy()
            _df.columns = [_norm_col(c) for c in _df.columns]
        except Exception:
            pass
        normalized_tables.append(_df)
    html_tables = normalized_tables

    def _df_text(df: pd.DataFrame) -> str:
        try:
            return " ".join(_norm_text(v) for v in df.astype(str).fillna("").values.flatten())
        except Exception:
            return ""

    def _current_rows(df: pd.DataFrame) -> pd.DataFrame:
        # Remove header-like rows accidentally read as data.
        work = df.copy().fillna("")
        work.columns = [_norm_col(c) for c in work.columns]
        if work.empty:
            return work
        # Prefer rows without a populated cessation date.
        cessation_cols = [c for c in work.columns if "date of cessation" in c]
        if cessation_cols:
            c = cessation_cols[0]
            vals = work[c].astype(str).str.strip().str.lower()
            work = work[(vals == "") | vals.isin(["na", "n/a", "-"])]
        # Some XBRL tables expose Current status instead of cessation.
        status_cols = [c for c in work.columns if "current status" in c]
        if status_cols:
            stv = work[status_cols[0]].astype(str).str.strip().str.lower()
            keep = (stv == "") | stv.isin(["active", "current", "nan"])
            work = work[keep]
        return work

    def _committee_count_df(df: pd.DataFrame) -> Optional[int]:
        work = _current_rows(df)
        din_cols = [c for c in work.columns if c == "din number" or "din number" in c]
        name_cols = [c for c in work.columns if "name of committee members" in c]
        if not din_cols and not name_cols:
            return None
        # DIN is the strongest row identifier. If a company uses a non-DIN
        # committee member (e.g. management on a risk committee), fall back to
        # non-empty member-name rows.
        key = din_cols[0] if din_cols else name_cols[0]
        vals = work[key].astype(str).str.strip()
        valid = vals[(vals != "") & (~vals.str.lower().isin(["nan", "none", "din number"]))]
        if len(valid):
            return int(len(valid))
        return None

    # Board table: identify by logical column names rather than exact DOM.
    if result.get("board_total") is None:
        for df in html_tables:
            cols = [_norm_col(c) for c in df.columns]
            blob = " | ".join(cols) + " " + _df_text(df).lower()
            has_name = any("name of the director" in c for c in cols)
            has_din = any(c == "din" or " din" in c or c.startswith("din ") for c in cols)
            has_cat = any("category 1 of directors" in c for c in cols)
            if not (has_name and has_din and has_cat):
                continue
            work = _current_rows(df)
            cat_cols = [c for c in work.columns if "category 1 of directors" in c]
            if not cat_cols:
                continue
            cat = work[cat_cols[0]].astype(str)
            # Rows can be wrapped by read_html; require a director/DIN signal.
            if any(c for c in cols if "name of the director" in c):
                name_col = next(c for c in work.columns if "name of the director" in c)
                work = work[work[name_col].astype(str).str.strip() != ""]
            if not work.empty:
                result["board_total"] = int(len(work))
                result["independent_directors"] = int(cat.str.contains("independent director", case=False, na=False).sum())
            break

    # Committee tables. A committee can be absent legitimately (e.g. risk
    # committee for an entity below the applicability threshold), so leave None
    # rather than converting absence into zero.
    committee_specs = [
        ("audit_members", ("audit committee", "audit committee details")),
        ("nrc_members", ("nomination and remuneration committee",)),
        ("stakeholder_members", ("stakeholders relationship committee", "stakeholder relationship committee")),
        ("risk_members", ("risk management committee",)),
    ]
    for key, labels in committee_specs:
        if result.get(key) is not None:
            continue
        for df in html_tables:
            cols = [_norm_col(c) for c in df.columns]
            if not any("name of committee members" in c for c in cols):
                continue
            blob = (" | ".join(cols) + " " + _df_text(df)).lower()
            if any(label in blob for label in labels):
                count = _committee_count_df(df)
                if count is not None:
                    result[key] = count
                    break

    # Board/committee meeting tables. Count actual dated rows and quorum=Yes.
    if result.get("board_meetings") is None:
        for df in html_tables:
            cols = [_norm_col(c) for c in df.columns]
            blob = (" | ".join(cols) + " " + _df_text(df)).lower()
            if not ("date(s) of meeting" in blob and "total number of directors" in blob and "number of independent directors" in blob):
                continue
            date_col = next((c for c in df.columns if "date(s) of meeting" in c), None)
            q_col = next((c for c in df.columns if "quorum" in c), None)
            if date_col is None:
                continue
            dates = df[date_col].astype(str).str.strip()
            dated = dates.str.contains(r"\b\d{1,2}[-/]?[A-Za-z]{3}[-/]?\d{4}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b", regex=True, na=False)
            n = int(dated.sum())
            if n:
                result["board_meetings"] = n
                if q_col is not None:
                    result["board_quorum_yes"] = int(df.loc[dated, q_col].astype(str).str.strip().str.lower().eq("yes").sum())
                break

    if result.get("committee_meetings") is None:
        for df in html_tables:
            cols = [_norm_col(c) for c in df.columns]
            blob = (" | ".join(cols) + " " + _df_text(df)).lower()
            if not ("name of committee" in blob and "quorum" in blob and "total number of directors in the committee" in blob):
                continue
            date_col = next((c for c in df.columns if "date(s) of meeting" in c), None)
            q_col = next((c for c in df.columns if "quorum" in c), None)
            if date_col is None:
                continue
            dates = df[date_col].astype(str).str.strip()
            dated = dates.str.contains(r"\b\d{1,2}[-/]?[A-Za-z]{3}[-/]?\d{4}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b", regex=True, na=False)
            n = int(dated.sum())
            if n:
                result["committee_meetings"] = n
                if q_col is not None:
                    result["committee_quorum_yes"] = int(df.loc[dated, q_col].astype(str).str.strip().str.lower().eq("yes").sum())
                break

    # Affirmations fallback: find the compliance-status column and count only
    # explicit Yes/No/NA values.
    if result.get("affirmations_yes") is None:
        for df in html_tables:
            cols = [_norm_col(c) for c in df.columns]
            status_cols = [c for c in df.columns if "compliance status" in c]
            if not status_cols:
                continue
            vals = df[status_cols[0]].astype(str).str.strip().str.lower()
            yes = int(vals.eq("yes").sum())
            no = int(vals.eq("no").sum())
            na = int(vals.isin(["na", "n/a"]).sum())
            if yes or no or na:
                result["affirmations_yes"] = yes
                result["affirmations_no"] = no
                result["affirmations_na"] = na
                break

    # ------------------------------------------------------------------
    # Signatory details are simple two-column rows.
    # ------------------------------------------------------------------
    for table in tables:
        rows = table_rows(table)
        for cells in rows:
            rt = " | ".join(cells)
            m = re.search(r"name of signatory\s*\|\s*(.+)", rt, re.I)
            if m:
                result["signatory"] = clean(m.group(1))
                break
        if result["signatory"]:
            break

    useful = (
        "board_total", "independent_directors", "audit_members", "nrc_members",
        "stakeholder_members", "risk_members", "committee_meetings",
        "board_meetings", "affirmations_yes", "affirmations_no",
        "cyber_security_count", "investor_grievance_unresolved"
    )
    extracted = sum(result.get(k) is not None for k in useful)
    result["parse_status"] = "parsed" if extracted >= 2 else ("partial" if extracted else "failed")
    return result


def _extract_governance_xbrl_html_from_html(html: str, source_url: str = "") -> Dict[str, Any]:
    return _extract_governance_xbrl_html(source_url or "https://www.nseindia.com/", html_override=html)



def _validate_governance_facts(facts: Dict[str, Any], source_name: str = "") -> Dict[str, Any]:
    """Fail-safe validation for governance facts before they reach the UI.

    NSE XBRL can contain multiple contexts/dimensions for the same person or
    committee. A context count is therefore NOT automatically a member count.
    This validator rejects impossible or structurally suspicious values instead
    of allowing a plausible-looking number to contaminate the research view.
    """
    if not isinstance(facts, dict):
        return {}
    out = dict(facts)
    notes = list(out.get("validation_notes") or [])

    def reject(key: str, reason: str):
        if out.get(key) is not None:
            notes.append(f"{source_name or 'source'}: rejected {key}={out.get(key)!r} ({reason})")
            out[key] = None

    def as_num(key):
        v = out.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            reject(key, "non-numeric value")
            return None

    bt = as_num("board_total")
    ind = as_num("independent_directors")

    if bt is not None and (bt < 1 or bt > 100):
        reject("board_total", "outside realistic listed-company board range")
        bt = None
    if ind is not None and (ind < 0 or ind > 100):
        reject("independent_directors", "outside realistic range")
        ind = None
    if bt is not None and ind is not None and ind > bt:
        reject("independent_directors", "cannot exceed total current directors")

    # These committees, where applicable, have statutory minimum membership
    # requirements. A parsed value of 1 or 2 is a strong signal that the parser
    # counted an XBRL context/dimension rather than actual people.
    for key in ("audit_members", "nrc_members", "stakeholder_members", "risk_members"):
        v = as_num(key)
        if v is not None:
            if v < 3:
                reject(key, "below the minimum committee membership; likely an XBRL context count")
            elif bt is not None and v > bt:
                reject(key, "cannot exceed total board directors")

    for key in ("committee_meetings", "board_meetings"):
        v = as_num(key)
        if v is not None and (v < 1 or v > 100):
            reject(key, "outside plausible filing-period meeting range")

    cm = as_num("committee_meetings")
    cq = as_num("committee_quorum_yes")
    if cq is not None and (cq < 0 or (cm is not None and cq > cm)):
        reject("committee_quorum_yes", "quorum-Yes count cannot exceed committee meetings")
    bm = as_num("board_meetings")
    bq = as_num("board_quorum_yes")
    if bq is not None and (bq < 0 or (bm is not None and bq > bm)):
        reject("board_quorum_yes", "quorum-Yes count cannot exceed board meetings")

    for key in ("affirmations_yes", "affirmations_no", "affirmations_na"):
        v = as_num(key)
        if v is not None and (v < 0 or v > 100):
            reject(key, "outside plausible affirmation count range")

    out["validation_notes"] = notes
    out["validation_passed"] = not any("rejected " in n for n in notes)
    return out

@st.cache_data(ttl=1800, show_spinner=False)

def _fetch_governance_attachment_via_browser(symbol: str) -> str:
    """Recover the actual NSE Governance PDF attachment through Chrome.

    NSE sometimes renders the Integrated Filing table with an attachment
    control rather than a normal <a href>. This helper uses the browser to
    inspect the newest Governance row, follows/clicks the attachment control,
    and returns either the official NSE URL or the downloaded local PDF path.
    No values are generated here.
    """
    import os
    import time
    import tempfile
    from pathlib import Path
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
    except Exception:
        return ""

    download_dir = tempfile.mkdtemp(prefix="nse_gov_")
    driver = None
    try:
        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        opts.add_experimental_option("prefs", {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
        })
        driver = webdriver.Chrome(options=opts)
        url = f"{NSE_INTEGRATED_URL}&symbol={quote_plus(symbol)}"
        driver.get(url)
        time.sleep(4)

        # Look for the real filing table and the newest row containing Governance.
        rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
        candidates = []
        for row in rows:
            txt = (row.text or "").strip()
            if symbol.upper() in txt.upper() and re.search(r"governance", txt, re.I):
                candidates.append(row)
        if not candidates:
            return ""

        row = candidates[0]
        cells = row.find_elements(By.CSS_SELECTOR, "td")
        attachment_candidates = []
        for cell in cells:
            ctext = (cell.text or "").strip().lower()
            if "attach" in ctext or "pdf" in ctext:
                attachment_candidates.append(cell)
        if not attachment_candidates:
            attachment_candidates = cells[-2:] if cells else []

        def inspect_elements(elements):
            for el in elements:
                for a in el.find_elements(By.CSS_SELECTOR, "a,button,[role='button'],[onclick]"):
                    attrs = []
                    for name in ("href","data-href","data-url","data-link","data-file",
                                 "data-file-url","onclick","title","aria-label"):
                        try:
                            v = a.get_attribute(name)
                        except Exception:
                            v = None
                        if v:
                            attrs.append(str(v))
                    joined = " ".join(attrs)
                    m = re.search(r"https?://[^\s\"']+?(?:\.pdf|/corporate/[^\s\"']+)", joined, re.I)
                    if m:
                        return m.group(0).rstrip("');,")
            return ""

        direct = inspect_elements(attachment_candidates)
        if direct:
            return direct

        # Click attachment controls and watch for a new tab or downloaded PDF.
        before_tabs = list(driver.window_handles)
        for cell in attachment_candidates:
            controls = cell.find_elements(By.CSS_SELECTOR, "a,button,[role='button'],[onclick]")
            for ctl in controls:
                try:
                    driver.execute_script("arguments[0].click();", ctl)
                    time.sleep(2)
                    for h in driver.window_handles:
                        if h not in before_tabs:
                            driver.switch_to.window(h)
                            u = driver.current_url
                            if u and (".pdf" in u.lower() or "nsearchives.nseindia.com" in u.lower()):
                                return u
                            driver.close()
                            driver.switch_to.window(before_tabs[0])
                    files = sorted(Path(download_dir).glob("*.pdf"),
                                   key=lambda p: p.stat().st_mtime, reverse=True)
                    if files:
                        return str(files[0])
                except Exception:
                    continue
        return ""
    except Exception:
        return ""
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_governance_xbrl_summary(ticker: str, filings_json: str, use_browser_fallback: bool = False) -> Dict[str, Any]:
    """Fetch and MERGE actual NSE Integrated Filing-Governance sources.

    Important fix in V23: a partial raw-XBRL parse (for example, only Board
    Directors=11) must NOT stop the pipeline. We continue through the filing's
    PDF and official NSE governance page and merge only non-null facts. This
    prevents one successfully parsed field from causing the remaining fields
    to stay N/A when the same filing is available in another representation.
    No values are synthesized.
    """
    try:
        filings = pd.read_json(io.StringIO(filings_json or "[]"), orient="records")
    except Exception:
        filings = pd.DataFrame()

    symbol = ticker.split(".")[0].upper()
    work = filings.copy()
    if not work.empty and "Date" in work.columns:
        work["_dt"] = pd.to_datetime(work["Date"], errors="coerce", dayfirst=True)
        work = work.sort_values("_dt", ascending=False, na_position="last")

    # With no official filing row there is no XBRL/PDF URL to parse. Avoid
    # repeating a second slow NSE detail-page request after the catalog timeout.
    if work.empty and not use_browser_fallback:
        return {
            "board_total": None, "independent_directors": None, "audit_members": None,
            "nrc_members": None, "stakeholder_members": None, "risk_members": None,
            "committee_meetings": None, "board_meetings": None,
            "affirmations_yes": None, "affirmations_no": None, "affirmations_na": None,
            "cyber_security_count": None, "investor_grievance_unresolved": None,
            "investor_grievance_pending": None, "investor_grievance_received": None,
            "investor_grievance_disposed": None, "committee_quorum_yes": None,
            "board_quorum_yes": None, "source": "NSE governance filing unavailable",
            "errors": ["No filing metadata was returned; no governance facts were inferred."],
            "field_sources": {}, "attempted_sources": [], "parse_status": "unavailable",
        }

    xbrl_urls=[]; pdf_urls=[]; ixbrl_urls=[]
    attempted=[]; errors=[]; source_hits=[]
    if not work.empty:
        for _, row in work.iterrows():
            x=_norm_text(row.get("XBRL"))
            ix=_norm_text(row.get("iXBRL"))
            a=_norm_text(row.get("Attachment"))
            if x.startswith("http") and x not in xbrl_urls and ix != x: xbrl_urls.append(x)
            if ix.startswith("http") and ix not in ixbrl_urls: ixbrl_urls.append(ix)
            if a.startswith("http") and a not in pdf_urls: pdf_urls.append(a)

    # The Integrated Filing catalog can expose XBRL but omit the attachment.
    # NSE's corporate-announcement feed often carries the exact PDF attachment
    # for the same "Integrated Filing- Governance" submission. Use it as an
    # official-source bridge to the submitted filing.
    if not pdf_urls:
        try:
            ann_df, _ann_source = fetch_governance_announcements(ticker)
            if ann_df is not None and not ann_df.empty:
                work_ann = ann_df.copy()
                if "Date" in work_ann.columns:
                    work_ann["_dt"] = pd.to_datetime(work_ann["Date"], errors="coerce", dayfirst=True)
                    work_ann = work_ann.sort_values("_dt", ascending=False, na_position="last")
                for _, ar in work_ann.iterrows():
                    typ = _norm_text(ar.get("Type"))
                    details = _norm_text(ar.get("Details"))
                    if re.search(r'integrated filing[- ]*governance', typ + ' ' + details, re.I):
                        a = _norm_text(ar.get("Attachment"))
                        if a.startswith("http") and a not in pdf_urls:
                            pdf_urls.append(a)
                            # Stop after the newest exact governance attachment.
                            break
        except Exception as exc:
            errors.append(f"announcement_pdf_discovery:{type(exc).__name__}")

    # V4: if NSE exposed the filing/XBRL row but did not expose its PDF
    # attachment to requests, recover the actual attachment through Chrome.
    if not pdf_urls and use_browser_fallback:
        try:
            browser_pdf = _fetch_governance_attachment_via_browser(symbol)
            if browser_pdf:
                pdf_urls.append(browser_pdf)
                source_hits.append("NSE browser attachment recovery: PDF attachment recovered")
        except Exception as exc:
            errors.append(f"browser_attachment_discovery:{type(exc).__name__}")

    # Keep explicitly provided iXBRL URLs separate from known historical
    # source-only fallbacks, which have a lower freshness priority.

    # Keep several candidates for PDF fallback because a revised filing may
    # supersede the original attachment. The first usable parsed source wins.
    xbrl_urls=xbrl_urls[:1]
    pdf_urls=pdf_urls[:1]
    ixbrl_urls=ixbrl_urls[:2]
    latest_row = work.iloc[0] if not work.empty else None
    useful=("board_total","independent_directors","audit_members","nrc_members",
            "stakeholder_members","risk_members","committee_meetings","board_meetings",
            "affirmations_yes","affirmations_no","cyber_security_count",
            "investor_grievance_unresolved")

    merged={k:None for k in useful}
    # Include other display fields too.
    merged.update({"chairperson_regular":None,"chairperson_related_to_md_ceo":None,
                   "committee_quorum_yes":None,"board_quorum_yes":None,
                   "affirmations_na":None,"investor_grievance_pending":None,
                   "investor_grievance_received":None,"investor_grievance_disposed":None,
                   "cyber_security_text":None,"investor_grievance_text":None,
                   "signatory":None,"period_end":None,"reporting_quarter":None})

    source_priority = {}
    field_sources = {}

    def _priority(name: str) -> int:
        name = name.lower()
        if "historical ixbrl fallback" in name:
            # Actual row-based official filing, but an older period: it may fill
            # missing fields from raw XML while current iXBRL/PDF/detail data wins.
            return 55
        if "detail page fallback parser" in name:
            return 95
        if "governance detail page" in name:
            return 100
        if "direct ixbrl" in name or "ixbrl html" in name:
            return 85
        if "filing pdf" in name:
            return 75
        if "raw xbrl" in name:
            return 20
        return 10

    def add_source(facts, source_name, url):
        if not isinstance(facts, dict): return 0
        facts = _validate_governance_facts(facts, source_name)
        hits=[]
        priority = _priority(source_name)
        for k in list(merged.keys()):
            v=facts.get(k)
            if v is None:
                continue
            # Prefer a higher-quality rendered filing/detail source over a
            # heuristic raw-XBRL context count. This prevents an earlier weak
            # value from blocking a later, row-aware value.
            if merged.get(k) is None or priority > source_priority.get(k, -1):
                merged[k]=v
                source_priority[k]=priority
                field_sources[k] = {
                    "source": source_name,
                    "url": url,
                    "period": _norm_text(facts.get("period_end") or facts.get("reporting_quarter") or facts.get("quarter_end_date")),
                }
                hits.append(k)
        if hits: source_hits.append(f"{source_name}: {', '.join(hits)}")
        errors.extend(facts.get("errors") or [])
        errors.extend(facts.get("validation_notes") or [])
        return len(hits)

    # A. Exact raw XBRL/XML. Keep partial results and continue.
    for raw in xbrl_urls:
        attempted.append(raw)
        facts=_extract_governance_raw_xbrl(raw)
        add_source(facts, "raw XBRL", raw)

    # B. Prefer an iXBRL URL explicitly provided by NSE metadata.
    for ix in ixbrl_urls:
        if ix in attempted: continue
        attempted.append(ix)
        facts=_extract_governance_xbrl_html(ix, browser_fallback=use_browser_fallback)
        add_source(facts, "NSE direct iXBRL link", ix)

    # C. Exact official iXBRL fallbacks. These URLs were verified to be actual
    # NSE-published rendered filings. We deliberately do NOT guess an HTML URL
    # by reusing the XML file's numeric ID; that pattern repeatedly returns 404.
    # The fallback period is captured from the report itself and displayed in
    # field-level evidence so historical values can never masquerade as current.
    for ix in KNOWN_GOVERNANCE_XBRL.get(symbol, []):
        if ix in attempted: continue
        attempted.append(ix)
        facts=_extract_governance_xbrl_html(ix, browser_fallback=use_browser_fallback)
        add_source(facts, "NSE historical iXBRL fallback", ix)

    # D. Actual PDF attachment from the same NSE filing row. This is especially
    # useful when raw XBRL contains opaque taxonomy concepts but the PDF has the
    # rendered governance tables. It outranks a historical fallback by source
    # freshness/quality.
    for pdf in pdf_urls:
        if pdf in attempted: continue
        attempted.append(pdf)
        facts=_extract_governance_pdf(pdf)
        add_source(facts, "NSE filing PDF", pdf)

    # E. Official NSE Governance detail page. Never treat the empty page shell
    # as a successful source: the browser helper returns HTML only after it sees
    # several distinct director DINs inside a Board table.
    detail_url=f"{NSE_GOV_URL}?symbol={quote_plus(symbol)}&tabIndex=equity"
    attempted.append(detail_url)
    detail_html, detail_messages = _fetch_governance_detail_html_verified(symbol, browser_fallback=use_browser_fallback)
    errors.extend(detail_messages)
    if detail_html:
        detail_facts=_extract_governance_detail_page_html(detail_html, source_url=detail_url)
        add_source(detail_facts, "NSE governance detail page", detail_url)
        # The page is validated as populated above; the dedicated parser should
        # be enough. Only run the iXBRL parser if the dedicated parser found no
        # core fields, which can happen after an NSE DOM schema change.
        if not any(detail_facts.get(k) is not None for k in ("board_total", "audit_members", "nrc_members", "stakeholder_members", "risk_members")):
            ix_facts=_extract_governance_xbrl_html_from_html(detail_html, source_url=detail_url)
            add_source(ix_facts, "NSE governance detail page fallback parser", detail_url)

    # Final cross-field validation after all sources have been merged. This is
    # the last gate before the values are exposed to Streamlit.
    merged = _validate_governance_facts(merged, "final merged governance data")
    errors.extend(merged.get("validation_notes") or [])

    extracted=sum(merged.get(k) is not None for k in useful)
    core_keys=("board_total", "independent_directors", "audit_members", "nrc_members",
               "stakeholder_members", "risk_members", "board_meetings", "committee_meetings")
    core_extracted=sum(merged.get(k) is not None for k in core_keys)
    if latest_row is not None:
        filing_date=_norm_text(latest_row.get("Date"))
        period=_norm_text(latest_row.get("Quarter / Period"))
        filing_type=_norm_text(latest_row.get("Type"))
    else:
        filing_date="N/A"; period=merged.get("period_end") or "N/A"; filing_type="Integrated Filing – Governance"

    if extracted:
        merged.update({
            "filing_date": filing_date,
            "period": period,
            "filing_type": filing_type,
            "source": f"NSE Integrated Filing – Governance ({filing_date})",
            "source_url": attempted[0] if attempted else "",
            "attempted_xbrl_urls": attempted,
            "attempted_sources": attempted,
            "source_hits": source_hits,
            "errors": errors,
            "parse_status": "parsed" if merged.get("board_total") is not None and core_extracted >= 3 else "partial",
            "core_fields_extracted": core_extracted,
            "core_fields_expected": len(core_keys),
            "retrieval_stage": "merged_sources",
            "taxonomy_parser": "enabled",
            "validation_passed": merged.get("validation_passed", False),
            "validation_notes": merged.get("validation_notes", []),
            "field_sources": {k: v for k, v in field_sources.items() if merged.get(k) is not None},
        })
        return merged

    return {
        "source":"NSE governance data could not be parsed by the local client",
        "facts":{}, "errors":errors or ["No readable NSE governance XBRL/iXBRL/PDF/detail page was returned"],
        "attempted_xbrl_urls":attempted, "attempted_sources":attempted, "source_hits":source_hits,
        "parse_status":"failed", "core_fields_extracted":0, "core_fields_expected":8,
        "retrieval_stage":errors[-1] if errors else "no_source_retrieved"
    }

BRSR_METRIC_PATTERNS = {
    "Scope 1 GHG emissions": [r"scope.*1.*ghg.*emission", r"ghg.*emission.*scope.*1"],
    "Scope 2 GHG emissions": [r"scope.*2.*ghg.*emission", r"ghg.*emission.*scope.*2"],
    "Total energy consumption": [r"total.*energy.*consumption", r"energy.*consumption"],
    "Renewable energy consumption": [r"renewable.*energy.*consumption"],
    "Water consumption": [r"water.*consumption"],
    "Water withdrawal": [r"water.*withdrawal"],
    "Waste generated": [r"waste.*generated"],
    "Waste recycled": [r"waste.*recycl"],
    "Total employees": [r"total.*employees", r"employees.*total"],
    "Women employees": [r"women.*employees", r"female.*employees"],
    "Employee turnover": [r"employee.*turnover"],
    "Work-related fatalities": [r"work.*related.*fatalit", r"fatalit.*work"],
    "Board meetings": [r"board.*meeting"],
    "Independent directors": [r"independent.*director"],
    "Women directors": [r"women.*director", r"female.*director"],
    "CSR expenditure": [r"csr.*expenditure", r"csr.*spent"],
}


def _brsr_numeric_candidates(text: str) -> List[Tuple[str, int, int]]:
    """Return numeric tokens while safely ignoring financial-year fragments.

    PDF text extraction commonly turns ``2025-26`` into separate tokens such as
    ``2025`` and ``-26``.  The old parser treated ``-26`` as the metric value.
    This helper rejects year fragments, page/year references and sign fragments
    while preserving genuine values such as ``-12.5`` when they are actually
    reported as a number.
    """
    text = str(text or "")
    out: List[Tuple[str, int, int]] = []
    # Do not let a regex starting at the minus sign in 2025-26 capture ``-26``.
    pat = re.compile(r"(?<!\d)([-+]?\d[\d,]*(?:\.\d+)?(?:[Ee][-+]?\d+)?)")
    for m in pat.finditer(text):
        raw = m.group(1)
        compact = raw.replace(',', '')
        digits = re.sub(r"\D", "", compact)
        before = text[max(0, m.start()-12):m.start()]
        after = text[m.end():m.end()+8]

        # 2025-26 / 2024–25 / 2025/26 year fragments.
        if re.search(r"20\d{2}\s*[-–—/]\s*$", before) and len(digits) <= 2:
            continue
        # If extraction begins at the second half of a year, e.g. ``-26``.
        if raw.startswith(('-', '+')) and len(digits) <= 2 and re.search(r"20\d{2}\s*$", before):
            continue
        # Four-digit calendar/fiscal years are not metric values for these fields.
        if len(digits) == 4 and digits.startswith(('19', '20')):
            continue
        # Standalone FY year fragments such as ``FY 26``.
        if len(digits) <= 2 and re.search(r"(?:FY|financial\s+year)\s*$", before, re.I):
            continue
        # Page-number style references (``Page 243``) are not values.
        if re.search(r"(?:page|pg\.?|pdf\s+page)\s*$", before, re.I):
            continue
        # A signed 1–2 digit value immediately after a fiscal-year range is
        # almost always an extracted ``-26`` / ``-25`` fragment, not the metric.
        if raw.startswith(('-', '+')) and len(digits) <= 2 and re.search(r"20\d{2}\s*[-–—/]\s*\d{1,2}\s*$", before):
            continue
        if raw.startswith(('-', '+')) and len(digits) <= 2 and re.search(r"20\d{2}[\s]*$", before):
            continue
        out.append((compact, m.start(), m.end()))
    return out


def _extract_brsr_value_after_label(text: str, patterns: List[str]) -> Optional[str]:
    """Extract the first defensible numeric value following a BRSR metric label.

    The function is deliberately conservative. If the only numbers near a label
    are years/page references, it returns ``None`` instead of inventing a value.
    """
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return None
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        # Metrics are normally followed by the current-year value in BRSR tables.
        tail = text[m.end():m.end()+260]
        candidates = _brsr_numeric_candidates(tail)
        if candidates:
            return candidates[0][0]
    return None


def _xbrl_numeric_facts(content: bytes) -> List[Dict[str, Any]]:
    """Parse generic XBRL/XML facts without hard-coding one NSE taxonomy version."""
    root = ET.fromstring(content)
    facts=[]
    for elem in root.iter():
        tag = str(elem.tag).split('}')[-1]
        text = (elem.text or '').strip()
        if not text or not re.search(r"[-+]?\d", text):
            continue
        if len(text) > 120 or not re.fullmatch(r"[-+]?\d[\d,]*(?:\.\d+)?(?:[Ee][-+]?\d+)?", text):
            continue
        facts.append({
            "Concept": tag,
            "Value": text.replace(',', ''),
            "Unit": elem.attrib.get('unitRef',''),
            "Context": elem.attrib.get('contextRef',''),
        })
    return facts

def _match_brsr_metric(concept: str) -> Optional[str]:
    c = re.sub(r"([a-z])([A-Z])", r"\1 \2", concept).lower()
    for label, pats in BRSR_METRIC_PATTERNS.items():
        if any(re.search(p, c, re.I) for p in pats):
            return label
    return None

def _parse_xbrl_payload(payload: bytes) -> List[Dict[str, Any]]:
    """Parse every XML/XBRL file in an NSE XBRL ZIP, not only the first file."""
    payloads = []
    if payload[:2] == b'PK':
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(('.xml', '.xbrl')):
                    try:
                        payloads.append(zf.read(name))
                    except Exception:
                        pass
    else:
        payloads = [payload]
    facts = []
    for part in payloads:
        try:
            facts.extend(_xbrl_numeric_facts(part))
        except Exception:
            continue
    return facts


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_brsr_xbrl_metrics(ticker: str, use_browser_fallback: bool = False) -> Tuple[pd.DataFrame, str]:
    """Download and parse the latest actual NSE BRSR XBRL, with annual-report fallback."""
    brsr, source = fetch_brsr_filings(ticker, use_browser_fallback=use_browser_fallback)
    candidates = brsr[brsr['XBRL'].astype(str).str.startswith('http')].copy() if (not brsr.empty and 'XBRL' in brsr.columns) else pd.DataFrame()
    for _, row in candidates.iterrows():
        url = str(row.get('XBRL') or '')
        try:
            r = requests.get(url, headers={
                'User-Agent': USER_AGENT, 'Accept': '*/*', 'Referer': NSE_BRSR_URL,
            }, timeout=(3, 12))
            r.raise_for_status()
            facts = _parse_xbrl_payload(r.content)
            matched=[]
            for f in facts:
                metric=_match_brsr_metric(f['Concept'])
                if metric:
                    f['Metric']=metric
                    matched.append(f)
            if matched:
                df=pd.DataFrame(matched).drop_duplicates(subset=['Metric'], keep='first')
                return df[['Metric','Value','Unit','Concept','Context']], f'NSE BRSR XBRL — {row.get("From Year","")}-{row.get("To Year","")}'
        except Exception:
            continue

    # Evidence-grade fallback: use the actual annual-report PDF and inspect its
    # BRSR section. This is especially important when NSE's BRSR grid is JS-only
    # or the XBRL attachment is not exposed to the local client.
    try:
        from data.annual_report import discover_annual_reports, extract_annual_report_pages
        reports, report_source = discover_annual_reports(ticker)
        if not reports.empty:
            candidate=reports[reports["Attachment"].astype(str).str.startswith("http")]
            if not candidate.empty:
                row=candidate.iloc[0]
                pdf_url=str(row.get("Attachment") or "")
                pages=extract_annual_report_pages(pdf_url)
                if pages:
                    # Locate pages belonging to BRSR / Business Responsibility
                    # disclosures. We intentionally use context + nearby numbers,
                    # not a hard-coded company value.
                    brsr_pages=[]
                    for page in pages:
                        text=re.sub(r"\s+", " ", str(page.get("text") or "")).strip()
                        low=text.lower()
                        if any(k in low for k in (
                            "business responsibility and sustainability report",
                            "business responsibility & sustainability report",
                            "business responsibility report",
                            "brsr core",
                            "brsr disclosure",
                            "principle 1",
                            "principle 2",
                        )):
                            brsr_pages.append(page)

                    # If the report does not contain the section heading on the
                    # same page as the metrics, inspect all pages as a controlled
                    # fallback. This still only extracts published text.
                    search_pages=brsr_pages or pages
                    found=[]
                    for page in search_pages:
                        raw=str(page.get("text") or "")
                        if not raw.strip():
                            continue
                        lines=[re.sub(r"\s+", " ", x).strip() for x in raw.splitlines() if str(x).strip()]
                        joined=" ".join(lines)
                        for metric,pats in BRSR_METRIC_PATTERNS.items():
                            if any(re.search(p, joined, re.I) for p in pats):
                                # First try line-level matches, then a small
                                # surrounding window. Avoid four-digit years as
                                # values unless the metric itself is a year field.
                                hit=None
                                for idx,line in enumerate(lines):
                                    if not any(re.search(p, line, re.I) for p in pats):
                                        continue
                                    # First preference: value on the same line as
                                    # the metric label, with fiscal-year fragments
                                    # explicitly removed by the safe tokenizer.
                                    hit=_extract_brsr_value_after_label(line, pats)
                                    if hit is None:
                                        # BRSR PDF tables often wrap the value onto
                                        # the next one or two extracted lines.
                                        window=" ".join(lines[idx:idx+3])
                                        hit=_extract_brsr_value_after_label(window, pats)
                                    if hit is not None:
                                        break
                                if hit is None:
                                    # Compact-table fallback: search after the
                                    # metric label, never treating 2025-26's -26
                                    # fragment as a reported metric.
                                    hit=_extract_brsr_value_after_label(joined, pats)
                                if hit is not None:
                                    found.append({
                                        "Metric":metric,
                                        "Value":hit,
                                        "Unit":"",
                                        "Concept":"Annual report BRSR section",
                                        "Context":f"PDF page {page.get('page')}",
                                    })
                    if found:
                        df=pd.DataFrame(found).drop_duplicates(subset=["Metric"], keep="first")
                        return df[["Metric","Value","Unit","Concept","Context"]], f"Official annual-report BRSR section — {row.get('From Year','')}-{row.get('To Year','')} ({report_source})"
    except Exception:
        pass

    return pd.DataFrame(), f'{source}; no XBRL link was accessible and annual-report BRSR fallback returned no parsable numeric metrics'


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_crisil_esg_rating(ticker: str) -> pd.DataFrame:
    """Fetch the public CRISIL ESG ratings list and match the selected company by name."""
    try:
        from data.fetch_live import get_live_profile
        company = str(get_live_profile(ticker).get("name") or ticker).lower()
    except Exception:
        company = ticker.split(".")[0].lower()
    url = "https://www.crisilesg.com/en/home/esg-ratings.html"
    try:
        r=requests.get(url, headers={"User-Agent":"Mozilla/5.0","Accept":"text/html"}, timeout=(2.5, 6))
        r.raise_for_status()
        tables=pd.read_html(io.StringIO(r.text))
        matches=[]
        for df in tables:
            if df.empty: continue
            df.columns=[str(c) for c in df.columns]
            text=df.astype(str).agg(" ".join, axis=1).str.lower()
            # Match company full/short name; strip common legal suffixes for better recall.
            names=[company, company.replace(" limited", ""), company.replace(" ltd", "")]
            mask=pd.Series(False,index=df.index)
            for n in names:
                n=re.sub(r"\s+", " ", n).strip()
                if len(n)>=4: mask |= text.str.contains(re.escape(n), regex=True, na=False)
            if mask.any():
                matches.append(df.loc[mask])
        if matches:
            return pd.concat(matches, ignore_index=True).drop_duplicates()
    except Exception:
        pass
    return pd.DataFrame()

def _clean_rationale_text(text: str) -> str:
    text=re.sub(r"\s+", " ", text or "").strip()
    return text

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_rating_rationale_summary(source_url: str) -> str:
    """Best-effort extraction of a short rationale from an NSE/agency public disclosure."""
    if not source_url or not source_url.startswith("http"):
        return ""
    try:
        r=requests.get(source_url, headers={"User-Agent":"Mozilla/5.0","Accept":"*/*"}, timeout=(2.5, 7))
        r.raise_for_status()
        content=r.content
        text=""
        ctype=r.headers.get("Content-Type","").lower()
        if content[:4] == b"%PDF" or "pdf" in ctype or source_url.lower().endswith(".pdf"):
            try:
                from pypdf import PdfReader
                reader=PdfReader(io.BytesIO(content))
                text=" ".join((page.extract_text() or "") for page in reader.pages[:12])
            except Exception:
                text=""
        if not text:
            from bs4 import BeautifulSoup
            text=BeautifulSoup(content, "lxml").get_text(" ", strip=True)
        text=_clean_rationale_text(text)
        if not text: return ""
        # Prefer the rating-driver section; otherwise return the first useful 700 chars.
        patterns=[r"rating drivers?[:\- ]+(.*?)(?:rating sensitivities|key rating factors|outlook|about the company)",
                  r"key rating drivers?[:\- ]+(.*?)(?:rating sensitivities|about the company)",
                  r"detailed description of key rating drivers[:\- ]+(.*?)(?:rating sensitivities|about the company)"]
        for pat in patterns:
            m=re.search(pat,text,re.I)
            if m and len(m.group(1))>80:
                return m.group(1)[:900].strip() + ("…" if len(m.group(1))>900 else "")
        return text[:900] + ("…" if len(text)>900 else "")
    except Exception:
        return ""

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_yahoo_esg(ticker: str) -> pd.DataFrame:
    try:
        import yfinance as yf
        s = yf.Ticker(ticker).sustainability
        if isinstance(s, pd.DataFrame) and not s.empty:
            return s.reset_index().rename(columns={"index": "Metric"})
    except Exception:
        pass
    return pd.DataFrame()

def yahoo_esg_scores(yahoo: pd.DataFrame) -> Dict[str, Optional[float]]:
    """Extract common Yahoo sustainability scores without assuming a fixed table orientation."""
    out={"Total ESG":None,"Environment":None,"Social":None,"Governance":None,"Controversy":None}
    if yahoo is None or yahoo.empty:
        return out
    rows=yahoo.copy()
    # yfinance sustainability is commonly metric x value; handle either orientation.
    for _, row in rows.iterrows():
        blob=' '.join(str(x) for x in row.tolist()).lower()
        vals=[]
        for x in row.tolist():
            try:
                v=float(x)
                if pd.notna(v): vals.append(v)
            except Exception: pass
        if not vals: continue
        v=vals[-1]
        if 'totalesg' in blob or 'total esg' in blob: out['Total ESG']=v
        elif 'environment' in blob and 'score' in blob: out['Environment']=v
        elif 'social' in blob and 'score' in blob: out['Social']=v
        elif 'governance' in blob and 'score' in blob: out['Governance']=v
        el# ---------------------------------------------------------------------------
# Credit-rating intelligence
# ---------------------------------------------------------------------------
# Ratings are sourced from official Indian CRA publications.  We search each
# agency separately (never combine multiple site: operators in one query),
# parse the public report/rationale, and retain the source URL beside every
# extracted rating.  If an agency has no public result, that agency simply
# contributes no row; the dashboard never invents a rating.

RATING_RE = re.compile(
    r"\b(?:CRISIL|CARE|ICRA|IND(?:-RA)?|BWR|ACUITE|IVR|ACER|CREDSTONE)?\s*"
    r"(?:AAA|AA\+|AA-|AA|A\+|A-|A|BBB\+|BBB-|BBB|BB\+|BB-|BB|B\+|B-|B|C|D|A1\+|A1|A2\+|A2|A3\+|A3|A4|A4\+|D)\b",
    re.I,
)
OUTLOOK_RE = re.compile(r"\b(Stable|Positive|Negative|Watch Positive|Watch Negative|Developing)\b", re.I)
AGENCY_RE = re.compile(r"\b(CRISIL|ICRA|CARE(?: Ratings|Edge)?|India Ratings|Ind-Ra|Acuité|Acuite|Brickwork|BWR|Infomerics|ACER|CredStone)\b", re.I)

# SEBI's current register has nine registered CRAs as of Oct-2026.  The seven
# established public archives are CRISIL, ICRA, CARE, India Ratings, Acuité,
# Brickwork and Infomerics; ACER and CredStone are newer registrants.
# We include all nine so a company rated by a newer CRA is not silently missed.
AGENCY_SEARCH_DOMAINS = {
    "CRISIL": ["crisilratings.com", "crisil.com"],
    "ICRA": ["icra.in"],
    "CARE Ratings": ["careratings.com", "careedge.in"],
    "India Ratings": ["indiaratings.co.in"],
    "Acuité": ["acuite.in"],
    "Brickwork": ["brickworkratings.com"],
    "Infomerics": ["infomerics.com"],
    "ACER": ["acerratings.com"],
    "CredStone": ["credstone.in", "credstoneratings.com"],
}

# Issuer-maintained credit-rating summary pages. These are used only as a
# labelled fallback when CRA report discovery is blocked; their publication
# date is not assumed. Rows are explicitly marked as issuer-published summaries.
ISSUER_RATING_SUMMARY_PAGES = {
    "ICICIBANK": {
        "company": "ICICI Bank Limited",
        "url": "https://www.icici.bank.in/about-us/credit-rating",
    },
    "HDFCBANK": {
        "company": "HDFC Bank Limited",
        "url": "https://www.hdfc.bank.in/about-us/ratings",
    },
}

AGENCY_ALIASES = {
    "CRISIL": ["CRISIL", "Crisil Ratings"],
    "ICRA": ["ICRA"],
    "CARE Ratings": ["CARE Ratings", "CareEdge", "CARE"],
    "India Ratings": ["India Ratings", "Ind-Ra"],
    "Acuité": ["Acuité", "Acuite", "SMERA"],
    "Brickwork": ["Brickwork", "BWR"],
    "Infomerics": ["Infomerics", "IVR"],
    "ACER": ["ACER Credit Rating", "ACER"],
    "CredStone": ["CredStone Ratings", "CredStone"],
}

# Kept only as verified seed URLs; web discovery handles every other company.
KNOWN_AGENCY_REPORTS = {
    "ULTRACEMCO": [
        {"Agency": "CRISIL", "Title": "UltraTech Cement Limited — Rating Rationale, 17-Aug-2026", "URL": "https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/RatingDocs/UltraTechCementLimited_August%2017_%202026_RR_401130.html"},
        {"Agency": "CRISIL", "Title": "UltraTech Cement Limited — Rating Rationale, 23-Jul-2026", "URL": "https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/RatingDocs/UltraTechCementLimited_July%2023_%202026_RR_400697.html"},
    ],
}

_RATING_SEARCH_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/156 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}


def _company_name_for_rating(ticker: str) -> str:
    symbol = str(ticker or "").split(".")[0].upper()
    try:
        from data.fetch_universe import build_listing
        listing, _ = build_listing()
        if isinstance(listing, pd.DataFrame) and not listing.empty:
            m = listing[listing["key"].astype(str).str.upper() == str(ticker).upper()]
            if not m.empty:
                return str(m.iloc[0].get("name") or symbol).strip()
            m = listing[listing["symbol"].astype(str).str.upper() == symbol]
            if not m.empty:
                return str(m.iloc[0].get("name") or symbol).strip()
    except Exception:
        pass
    # Reliable fallback when the NSE/BSE universe file is unavailable. Yahoo's
    # chart endpoint returns the exchange security's display name without needing
    # the slower full .info payload. This is important because CRA reports use
    # legal company names (e.g. HDFC Bank Limited), not NSE tickers (HDFCBANK).
    try:
        u = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}?range=1d&interval=1d"
        r = requests.get(u, headers=_RATING_SEARCH_UA, timeout=(2.5, 6))
        if r.ok:
            meta = ((r.json().get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
            for k in ("longName", "shortName"):
                name = str(meta.get(k) or "").strip()
                if name and name.upper() != symbol:
                    return name
    except Exception:
        pass
    return symbol


def _agency_from_text(text: str, fallback: str = "") -> str:
    blob = str(text or "")
    for agency, aliases in AGENCY_ALIASES.items():
        if any(re.search(r"\b" + re.escape(a) + r"\b", blob, re.I) for a in aliases):
            return agency
    return fallback


def _rating_symbol_from_text(text: str) -> str:
    """Extract a rating symbol without truncating suffixes such as AA+ or A1+."""
    blob = re.sub(r"\s+", " ", str(text or ""))
    prefix = r"(?:CRISIL|CARE|ICRA|IND(?:-RA)?|BWR|ACUITE|IVR|ACER|CREDSTONE)?\s*"
    # Do not use a trailing word-boundary after '+' or '-': those signs are
    # non-word characters and '\b' can incorrectly truncate AA+ to AA.
    short = re.search(r"\b" + prefix + r"(A1\+|A1|A2\+|A2|A3\+|A3|A4\+|A4)(?![A-Z0-9])", blob, re.I)
    if short:
        return short.group(1).upper()
    long = re.search(r"\b" + prefix + r"(AAA|AA\+|AA-|AA|A\+|A-|A|BBB\+|BBB-|BBB|BB\+|BB-|BB|B\+|B-|B|C|D)(?![A-Z0-9])", blob, re.I)
    return long.group(1).upper() if long else ""


def _extract_instrument(text: str) -> str:
    patterns = [
        (r"commercial paper|\bCP\b", "Commercial Paper"),
        (r"certificate[s]? of deposit|\bCD\b", "Certificate of Deposit"),
        (r"non[- ]?convertible debenture|\bNCD\b", "NCD"),
        (r"fixed deposit", "Fixed Deposit"),
        (r"bank facilit(?:y|ies)|term loan|working capital|cash credit|overdraft", "Bank Facilities"),
        (r"long[- ]?term", "Long Term"),
        (r"short[- ]?term", "Short Term"),
        (r"issuer rating", "Issuer Rating"),
        (r"subordinated|tier[- ]?ii|tier[- ]?1|tier[- ]?i", "Capital / Tier Instrument"),
    ]
    for pat, label in patterns:
        if re.search(pat, text or "", re.I):
            return label
    return "Instrument / Facility"


def _extract_action(text: str) -> str:
    b = str(text or "")
    for pat, action in [
        (r"downgrad", "Downgraded"), (r"upgrad", "Upgraded"),
        (r"reaffirm|re-affirm", "Reaffirmed"), (r"assign|assigned", "Assigned"),
        (r"withdraw", "Withdrawn"), (r"suspend", "Suspended"),
        (r"migrate", "Migrated"), (r"placed on watch", "Watch / Review"),
    ]:
        if re.search(pat, b, re.I):
            return action
    return "Rating Update"


def _extract_report_date(text: str, title: str = "") -> str:
    blob = f"{title} {text[:8000]}"
    patterns = [
        r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b",
        r"\b(\d{1,2}[-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[-/]\d{4})\b",
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
        r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
    ]
    for pat in patterns:
        m = re.search(pat, blob, re.I)
        if m:
            return m.group(1)
    return ""


def _extract_rating_outlook(text: str) -> Tuple[str, str]:
    b = re.sub(r"\s+", " ", str(text or ""))
    rating = _rating_symbol_from_text(b)
    outlook = ""
    if rating:
        # Look close to the rating for the outlook, e.g. AAA/Stable.
        idx = b.upper().find(rating.upper())
        local = b[max(0, idx - 80): idx + 140] if idx >= 0 else b[:300]
        m = OUTLOOK_RE.search(local)
        if m:
            outlook = m.group(1).title()
    if not outlook:
        m = OUTLOOK_RE.search(b)
        outlook = m.group(1).title() if m else ""
    return rating, outlook


def _clean_report_text(raw: str) -> str:
    try:
        from bs4 import BeautifulSoup
        raw = BeautifulSoup(raw, "lxml").get_text(" ", strip=True)
    except Exception:
        raw = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", raw or "").strip()


def _fetch_rating_page(url: str) -> Tuple[str, str]:
    if not url.startswith("http"):
        return "", ""
    targets = [url]
    if "icra.in/Rationale/ShowRationaleReport" in url:
        match = re.search(r"[?&]Id=(\d+)", url, re.I)
        if match:
            targets.insert(0, f"https://www.icra.in/Rating/GetRationalReportFilePdf?Id={match.group(1)}")
    for target in targets:
        try:
            r = requests.get(target, headers=_RATING_SEARCH_UA, timeout=(2.5, 6))
            if not r.ok:
                continue
            ctype = r.headers.get("Content-Type", "").lower()
            data = r.content
            if data[:4] == b"%PDF" or "pdf" in ctype or target.lower().endswith(".pdf"):
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(data))
                    text = " ".join((p.extract_text() or "") for p in reader.pages[:10])
                except Exception:
                    text = ""
            else:
                text = _clean_report_text(r.text)
            if text:
                return _clean_report_text(text), ctype
        except Exception:
            continue
    return "", ""


def _extract_rationale_drivers(text: str) -> str:
    b = _clean_report_text(text)
    patterns = [
        r"key rating drivers?[:\- ]+(.*?)(?:rating sensitivities|key rating sensitivities|outlook|about the company|analytical approach)",
        r"rating drivers?[:\- ]+(.*?)(?:rating sensitivities|outlook|about the company)",
        r"strengths?[:\- ]+(.*?)(?:weaknesses|rating sensitivities|outlook)",
        r"key rating factors?[:\- ]+(.*?)(?:rating sensitivities|outlook)",
        r"the rating factors?[:\- ]+(.*?)(?:rating sensitivities|outlook)",
    ]
    for pat in patterns:
        m = re.search(pat, b, re.I)
        if m and len(m.group(1).strip()) >= 100:
            return m.group(1).strip()[:1400] + ("…" if len(m.group(1).strip()) > 1400 else "")
    return b[:1200] + ("…" if len(b) > 1200 else "") if b else ""


def _search_engine(query: str, agency: str, domains: List[str], engine: str = "google") -> List[Dict[str, str]]:
    """Search one agency at a time and return only official-domain results.

    Google/Bing/DDG HTML layouts change frequently, so this parser supports all
    three and unwraps common redirect URLs. The important rule is that each
    agency/domain is searched separately; multiple `site:` operators are never
    ANDed together.
    """
    try:
        if engine == "google":
            url = "https://www.google.com/search?q=" + quote_plus(query) + "&num=10&hl=en"
        elif engine == "bing":
            url = "https://www.bing.com/search?q=" + quote_plus(query) + "&count=10&setlang=en-IN"
        else:
            url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        r = requests.get(url, headers=_RATING_SEARCH_UA, timeout=(3, 7), allow_redirects=True)
        if not r.ok:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        out=[]
        for a in soup.find_all("a", href=True):
            href=a.get("href","").strip()
            title=re.sub(r"\s+"," ",a.get_text(" ",strip=True))
            if not href or not title:
                continue
            # Google/Bing sometimes wrap result URLs in a query parameter.
            parsed=urlparse(href)
            host=parsed.netloc.lower()
            if host in {"www.google.com","google.com","www.bing.com","bing.com","html.duckduckgo.com","duckduckgo.com"}:
                qv=(parse_qs(parsed.query).get("q") or
                    parse_qs(parsed.query).get("url") or
                    parse_qs(parsed.query).get("uddg") or
                    parse_qs(parsed.query).get("r"))
                if qv:
                    href=qv[0]
            if not href.startswith("http"):
                continue
            low=href.lower()
            if not any(d.lower() in low for d in domains):
                continue
            # Avoid agency home/search pages unless the title looks report-like.
            if len(href.rstrip('/').split('/')) <= 4 and not re.search(r"rating|rationale|report|factsheet|rating details", title, re.I):
                continue
            if not any(x["URL"]==href for x in out):
                out.append({"Agency":agency,"Title":title[:220],"URL":href})
        return out[:10]
    except Exception:
        return []


def _search_one_agency(company: str, agency: str, symbol: str = "") -> List[Dict[str, str]]:
    """Bounded web discovery fallback. Direct official archives run separately."""
    domains = AGENCY_SEARCH_DOMAINS.get(agency, [])
    if not domains:
        return []
    clean = re.sub(r"\b(limited|ltd\.?|private|pvt\.?|company|corporation|corp\.?)\b", "", company, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip()
    names = [company]
    if clean and clean.lower() != company.lower():
        names.append(clean)
    found = []
    # Two focused queries × at most two engines. Search engines are a fallback,
    # not the primary source; this avoids dozens of requests per agency/company.
    for domain in domains:
        for name in names[:2]:
            queries = [
                f'"{name}" "rating rationale" site:{domain}',
                f'"{name}" "rating reaffirmed" site:{domain}',
            ]
            for q in queries:
                for engine in ("bing", "ddg"):
                    found.extend(_search_engine(q, agency, [domain], engine))
                if len(found) >= 4:
                    break
            if len(found) >= 4:
                break
        if len(found) >= 4:
            break
    dedup = {x["URL"]: x for x in found}
    return list(dedup.values())[:4]


def _search_icra_rationales(company: str, symbol: str = "") -> List[Dict[str, str]]:
    """Query ICRA's own issuer-filtered rating-rationale archive directly."""
    url = "https://www.icra.in/Rating/AllRatingRationales"
    try:
        r = requests.get(url, params={"Keyword": company}, headers=_RATING_SEARCH_UA, timeout=(3, 7))
        if not r.ok or len(r.text) < 500:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        def norm(v: str) -> str:
            v = re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()
            return re.sub(r"\s+", " ", v)
        full = norm(company)
        clean = norm(re.sub(r"\b(limited|ltd|private|pvt|company|corporation|corp)\b", "", company, flags=re.I))
        needles = [x for x in (full, clean) if len(x) >= 5]
        out = []
        for tr in soup.find_all("tr"):
            row_text = re.sub(r"\s+", " ", tr.get_text(" ", strip=True))
            row_norm = norm(row_text)
            # Require a full legal-name or normalized name match. Ticker-only
            # substring matches are intentionally not accepted for rating data.
            if not any(n and n in row_norm for n in needles):
                continue
            for a in tr.find_all("a", href=True):
                href = urljoin("https://www.icra.in", a["href"].strip())
                if "/Rationale/ShowRationaleReport" not in href:
                    continue
                title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)) or row_text
                id_match = re.search(r"[?&]Id=(\d+)", href, re.I)
                pdf_url = f"https://www.icra.in/Rating/GetRationalReportFilePdf?Id={id_match.group(1)}" if id_match else ""
                date_match = re.search(r"\b\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\b", row_text)
                out.append({"Agency": "ICRA", "Title": title[:220], "URL": href,
                            "_PDF_URL": pdf_url, "_context": row_text,
                            "Date": date_match.group(0) if date_match else ""})
                break
        dedup = {x["URL"]: x for x in out}
        return list(dedup.values())[:8]
    except Exception:
        return []


def _fetch_issuer_rating_summary(ticker: str) -> pd.DataFrame:
    """Parse issuer-maintained rating tables without inventing dates/outlooks."""
    symbol = str(ticker or "").split(".")[0].upper()
    config = ISSUER_RATING_SUMMARY_PAGES.get(symbol)
    columns = ["Date", "Agency", "Rating", "Outlook", "Action", "Details", "Source", "Instrument", "Source Type"]
    if not config:
        return pd.DataFrame(columns=columns)
    try:
        r = requests.get(config["url"], headers=_RATING_SEARCH_UA, timeout=(3, 7))
        r.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        rows = []
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = [re.sub(r"\s+", " ", x.get_text(" ", strip=True)).strip() for x in tr.find_all(["th", "td"])]
                if len(cells) < 3:
                    continue
                # HDFC Bank format: Instrument | Rating | Rating Agency | Comments
                agency_idx = next((i for i, x in enumerate(cells) if re.search(r"^(CRISIL|ICRA|CARE(?: Ratings)?|India Ratings|Ind-Ra)$", x, re.I)), None)
                if agency_idx is not None:
                    rating_candidates = [x for i, x in enumerate(cells) if i != agency_idx and _rating_symbol_from_text(x)]
                    inst_candidates = [x for i, x in enumerate(cells) if i != agency_idx and not _rating_symbol_from_text(x)]
                    if not rating_candidates:
                        continue
                    agency_raw = cells[agency_idx]
                    rating_raw = rating_candidates[0]
                    instrument = inst_candidates[0] if inst_candidates else "Instrument / Facility"
                    agency = _agency_from_text(agency_raw, agency_raw)
                    rating, outlook = _extract_rating_outlook(rating_raw)
                    rows.append({"Date": "Not stated on issuer page", "Agency": agency, "Rating": rating or rating_raw,
                                 "Outlook": outlook or "Not stated", "Action": "Issuer-published rating summary; action date not stated",
                                 "Details": "Rating reproduced from the issuer's own credit-rating page. The issuer page does not state the rating action date.",
                                 "Source": config["url"], "Instrument": instrument, "Source Type": "Issuer summary (date not stated)"})
                    continue
                # ICICI Bank format: Instrument type | CARE | ICRA | CRISIL
                header = [x.lower() for x in cells]
                if any(x in {"care", "icra", "crisil"} for x in header[1:]):
                    continue
        # Generic ICICI issuer table parser using pandas' HTML table reader.
        try:
            tables = pd.read_html(io.StringIO(r.text))
        except Exception:
            tables = []
        if symbol == "ICICIBANK":
            for table in tables:
                table.columns = [str(c).strip() for c in table.columns]
                cols_l = {str(c).lower(): c for c in table.columns}
                inst_col = next((v for k, v in cols_l.items() if "instrument" in k or "facility" in k), None)
                agency_cols = {a: next((v for k, v in cols_l.items() if a.lower() in k), None) for a in ("CARE", "ICRA", "CRISIL")}
                if inst_col is None or not any(agency_cols.values()):
                    continue
                for _, rr in table.iterrows():
                    instrument = str(rr.get(inst_col, "")).strip()
                    if not instrument or instrument.lower() == "nan":
                        continue
                    for agency, c in agency_cols.items():
                        if c is None:
                            continue
                        raw = str(rr.get(c, "")).strip()
                        if not raw or raw.lower() == "nan":
                            continue
                        rating, outlook = _extract_rating_outlook(raw)
                        if not rating:
                            continue
                        rows.append({"Date": "Not stated on issuer page", "Agency": "CARE Ratings" if agency == "CARE" else agency,
                                     "Rating": rating, "Outlook": outlook or "Not stated",
                                     "Action": "Issuer-published rating summary; action date not stated",
                                     "Details": "Rating reproduced from the issuer's own credit-rating page. The issuer page does not state the rating action date.",
                                     "Source": config["url"], "Instrument": instrument, "Source Type": "Issuer summary (date not stated)"})
        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(rows, columns=columns).drop_duplicates(subset=["Agency", "Instrument", "Rating", "Source"])
    except Exception:
        return pd.DataFrame(columns=columns)

def _search_crisil_rating_actions(company: str, symbol: str = "") -> List[Dict[str, str]]:
    """Direct CRISIL fallback that parses rating-action TABLE ROWS, not anchor text.

    CRISIL's monthly rating-action pages normally put the issuer name in a table
    cell and the rationale link in a different cell. The older implementation
    looked only at anchor text, so a valid issuer could be present while zero
    links were returned. This row-based parser fixes that failure mode.
    """
    months=["january","february","march","april","may","june","july","august","september","october","november","december"]
    now=datetime.now()
    targets=[]
    for back in range(0,6):
        y=now.year; m=now.month-back
        while m<=0:
            y-=1; m+=12
        targets.append((y,months[m-1]))

    def norm(v: str) -> str:
        v=re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()
        return re.sub(r"\s+", " ", v)

    target=norm(company)
    symbol_low=norm(symbol)
    clean=norm(re.sub(r"\b(limited|ltd|private|pvt|company|corporation|corp)\b", "", company, flags=re.I))
    needles=[x for x in (target, clean, symbol_low) if x and len(x)>=3]
    found=[]

    for y,mon in targets:
        url=f"https://www.crisilratings.com/en/home/our-business/ratings/newsletters/{y}/{mon}/rating-actions.html"
        try:
            r=requests.get(url,headers=_RATING_SEARCH_UA,timeout=(2.5, 6))
            if not r.ok:
                continue
            from bs4 import BeautifulSoup
            soup=BeautifulSoup(r.text,"lxml")
            for tr in soup.find_all("tr"):
                rowtxt=re.sub(r"\s+"," ",tr.get_text(" ",strip=True))
                nrow=norm(rowtxt)
                if not rowtxt or not any(n in nrow for n in needles):
                    continue

                # Prefer the direct RatingDocs/rationale link in this issuer row.
                links=[]
                for a in tr.find_all("a",href=True):
                    href=a.get("href","").strip()
                    if href.startswith("/"):
                        href="https://www.crisilratings.com"+href
                    if not href.startswith("http"):
                        continue
                    if "crisilratings.com" not in href.lower():
                        continue
                    txt=re.sub(r"\s+"," ",a.get_text(" ",strip=True))
                    links.append((href,txt))

                chosen=""
                for href,txt in links:
                    low=href.lower()
                    if "ratingdocs" in low or "rating" in low and ("rationale" in low or "rr_" in low):
                        chosen=href; break
                if not chosen and links:
                    # Company-name anchor is often the rationale page itself.
                    chosen=links[0][0]
                if not chosen:
                    continue

                # Keep the issuer row as context so rating/outlook/action can be
                # extracted even if the detailed page is temporarily unavailable.
                found.append({
                    "Agency":"CRISIL",
                    "Title":rowtxt[:220],
                    "URL":chosen,
                    "_context":rowtxt,
                    "Date":f"{mon.title()} {y}",
                })
        except Exception:
            continue
        if found:
            break

    dedup={x["URL"]:x for x in found}
    return list(dedup.values())[:10]

def _report_row_from_url(seed: Dict[str, str], company: str) -> Optional[Dict[str, str]]:
    read_url = seed.get("_PDF_URL") or seed.get("URL", "")
    text, _ = _fetch_rating_page(read_url)
    title = seed.get("Title", "")
    context = seed.get("_context", "")
    blob = f"{title} {context} {text}"
    def norm(v: str) -> str:
        v = re.sub(r"[^a-z0-9]+", " ", str(v or "").lower()).strip()
        return re.sub(r"\s+", " ", v)
    clean_company = norm(re.sub(r"\b(limited|ltd|private|pvt|company|corporation|corp)\b", "", company, flags=re.I))
    company_full = norm(company)
    identity_ok = (company_full and company_full in norm(blob)) or (clean_company and len(clean_company) >= 5 and clean_company in norm(blob))
    if not identity_ok:
        return None
    rating, outlook = _extract_rating_outlook(blob)
    if not rating:
        return None
    agency = _agency_from_text(blob, seed.get("Agency", ""))
    if not agency:
        return None
    return {
        "Agency": agency,
        "Title": title[:220] or f"{company} — {agency} rating report",
        "URL": seed.get("URL", ""),
        "Date": seed.get("Date") or _extract_report_date(blob, title),
        "Rating": rating,
        "Outlook": outlook or "Not stated",
        "Action": _extract_action(blob),
        "Instrument": _extract_instrument(blob),
        "Rationale": _extract_rationale_drivers(text),
        "Source Type": "Official CRA report",
    }


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_agency_rating_reports(ticker: str) -> pd.DataFrame:
    """Fetch company-specific CRA reports, prioritising direct official archives."""
    company = _company_name_for_rating(ticker)
    symbol = ticker.split(".")[0].upper()
    seeds = list(KNOWN_AGENCY_REPORTS.get(symbol, []))
    # Direct issuer-filtered ICRA archive and CRISIL rating-action archive.
    try:
        seeds.extend(_search_icra_rationales(company, symbol))
    except Exception:
        pass
    try:
        seeds.extend(_search_crisil_rating_actions(company, symbol))
    except Exception:
        pass

    # Search other agency domains with a strict request cap and a hard discovery budget.
    pool = ThreadPoolExecutor(max_workers=8)
    futures = {pool.submit(_search_one_agency, company, agency, symbol): agency
               for agency in AGENCY_SEARCH_DOMAINS if agency not in {"ICRA", "CRISIL"}}
    try:
        for future in as_completed(futures, timeout=12):
            try:
                seeds.extend(future.result())
            except Exception:
                pass
    except Exception:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    unique = {x.get("URL"): x for x in seeds if x.get("URL")}
    by_agency: Dict[str, List[Dict[str, str]]] = {}
    for row in unique.values():
        by_agency.setdefault(row.get("Agency", ""), []).append(row)
    selected = []
    for agency, rows in by_agency.items():
        rows = sorted(rows, key=lambda x: (bool(x.get("_PDF_URL")), "rationale" in x.get("Title", "").lower()), reverse=True)
        selected.extend(rows[:2])

    parsed: List[Dict[str, str]] = []
    pool = ThreadPoolExecutor(max_workers=8)
    futures = [pool.submit(_report_row_from_url, row, company) for row in selected]
    try:
        for future in as_completed(futures, timeout=12):
            try:
                row = future.result()
                if row:
                    parsed.append(row)
            except Exception:
                pass
    except Exception:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if not parsed:
        return pd.DataFrame(columns=["Agency", "Title", "URL", "Date", "Rating", "Outlook", "Action", "Instrument", "Rationale"])
    df = pd.DataFrame(parsed).drop_duplicates(subset=["Agency", "URL"])
    df["_date"] = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)
    return df.sort_values(["_date", "Agency"], ascending=[False, True], na_position="last").drop(columns=["_date"]).reset_index(drop=True)


def _agency_ratings_as_credit_rows(ticker: str) -> pd.DataFrame:
    """Convert agency report rows into the same schema as NSE credit rows."""
    reports = fetch_agency_rating_reports(ticker)
    if reports.empty:
        return pd.DataFrame(columns=["Date", "Agency", "Rating", "Outlook", "Action", "Details", "Source", "Instrument"])
    rows = []
    for _, r in reports.iterrows():
        if not str(r.get("Rating", "")).strip():
            continue
        rows.append({
            "Date": r.get("Date", ""),
            "Agency": r.get("Agency", ""),
            "Rating": r.get("Rating", ""),
            "Outlook": r.get("Outlook", "") or "Not stated",
            "Action": r.get("Action", "Rating Update"),
            "Details": r.get("Rationale", ""),
            "Source": r.get("URL", ""),
            "Instrument": r.get("Instrument", ""),
            "Source Type": "Official CRA report",
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_credit_announcements(ticker: str, days: int = 1825) -> Tuple[pd.DataFrame, str]:
    """Combine NSE credit disclosures with official CRA reports.

    NSE is attempted first, but agency ratings are authoritative for the actual
    rating value/rationale and are used when NSE has no usable disclosure.
    """
    symbol = ticker.split(".")[0].upper()
    end = datetime.now().date()
    start = end - timedelta(days=days)
    nse_records = []
    try:
        data = _nse_json("/corporate-announcements", {
            "index": "equities", "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y"),
        })
        for r in _rows(data):
            subject = str(_first(r, "subject", "type") or "")
            details = str(_first(r, "details", "description", "remarks") or "")
            blob = f"{subject} {details}"
            if not re.search(r"credit rating|rating reaffirm|rating assigned|rating upgraded|rating downgraded|rating rationale|rating agency", blob, re.I):
                continue
            rating = _rating_symbol_from_text(blob)
            om = OUTLOOK_RE.search(blob)
            am = AGENCY_RE.search(blob)
            nse_records.append({
                "Date": _first(r, "broadcastDateTime", "broadcastDate", "date"),
                "Agency": am.group(1) if am else "NSE disclosure",
                "Rating": rating,
                "Outlook": om.group(1).title() if om else "",
                "Action": _extract_action(blob),
                "Details": details[:1400],
                "Source": _link(_first(r, "attachment", "attachmentLink", "fileLink", "link", "source")),
                "Instrument": _extract_instrument(blob),
                "Source Type": "NSE disclosure",
            })
    except Exception:
        pass

    agency_df = _agency_ratings_as_credit_rows(ticker)
    nse_df = pd.DataFrame(nse_records)
    issuer_df = _fetch_issuer_rating_summary(ticker)
    frames = [x for x in (agency_df, nse_df, issuer_df) if isinstance(x, pd.DataFrame) and not x.empty]
    if frames:
        df = pd.concat(frames, ignore_index=True, sort=False)
        for c in ["Date", "Agency", "Rating", "Outlook", "Action", "Details", "Source", "Instrument", "Source Type"]:
            if c not in df.columns:
                df[c] = ""
        df["_date"] = pd.to_datetime(df["Date"], errors="coerce", dayfirst=True)
        df = df.sort_values("_date", ascending=False, na_position="last").drop(columns=["_date"]).reset_index(drop=True)
        return df, "NSE disclosures + official CRA reports + issuer-published rating summaries (undated summaries labelled)"
    return pd.DataFrame(columns=["Date", "Agency", "Rating", "Outlook", "Action", "Details", "Source", "Instrument"]), "No verified public credit rating was found across NSE and the official Indian rating-agency sources."


@st.cache_data(ttl=21600, show_spinner=False)
def download_public_rating_report(url: str) -> Tuple[bytes, str, str]:
    """Download a public agency rationale/report for Streamlit's download button."""
    if not url or not url.startswith('http'):
        return b'', '', ''
    try:
        r=requests.get(url,headers=_RATING_SEARCH_UA,timeout=(2.5, 7))
        r.raise_for_status()
        ctype=r.headers.get('Content-Type','').lower()
        data=r.content
        if data[:4]==b'%PDF' or 'pdf' in ctype or url.lower().endswith('.pdf'):
            ext='pdf'; mime='application/pdf'
        else:
            ext='html'; mime='text/html'
        return data, ext, mime
    except Exception:
        return b'', '', ''

def source_links(ticker: str) -> Dict[str, str]:
    symbol = ticker.split(".")[0].upper()
    return {
        "NSE Governance": f"{NSE_GOV_URL}?symbol={symbol}&tabIndex=equity",
        "NSE Integrated Governance": f"{NSE_INTEGRATED_URL}&symbol={symbol}",
        "NSE BRSR": f"{NSE_BRSR_URL}?symbol={symbol}",
        "NSE Announcements": f"{NSE_ANN_URL}?symbol={symbol}",
        "NSE Credit Rating XBRL": f"https://www.nseindia.com/companies-listing/corporate-filings-announcements-xbrl?symbol={symbol}&tabIndex=equity",
    }
