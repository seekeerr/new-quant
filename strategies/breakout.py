"""
Volatility Breakout Strategy.

Identifies stocks breaking out of consolidation zones with volume confirmation.
Uses Donchian Channel breakout + volume surge + consolidation tightness.
"""

import pandas as pd
import numpy as np
from typing import List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies.base import BaseStrategy
from config import BreakoutConfig
from utils.indicators import highest_high, atr, atr_percent, volume_sma, relative_volume


class BreakoutStrategy(BaseStrategy):
    """
    Volatility breakout / range expansion strategy.

    Signals:
    1. Price breaks N-day high → Donchian breakout
    2. Volume surges above average → confirmation
    3. Prior consolidation → tighter = stronger breakout
    """

    def __init__(self, config: Optional[BreakoutConfig] = None):
        super().__init__("breakout")
        self.config = config or BreakoutConfig()

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
        Compute breakout scores.

        Returns higher scores for stocks with recent, high-quality breakouts.
        """
        cfg = self.config

        cols = [s for s in universe if s in close.columns]
        mask = close.index <= date
        c = close.loc[mask, cols]
        h = high.loc[mask, [s for s in cols if s in high.columns]]
        l = low.loc[mask, [s for s in cols if s in low.columns]]
        v = volume.loc[mask, [s for s in cols if s in volume.columns]]

        min_needed = cfg.donchian_period + 10
        if len(c) < min_needed:
            self.logger.warning(
                f"Insufficient data for breakout on {date.date()}"
            )
            return pd.Series(dtype=float)

        scores = pd.Series(index=cols, dtype=float)

        for sym in cols:
            try:
                score = self._score_single(
                    c.get(sym), h.get(sym), l.get(sym), v.get(sym), cfg
                )
                scores[sym] = score
            except Exception as e:
                self.logger.debug(f"Error scoring {sym}: {e}")
                scores[sym] = np.nan

        scores = scores.dropna()
        self.logger.debug(
            f"Breakout scores for {date.date()}: {len(scores)} stocks scored"
        )
        return scores

    def _score_single(
        self,
        close_s: Optional[pd.Series],
        high_s: Optional[pd.Series],
        low_s: Optional[pd.Series],
        vol_s: Optional[pd.Series],
        cfg: BreakoutConfig,
    ) -> float:
        """Score a single stock's breakout characteristics."""
        if close_s is None or close_s.empty:
            return np.nan

        latest_close = close_s.iloc[-1]

        # ── Signal 1: Donchian breakout ──
        # How close is the current price to the N-day high?
        if high_s is not None and not high_s.empty:
            n_day_high = highest_high(high_s, cfg.donchian_period)
            latest_high = n_day_high.iloc[-1]
        else:
            n_day_high = close_s.rolling(cfg.donchian_period).max()
            latest_high = n_day_high.iloc[-1]

        if latest_high > 0 and not np.isnan(latest_high):
            # Proximity to N-day high: 1.0 = at high, 0.0 = far below
            proximity = latest_close / latest_high
            # At or above N-day high = breakout
            is_breakout = float(proximity >= 0.98)
            # Continuous measure
            breakout_score = max(0, (proximity - 0.90) / 0.10)  # 0 at 90%, 1 at 100%
            breakout_score = min(breakout_score, 1.0)
        else:
            is_breakout = 0.0
            breakout_score = 0.0

        # ── Signal 2: Volume confirmation ──
        if vol_s is not None and not vol_s.empty:
            vol_avg = vol_s.tail(cfg.volume_sma_period).mean()
            latest_vol = vol_s.iloc[-1]

            if vol_avg > 0 and not np.isnan(vol_avg):
                rvol = latest_vol / vol_avg
                volume_surge = float(rvol >= cfg.volume_surge_multiplier)
                # Continuous: normalise relative volume
                volume_score = min(rvol / (cfg.volume_surge_multiplier * 2), 1.0)
            else:
                volume_surge = 0.0
                volume_score = 0.0
        else:
            volume_surge = 0.0
            volume_score = 0.5  # neutral

        # ── Signal 3: Prior consolidation (tighter = better) ──
        if high_s is not None and low_s is not None:
            atr_val = atr(high_s, low_s, close_s, cfg.atr_period)
            latest_atr = atr_val.iloc[-1]
            atr_pct = latest_atr / latest_close if latest_close > 0 else 0

            # Lower ATR% = tighter consolidation = better breakout
            # Invert: tight consolidation gets high score
            if atr_pct > 0:
                consolidation_score = max(0, 1 - atr_pct / (cfg.consolidation_threshold * 3))
            else:
                consolidation_score = 0.5
        else:
            consolidation_score = 0.5

        # ── Composite ──
        # Weight breakout signal heavily, volume as confirmation
        score = (
            0.50 * breakout_score +
            0.25 * volume_score +
            0.25 * consolidation_score
        )

        # Bonus for confirmed breakout (at high + volume surge)
        if is_breakout and volume_surge:
            score *= 1.3  # 30% bonus

        return min(score, 1.0)
