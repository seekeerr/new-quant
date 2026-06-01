"""
Composite stock ranker.

Aggregates scores from all strategy modules using regime-dependent weights
and applies sector diversification constraints.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PortfolioConfig, setup_logging
from regime.regime_filter import RegimeState

logger = setup_logging("ranker")


def compute_composite_scores(
    strategy_scores: Dict[str, pd.Series],
    regime: RegimeState,
) -> pd.Series:
    """
    Compute composite stock scores from individual strategy scores
    using regime-dependent weights.

    Parameters
    ----------
    strategy_scores : dict
        Maps strategy name -> pd.Series (symbol -> percentile score 0-100).
    regime : RegimeState
        Current market regime with strategy weights.

    Returns
    -------
    pd.Series with composite scores (0-100), indexed by symbol.
    """
    weights = regime.strategy_weights

    # Collect all symbols across strategies
    all_symbols = set()
    for scores in strategy_scores.values():
        all_symbols.update(scores.index)

    # Build score matrix
    score_matrix = pd.DataFrame(index=sorted(all_symbols))
    for strategy_name, scores in strategy_scores.items():
        score_matrix[strategy_name] = scores

    # Compute weighted composite — only use strategies that actually scored each stock
    # (no NaN fill; compute per-stock weighted avg over available scores)
    composite = pd.Series(0.0, index=score_matrix.index)
    weight_sums = pd.Series(0.0, index=score_matrix.index)

    for strategy_name, weight in weights.items():
        if strategy_name in score_matrix.columns and weight > 0:
            mask = score_matrix[strategy_name].notna()
            composite[mask] += weight * score_matrix.loc[mask, strategy_name]
            weight_sums[mask] += weight

    # Normalise by actual weight sum per stock
    valid = weight_sums > 0
    composite[valid] /= weight_sums[valid]
    composite[~valid] = np.nan
    composite = composite.dropna()

    return composite.sort_values(ascending=False)


def select_top_stocks(
    composite_scores: pd.Series,
    n_stocks: int = 15,
    sector_map: Optional[Dict[str, str]] = None,
    max_sector_pct: float = 0.30,
    buffer: int = 10,
    existing_portfolio: Optional[List[str]] = None,
) -> List[str]:
    """
    Select top N stocks from composite scores with diversification constraints.

    Parameters
    ----------
    composite_scores : Series
        Ranked scores (higher = better), indexed by symbol.
    n_stocks : int
        Target number of stocks.
    sector_map : dict, optional
        Maps symbol -> sector for diversification. If None, no sector constraint.
    max_sector_pct : float
        Maximum weight in any single sector (as fraction).
    buffer : int
        Buffer zone: existing holdings must drop below rank (n_stocks + buffer)
        to be removed.
    existing_portfolio : list, optional
        Symbols currently held.

    Returns
    -------
    List of selected symbols.
    """
    ranked = composite_scores.sort_values(ascending=False)

    # Apply buffer for existing holdings
    if existing_portfolio:
        selected = []
        for sym in ranked.index:
            if len(selected) >= n_stocks:
                break

            # Check sector constraint
            if sector_map and not _check_sector_constraint(
                sym, selected, sector_map, max_sector_pct, n_stocks
            ):
                continue

            selected.append(sym)

        # Add existing holdings that haven't dropped below buffer
        for sym in existing_portfolio:
            if sym not in selected and sym in ranked.index:
                rank = list(ranked.index).index(sym)
                if rank < n_stocks + buffer:
                    # Check if we can add without exceeding sector limit
                    if sector_map and not _check_sector_constraint(
                        sym, selected, sector_map, max_sector_pct, n_stocks
                    ):
                        continue
                    selected.append(sym)

        # Trim to n_stocks if buffer additions pushed us over
        selected = selected[:n_stocks]
    else:
        # No existing portfolio — simple top-N with sector constraints
        selected = []
        for sym in ranked.index:
            if len(selected) >= n_stocks:
                break

            if sector_map and not _check_sector_constraint(
                sym, selected, sector_map, max_sector_pct, n_stocks
            ):
                continue

            selected.append(sym)

    logger.info(f"Selected {len(selected)} stocks from {len(ranked)} candidates")
    return selected


def _check_sector_constraint(
    symbol: str,
    current_selection: List[str],
    sector_map: Dict[str, str],
    max_sector_pct: float,
    n_stocks: int,
) -> bool:
    """Check if adding symbol would violate sector concentration limits."""
    sector = sector_map.get(symbol, "Unknown")
    if sector == "Unknown":
        return True  # allow if sector unknown

    # Count current stocks in this sector
    sector_count = sum(
        1 for s in current_selection
        if sector_map.get(s, "Unknown") == sector
    )

    max_in_sector = max(1, int(n_stocks * max_sector_pct))
    return sector_count < max_in_sector
