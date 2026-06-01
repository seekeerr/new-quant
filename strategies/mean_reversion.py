"""
Mean Reversion Strategy.

KEY INSIGHT: Pure mean reversion is dangerous. We only mean-revert
within an established uptrend. This avoids catching falling knives.

Signal: Uptrending stock that's temporarily oversold.
"""

import pandas as pd
import numpy as np
from typing import List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies.base import BaseStrategy
from config import MeanReversionConfig
from utils.indicators import sma, rsi, atr, slope


class MeanReversionStrategy(BaseStrategy):
    """
    Mean reversion in uptrending stocks.

    Steps:
    1. Confirm uptrend: price > 200 SMA AND 200 SMA slope positive
    2. Identify oversold: RSI(5) < 30 OR price > 2×ATR below 20-day mean
    3. Score by distance from mean (more oversold = higher score)

    This strategy has a shorter holding period (~3-10 days) compared
    to momentum (~20-60 days).
    """

    def __init__(self, config: Optional[MeanReversionConfig] = None):
        super().__init__("mean_reversion")
        self.config = config or MeanReversionConfig()

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
        Compute mean reversion scores.

        Returns higher scores for stocks that are:
        1. In an uptrend (confirmed by 200 SMA)
        2. Temporarily oversold (RSI, distance from mean)
        """
        cfg = self.config

        cols = [s for s in universe if s in close.columns]
        mask = close.index <= date
        c = close.loc[mask, cols]
        h = high.loc[mask, [s for s in cols if s in high.columns]]
        l = low.loc[mask, [s for s in cols if s in low.columns]]

        min_needed = cfg.trend_sma_period + cfg.trend_slope_window + 10
        if len(c) < min_needed:
            self.logger.warning(
                f"Insufficient data for mean reversion on {date.date()}"
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
            f"Mean reversion scores for {date.date()}: "
            f"{len(scores)} stocks scored"
        )
        return scores

    def _score_single(
        self,
        close_s: pd.Series,
        high_s: Optional[pd.Series],
        low_s: Optional[pd.Series],
        cfg: MeanReversionConfig,
    ) -> float:
        """Score a single stock for mean reversion opportunity."""

        latest_close = close_s.iloc[-1]

        # ── Step 1: Confirm uptrend ──
        sma_200 = sma(close_s, cfg.trend_sma_period)
        latest_sma200 = sma_200.iloc[-1]

        if np.isnan(latest_sma200) or latest_sma200 <= 0:
            return 0.0  # can't confirm trend

        # Price above 200 SMA
        above_sma = latest_close > latest_sma200

        # 200 SMA slope positive
        sma_slope = slope(sma_200, cfg.trend_slope_window)
        slope_positive = sma_slope.iloc[-1] > 0 if not np.isnan(sma_slope.iloc[-1]) else False

        # Must pass BOTH uptrend conditions
        if not (above_sma and slope_positive):
            return 0.0  # Not in uptrend — no mean reversion signal

        # ── Step 2: Identify oversold condition ──
        # RSI(5) < 30
        rsi_val = rsi(close_s, cfg.rsi_period)
        latest_rsi = rsi_val.iloc[-1]
        is_rsi_oversold = latest_rsi < cfg.rsi_oversold if not np.isnan(latest_rsi) else False

        # Price below 20-day SMA by > 2×ATR
        sma_short = sma(close_s, cfg.short_sma_period)
        latest_sma_short = sma_short.iloc[-1]

        if high_s is not None and low_s is not None:
            atr_val = atr(high_s, low_s, close_s, cfg.atr_period)
            latest_atr = atr_val.iloc[-1]
        else:
            # Approximate ATR from close only
            daily_range = close_s.diff().abs()
            latest_atr = daily_range.tail(cfg.atr_period).mean()

        distance_below_mean = latest_sma_short - latest_close
        is_atr_oversold = distance_below_mean > (cfg.atr_distance_multiplier * latest_atr)

        # Must be oversold by at least one criterion
        if not (is_rsi_oversold or is_atr_oversold):
            return 0.0  # Not oversold

        # ── Step 3: Score by degree of oversold ──
        # More oversold = higher score (better entry)

        # RSI component: lower RSI = higher score
        if not np.isnan(latest_rsi):
            rsi_score = max(0, (cfg.rsi_oversold - latest_rsi) / cfg.rsi_oversold)
        else:
            rsi_score = 0.0

        # Distance component: further below mean = higher score
        if latest_atr > 0 and not np.isnan(latest_atr):
            distance_score = min(
                distance_below_mean / (3 * latest_atr), 1.0
            )
            distance_score = max(0, distance_score)
        else:
            distance_score = 0.0

        # Trend strength bonus: higher if SMA200 slope is strong
        trend_strength = min(abs(sma_slope.iloc[-1]) * 100, 1.0)

        # Composite
        score = (
            0.40 * rsi_score +
            0.40 * distance_score +
            0.20 * trend_strength
        )

        return score
