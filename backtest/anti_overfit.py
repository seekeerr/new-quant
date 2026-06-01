"""
Anti-overfitting measures for backtesting.

Implements walk-forward optimization and parameter stability testing
to ensure results are robust and not overfit.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import SystemConfig, BacktestConfig, setup_logging

logger = setup_logging("anti_overfit")


@dataclass
class WalkForwardWindow:
    """A single walk-forward train/test window."""
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def generate_walk_forward_windows(
    start_date: str,
    end_date: str,
    train_years: int = 3,
    test_years: int = 1,
    step_months: int = 6,
) -> List[WalkForwardWindow]:
    """
    Generate walk-forward optimisation windows.

    Example with train=3yr, test=1yr, step=6mo:
    Window 1: Train [2011-2014], Test [2014-2015]
    Window 2: Train [2011.5-2014.5], Test [2014.5-2015.5]
    ...

    Returns list of WalkForwardWindow objects.
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    windows = []
    current_train_start = start

    while True:
        train_end = current_train_start + pd.DateOffset(years=train_years)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(years=test_years) - pd.Timedelta(days=1)

        if test_end > end:
            break

        windows.append(WalkForwardWindow(
            train_start=current_train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
        ))

        current_train_start += pd.DateOffset(months=step_months)

    logger.info(f"Generated {len(windows)} walk-forward windows")
    return windows


def deflated_sharpe_ratio(
    sharpe: float,
    n_trials: int,
    backtest_length_years: float,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """
    Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

    Adjusts the observed Sharpe ratio for the number of strategy
    configurations tested (multiple testing bias).

    Parameters
    ----------
    sharpe : float
        Observed annualised Sharpe ratio.
    n_trials : int
        Number of strategy variants tested.
    backtest_length_years : float
        Length of backtest in years.
    skewness : float
        Skewness of returns.
    kurtosis : float
        Kurtosis of returns.

    Returns
    -------
    Probability that the true Sharpe ratio > 0.
    """
    from scipy import stats

    if n_trials <= 1:
        return 1.0

    # Expected max Sharpe under null (all strategies have Sharpe=0)
    e_max_sharpe = stats.norm.ppf(1 - 1 / n_trials)

    # Variance of Sharpe estimate
    n_obs = backtest_length_years * 252
    var_sharpe = (
        1 + 0.5 * sharpe ** 2 -
        skewness * sharpe +
        (kurtosis - 3) / 4 * sharpe ** 2
    ) / n_obs

    if var_sharpe <= 0:
        return 0.0

    # DSR = P(true_sharpe > 0)
    z = (sharpe - e_max_sharpe) / np.sqrt(var_sharpe)
    dsr = stats.norm.cdf(z)

    return dsr


def minimum_backtest_length(
    target_sharpe: float = 1.0,
    confidence: float = 0.95,
    n_trials: int = 1,
) -> float:
    """
    Minimum Backtest Length (MBL) in years.

    How many years of data are needed to achieve statistical significance
    for a given Sharpe ratio target.

    Based on Bailey & López de Prado (2012).
    """
    from scipy import stats

    z = stats.norm.ppf(confidence)

    if target_sharpe <= 0:
        return float("inf")

    # MBL in years (approximate)
    mbl = (z / target_sharpe) ** 2 / 252 * 252

    # Adjust for multiple testing
    if n_trials > 1:
        z_adj = stats.norm.ppf(1 - (1 - confidence) / n_trials)
        mbl = (z_adj / target_sharpe) ** 2

    return mbl


def parameter_stability_test(
    base_results: Dict[str, float],
    variation_pct: float = 0.20,
) -> Dict:
    """
    Test parameter stability by checking if performance degrades
    significantly with ±variation_pct parameter changes.

    This is a framework function — the actual parameter variation
    and re-running of backtests should be done by the caller.

    Parameters
    ----------
    base_results : dict
        Metrics from the base parameter set: {'sharpe': x, 'cagr': y, ...}
    variation_pct : float
        How much to vary parameters (±20% default).

    Returns
    -------
    Dict with stability assessment.
    """
    return {
        "base_sharpe": base_results.get("sharpe", 0),
        "variation_pct": variation_pct,
        "note": (
            "Run backtest with parameters varied by ±{:.0%}. "
            "If Sharpe drops by >50%, parameters are likely overfit."
        ).format(variation_pct),
    }
