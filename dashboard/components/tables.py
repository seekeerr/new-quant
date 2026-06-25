"""Styled dataframe renderers: P&L coloring and BUY/HOLD/SELL coloring."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.utils import formatting as fmt


def holdings_table(df: pd.DataFrame) -> None:
    """Render enriched holdings with formatted, color-coded columns."""
    if df is None or df.empty:
        return
    view = pd.DataFrame({
        "Symbol": df["symbol"],
        "Qty": df["quantity"].astype("Int64"),
        "Cost Price": df["cost_price"].map(fmt.price),
        "Current Price": df["current_price"].map(fmt.price),
        "Market Value": df["market_value"].map(lambda v: fmt.rupees(v)),
        "P&L %": df["pnl_pct"],
        "Weight": df["weight"],
    })

    def _style(s: pd.Series):
        if s.name == "P&L %":
            return [f"color:{fmt.pnl_color(v)}" for v in s]
        return ["" for _ in s]

    styled = (view.style
              .apply(_style, axis=0)
              .format({"P&L %": fmt.signed_pct, "Weight": fmt.pct}))
    st.dataframe(styled, use_container_width=True, hide_index=True)


def target_table(df: pd.DataFrame) -> None:
    """Render the target portfolio with BUY/HOLD/SELL color coding."""
    if df is None or df.empty:
        return
    view = df.copy()

    def _row_style(row):
        color = fmt.classification_color(row.get("classification", ""))
        return [f"color:{color}"] * len(row)

    styled = view.style.apply(_row_style, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)


def plain_table(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    st.dataframe(df, use_container_width=True, hide_index=True)
