"""6. Performance — equity, drawdown, benchmark; falls back to research PNGs."""
from __future__ import annotations

import streamlit as st

from dashboard.components import cards, charts, layout
from dashboard.utils import data_loader as dl
from dashboard.utils import formatting as fmt
from dashboard.utils import metrics, paths

layout.page_header("Performance",
                   "Paper equity curve, drawdown, and benchmark comparison.")

equity = dl.equity_curve()
benchmark = dl.benchmark()

if equity.empty:
    layout.no_data(
        "No paper equity curve in paper_trading/equity_curve.csv.",
        "Columns: date, portfolio_value. "
        "The research charts below are shown as reference.")
else:
    cards.kpi_row([
        ("CAGR", fmt.pct(metrics.cagr(equity))),
        ("Total Return", fmt.signed_pct(metrics.total_return(equity))),
        ("Max Drawdown", fmt.pct(metrics.max_drawdown(equity))),
        ("Current DD", fmt.pct(metrics.current_drawdown(equity))),
    ])
    log = st.toggle("Log scale", value=True)
    st.plotly_chart(charts.equity_curve_chart(equity, benchmark, log_scale=log),
                    use_container_width=True)
    st.plotly_chart(charts.drawdown_chart(equity), use_container_width=True)

st.divider()
st.subheader("Reference research charts (frozen champion)")
st.caption("Read-only static reports from the validated backtest — not the "
           "paper book. Source: results/.")

png_candidates = [
    paths.CHAMPION_RESULTS_DIR / "report.png",
    paths.RESULTS_DIR / "pure_momentum" / "factor_report_10stocks_quarterly.png",
    paths.RESULTS_DIR / "ranking_buffer" / "report.png",
]
shown = 0
for png in png_candidates:
    if png.exists():
        st.image(str(png), caption=str(png.relative_to(paths.PROJECT_ROOT)),
                 use_container_width=True)
        shown += 1
if shown == 0:
    st.caption("No research report PNGs found under results/.")
