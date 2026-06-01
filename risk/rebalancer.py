"""
Rebalancing engine: compares target vs. current portfolio and
generates the trade list needed to rebalance.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import setup_logging
from portfolio.constructor import PortfolioTarget

logger = setup_logging("rebalancer")


@dataclass
class Trade:
    """A single trade to execute."""
    symbol: str
    side: str              # "BUY" or "SELL"
    shares: int
    price: float
    reason: str            # "new_entry", "increase", "exit", "decrease", "stop_loss"
    value: float = 0.0     # trade value = shares × price

    def __post_init__(self):
        self.value = self.shares * self.price


@dataclass
class RebalanceResult:
    """Result of a rebalancing operation."""
    date: pd.Timestamp
    trades: List[Trade] = field(default_factory=list)
    buys: int = 0
    sells: int = 0
    holds: int = 0
    total_buy_value: float = 0.0
    total_sell_value: float = 0.0
    turnover: float = 0.0      # one-way turnover as fraction of portfolio


def generate_rebalance_trades(
    current_holdings: Dict[str, int],
    target: PortfolioTarget,
    current_prices: Dict[str, float],
    date: pd.Timestamp,
    stop_loss_exits: Optional[List[str]] = None,
    min_trade_value: float = 200.0,
    drift_threshold: float = 0.03,
) -> RebalanceResult:
    """
    Generate trades to move from current holdings to target portfolio.

    Parameters
    ----------
    current_holdings : dict
        symbol -> current number of shares held.
    target : PortfolioTarget
        Target portfolio from the constructor.
    current_prices : dict
        symbol -> current market price.
    date : Timestamp
    stop_loss_exits : list, optional
        Symbols to force-exit (from risk manager).
    min_trade_value : float
        Minimum trade value to execute (avoid dust trades).
    drift_threshold : float
        Only rebalance if weight drift > this threshold.

    Returns
    -------
    RebalanceResult with list of trades.
    """
    stop_loss_exits = stop_loss_exits or []
    target_shares = target.shares
    trades = []

    all_symbols = set(current_holdings.keys()) | set(target_shares.keys()) | set(stop_loss_exits)

    buys = 0
    sells = 0
    holds = 0
    total_buy = 0.0
    total_sell = 0.0

    for sym in all_symbols:
        current_qty = current_holdings.get(sym, 0)
        target_qty = target_shares.get(sym, 0)
        price = current_prices.get(sym, 0)

        if price <= 0:
            continue

        # Force-exit for stop losses
        if sym in stop_loss_exits and current_qty > 0:
            trade = Trade(
                symbol=sym,
                side="SELL",
                shares=current_qty,
                price=price,
                reason="stop_loss",
            )
            trades.append(trade)
            sells += 1
            total_sell += trade.value
            continue

        diff = target_qty - current_qty

        if diff == 0:
            if current_qty > 0:
                holds += 1
            continue

        trade_value = abs(diff * price)

        # Skip small trades that aren't worth the transaction costs
        if trade_value < min_trade_value:
            holds += 1
            continue

        if diff > 0:
            # BUY
            reason = "new_entry" if current_qty == 0 else "increase"
            trade = Trade(
                symbol=sym,
                side="BUY",
                shares=diff,
                price=price,
                reason=reason,
            )
            trades.append(trade)
            buys += 1
            total_buy += trade.value
        else:
            # SELL
            reason = "exit" if target_qty == 0 else "decrease"
            trade = Trade(
                symbol=sym,
                side="SELL",
                shares=abs(diff),
                price=price,
                reason=reason,
            )
            trades.append(trade)
            sells += 1
            total_sell += trade.value

    # Calculate turnover
    portfolio_value = sum(
        qty * current_prices.get(sym, 0)
        for sym, qty in current_holdings.items()
    )
    if portfolio_value > 0:
        turnover = max(total_buy, total_sell) / portfolio_value
    else:
        turnover = 1.0 if total_buy > 0 else 0.0

    result = RebalanceResult(
        date=date,
        trades=trades,
        buys=buys,
        sells=sells,
        holds=holds,
        total_buy_value=total_buy,
        total_sell_value=total_sell,
        turnover=turnover,
    )

    logger.info(
        f"Rebalance on {date.date()}: "
        f"{buys} buys (₹{total_buy:,.0f}), "
        f"{sells} sells (₹{total_sell:,.0f}), "
        f"{holds} holds, turnover={turnover:.1%}"
    )

    return result
