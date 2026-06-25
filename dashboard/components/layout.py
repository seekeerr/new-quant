"""Shared page chrome: header, mode banner, no-data notices, alert badge."""
from __future__ import annotations

import streamlit as st

from dashboard.utils import alerts as alert_utils
from dashboard.utils import data_loader as dl

_MODE_STYLE = {
    "EXAMPLE": ("⚠️ EXAMPLE DATA", "#b45309",
                "Showing shipped sample data, not real positions. "
                "Replace paper_trading/* and set mode to PAPER."),
    "PAPER": ("📝 PAPER TRADING", "#1d4ed8", "Live forward paper-trading mode."),
    "LIVE": ("🔴 LIVE", "#b91c1c", "Live capital deployed."),
}


def page_header(title: str, subtitle: str = "") -> None:
    """Render the standard page title + strategy/mode banner + alert badge."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)
    _mode_banner()
    _alert_badge()
    st.divider()


def _mode_banner() -> None:
    state = dl.state()
    mode = str(state.get("mode", "")).upper() or "UNKNOWN"
    label, color, detail = _MODE_STYLE.get(
        mode, (f"MODE: {mode}", "#555", "No state.json found."))
    strat = state.get("strategy_label", "Frozen champion")
    commit = state.get("frozen_commit", "")
    stamp = f" · commit `{commit}`" if commit else ""
    st.markdown(
        f"<div style='padding:8px 12px;border-radius:6px;background:{color}22;"
        f"border-left:4px solid {color};margin-bottom:6px'>"
        f"<b style='color:{color}'>{label}</b> — {detail}<br>"
        f"<span style='font-size:0.85em;opacity:0.8'>{strat}{stamp}</span></div>",
        unsafe_allow_html=True,
    )


def _alert_badge() -> None:
    alerts = alert_utils.evaluate()
    halt, notify = alert_utils.counts(alerts)
    if halt:
        st.error(f"🔴 {halt} HALT alert(s) and {notify} notice(s) — see Alerts page.")
    elif notify:
        st.warning(f"🟡 {notify} notice(s) — see Alerts page.")


def no_data(message: str, hint: str = "") -> None:
    """Standard empty-state block — used everywhere a file is missing/empty."""
    st.info(f"**No data yet.** {message}")
    if hint:
        st.caption(hint)
