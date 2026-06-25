"""5. Trade Log — append-only record of paper fills."""
from __future__ import annotations

import streamlit as st

from dashboard.components import cards, layout, tables
from dashboard.utils import data_loader as dl
from dashboard.utils import formatting as fmt

layout.page_header("Trade Log",
                   "Append-only record of every paper trade (the paper ledger).")

trades = dl.trades()

if trades.empty:
    layout.no_data("No trades in paper_trading/trade_log.csv.",
                   "Columns: date, symbol, action, quantity, price, costs, notes.")
    st.stop()

n_buy = int((trades["action"].astype(str).str.upper() == "BUY").sum()) \
    if "action" in trades else 0
n_sell = int((trades["action"].astype(str).str.upper() == "SELL").sum()) \
    if "action" in trades else 0
total_costs = None
if "costs" in trades:
    c = trades["costs"].astype(float, errors="ignore")
    try:
        total_costs = float(c.sum())
    except Exception:
        total_costs = None

cards.kpi_row([
    ("Total Trades", str(len(trades))),
    ("Buys", str(n_buy)),
    ("Sells", str(n_sell)),
    ("Total Costs", fmt.rupees(total_costs) if total_costs is not None else fmt.DASH),
])

st.divider()

cols = st.columns(2)
with cols[0]:
    syms = ["(all)"] + sorted(trades["symbol"].dropna().unique().tolist()) \
        if "symbol" in trades else ["(all)"]
    pick_sym = st.selectbox("Symbol", syms)
with cols[1]:
    pick_act = st.selectbox("Action", ["(all)", "BUY", "SELL"])

view = trades
if pick_sym != "(all)":
    view = view[view["symbol"] == pick_sym]
if pick_act != "(all)":
    view = view[view["action"].astype(str).str.upper() == pick_act]

tables.plain_table(view)
