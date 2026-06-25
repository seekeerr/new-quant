"""Operational dashboard entry point + navigation router.

Read-only, local-first monitoring for the frozen momentum champion. Launch with:

    py -m streamlit run dashboard/app.py

See DASHBOARD_ARCHITECTURE.md. This app never writes trading state and never
recomputes signals.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make the project root importable so `dashboard.*` resolves regardless of CWD.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

st.set_page_config(
    page_title="Champion — Operations",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

_PAGES_DIR = Path(__file__).resolve().parent / "pages"


def _page(file: str, title: str, icon: str, default: bool = False):
    return st.Page(_PAGES_DIR / file, title=title, icon=icon, default=default)


def main() -> None:
    nav = st.navigation([
        _page("overview.py", "Portfolio Overview", "🏠", default=True),
        _page("holdings.py", "Current Holdings", "📦"),
        _page("target.py", "Target Portfolio", "🎯"),
        _page("rebalances.py", "Rebalance History", "🔄"),
        _page("trades.py", "Trade Log", "🧾"),
        _page("performance.py", "Performance", "📈"),
        _page("audit.py", "Audit Package Viewer", "🗂️"),
        _page("alerts.py", "Alerts", "🚨"),
    ])
    with st.sidebar:
        st.caption("Frozen champion · read-only operations")
        st.caption("Momentum + LowVol · Top10 · Quarterly · Buffer20")
    nav.run()


if __name__ == "__main__":
    main()
