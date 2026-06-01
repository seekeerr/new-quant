"""
Performance metrics for backtesting.

Computes CAGR, Sharpe, Sortino, max drawdown, Calmar, win rate,
profit factor, turnover, alpha, beta, information ratio, and more.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import setup_logging

logger = setup_logging("metrics")


@dataclass
class PerformanceMetrics:
    """Complete performance metrics for a backtest."""
    # Returns
    total_return: float = 0.0
    cagr: float = 0.0

    # Risk-adjusted
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Risk
    annualised_volatility: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration_days: int = 0

    # Trade-level
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_win_loss_ratio: float = 0.0
    total_trades: int = 0

    # Benchmark comparison
    beta: float = 0.0
    alpha: float = 0.0
    information_ratio: float = 0.0
    tracking_error: float = 0.0

    # Portfolio
    avg_monthly_turnover: float = 0.0
    total_costs: float = 0.0
    cost_drag: float = 0.0

    # Distribution
    skewness: float = 0.0
    kurtosis: float = 0.0
    best_month: float = 0.0
    worst_month: float = 0.0

    # Period
    start_date: str = ""
    end_date: str = ""
    trading_days: int = 0


def compute_metrics(
    equity_curve: pd.Series,
    returns: Optional[pd.Series] = None,
    benchmark_returns: Optional[pd.Series] = None,
    risk_free_rate: float = 0.065,
    trades: Optional[list] = None,
    total_costs: float = 0.0,
    initial_capital: float = 100_000.0,
) -> PerformanceMetrics:
    """
    Compute comprehensive performance metrics.

    Parameters
    ----------
    equity_curve : Series
        Daily portfolio values indexed by date.
    returns : Series, optional
        Daily returns. Computed from equity_curve if not provided.
    benchmark_returns : Series, optional
        Benchmark daily returns for relative metrics.
    risk_free_rate : float
        Annual risk-free rate (6.5% for India).
    trades : list, optional
        List of trade dicts with 'value', 'side', 'cost' keys.
    total_costs : float
        Total transaction costs.
    initial_capital : float
    """
    metrics = PerformanceMetrics()

    if equity_curve.empty:
        return metrics

    # Ensure clean data
    equity_curve = equity_curve.dropna()
    if len(equity_curve) < 2:
        return metrics

    # Compute returns if not provided
    if returns is None:
        returns = equity_curve.pct_change().fillna(0)

    # ── Basic return metrics ──
    start_val = equity_curve.iloc[0]
    end_val = equity_curve.iloc[-1]
    metrics.total_return = (end_val / start_val) - 1

    n_days = (equity_curve.index[-1] - equity_curve.index[0]).days
    n_years = n_days / 365.25
    metrics.trading_days = len(equity_curve)
    metrics.start_date = str(equity_curve.index[0].date())
    metrics.end_date = str(equity_curve.index[-1].date())

    if n_years > 0:
        metrics.cagr = (end_val / start_val) ** (1 / n_years) - 1
    else:
        metrics.cagr = 0.0

    # ── Volatility ──
    daily_rf = (1 + risk_free_rate) ** (1 / 252) - 1
    excess_returns = returns - daily_rf
    metrics.annualised_volatility = returns.std() * np.sqrt(252)

    # ── Sharpe Ratio ──
    if metrics.annualised_volatility > 0:
        metrics.sharpe_ratio = (
            (metrics.cagr - risk_free_rate) / metrics.annualised_volatility
        )
    else:
        metrics.sharpe_ratio = 0.0

    # ── Sortino Ratio ──
    downside_returns = returns[returns < daily_rf] - daily_rf
    downside_vol = downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0
    if downside_vol > 0:
        metrics.sortino_ratio = (metrics.cagr - risk_free_rate) / downside_vol
    else:
        metrics.sortino_ratio = 0.0

    # ── Drawdown analysis ──
    cummax = equity_curve.cummax()
    drawdown = (equity_curve - cummax) / cummax
    metrics.max_drawdown = drawdown.min()

    # Drawdown duration
    is_drawdown = drawdown < 0
    if is_drawdown.any():
        dd_groups = (~is_drawdown).cumsum()
        dd_durations = is_drawdown.groupby(dd_groups).sum()
        metrics.max_drawdown_duration_days = int(dd_durations.max())
    else:
        metrics.max_drawdown_duration_days = 0

    # ── Calmar Ratio ──
    if metrics.max_drawdown < 0:
        metrics.calmar_ratio = metrics.cagr / abs(metrics.max_drawdown)
    else:
        metrics.calmar_ratio = 0.0

    # ── Distribution ──
    metrics.skewness = float(returns.skew())
    metrics.kurtosis = float(returns.kurtosis())

    # Monthly returns
    monthly = equity_curve.resample("ME").last().pct_change().dropna()
    if not monthly.empty:
        metrics.best_month = float(monthly.max())
        metrics.worst_month = float(monthly.min())

    # ── Trade-level metrics ──
    if trades:
        # Compute P&L per completed trade
        trade_pnls = _compute_trade_pnl(trades)
        if trade_pnls:
            winners = [p for p in trade_pnls if p > 0]
            losers = [p for p in trade_pnls if p <= 0]

            metrics.total_trades = len(trade_pnls)
            metrics.win_rate = len(winners) / len(trade_pnls) if trade_pnls else 0

            if winners:
                metrics.avg_win = np.mean(winners)
            if losers:
                metrics.avg_loss = abs(np.mean(losers))

            if metrics.avg_loss > 0:
                metrics.avg_win_loss_ratio = metrics.avg_win / metrics.avg_loss

            gross_profit = sum(winners) if winners else 0
            gross_loss = abs(sum(losers)) if losers else 0
            if gross_loss > 0:
                metrics.profit_factor = gross_profit / gross_loss

    # ── Costs ──
    metrics.total_costs = total_costs
    if start_val > 0:
        metrics.cost_drag = total_costs / start_val  # costs as % of initial capital

    # ── Benchmark comparison ──
    if benchmark_returns is not None and not benchmark_returns.empty:
        # Align dates
        common = returns.index.intersection(benchmark_returns.index)
        if len(common) > 20:
            strat = returns.reindex(common).fillna(0)
            bench = benchmark_returns.reindex(common).fillna(0)

            # Beta
            cov = np.cov(strat, bench)
            bench_var = np.var(bench)
            if bench_var > 0:
                metrics.beta = cov[0, 1] / bench_var

            # Alpha (Jensen's)
            bench_annual_return = (1 + bench).prod() ** (252 / len(bench)) - 1
            metrics.alpha = metrics.cagr - (
                risk_free_rate + metrics.beta * (bench_annual_return - risk_free_rate)
            )

            # Tracking error and Information Ratio
            active_returns = strat - bench
            metrics.tracking_error = active_returns.std() * np.sqrt(252)
            if metrics.tracking_error > 0:
                metrics.information_ratio = (
                    active_returns.mean() * 252 / metrics.tracking_error
                )

    return metrics


def _compute_trade_pnl(trades: list) -> list:
    """
    Compute P&L for round-trip trades from trade history.

    Matches BUY and SELL trades for the same symbol.
    """
    # Build entry/exit pairs
    positions = {}  # symbol -> list of (price, shares)
    pnls = []

    for trade in sorted(trades, key=lambda t: t.get("date", "")):
        sym = trade["symbol"]
        side = trade["side"]
        shares = trade["shares"]
        price = trade["price"]
        cost = trade.get("cost", 0)

        if side == "BUY":
            if sym not in positions:
                positions[sym] = []
            positions[sym].append({"price": price, "shares": shares, "cost": cost})

        elif side == "SELL" and sym in positions:
            remaining = shares
            while remaining > 0 and positions.get(sym):
                entry = positions[sym][0]
                sell_shares = min(remaining, entry["shares"])

                pnl = (price - entry["price"]) * sell_shares - cost - entry["cost"]
                pnls.append(pnl)

                entry["shares"] -= sell_shares
                remaining -= sell_shares

                if entry["shares"] <= 0:
                    positions[sym].pop(0)

    return pnls


def print_metrics(metrics: PerformanceMetrics, title: str = "Performance Summary"):
    """Print a formatted metrics table."""
    print(f"\n{'='*60}")
    print(f"{title:^60}")
    print(f"{'='*60}")
    print(f"Period: {metrics.start_date} to {metrics.end_date} ({metrics.trading_days} days)")
    print(f"{'-'*60}")

    print(f"{'RETURNS':}")
    print(f"  Total Return:          {metrics.total_return:>10.2%}")
    print(f"  CAGR:                  {metrics.cagr:>10.2%}")

    print(f"\n{'RISK-ADJUSTED':}")
    print(f"  Sharpe Ratio:          {metrics.sharpe_ratio:>10.2f}")
    print(f"  Sortino Ratio:         {metrics.sortino_ratio:>10.2f}")
    print(f"  Calmar Ratio:          {metrics.calmar_ratio:>10.2f}")

    print(f"\n{'RISK':}")
    print(f"  Annual Volatility:     {metrics.annualised_volatility:>10.2%}")
    print(f"  Max Drawdown:          {metrics.max_drawdown:>10.2%}")
    print(f"  Max DD Duration:       {metrics.max_drawdown_duration_days:>10d} days")

    if metrics.total_trades > 0:
        print(f"\n{'TRADES':}")
        print(f"  Total Trades:          {metrics.total_trades:>10d}")
        print(f"  Win Rate:              {metrics.win_rate:>10.2%}")
        print(f"  Profit Factor:         {metrics.profit_factor:>10.2f}")
        print(f"  Avg Win/Loss:          {metrics.avg_win_loss_ratio:>10.2f}x")

    if metrics.beta != 0:
        print(f"\n{'BENCHMARK':}")
        print(f"  Beta:                  {metrics.beta:>10.2f}")
        print(f"  Alpha (annual):        {metrics.alpha:>10.2%}")
        print(f"  Information Ratio:     {metrics.information_ratio:>10.2f}")
        print(f"  Tracking Error:        {metrics.tracking_error:>10.2%}")

    print(f"\n{'COSTS':}")
    print(f"  Total Costs:          ₹{metrics.total_costs:>9,.0f}")
    print(f"  Cost Drag:             {metrics.cost_drag:>10.2%}")

    print(f"\n{'DISTRIBUTION':}")
    print(f"  Skewness:              {metrics.skewness:>10.2f}")
    print(f"  Kurtosis:              {metrics.kurtosis:>10.2f}")
    print(f"  Best Month:            {metrics.best_month:>10.2%}")
    print(f"  Worst Month:           {metrics.worst_month:>10.2%}")

    print(f"{'='*60}\n")


def compute_rolling_metrics(
    returns: pd.Series,
    window: int = 252,
    risk_free_rate: float = 0.065,
) -> pd.DataFrame:
    """
    Compute rolling performance metrics.

    Returns DataFrame with columns:
    - rolling_return: annualised rolling return
    - rolling_sharpe: rolling Sharpe ratio
    - rolling_vol: rolling annualised volatility
    - rolling_drawdown: rolling drawdown from peak
    """
    daily_rf = (1 + risk_free_rate) ** (1 / 252) - 1

    rolling_ret = returns.rolling(window).mean() * 252
    rolling_vol = returns.rolling(window).std() * np.sqrt(252)
    rolling_sharpe = (rolling_ret - risk_free_rate) / rolling_vol.replace(0, np.nan)

    # Rolling drawdown
    equity = (1 + returns).cumprod()
    rolling_max = equity.rolling(window, min_periods=1).max()
    rolling_dd = (equity - rolling_max) / rolling_max

    return pd.DataFrame({
        "rolling_return": rolling_ret,
        "rolling_sharpe": rolling_sharpe,
        "rolling_volatility": rolling_vol,
        "rolling_drawdown": rolling_dd,
    }, index=returns.index)
