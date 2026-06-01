"""
Compute rupee-value portfolio statistics for all 4 pure momentum configurations.

Outputs:
  1. Initial Capital
  2. Final Portfolio Value
  3. Peak Portfolio Value + Date
  4. Portfolio Value at Maximum Drawdown + Date
  5. Recovery Time After Maximum Drawdown
  6. Underwater Curve Statistics
"""

import sys
import io
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import logging
logging.basicConfig(level=logging.ERROR)
for name in logging.root.manager.loggerDict:
    logging.getLogger(name).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

from config import SystemConfig
from data.downloader import download_all_stocks, download_market_proxy, build_price_panel
from run_pure_momentum import run_pure_momentum_backtest


def compute_drawdown_curve(equity: pd.Series) -> pd.Series:
    running_max = equity.cummax()
    return (equity - running_max) / running_max


def analyze_max_drawdown(equity: pd.Series):
    """Find peak, trough, recovery for the maximum drawdown."""
    dd = compute_drawdown_curve(equity)
    trough_idx = dd.idxmin()
    max_dd_pct = dd[trough_idx]
    trough_value = equity[trough_idx]

    # Peak is the last all-time-high before the trough
    pre_trough = equity[:trough_idx]
    peak_idx = pre_trough.idxmax()
    peak_value = equity[peak_idx]

    # Recovery: first date after trough where value >= peak_value
    post_trough = equity[trough_idx:]
    recovered = post_trough[post_trough >= peak_value]
    if recovered.empty:
        recovery_date = None
        recovery_days = None
    else:
        recovery_date = recovered.index[0]
        recovery_days = (recovery_date - trough_idx).days

    # Trough-to-recovery calendar days
    drawdown_duration_days = (trough_idx - peak_idx).days

    return {
        "peak_date": peak_idx,
        "peak_value": peak_value,
        "trough_date": trough_idx,
        "trough_value": trough_value,
        "max_dd_pct": max_dd_pct,
        "recovery_date": recovery_date,
        "recovery_days": recovery_days,
        "drawdown_duration_days": drawdown_duration_days,
    }


def underwater_curve_stats(equity: pd.Series):
    """Statistics on the underwater (drawdown) curve."""
    dd = compute_drawdown_curve(equity)
    underwater = dd[dd < 0]

    if underwater.empty:
        return {}

    # Find all drawdown periods (sequences of consecutive days below 0)
    in_dd = (dd < 0).astype(int)
    # Group consecutive days
    groups = (in_dd.diff() != 0).cumsum()
    dd_groups = dd[in_dd == 1].groupby(groups[in_dd == 1])

    period_depths = []
    period_lengths = []
    for _, grp in dd_groups:
        period_depths.append(grp.min())
        period_lengths.append(len(grp))

    avg_depth_pct = np.mean(period_depths) if period_depths else 0
    median_depth_pct = np.median(period_depths) if period_depths else 0
    avg_length_days = np.mean(period_lengths) if period_lengths else 0
    num_periods = len(period_depths)
    pct_time_underwater = len(underwater) / len(dd) * 100

    return {
        "pct_time_underwater": pct_time_underwater,
        "num_dd_periods": num_periods,
        "avg_depth_pct": avg_depth_pct,
        "median_depth_pct": median_depth_pct,
        "avg_duration_days": avg_length_days,
        "worst_5_drawdowns": sorted(period_depths)[:5],
    }


def print_config_report(label, equity, initial_capital):
    print(f"\n{'='*65}")
    print(f"  CONFIG: {label}")
    print(f"{'='*65}")

    # 1. Initial Capital
    print(f"\n  1. Initial Capital:          Rs {initial_capital:>14,.2f}")

    # 2. Final Portfolio Value
    final_value = equity.iloc[-1]
    total_return_pct = (final_value / initial_capital - 1) * 100
    print(f"  2. Final Portfolio Value:    Rs {final_value:>14,.2f}  ({total_return_pct:+.1f}%)")

    # 3 & 4. Peak and Max Drawdown
    all_time_peak_value = equity.max()
    all_time_peak_date = equity.idxmax()
    print(f"  3. Peak Portfolio Value:     Rs {all_time_peak_value:>14,.2f}  ({all_time_peak_date.date()})")

    mdd = analyze_max_drawdown(equity)
    print(f"\n  4. Maximum Drawdown:")
    print(f"     Peak before drawdown:     Rs {mdd['peak_value']:>14,.2f}  ({mdd['peak_date'].date()})")
    print(f"     Portfolio at Trough:      Rs {mdd['trough_value']:>14,.2f}  ({mdd['trough_date'].date()})")
    print(f"     Drawdown Amount:          Rs {mdd['peak_value'] - mdd['trough_value']:>14,.2f}  ({mdd['max_dd_pct']:.1%})")
    print(f"     Peak-to-Trough Duration:  {mdd['drawdown_duration_days']} calendar days")

    # 5. Recovery Time
    print(f"\n  5. Recovery After Max Drawdown:")
    if mdd['recovery_date']:
        print(f"     Recovery Date:            {mdd['recovery_date'].date()}")
        print(f"     Trough-to-Recovery:       {mdd['recovery_days']} calendar days")
        total_dd_cycle = mdd['drawdown_duration_days'] + mdd['recovery_days']
        print(f"     Full DD Cycle (P->T->R):  {total_dd_cycle} calendar days")
    else:
        print(f"     *** NOT YET RECOVERED as of backtest end ***")
        days_since_trough = (equity.index[-1] - mdd['trough_date']).days
        current_from_trough = (equity.iloc[-1] / mdd['trough_value'] - 1) * 100
        print(f"     Days since trough:        {days_since_trough} calendar days")
        print(f"     Recovery progress:        {current_from_trough:+.1f}% from trough")
        still_needed = (mdd['peak_value'] / equity.iloc[-1] - 1) * 100
        print(f"     Still needs:              +{still_needed:.1f}% to reach prior peak")

    # 6. Underwater Curve Statistics
    uw = underwater_curve_stats(equity)
    if uw:
        print(f"\n  6. Underwater Curve Statistics:")
        print(f"     % Time Spent Underwater:  {uw['pct_time_underwater']:.1f}%")
        print(f"     # Drawdown Periods:       {uw['num_dd_periods']}")
        print(f"     Avg Depth:                {uw['avg_depth_pct']:.2%}")
        print(f"     Median Depth:             {uw['median_depth_pct']:.2%}")
        print(f"     Avg Duration (days):      {uw['avg_duration_days']:.0f} days")
        if uw['worst_5_drawdowns']:
            worst = uw['worst_5_drawdowns']
            print(f"     5 Worst Drawdowns:")
            for i, d in enumerate(worst, 1):
                dd_amount = mdd['peak_value'] * abs(d)  # rough proxy
                print(f"       #{i}: {d:.2%}")


def main():
    config = SystemConfig()
    initial_capital = config.portfolio.initial_capital

    print("=" * 65)
    print("  PURE MOMENTUM — RUPEE VALUE PORTFOLIO STATISTICS")
    print(f"  Initial Capital: Rs {initial_capital:,.0f}")
    print(f"  Period: {config.backtest.start_date} to {config.backtest.end_date}")
    print("=" * 65)

    print("\nLoading data from cache...")
    stock_data = download_all_stocks(use_cache=True)
    if not stock_data:
        print("ERROR: No stock data. Run 'python main.py download' first.")
        return

    close_panel  = build_price_panel(stock_data, "Close")
    open_panel   = build_price_panel(stock_data, "Open")
    high_panel   = build_price_panel(stock_data, "High")
    low_panel    = build_price_panel(stock_data, "Low")
    volume_panel = build_price_panel(stock_data, "Volume")
    print(f"Loaded {len(close_panel)} dates x {len(close_panel.columns)} stocks")

    param_grid = [
        (5,  "monthly"),
        (5,  "quarterly"),
        (10, "monthly"),
        (10, "quarterly"),
    ]

    for n_stocks, freq in param_grid:
        label = f"{n_stocks} Stocks / {freq.capitalize()} (NET)"
        print(f"\nRunning {label}...")

        result = run_pure_momentum_backtest(
            close_panel, open_panel, high_panel, low_panel, volume_panel,
            n_stocks=n_stocks,
            rebalance_freq=freq,
            initial_capital=initial_capital,
            config=config,
            apply_costs=True,
        )

        if result["equity_curve"].empty:
            print(f"  No results for {label}")
            continue

        equity = result["equity_curve"]
        print_config_report(label, equity, initial_capital)

    print(f"\n{'='*65}\n")


if __name__ == "__main__":
    main()
