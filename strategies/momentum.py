"""
Cross-Sectional Momentum Strategy.

Based on Jegadeesh & Titman (1993), adapted for Indian markets.
Core signal: 12-1 momentum (12-month return, skipping most recent month).
Enhanced with multi-horizon blending and risk-adjusted momentum.
"""

import pandas as pd
import numpy as np
from typing import List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies.base import BaseStrategy
from config import MomentumConfig
from utils.indicators import rolling_returns, rolling_volatility, simple_returns


class MomentumStrategy(BaseStrategy):
    """
    Cross-sectional momentum: buy recent winners, avoid recent losers.

    Signal construction:
    1. 12-1 momentum: 12-month return minus last 1-month return
       (skip-month avoids short-term mean-reversion noise)
    2. Risk-adjusted: momentum / rolling volatility
    3. Multi-horizon blend: weighted average of 3M, 6M, 12M momentum
    4. Acceleration filter: prefer accelerating momentum
    """

    def __init__(self, config: Optional[MomentumConfig] = None):
        super().__init__("momentum")
        self.config = config or MomentumConfig()

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
        Compute momentum scores for the universe.

        Returns higher scores for stocks with stronger, more consistent momentum.
        """
        cfg = self.config

        # Get data up to signal date, restrict to universe
        cols = [s for s in universe if s in close.columns]
        mask = close.index <= date
        prices = close.loc[mask, cols]

        if len(prices) < cfg.lookback_long + cfg.skip_recent:
            self.logger.warning(
                f"Insufficient data for momentum on {date.date()}"
            )
            return pd.Series(dtype=float)

        # ── Component 1: 12-1 Momentum (skip-month) ──
        # Return over [T-252, T-21] period
        price_now = prices.iloc[-1]
        price_skip = prices.iloc[-(cfg.skip_recent + 1)]  # T - skip_recent
        price_long = prices.iloc[-(cfg.lookback_long + 1)]  # T - lookback_long

        # Total 12M return
        ret_12m = (price_skip / price_long) - 1

        # ── Component 2: Multi-horizon returns ──
        # 6-month return (skip recent month)
        if len(prices) >= cfg.lookback_medium + cfg.skip_recent:
            price_6m = prices.iloc[-(cfg.lookback_medium + 1)]
            ret_6m = (price_skip / price_6m) - 1
        else:
            ret_6m = ret_12m  # fallback

        # 3-month return (skip recent month)
        if len(prices) >= cfg.lookback_short + cfg.skip_recent:
            price_3m = prices.iloc[-(cfg.lookback_short + 1)]
            ret_3m = (price_skip / price_3m) - 1
        else:
            ret_3m = ret_6m  # fallback

        # ── Component 3: Risk-adjusted momentum ──
        daily_returns = prices.pct_change()
        vol = daily_returns.tail(cfg.vol_lookback).std() * np.sqrt(252)
        vol = vol.replace(0, np.nan)

        # Risk-adjusted 12-1 momentum
        risk_adj_mom = ret_12m / vol

        # ── Component 4: Acceleration (3M > 6M implies accelerating) ──
        acceleration = (ret_3m > ret_6m).astype(float)

        # ── Composite Score ──
        # Blend multi-horizon returns
        blended_return = (
            cfg.weight_12m * ret_12m.rank(pct=True) +
            cfg.weight_6m * ret_6m.rank(pct=True) +
            cfg.weight_3m * ret_3m.rank(pct=True)
        )

        # Final score: blended momentum + risk-adjustment bonus + acceleration bonus
        score = (
            0.50 * blended_return +
            0.35 * risk_adj_mom.rank(pct=True) +
            0.15 * acceleration
        )

        # Drop NaN
        score = score.dropna()

        self.logger.debug(
            f"Momentum scores for {date.date()}: "
            f"{len(score)} stocks scored"
        )

        return score
