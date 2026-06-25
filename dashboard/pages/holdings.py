"""2. Current Holdings — positions with live price, weight and P&L."""
from __future__ import annotations

import numpy as np
import streamlit as st

from dashboard.components import cards, layout, tables
from dashboard.utils import data_loader as dl
from dashboard.utils import formatting as fmt
from dashboard.utils import metrics, prices

layout.page_header("Current Holdings",
                   "Open positions, valued at the latest cached close.")

state = dl.state()
holdings = dl.holdings()
cash = float(state.get("cash", 0.0) or 0.0)

if holdings.empty:
    layout.no_data("No holdings recorded in paper_trading/holdings.csv.",
                   "Columns: symbol, quantity, cost_price, entry_date.")
    st.stop()

enriched = metrics.enrich_holdings(holdings, prices.latest_prices(), cash)
invested = float(np.nansum(enriched["market_value"].to_numpy()))
total_pnl = float(np.nansum(enriched["pnl_value"].to_numpy()))
cost_basis = float(np.nansum(enriched["cost_value"].to_numpy()))

cards.kpi_row([
    ("Invested Value", fmt.rupees(invested)),
    ("Cost Basis", fmt.rupees(cost_basis)),
    ("Unrealised P&L", fmt.rupees(total_pnl),
     fmt.signed_pct(total_pnl / cost_basis) if cost_basis else None),
    ("Positions", str(len(enriched))),
])

st.divider()
tables.holdings_table(enriched)

missing = enriched[enriched["current_price"].isna()]["symbol"].tolist()
if missing:
    st.warning("No cached price for: " + ", ".join(missing)
               + " — shown as '—'. See the Alerts page.")
st.caption(f"Last price date in cache: "
           f"{fmt.date_str(prices.last_close_date())}")
