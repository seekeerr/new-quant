"""
Universe builder: constructs the point-in-time tradeable universe
for each rebalancing date.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import UniverseConfig, setup_logging
from universe.filters import apply_all_filters, classify_liquidity_tier, FilterResult
from utils.helpers import get_rebalance_dates

logger = setup_logging("universe_builder")


@dataclass
class UniverseSnapshot:
    """Tradeable universe at a specific point in time."""
    date: pd.Timestamp
    symbols: List[str]
    liquidity_tiers: Dict[str, int]  # symbol -> tier (1, 2, 3)
    filter_result: FilterResult


class UniverseBuilder:
    """
    Builds the tradeable universe for each rebalancing date.

    Key principle: point-in-time only. For date T, only data
    up to and including T is used. No look-ahead bias.
    """

    def __init__(
        self,
        close_panel: pd.DataFrame,
        high_panel: pd.DataFrame,
        low_panel: pd.DataFrame,
        volume_panel: pd.DataFrame,
        config: Optional[UniverseConfig] = None,
    ):
        """
        Parameters
        ----------
        close_panel, high_panel, low_panel, volume_panel : DataFrame
            Wide-format DataFrames (dates × symbols).
        config : UniverseConfig, optional
        """
        self.close = close_panel
        self.high = high_panel
        self.low = low_panel
        self.volume = volume_panel
        self.config = config or UniverseConfig()

        # Cache for built universes
        self._cache: Dict[pd.Timestamp, UniverseSnapshot] = {}

    def build_universe(self, date: pd.Timestamp) -> UniverseSnapshot:
        """
        Build the tradeable universe for a specific date.

        Uses cached result if available.
        """
        date = pd.Timestamp(date)

        if date in self._cache:
            return self._cache[date]

        # Apply all filters
        filter_result = apply_all_filters(
            self.close, self.high, self.low, self.volume,
            date, self.config,
        )

        # Classify liquidity tiers
        tiers = classify_liquidity_tier(
            self.close, self.volume, date,
            filter_result.passed_symbols,
        )

        snapshot = UniverseSnapshot(
            date=date,
            symbols=filter_result.passed_symbols,
            liquidity_tiers=tiers,
            filter_result=filter_result,
        )

        self._cache[date] = snapshot
        return snapshot

    def build_all_universes(
        self,
        rebalance_dates: pd.DatetimeIndex,
    ) -> Dict[pd.Timestamp, UniverseSnapshot]:
        """
        Build universes for all rebalance dates.

        Returns dict mapping date -> UniverseSnapshot.
        """
        universes = {}
        for date in rebalance_dates:
            # Ensure the date is within our data range
            if date < self.close.index.min() or date > self.close.index.max():
                continue
            # Find the closest actual trading date <= rebalance date
            actual_dates = self.close.index[self.close.index <= date]
            if actual_dates.empty:
                continue
            actual_date = actual_dates[-1]

            universes[actual_date] = self.build_universe(actual_date)

        logger.info(
            f"Built {len(universes)} universe snapshots. "
            f"Avg size: {np.mean([len(u.symbols) for u in universes.values()]):.0f} stocks"
        )
        return universes

    def get_universe_history(
        self,
        universes: Dict[pd.Timestamp, UniverseSnapshot],
    ) -> pd.DataFrame:
        """
        Create a summary DataFrame of universe composition over time.

        Returns DataFrame with columns: date, universe_size, tier1, tier2, tier3.
        """
        records = []
        for date, snapshot in sorted(universes.items()):
            tier_counts = {1: 0, 2: 0, 3: 0}
            for tier in snapshot.liquidity_tiers.values():
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

            records.append({
                "date": date,
                "universe_size": len(snapshot.symbols),
                "tier1_count": tier_counts[1],
                "tier2_count": tier_counts[2],
                "tier3_count": tier_counts[3],
            })

        return pd.DataFrame(records).set_index("date")
