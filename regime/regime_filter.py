"""
Market Regime Detection.

Classifies the market into BULL / NEUTRAL / BEAR regimes
using the Nifty 50 as a market proxy.

Adjusts strategy weights and capital allocation accordingly.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import RegimeConfig, setup_logging
from utils.indicators import sma, ema, adx

logger = setup_logging("regime")


@dataclass
class RegimeState:
    """Market regime at a point in time."""
    date: pd.Timestamp
    regime: str                          # "BULL", "NEUTRAL", "BEAR"
    strategy_weights: Dict[str, float]   # strategy_name -> weight
    capital_allocation: float            # 0.0 to 1.0
    details: Dict[str, float]           # diagnostic values


class RegimeFilter:
    """
    Detects market regime from a broad market proxy.

    Classification logic:
    - BULL:    Nifty > 200 SMA AND 50 SMA > 200 SMA AND ADX > 20
    - NEUTRAL: Nifty > 200 SMA BUT (50 SMA < 200 SMA OR ADX < 20)
    - BEAR:    Nifty < 200 SMA AND 50 SMA < 200 SMA
    """

    def __init__(self, config: Optional[RegimeConfig] = None):
        self.config = config or RegimeConfig()

    def detect_regime(
        self,
        market_close: pd.Series,
        market_high: Optional[pd.Series],
        market_low: Optional[pd.Series],
        date: pd.Timestamp,
    ) -> RegimeState:
        """
        Detect the market regime as of `date`.

        Parameters
        ----------
        market_close : Series
            Close prices for the market proxy (e.g., Nifty 50).
        market_high, market_low : Series, optional
            For ADX calculation.
        date : Timestamp
            Point-in-time date.

        Returns
        -------
        RegimeState with regime classification and weights.
        """
        cfg = self.config

        # Get data up to date
        data = market_close[market_close.index <= date]
        if len(data) < cfg.sma_slow + 50:
            logger.warning(f"Insufficient data for regime detection on {date.date()}")
            return self._default_regime(date)

        # Compute indicators
        sma_fast = sma(data, cfg.sma_fast)
        sma_slow_val = sma(data, cfg.sma_slow)

        latest_close = data.iloc[-1]
        latest_sma_fast = sma_fast.iloc[-1]
        latest_sma_slow = sma_slow_val.iloc[-1]

        # ADX
        if market_high is not None and market_low is not None:
            h = market_high[market_high.index <= date]
            l = market_low[market_low.index <= date]
            adx_df = adx(h, l, data, cfg.adx_period)
            latest_adx = adx_df["ADX"].iloc[-1]
        else:
            latest_adx = 25.0  # assume trending if no H/L data

        # ── Classify regime ──
        above_slow_sma = latest_close > latest_sma_slow
        fast_above_slow = latest_sma_fast > latest_sma_slow
        trending = latest_adx > cfg.adx_trending_threshold

        if above_slow_sma and fast_above_slow and trending:
            regime = "BULL"
        elif above_slow_sma:
            regime = "NEUTRAL"
        else:
            regime = "BEAR"

        # Get weights and allocation
        strategy_weights = cfg.regime_weights.get(regime, cfg.regime_weights["NEUTRAL"])
        capital_allocation = cfg.regime_capital_allocation.get(regime, 0.70)

        details = {
            "close": latest_close,
            "sma_fast": latest_sma_fast,
            "sma_slow": latest_sma_slow,
            "adx": latest_adx,
            "above_slow_sma": float(above_slow_sma),
            "fast_above_slow": float(fast_above_slow),
            "trending": float(trending),
        }

        logger.info(
            f"Regime on {date.date()}: {regime} "
            f"(close={latest_close:.0f}, SMA50={latest_sma_fast:.0f}, "
            f"SMA200={latest_sma_slow:.0f}, ADX={latest_adx:.1f}) "
            f"→ capital={capital_allocation:.0%}"
        )

        return RegimeState(
            date=date,
            regime=regime,
            strategy_weights=strategy_weights,
            capital_allocation=capital_allocation,
            details=details,
        )

    def detect_regime_series(
        self,
        market_close: pd.Series,
        market_high: Optional[pd.Series],
        market_low: Optional[pd.Series],
        dates: pd.DatetimeIndex,
    ) -> Dict[pd.Timestamp, RegimeState]:
        """
        Detect regimes for multiple dates.

        Returns dict mapping date -> RegimeState.
        """
        regimes = {}
        for date in dates:
            regimes[date] = self.detect_regime(
                market_close, market_high, market_low, date
            )
        return regimes

    def _default_regime(self, date: pd.Timestamp) -> RegimeState:
        """Return a default neutral regime when data is insufficient."""
        return RegimeState(
            date=date,
            regime="NEUTRAL",
            strategy_weights=self.config.regime_weights["NEUTRAL"],
            capital_allocation=self.config.regime_capital_allocation["NEUTRAL"],
            details={},
        )

    def get_regime_history(
        self,
        regimes: Dict[pd.Timestamp, RegimeState],
    ) -> pd.DataFrame:
        """Convert regime history to a DataFrame for analysis."""
        records = []
        for date, state in sorted(regimes.items()):
            records.append({
                "date": date,
                "regime": state.regime,
                "capital_allocation": state.capital_allocation,
                **state.details,
            })
        return pd.DataFrame(records).set_index("date")
