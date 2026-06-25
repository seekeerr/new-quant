"""1. Portfolio Overview — top-level operational KPIs."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import cards, layout
from dashboard.utils import data_loader as dl
from dashboard.utils import formatting as fmt
from dashboard.utils import metrics, prices

layout.page_header("Portfolio Overview",
                   "Current operational snapshot of the frozen champion.")

state = dl.state()
holdings = dl.holdings()
equity = dl.equity_curve()
close = prices.latest_prices()
cash = float(state.get("cash", 0.0) or 0.0)

enriched = metrics.enrich_holdings(holdings, close, cash)
nav = metrics.portfolio_value(enriched, cash)
initial = float(state.get("initial_capital", 0.0) or 0.0)

cur_dd = metrics.current_drawdown(equity)
cagr = metrics.cagr(equity)
tot_ret = (nav / initial - 1) if initial > 0 else None

cards.kpi_row([
    ("Portfolio Value", fmt.rupees(nav) if nav else fmt.DASH,
     fmt.signed_pct(tot_ret) if tot_ret is not None else None),
    ("Cash", fmt.rupees(cash)),
    ("Holdings", str(len(holdings)) if not holdings.empty else "0"),
    ("Current Drawdown", fmt.pct(cur_dd) if cur_dd is not None else fmt.DASH),
])
cards.kpi_row([
    ("CAGR (paper)", fmt.pct(cagr) if cagr is not None else fmt.DASH),
    ("Last Rebalance", fmt.date_str(state.get("last_rebalance"))),
    ("Next Rebalance", fmt.date_str(state.get("next_rebalance"))),
    ("Inception", fmt.date_str(state.get("inception_date"))),
])

st.divider()

if not state:
    layout.no_data(
        "No paper_trading/state.json found.",
        "Seed the paper_trading/ directory per DASHBOARD_ARCHITECTURE.md §5.")
elif equity.empty and holdings.empty:
    layout.no_data(
        "State loaded, but no equity curve or holdings recorded yet.",
        "KPIs populate once holdings.csv and equity_curve.csv exist.")
else:
    if not equity.empty:
        st.subheader("Paper NAV")
        st.line_chart(equity.rename("Portfolio Value"))
    if not enriched.empty:
        st.subheader("Holdings at a glance")
        st.caption("Full detail on the Current Holdings page.")
        glance = pd.DataFrame({
            "Symbol": enriched["symbol"],
            "Weight": enriched["weight"].map(fmt.pct),
            "P&L %": enriched["pnl_pct"].map(fmt.signed_pct),
        })
        st.dataframe(glance, use_container_width=True, hide_index=True)
