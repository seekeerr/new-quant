"""4. Rebalance History — one row per rebalance, with turnover and notes."""
from __future__ import annotations

import streamlit as st

from dashboard.components import cards, layout, tables
from dashboard.utils import data_loader as dl
from dashboard.utils import formatting as fmt

layout.page_header("Rebalance History",
                   "Every recorded quarterly rebalance.")

reb = dl.rebalances()

if reb.empty:
    layout.no_data("No rebalances in paper_trading/rebalance_history.csv.",
                   "Columns: date, num_holdings, turnover_pct, "
                   "holdings_snapshot, notes, snapshot_id.")
    st.stop()

avg_turn = None
if "turnover_pct" in reb:
    vals = reb["turnover_pct"].astype(float).dropna()
    avg_turn = vals.mean() / 100 if not vals.empty else None

cards.kpi_row([
    ("Rebalances", str(len(reb))),
    ("Latest", fmt.date_str(reb["date"].iloc[0]) if "date" in reb else fmt.DASH),
    ("Avg Turnover", fmt.pct(avg_turn) if avg_turn is not None else fmt.DASH),
])
st.caption("Buffer-20 expectation is ~38% turnover per rebalance "
           "(per LIVE_TRADING_ARCHITECTURE.md).")

st.divider()
tables.plain_table(reb)

st.subheader("Holdings snapshot")
options = reb["date"].tolist() if "date" in reb else []
if options:
    pick = st.selectbox("Rebalance date", options)
    row = reb[reb["date"] == pick].iloc[0]
    snap = str(row.get("holdings_snapshot", "") or "")
    names = [s.strip() for s in snap.split(";") if s.strip()]
    if names:
        st.write(", ".join(names))
    else:
        st.caption("No holdings snapshot recorded for this date.")
    if row.get("notes"):
        st.info(row["notes"])
