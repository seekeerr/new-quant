"""Plotly charts for the Performance page (equity, drawdown, benchmark)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.utils import metrics


def equity_curve_chart(equity: pd.Series, benchmark: pd.Series | None = None,
                       log_scale: bool = True) -> go.Figure:
    """Rebased (base 100) paper NAV vs benchmark."""
    fig = go.Figure()
    if equity is not None and not equity.empty:
        rebased = equity / equity.iloc[0] * 100
        fig.add_trace(go.Scatter(
            x=rebased.index, y=rebased.values, name="Paper Portfolio",
            line=dict(color="#16c784", width=2)))
    if benchmark is not None and not benchmark.empty and equity is not None \
            and not equity.empty:
        bm = benchmark[(benchmark.index >= equity.index[0])
                       & (benchmark.index <= equity.index[-1])]
        if not bm.empty:
            bm = bm / bm.iloc[0] * 100
            fig.add_trace(go.Scatter(
                x=bm.index, y=bm.values, name="NIFTY 500 (price)",
                line=dict(color="#888", width=1.4, dash="dash")))
    fig.update_layout(
        title="Equity Curve (base 100)", height=420,
        yaxis_type="log" if log_scale else "linear",
        legend=dict(orientation="h", y=1.02, x=0),
        margin=dict(l=40, r=20, t=50, b=30), template="plotly_dark")
    return fig


def drawdown_chart(equity: pd.Series) -> go.Figure:
    dd = metrics.drawdown_series(equity) * 100
    fig = go.Figure()
    if not dd.empty:
        fig.add_trace(go.Scatter(
            x=dd.index, y=dd.values, name="Drawdown",
            fill="tozeroy", line=dict(color="#ea3943", width=1)))
    fig.update_layout(
        title="Drawdown (%)", height=320,
        margin=dict(l=40, r=20, t=50, b=30), template="plotly_dark")
    return fig
