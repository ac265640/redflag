"""Alert delivery (SKELETON). Wire to email / Slack / Telegram / WhatsApp Business API."""
from __future__ import annotations

from typing import Dict, Iterable, List


def format_alert(ticker: str, alert: Dict[str, str]) -> str:
    """One-line human-readable alert."""
    return f"[{alert['severity']}] {ticker}: {alert['title']} - {alert['message']}"


def dispatch(ticker: str, alerts: Iterable[Dict[str, str]], channels: List[str] | None = None) -> List[str]:
    """Return formatted messages; TODO: actually send via ``channels`` (smtp, slack webhook, ...). Dedupe by (ticker, title)."""
    return [format_alert(ticker, a) for a in alerts]
