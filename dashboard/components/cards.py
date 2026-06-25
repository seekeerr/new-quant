"""KPI metric cards / rows built on st.metric."""
from __future__ import annotations

from typing import Sequence

import streamlit as st


def kpi_row(items: Sequence[tuple]) -> None:
    """Render a row of metric cards.

    Each item is (label, value_str) or (label, value_str, delta_str).
    """
    cols = st.columns(len(items)) if items else []
    for col, item in zip(cols, items):
        label, value = item[0], item[1]
        delta = item[2] if len(item) > 2 else None
        with col:
            st.metric(label, value, delta=delta)
