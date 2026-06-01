"""
Risk management: stop losses, drawdown limits, and position protection.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import RiskConfig, setup_logging
from utils.indicators import atr

logger = setup_logging("risk_manager")


@dataclass
class StopLossLevel:
    """Stop loss information for a single position."""
    symbol: str
    entry_price: float
    entry_date: pd.Timestamp
    current_stop: float
    stop_type: str             # "trailing", "time", "drawdown"
    atr_at_entry: float = 0.0
    highest_since_entry: float = 0.0
    days_held: int = 0


class RiskManager:
    """
    Portfolio-level and position-level risk management.

    Position-level:
    - Trailing stop: 2.5 × ATR below entry or highest price since entry
    - Time stop: exit after max hold days
    - Profit target: optional, for mean reversion trades

    Portfolio-level:
    - Max drawdown thresholds with progressive response
    - Max daily loss halt
    - Sector concentration limits
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self._stop_levels: Dict[str, StopLossLevel] = {}
        self._halt_until: Optional[pd.Timestamp] = None
        self._in_reduce_mode: bool = False
        self._in_liquidate_mode: bool = False

    def initialize_stop(
        self,
        symbol: str,
        entry_price: float,
        entry_date: pd.Timestamp,
        atr_value: float,
        strategy_type: str = "momentum",
    ):
        """Set initial stop loss for a new position."""
        cfg = self.config

        stop_price = entry_price - cfg.trailing_stop_atr_multiplier * atr_value
        stop_price = max(0, stop_price)  # can't be negative

        self._stop_levels[symbol] = StopLossLevel(
            symbol=symbol,
            entry_price=entry_price,
            entry_date=entry_date,
            current_stop=stop_price,
            stop_type="trailing",
            atr_at_entry=atr_value,
            highest_since_entry=entry_price,
            days_held=0,
        )

        logger.debug(
            f"Stop set for {symbol}: entry={entry_price:.2f}, "
            f"stop={stop_price:.2f} (ATR={atr_value:.2f})"
        )

    def update_stops(
        self,
        current_prices: Dict[str, float],
        current_date: pd.Timestamp,
        strategy_types: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """
        Update trailing stops and check for triggered stops.

        Parameters
        ----------
        current_prices : dict
            symbol -> current close price
        current_date : Timestamp
        strategy_types : dict, optional
            symbol -> strategy type (for hold duration limits)

        Returns
        -------
        List of symbols that should be exited (stop triggered).
        """
        cfg = self.config
        strategy_types = strategy_types or {}
        exits = []

        for symbol, stop in list(self._stop_levels.items()):
            price = current_prices.get(symbol)
            if price is None:
                continue

            # Update days held
            stop.days_held = (current_date - stop.entry_date).days

            # Update trailing stop (only moves up, never down)
            if price > stop.highest_since_entry:
                stop.highest_since_entry = price
                new_stop = price - cfg.trailing_stop_atr_multiplier * stop.atr_at_entry
                stop.current_stop = max(stop.current_stop, new_stop)

            # ── Check stop triggers ──

            # 1. Price below trailing stop
            if price <= stop.current_stop:
                stop.stop_type = "trailing"
                exits.append(symbol)
                logger.info(
                    f"TRAILING STOP: {symbol} @ {price:.2f} "
                    f"(stop={stop.current_stop:.2f})"
                )
                continue

            # 2. Time stop
            strategy = strategy_types.get(symbol, "momentum")
            max_days = (
                cfg.max_hold_days_mean_reversion
                if strategy == "mean_reversion"
                else cfg.max_hold_days_momentum
            )
            if stop.days_held >= max_days:
                stop.stop_type = "time"
                exits.append(symbol)
                logger.info(
                    f"TIME STOP: {symbol} after {stop.days_held} days "
                    f"(max={max_days})"
                )
                continue

            # 3. Profit target (mean reversion only)
            if strategy == "mean_reversion":
                target = stop.entry_price + cfg.profit_target_atr_multiplier * stop.atr_at_entry
                if price >= target:
                    stop.stop_type = "profit_target"
                    exits.append(symbol)
                    logger.info(
                        f"PROFIT TARGET: {symbol} @ {price:.2f} "
                        f"(target={target:.2f})"
                    )

        # Remove exited positions from tracking
        for sym in exits:
            if sym in self._stop_levels:
                del self._stop_levels[sym]

        return exits

    def check_portfolio_risk(
        self,
        portfolio_value: float,
        peak_value: float,
        daily_return: float,
        current_date: pd.Timestamp,
    ) -> Dict[str, any]:
        """
        Check portfolio-level risk limits.

        Returns dict with:
        - 'action': 'none', 'reduce', 'liquidate', 'halt'
        - 'reason': description
        - 'scale_factor': how much to scale positions (1.0 = no change)
        """
        cfg = self.config

        # Check if we're in a halt period
        if self._halt_until and current_date < self._halt_until:
            return {
                "action": "halt",
                "reason": f"Trading halted until {self._halt_until.date()}",
                "scale_factor": 0.0,
            }

        # Calculate drawdown
        drawdown = (portfolio_value / peak_value - 1) if peak_value > 0 else 0

        # Check drawdown thresholds
        if drawdown <= cfg.max_drawdown_liquidate:
            if not self._in_liquidate_mode:
                logger.warning(
                    f"LIQUIDATE: Drawdown {drawdown:.1%} "
                    f"exceeds limit {cfg.max_drawdown_liquidate:.1%}"
                )
                self._in_liquidate_mode = True
            return {
                "action": "liquidate",
                "reason": f"Max drawdown ({drawdown:.1%}) breached",
                "scale_factor": 0.0,
            }
        else:
            self._in_liquidate_mode = False

        if drawdown <= cfg.max_drawdown_reduce:
            if not self._in_reduce_mode:
                logger.warning(
                    f"REDUCE: Drawdown {drawdown:.1%} "
                    f"exceeds soft limit {cfg.max_drawdown_reduce:.1%}"
                )
                self._in_reduce_mode = True
            return {
                "action": "reduce",
                "reason": f"Drawdown warning ({drawdown:.1%})",
                "scale_factor": 0.5,
            }
        else:
            self._in_reduce_mode = False

        # Check daily loss
        if daily_return <= cfg.max_daily_loss:
            self._halt_until = current_date + pd.Timedelta(days=cfg.halt_days)
            logger.warning(
                f"HALT: Daily loss {daily_return:.1%} "
                f"exceeds limit. Halting until {self._halt_until.date()}"
            )
            return {
                "action": "halt",
                "reason": f"Daily loss ({daily_return:.1%}) halt",
                "scale_factor": 0.0,
            }

        return {
            "action": "none",
            "reason": "All clear",
            "scale_factor": 1.0,
        }

    def clear_stops(self):
        """Clear all stop levels (e.g., on full liquidation)."""
        self._stop_levels.clear()

    def get_active_stops(self) -> Dict[str, StopLossLevel]:
        """Get all active stop loss levels."""
        return dict(self._stop_levels)
