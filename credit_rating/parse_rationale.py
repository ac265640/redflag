"""Rationale parser: pulls strengths / weaknesses out of agency rationale text."""
from __future__ import annotations

import re
from typing import Dict, List


def parse_rationale(text: str) -> Dict[str, List[str]]:
    """Split a 'Strengths: ... Weaknesses: ...' blurb into bullet lists.

    TODO(real data): feed PDF text through an LLM or rule-based sectioner ('Key rating drivers', 'Rating sensitivities',
    'Detailed description of key rating drivers') and extract downgrade triggers.
    """
    m = re.search(r"Strengths:(.*?)Weaknesses:(.*)", text, flags=re.S | re.I)
    if not m:
        return {"strengths": [], "weaknesses": [text.strip()]}
    split = lambda s: [x.strip(" .") for x in re.split(r"[;]", s) if x.strip(" .")]
    return {"strengths": split(m.group(1)), "weaknesses": split(m.group(2))}
