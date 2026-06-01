"""
Trend Following Strategy.

Identifies stocks in established uptrends using:
1. Price vs. EMA position
2. EMA slope (momentum of the trend)
3. ADX (trend strength)
"""

import pandas as pd
import numpy as np
from typing import List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies.base import BaseStrategy
from config import TrendConfig
from utils.indicators import ema, slope, adx


class TrendFollowingStrategy(BaseStrategy):
    """
    Systematic trend identification.

    Combines three signals:
    1. Price above both 50-day and 100-day EMA → in uptrend
    2. 50-day EMA slope positive → trend is rising
    3. ADX > 20 → trend is strong (not range-bound)
    """

    def __init__(self, config: Optional[TrendConfig] = None):
        super().__init__("trend_following")
        self.config = config or TrendConfig()

    def compute_raw_scores(
        self,
        close: pd.DataFrame,
        high: pd.DataFrame,
        low: pd.DataFrame,
        volume: pd.DataFrame,
        date: pd.Timestamp,
        universe: List[str],
    ) -> pd.Series:
        """
        Compute trend following scores.

        Returns higher scores for stocks in stronger, more established uptrends.
        """
        cfg = self.config

        # Restrict to universe and data up to date
        cols = [s for s in universe if s in close.columns]
        mask = close.index <= date
        c = close.loc[mask, cols]
        h = high.loc[mask, [s for s in cols if s in high.columns]]
        l = low.loc[mask, [s for s in cols if s in low.columns]]

        min_needed = max(cfg.ema_long, cfg.adx_period) + cfg.ema_slope_window + 50
        if len(c) < min_needed:
            self.logger.warning(
                f"Insufficient data for trend following on {date.date()}"
            )
            return pd.Series(dtype=float)

        scores = pd.Series(index=cols, dtype=float)

        for sym in cols:
            try:
                score = self._score_single(
                    c[sym], h.get(sym), l.get(sym), cfg
                )
                scores[sym] = score
            except Exception as e:
                self.logger.debug(f"Error scoring {sym}: {e}")
                scores[sym] = np.nan

        scores = scores.dropna()
        self.logger.debug(
            f"Trend scores for {date.date()}: {len(scores)} stocks scored"
        )
        return scores

    def _score_single(
        self,
        close_s: pd.Series,
        high_s: Optional[pd.Series],
        low_s: Optional[pd.Series],
        cfg: TrendConfig,
    ) -> float:
        """Score a single stock's trend characteristics."""

        # ── Signal 1: Price above EMAs ──
        ema_short = ema(close_s, cfg.ema_short)
        ema_long_val = ema(close_s, cfg.ema_long)

        latest_close = close_s.iloc[-1]
        latest_ema_short = ema_short.iloc[-1]
        latest_ema_long = ema_long_val.iloc[-1]

        # Binary: above both EMAs
        above_emas = float(
            (latest_close > latest_ema_short) and
            (latest_close > latest_ema_long)
        )

        # Distance above EMA (stronger trend = further above)
        ema_distance = (latest_close / latest_ema_long - 1) if latest_ema_long > 0 else 0
        # Clip to reasonable range
        ema_distance = max(0, min(ema_distance, 0.5))

        # Combined signal 1: binary + continuous
        signal1 = 0.7 * above_emas + 0.3 * min(ema_distance * 5, 1.0)

        # ── Signal 2: EMA slope ──
        ema_slope = slope(ema_short, cfg.ema_slope_window)
        latest_slope = ema_slope.iloc[-1]

        # Normalise slope to [0, 1]
        signal2 = 1.0 if latest_slope > 0 else 0.0

        # ── Signal 3: ADX ──
        if high_s is not None and low_s is not None:
            adx_df = adx(high_s, low_s, close_s, cfg.adx_period)
            latest_adx = adx_df["ADX"].iloc[-1]
            latest_di_plus = adx_df["DI_plus"].iloc[-1]
            latest_di_minus = adx_df["DI_minus"].iloc[-1]

            # ADX above threshold AND +DI > -DI (uptrend specifically)
            adx_strong = float(latest_adx > cfg.adx_threshold)
            uptrend_di = float(latest_di_plus > latest_di_minus)
            signal3 = adx_strong * uptrend_di
        else:
            signal3 = 0.5  # neutral if no H/L data

        # ── Composite ──
        score = (
            cfg.weight_price_above_ema * signal1 +
            cfg.weight_ema_slope * signal2 +
            cfg.weight_adx * signal3
        )

        return score
