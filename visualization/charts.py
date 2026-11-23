"""Plotly charts styled to the Institutional Premium palette."""
from __future__ import annotations

from typing import Dict, List

import pandas as pd
import plotly.graph_objects as go

from core.constants import COLORS, GRADE_COLORS

FONT = dict(family="Inter, Segoe UI, sans-serif", color="#CBD9E2", size=13)
PALETTE = [COLORS["blue"], COLORS["amber"], COLORS["green"], COLORS["red"], "#AF52DE", "#5AC8FA"]


def _base(fig: go.Figure, height: int = 340) -> go.Figure:
    fig.update_layout(font=FONT, height=height, margin=dict(l=8, r=8, t=36, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      legend=dict(orientation="h", y=-0.15), hoverlabel=dict(font=FONT))
    fig.update_xaxes(gridcolor="rgba(137,170,195,.15)", zeroline=False, linecolor="rgba(137,170,195,.30)")
    fig.update_yaxes(gridcolor="rgba(137,170,195,.15)", zeroline=False)
    return fig


def gauge(value: float, title: str, higher_is_better: bool, height: int = 230) -> go.Figure:
    """Semi-circular gauge; colour bands flip depending on direction."""
    good, mid, bad = COLORS["green"], COLORS["amber"], COLORS["red"]
    steps = [(0, 40, bad), (40, 66, mid), (66, 100, good)] if higher_is_better else [(0, 34, good), (34, 60, mid), (60, 100, bad)]
    cur = next(c for lo, hi, c in steps if lo <= value <= hi) if 0 <= value <= 100 else mid
    fig = go.Figure(go.Indicator(mode="gauge+number", value=value, number=dict(font=dict(size=40, family=FONT["family"]), valueformat=".0f"),
                                 title=dict(text=title, font=dict(size=15, color="#CBD9E2")),
                                 gauge=dict(axis=dict(range=[0, 100], tickwidth=0, showticklabels=False), bar=dict(color=cur, thickness=0.28),
                                            bgcolor="rgba(148,163,184,.10)", borderwidth=0)))
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=40, b=0), paper_bgcolor="rgba(0,0,0,0)", font=FONT)
    return fig


def trend_lines(df: pd.DataFrame, cols: List[str], title: str = "", height: int = 320) -> go.Figure:
    fig = go.Figure()
    for i, c in enumerate(cols):
        fig.add_trace(go.Scatter(x=df.index, y=df[c], name=c, mode="lines+markers", line=dict(width=3, color=PALETTE[i % len(PALETTE)]), marker=dict(size=7)))
    fig.update_layout(title=dict(text=title, font=dict(size=16)))
    return _base(fig, height)


def bars(df: pd.DataFrame, cols: List[str], title: str = "", height: int = 320) -> go.Figure:
    fig = go.Figure()
    for i, c in enumerate(cols):
        fig.add_trace(go.Bar(x=df.index, y=df[c], name=c, marker_color=PALETTE[i % len(PALETTE)], marker_cornerradius=6))
    fig.update_layout(barmode="group", title=dict(text=title, font=dict(size=16)))
    return _base(fig, height)


def radar(categories: List[str], series: Dict[str, List[float]], title: str = "", height: int = 380) -> go.Figure:
    fig = go.Figure()
    for i, (name, vals) in enumerate(series.items()):
        fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=categories + categories[:1], name=name, fill="toself", opacity=0.35 if len(series) > 1 else 0.25,
                                      line=dict(color=PALETTE[i % len(PALETTE)], width=2.5)))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100], gridcolor="rgba(137,170,195,.15)", showline=False), angularaxis=dict(gridcolor="rgba(137,170,195,.15)")),
                      title=dict(text=title, font=dict(size=16)))
    return _base(fig, height)


def hbar(labels: List[str], values: List[float], title: str = "", height: int = 340, color: str = COLORS["blue"]) -> go.Figure:
    fig = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color=color, marker_cornerradius=6, text=[f"{v:.0f}" for v in values], textposition="outside"))
    fig.update_xaxes(range=[0, 110])
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(title=dict(text=title, font=dict(size=16)))
    return _base(fig, height)


def heatmap(z: pd.DataFrame, title: str = "", height: int = 420, higher_is_worse: Dict[str, bool] | None = None) -> go.Figure:
    """Risk heatmap. Columns where higher = better are inverted so red always means 'worse'."""
    hw = higher_is_worse or {}
    risk = z.copy()
    for c in risk.columns:
        if not hw.get(c, True):
            risk[c] = 100 - risk[c]
    fig = go.Figure(go.Heatmap(z=risk.values, x=list(z.columns), y=list(z.index), text=z.round(0).astype(object).where(z.notna(), "n/a").values, texttemplate="%{text}", zmin=0, zmax=100,
                               colorscale=[[0, "#214B42"], [0.4, "#827348"], [0.7, "#985A52"], [1, "#793942"]], showscale=False, xgap=3, ygap=3))
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(title=dict(text=title, font=dict(size=16)))
    return _base(fig, height)


def risk_scatter(summary: pd.DataFrame, height: int = 420) -> go.Figure:
    fig = go.Figure()
    for g, d in summary.groupby("Grade"):
        fig.add_trace(go.Scatter(x=d["Forensic risk"], y=d["ESG"], mode="markers+text", text=d["Ticker"], textposition="top center", name=g,
                                 marker=dict(size=(d["Market cap (₹ Cr)"] ** 0.5) / 6 + 10, color=GRADE_COLORS[g], opacity=0.85, line=dict(color="#7890A2", width=1.5))))
    fig.update_xaxes(title="Forensic risk (higher = worse)", range=[-5, 105])
    fig.update_yaxes(title="ESG score (higher = better)", range=[0, 100])
    return _base(fig, height)


def donut(labels: List[str], values: List[float], colors: List[str], height: int = 300) -> go.Figure:
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.68, marker=dict(colors=colors, line=dict(color="#183047", width=2)), textinfo="value", sort=False))
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=-0.05))
    return _base(fig, height)
