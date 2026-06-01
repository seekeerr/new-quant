"""
Portfolio constructor: weight optimization and position sizing.

Supports equal weight, inverse volatility, and risk parity methods.
Handles constraints for small capital (₹1L) including whole-share rounding.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PortfolioConfig, CostConfig, setup_logging
from utils.indicators import rolling_volatility, atr_percent
from utils.helpers import round_to_lot_size

logger = setup_logging("constructor")


@dataclass
class PortfolioTarget:
    """Target portfolio with weights and share counts."""
    date: pd.Timestamp
    weights: Dict[str, float]          # symbol -> target weight (0 to 1)
    shares: Dict[str, int]             # symbol -> number of shares
    values: Dict[str, float]           # symbol -> target value in ₹
    total_invested: float = 0.0        # total allocated ₹
    cash: float = 0.0                  # remaining cash
    capital_allocation: float = 1.0    # regime-based (0 to 1)


def compute_weights(
    selected_stocks: List[str],
    close_panel: pd.DataFrame,
    date: pd.Timestamp,
    method: str = "inverse_volatility",
    config: Optional[PortfolioConfig] = None,
) -> Dict[str, float]:
    """
    Compute portfolio weights for selected stocks.

    Parameters
    ----------
    selected_stocks : list
        Symbols to include.
    close_panel : DataFrame
        Wide-format close prices.
    date : Timestamp
        Point-in-time date.
    method : str
        'equal', 'inverse_volatility', or 'risk_parity'.
    config : PortfolioConfig, optional

    Returns
    -------
    Dict mapping symbol -> weight (sums to 1.0).
    """
    config = config or PortfolioConfig()

    if not selected_stocks:
        return {}

    if method == "equal":
        return _equal_weight(selected_stocks)
    elif method == "inverse_volatility":
        return _inverse_volatility_weight(
            selected_stocks, close_panel, date, config
        )
    elif method == "risk_parity":
        return _risk_parity_weight(
            selected_stocks, close_panel, date, config
        )
    else:
        logger.warning(f"Unknown method '{method}', falling back to equal weight")
        return _equal_weight(selected_stocks)


def _equal_weight(stocks: List[str]) -> Dict[str, float]:
    """Equal weight allocation."""
    n = len(stocks)
    if n == 0:
        return {}
    w = 1.0 / n
    return {s: w for s in stocks}


def _inverse_volatility_weight(
    stocks: List[str],
    close_panel: pd.DataFrame,
    date: pd.Timestamp,
    config: PortfolioConfig,
) -> Dict[str, float]:
    """
    Inverse volatility weighting: lower-vol stocks get higher weight.
    weight_i ∝ 1 / σ_i
    """
    mask = close_panel.index <= date
    cols = [s for s in stocks if s in close_panel.columns]
    prices = close_panel.loc[mask, cols].tail(63)  # 3-month lookback

    if len(prices) < 20:
        return _equal_weight(stocks)

    returns = prices.pct_change().dropna()
    vol = returns.std() * np.sqrt(252)  # annualised vol
    vol = vol.replace(0, np.nan).dropna()

    if vol.empty:
        return _equal_weight(stocks)

    inv_vol = 1.0 / vol
    raw_weights = inv_vol / inv_vol.sum()

    # Apply max weight constraint
    weights = _apply_weight_constraints(raw_weights, config)

    return weights


def _risk_parity_weight(
    stocks: List[str],
    close_panel: pd.DataFrame,
    date: pd.Timestamp,
    config: PortfolioConfig,
) -> Dict[str, float]:
    """
    Risk parity: each stock contributes equally to portfolio variance.
    Simplified version using inverse volatility as approximation
    (true risk parity requires covariance matrix optimisation).
    """
    # Use inverse volatility as a reasonable approximation
    # True risk parity via scipy.optimize is more complex and
    # the difference is small for 5-15 stocks
    return _inverse_volatility_weight(stocks, close_panel, date, config)


def _apply_weight_constraints(
    raw_weights: pd.Series,
    config: PortfolioConfig,
) -> Dict[str, float]:
    """
    Apply weight constraints:
    - Max single stock weight
    - Min stock weight
    - Re-normalise after clipping
    """
    weights = raw_weights.copy()

    # Cap at max weight
    weights = weights.clip(upper=config.max_single_stock_weight)

    # Floor at min weight (remove if below)
    weights = weights[weights >= config.min_stock_weight]

    # Re-normalise
    if weights.sum() > 0:
        weights = weights / weights.sum()

    return weights.to_dict()


def construct_portfolio(
    selected_stocks: List[str],
    close_panel: pd.DataFrame,
    date: pd.Timestamp,
    capital: float = 100_000.0,
    capital_allocation: float = 1.0,
    config: Optional[PortfolioConfig] = None,
    cost_config: Optional[CostConfig] = None,
) -> PortfolioTarget:
    """
    Full portfolio construction: weights → shares → values.

    Handles small capital by rounding to whole shares and
    accounting for minimum viable position sizes.

    Parameters
    ----------
    selected_stocks : list
        Stocks to include.
    close_panel : DataFrame
        Close prices.
    date : Timestamp
    capital : float
        Total available capital.
    capital_allocation : float
        Fraction of capital to deploy (from regime filter).
    config : PortfolioConfig
    cost_config : CostConfig

    Returns
    -------
    PortfolioTarget with weights, shares, and values.
    """
    config = config or PortfolioConfig()
    cost_config = cost_config or CostConfig()

    # Compute target weights
    weights = compute_weights(
        selected_stocks, close_panel, date,
        config.weighting_method, config,
    )

    if not weights:
        return PortfolioTarget(
            date=date, weights={}, shares={}, values={},
            cash=capital, capital_allocation=capital_allocation,
        )

    # Allocable capital (after regime adjustment)
    allocable = capital * capital_allocation

    # Get latest prices
    mask = close_panel.index <= date
    latest_prices = close_panel.loc[mask].iloc[-1]

    # Compute share counts (must be whole numbers for Indian equities)
    shares = {}
    values = {}
    total_invested = 0.0

    for sym, weight in weights.items():
        target_value = allocable * weight
        price = latest_prices.get(sym, np.nan)

        if np.isnan(price) or price <= 0:
            continue

        # Round down to whole shares
        n_shares = round_to_lot_size(target_value / price, lot_size=1)

        # Check minimum viable position (must cover at least the fixed costs)
        min_position_value = cost_config.brokerage_per_order * 10  # ₹200 minimum
        if n_shares * price < min_position_value:
            # Position too small to be worth the transaction costs
            logger.debug(
                f"Skipping {sym}: position ₹{n_shares * price:.0f} "
                f"too small (min ₹{min_position_value:.0f})"
            )
            continue

        if n_shares > 0:
            shares[sym] = n_shares
            actual_value = n_shares * price
            values[sym] = actual_value
            total_invested += actual_value

    # Recalculate actual weights
    actual_weights = {}
    for sym, val in values.items():
        actual_weights[sym] = val / capital if capital > 0 else 0

    cash = capital - total_invested

    target = PortfolioTarget(
        date=date,
        weights=actual_weights,
        shares=shares,
        values=values,
        total_invested=total_invested,
        cash=cash,
        capital_allocation=capital_allocation,
    )

    logger.info(
        f"Portfolio on {date.date()}: {len(shares)} stocks, "
        f"₹{total_invested:,.0f} invested, ₹{cash:,.0f} cash "
        f"({capital_allocation:.0%} allocation)"
    )

    return target
