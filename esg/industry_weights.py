"""Industry-specific pillar weights (E, S, G; sum = 1). Materiality differs by sector."""
from __future__ import annotations

from typing import Dict, Tuple

_W: Dict[str, Tuple[float, float, float]] = {
    "Metals & Mining": (0.50, 0.30, 0.20), "Power": (0.55, 0.25, 0.20), "Chemicals": (0.50, 0.30, 0.20),
    "Infrastructure": (0.35, 0.30, 0.35), "Real Estate": (0.30, 0.30, 0.40), "Auto Components": (0.40, 0.30, 0.30),
    "Textiles": (0.35, 0.40, 0.25), "Pharmaceuticals": (0.30, 0.35, 0.35), "Healthcare": (0.20, 0.45, 0.35),
    "FMCG": (0.30, 0.35, 0.35), "IT Services": (0.15, 0.45, 0.40),
}
DEFAULT = (0.34, 0.33, 0.33)


def get_weights(sector: str) -> Dict[str, float]:
    """Return {'E','S','G'} weights for a sector (default: roughly equal)."""
    e, s, g = _W.get(sector, DEFAULT)
    return {"E": e, "S": s, "G": g}
