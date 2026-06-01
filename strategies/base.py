"""
Abstract base class for all strategy modules.

Every strategy must implement `compute_scores()` which returns
a cross-sectional percentile rank (0-100) for each stock.
"""

import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, List

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import setup_logging
from utils.helpers import cross_sectional_percentile_rank

logger = setup_logging("strategy_base")


class BaseStrategy(ABC):
    """
    Abstract base strategy.

    All strategy modules inherit from this and implement
    compute_raw_scores() which returns raw signal values.
    The base class handles percentile ranking.
    """

    def __init__(self, name: str):
        self.name = name
        self.logger = setup_logging(f"strategy.{name}")

    @abstractmethod
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
        Compute raw strategy scores for each stock in the universe.

        Parameters
        ----------
        close, high, low, volume : DataFrame
            Wide-format panels (dates × symbols), data up to `date`.
        date : Timestamp
            Signal date (point-in-time).
        universe : list of str
            Symbols in the tradeable universe for this date.

        Returns
        -------
        pd.Series with symbol index and raw score values.
        Higher values = stronger signal.
        """
        pass

    def compute_scores(
        self,
        close: pd.DataFrame,
        high: pd.DataFrame,
        low: pd.DataFrame,
        volume: pd.DataFrame,
        date: pd.Timestamp,
        universe: List[str],
    ) -> pd.Series:
        """
        Compute percentile-ranked strategy scores (0-100).

        Calls compute_raw_scores() and then ranks cross-sectionally.
        """
        raw = self.compute_raw_scores(close, high, low, volume, date, universe)

        if raw.empty:
            return pd.Series(dtype=float)

        # Drop NaN before ranking
        raw = raw.dropna()

        if len(raw) < 2:
            return raw * 0 + 50  # single stock gets neutral rank

        # Percentile rank: 0 = worst, 100 = best
        ranked = raw.rank(pct=True, method="average") * 100
        return ranked

    def __repr__(self):
        return f"{self.__class__.__name__}(name='{self.name}')"
