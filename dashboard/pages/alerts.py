"""8. Alerts — operational HALT / NOTIFY conditions (read-only)."""
from __future__ import annotations

import streamlit as st

from dashboard.components import cards, layout
from dashboard.utils import alerts as alert_utils

layout.page_header("Alerts",
                   "Operational checks: missing data, missing holdings, "
                   "rebalance due, validation failures, weight drift.")

alerts = alert_utils.evaluate()
halt, notify = alert_utils.counts(alerts)

cards.kpi_row([
    ("HALT", str(halt)),
    ("NOTIFY", str(notify)),
    ("Status", "ALL CLEAR" if not alerts else ("ACTION NEEDED" if halt else "REVIEW")),
])
st.divider()

if not alerts:
    st.success("✅ All clear — no operational alerts.")
    st.caption("HALT = blocks the pipeline (bad/stale data, missing holdings, "
               "validation failure). NOTIFY = review at leisure.")
else:
    halts = [a for a in alerts if a["severity"] == alert_utils.HALT]
    notes = [a for a in alerts if a["severity"] == alert_utils.NOTIFY]
    if halts:
        st.subheader("🔴 HALT")
        for a in halts:
            st.error(f"**{a['title']}** — {a['detail']}")
    if notes:
        st.subheader("🟡 NOTIFY")
        for a in notes:
            st.warning(f"**{a['title']}** — {a['detail']}")
