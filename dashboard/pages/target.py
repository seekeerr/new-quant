"""3. Target Portfolio — latest Top10 + Buffer20 with BUY/HOLD/SELL."""
from __future__ import annotations

import streamlit as st

from dashboard.components import cards, layout, tables
from dashboard.utils import data_loader as dl

layout.page_header("Target Portfolio",
                   "Latest generated Top10, the Buffer20 band, and the "
                   "buy / hold / sell classification vs current holdings.")

target = dl.target()

if target.empty:
    layout.no_data("No target in paper_trading/target_portfolio.csv.",
                   "Columns: rank, symbol, score, in_top10, in_buffer20, "
                   "classification, current_held.")
    st.stop()


def _truthy(series):
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


cls = target.get("classification")
n_buy = int((cls.str.upper() == "BUY").sum()) if cls is not None else 0
n_sell = int((cls.str.upper() == "SELL").sum()) if cls is not None else 0
n_hold = int((cls.str.upper() == "HOLD").sum()) if cls is not None else 0

cards.kpi_row([
    ("Top 10", str(int(_truthy(target["in_top10"]).sum())
                   if "in_top10" in target else len(target))),
    ("BUY", str(n_buy)),
    ("HOLD", str(n_hold)),
    ("SELL", str(n_sell)),
])

st.divider()
st.subheader("Top 10 target")
top10 = target[_truthy(target["in_top10"])] if "in_top10" in target else target
tables.target_table(top10)

if "in_buffer20" in target:
    buffer = target[_truthy(target["in_buffer20"]) & ~_truthy(target["in_top10"])]
    if not buffer.empty:
        st.subheader("Buffer 20 band (ranks 11–20)")
        st.caption("Names held inside this band are retained by the buffer rule "
                   "even if they slip below the Top 10.")
        tables.target_table(buffer)

with st.expander("Full ranking"):
    tables.target_table(target)
