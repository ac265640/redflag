"""Evidence-first classification of NSE corporate announcements.

The module distinguishes routine statutory disclosures from actual enforcement
or adverse legal events. Keyword classifications are analyst-review prompts,
not findings of misconduct and not an independent corporate risk score.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

from data.public_sources import _nse_json, _rows, _normalize_records


# Keep categories mutually interpretable. In particular, the presence of the
# word "SEBI" by itself is never treated as evidence of enforcement.
CATEGORIES: Dict[str, List[str]] = {
    "Regulatory actions & enforcement": [
        r"show[- ]cause notice", r"adjudication order", r"penalty imposed",
        r"fine imposed", r"penalt(?:y|ies)", r"\bfine(?:s)?\b", r"enforcement action", r"regulatory order",
        r"interim order", r"final order", r"\bsebi\b.{0,40}\b(?:order|direction)\b", r"order.{0,20}\bsebi\b", r"prosecution", r"settlement order",
        r"inspection findings", r"investigation initiated", r"non[- ]compliance.*penalty",
        r"fraud", r"money laundering", r"wilful defaulter",
    ],
    "Legal & litigation": [
        r"legal proceeding", r"litigation", r"court", r"tribunal", r"nclt", r"nclat",
        r"high court", r"supreme court", r"arbitration", r"claim", r"dispute",
        r"legal notice", r"writ petition", r"admission of petition",
    ],
    "Management & key personnel": [
        r"\bceo\b", r"chief executive officer", r"managing director", r"whole[- ]time director",
        r"key managerial personnel", r"senior management personnel", r"senior management person",
        r"cessation.{0,90}(?:director|ceo|cfo|chief executive|senior management|key managerial personnel|company secretary)",
        r"(?:director|ceo|cfo|chief executive|senior management|key managerial personnel|company secretary).{0,60}cessation",
        r"appointment.{0,60}(?:director|ceo|cfo|chief executive|key managerial personnel|company secretary)",
        r"resignation.{0,60}(?:director|ceo|cfo|chief executive|key managerial personnel|company secretary)",
        r"change in (?:senior )?management", r"change in key managerial personnel",
    ],
    "Audit & accounting": [
        r"auditor", r"resignation of auditor", r"qualified opinion", r"qualification",
        r"emphasis of matter", r"forensic audit", r"restatement", r"accounting irregular",
        r"accounting policy", r"material weakness", r"material uncertainty.{0,40}going concern",
        r"substantial doubt.{0,40}going concern", r"going concern.{0,50}(?:qualification|uncertainty|material doubt)",
    ],
    "Promoter & shareholding": [
        r"pledge", r"encumbrance", r"promoter shareholding", r"promoter group",
        r"shareholding pattern", r"acquisition of shares", r"sale of shares",
        r"change in shareholding", r"disclosure under regulation 29",
        r"disclosure under regulation 31",
    ],
    "Related party & corporate transactions": [
        r"related party", r"material related party", r"acquisition", r"acquire",
        r"merger", r"amalgamation", r"demerger", r"slump sale", r"joint venture",
        r"scheme of arrangement", r"business transfer",
    ],
    "Business disruption & financial stress": [
        r"default", r"insolvency", r"bankruptcy", r"shutdown", r"plant closure",
        r"fire incident", r"cyber attack", r"cyber security incident", r"strike",
        r"force majeure", r"business interruption", r"going into liquidation",
    ],
    "Regulatory filings & compliance": [
        r"disclosure under sebi", r"sebi \(listing obligations", r"listing obligations",
        r"trading window", r"compliance certificate", r"secretarial compliance",
        r"certificate under sebi", r"depositories and participants regulations",
        r"corporate governance compliance", r"statement of deviation",
        r"regulation 30", r"regulation 31", r"regulation 74",
        r"insider trading code", r"closure of trading window",
    ],
    "Material corporate events": [
        r"fund raising", r"fund-raising", r"qualified institutional placement", r"qip",
        r"rights issue", r"preferential issue", r"buyback", r"delisting",
        r"capital reduction", r"board approved", r"material event", r"project commissioning",
        r"capacity expansion", r"business acquisition",
    ],
}

HIGH_PATTERNS = [
    r"show[- ]cause notice", r"adjudication order", r"penalty imposed", r"penalt(?:y|ies)", r"fine imposed", r"\bfine(?:s)?\b",
    r"enforcement action", r"regulatory order", r"interim order", r"final order", r"\bsebi\b.{0,40}\b(?:order|direction)\b", r"order.{0,20}\bsebi\b",
    r"prosecution", r"fraud", r"money laundering", r"default", r"insolvency",
    r"bankruptcy", r"qualified opinion", r"material uncertainty.{0,40}going concern",
    r"substantial doubt.{0,40}going concern", r"material weakness",
    r"forensic audit", r"restatement", r"wilful defaulter",
]
ROUTINE_PATTERNS = [
    r"trading window", r"closure of trading window", r"compliance certificate",
    r"secretarial compliance", r"certificate under sebi",
    r"depositories and participants regulations", r"corporate governance compliance",
]
REVIEW_PATTERNS = [
    r"litigation", r"legal proceeding", r"court", r"tribunal", r"arbitration",
    r"dispute", r"auditor resignation", r"resignation of auditor", r"resignation.{0,35}auditor", r"auditor.{0,35}resignation", r"pledge",
    r"encumbrance", r"related party", r"acquisition", r"merger", r"demerger",
    r"cyber attack", r"business interruption", r"plant closure", r"fire incident",
    r"\bceo\b", r"chief executive officer", r"managing director", r"key managerial personnel",
    r"senior management personnel", r"cessation.{0,60}(?:director|ceo|cfo|management)",
    r"appointment.{0,60}(?:director|ceo|cfo)", r"resignation.{0,60}(?:director|ceo|cfo)",
]


def _blob(row: pd.Series) -> str:
    return f"{row.get('Type', '')} {row.get('Details', '')}".strip()


def _matches(patterns: List[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _classify(blob: str) -> Tuple[str, str]:
    """Return (category, attention) using specific signals before broad terms."""
    text = re.sub(r"\s+", " ", str(blob or "")).strip()

    # Attention is intentionally independent of category. A routine filing can
    # mention a regulator without being a regulatory action.
    if _matches(HIGH_PATTERNS, text):
        attention = "Urgent review"
    elif _matches(REVIEW_PATTERNS, text):
        attention = "Analyst review"
    elif _matches(ROUTINE_PATTERNS, text):
        attention = "Routine"
    else:
        attention = "Monitor"

    # Specific/adverse event types take precedence over generic compliance terms.
    precedence = [
        "Regulatory actions & enforcement",
        "Legal & litigation",
        "Management & key personnel",
        "Audit & accounting",
        "Business disruption & financial stress",
        "Promoter & shareholding",
        "Related party & corporate transactions",
        "Material corporate events",
        "Regulatory filings & compliance",
    ]
    for category in precedence:
        if _matches(CATEGORIES[category], text):
            return category, attention

    return "Other corporate disclosure", "Routine"


def _short_details(text: str, max_words: int = 100) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return "N/A"
    words = text.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_corporate_regulatory_events(ticker: str, years: int = 5) -> Tuple[pd.DataFrame, str]:
    """Retrieve NSE company announcements and classify them for analyst review."""
    symbol = str(ticker).split(".")[0].upper().strip()
    end = datetime.now().date()
    start = end - timedelta(days=365 * int(years) + 2)
    try:
        data = _nse_json("/corporate-announcements", {
            "index": "equities", "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y"),
        })
        rows = _rows(data)
        df = _normalize_records(rows)
        if df.empty:
            return pd.DataFrame(columns=["Date", "Type", "Category", "Analyst attention", "Details", "Source"]), "NSE Corporate Announcements — no records returned"

        # Keep announcements that map to a defined research category. Generic
        # regulator names alone are deliberately excluded from enforcement.
        all_patterns = [pattern for patterns in CATEGORIES.values() for pattern in patterns]
        combined = "|".join(f"(?:{pattern})" for pattern in all_patterns)
        blob = df.get("Type", pd.Series("", index=df.index)).fillna("").astype(str) + " " + df.get("Details", pd.Series("", index=df.index)).fillna("").astype(str)
        df = df.loc[blob.str.contains(combined, regex=True, case=False, na=False)].copy()
        if df.empty:
            return pd.DataFrame(columns=["Date", "Type", "Category", "Analyst attention", "Details", "Source"]), "NSE Corporate Announcements — no research-category events found"

        classified = df.apply(lambda row: _classify(_blob(row)), axis=1)
        df[["Category", "Analyst attention"]] = pd.DataFrame(classified.tolist(), index=df.index)

        date_values = pd.to_datetime(df.get("Date", pd.Series(index=df.index, dtype=object)), errors="coerce", dayfirst=True)
        df["_date_sort"] = date_values
        df["Date"] = date_values.dt.strftime("%d-%b-%Y").fillna("Date not supplied")
        df["Type"] = df.get("Type", pd.Series("Corporate disclosure", index=df.index)).fillna("Corporate disclosure").astype(str)
        df["Details"] = df.get("Details", pd.Series("", index=df.index)).map(_short_details)

        attachment = df.get("Attachment", pd.Series("", index=df.index)).fillna("").astype(str)
        source = df.get("Source", pd.Series("", index=df.index)).fillna("").astype(str)
        df["Source"] = attachment.where(attachment.str.startswith("http", na=False), source)
        df["Source"] = df["Source"].where(df["Source"].str.startswith("http", na=False), "")

        # Drop duplicate exchange records without collapsing distinct filing dates.
        df = df.drop_duplicates(subset=["Date", "Type", "Details", "Source"])
        df = df.sort_values("_date_sort", ascending=False, na_position="last")
        df = df.drop(columns=["_date_sort"], errors="ignore").reset_index(drop=True)
        return df[["Date", "Type", "Category", "Analyst attention", "Details", "Source"]], "NSE Corporate Announcements"
    except Exception as exc:
        empty = pd.DataFrame(columns=["Date", "Type", "Category", "Analyst attention", "Details", "Source"])
        return empty, f"NSE unavailable: {type(exc).__name__}"


def event_summary(df: pd.DataFrame) -> Dict[str, int]:
    """Counts used by Corporate Intelligence and the cross-module Summary page."""
    if df is None or df.empty:
        return {"events": 0, "high": 0, "regulatory": 0, "legal": 0, "audit": 0,
                "routine": 0, "promoter": 0, "related": 0, "business": 0, "management": 0}

    category = df.get("Category", pd.Series("", index=df.index)).fillna("").astype(str)
    attention = df.get("Analyst attention", pd.Series("", index=df.index)).fillna("").astype(str)
    return {
        "events": int(len(df)),
        "high": int((attention == "Urgent review").sum()),
        "regulatory": int((category == "Regulatory actions & enforcement").sum()),
        "legal": int((category == "Legal & litigation").sum()),
        "audit": int((category == "Audit & accounting").sum()),
        "management": int((category == "Management & key personnel").sum()),
        "routine": int((attention == "Routine").sum()),
        "promoter": int((category == "Promoter & shareholding").sum()),
        "related": int((category == "Related party & corporate transactions").sum()),
        "business": int((category == "Business disruption & financial stress").sum()),
    }
