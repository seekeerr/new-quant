"""
Portfolio value analysis — actual rupee values for each config.
"""
import sys, io, time
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

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from config import SystemConfig, RESULTS_DIR
from data.downloader import download_all_stocks, build_price_panel, download_market_proxy
from run_pure_momentum import run_pure_momentum_backtest


def analyze_equity_curve(equity_curve: pd.Series, label: str, cost_type: str):
    """Extract detailed rupee-value stats from equity curve."""
    
    initial = equity_curve.iloc[0]
    final = equity_curve.iloc[-1]
    
    # Peak
    peak_value = equity_curve.max()
    peak_date = equity_curve.idxmax()
    
    # Drawdown series
    cummax = equity_curve.cummax()
    drawdown = (equity_curve - cummax) / cummax
    drawdown_rupee = equity_curve - cummax
    
    # Max drawdown point
    max_dd_idx = drawdown.idxmin()
    max_dd_pct = drawdown.loc[max_dd_idx]
    portfolio_at_max_dd = equity_curve.loc[max_dd_idx]
    peak_before_dd = cummax.loc[max_dd_idx]
    rupee_loss_at_dd = drawdown_rupee.loc[max_dd_idx]
    
    # Recovery time after max drawdown
    after_dd = equity_curve.loc[max_dd_idx:]
    recovery_mask = after_dd >= peak_before_dd
    if recovery_mask.any():
        recovery_date = after_dd[recovery_mask].index[0]
        recovery_days = (recovery_date - max_dd_idx).days
        recovered = True
    else:
        recovery_date = None
        recovery_days = (equity_curve.index[-1] - max_dd_idx).days
        recovered = False
    
    # Underwater curve stats
    is_underwater = drawdown < 0
    underwater_pct = is_underwater.sum() / len(drawdown) * 100
    
    # Longest underwater period
    dd_groups = (~is_underwater).cumsum()
    dd_durations = is_underwater.groupby(dd_groups).sum()
    longest_underwater = int(dd_durations.max()) if not dd_durations.empty else 0
    
    # Average drawdown when underwater
    avg_dd_when_underwater = drawdown[is_underwater].mean() if is_underwater.any() else 0
    avg_dd_rupee = drawdown_rupee[is_underwater].mean() if is_underwater.any() else 0
    
    # Median drawdown
    median_dd = drawdown[is_underwater].median() if is_underwater.any() else 0
    
    # Number of drawdown periods > 10%
    significant_dd_count = 0
    in_significant_dd = False
    for val in drawdown.values:
        if val < -0.10 and not in_significant_dd:
            significant_dd_count += 1
            in_significant_dd = True
        elif val >= 0:
            in_significant_dd = False
    
    return {
        "label": label,
        "cost_type": cost_type,
        "initial": initial,
        "final": final,
        "peak_value": peak_value,
        "peak_date": peak_date,
        "portfolio_at_max_dd": portfolio_at_max_dd,
        "peak_before_dd": peak_before_dd,
        "max_dd_date": max_dd_idx,
        "max_dd_pct": max_dd_pct,
        "rupee_loss_at_dd": rupee_loss_at_dd,
        "recovered": recovered,
        "recovery_date": recovery_date,
        "recovery_days": recovery_days,
        "underwater_pct": underwater_pct,
        "longest_underwater": longest_underwater,
        "avg_dd_when_underwater": avg_dd_when_underwater,
        "avg_dd_rupee": avg_dd_rupee,
        "median_dd": median_dd,
        "significant_dd_count": significant_dd_count,
    }


def print_config_analysis(stats: dict):
    """Print detailed analysis for one config."""
    s = stats
    
    print(f"\n{'─'*65}")
    print(f"  {s['label']} ({s['cost_type'].upper()})")
    print(f"{'─'*65}")
    
    print(f"\n  1. PORTFOLIO VALUES")
    print(f"     Initial Capital:              ₹{s['initial']:>12,.0f}")
    print(f"     Final Portfolio Value:         ₹{s['final']:>12,.0f}")
    print(f"     Total P&L:                    ₹{s['final']-s['initial']:>12,.0f}")
    print(f"     Return Multiple:              {s['final']/s['initial']:>12.1f}x")
    
    print(f"\n  2. PEAK")
    print(f"     Peak Portfolio Value:          ₹{s['peak_value']:>12,.0f}")
    print(f"     Date of Peak:                 {s['peak_date'].strftime('%d-%b-%Y'):>12}")
    
    print(f"\n  3. MAXIMUM DRAWDOWN")
    print(f"     Peak Before Crash:             ₹{s['peak_before_dd']:>12,.0f}")
    print(f"     Portfolio at Max Drawdown:      ₹{s['portfolio_at_max_dd']:>12,.0f}")
    print(f"     Rupee Loss from Peak:          ₹{s['rupee_loss_at_dd']:>12,.0f}")
    print(f"     Drawdown %:                   {s['max_dd_pct']:>12.1%}")
    print(f"     Date of Max Drawdown:          {s['max_dd_date'].strftime('%d-%b-%Y'):>12}")
    
    print(f"\n  4. RECOVERY")
    if s['recovered']:
        print(f"     Recovered:                    {'YES':>12}")
        print(f"     Recovery Date:                {s['recovery_date'].strftime('%d-%b-%Y'):>12}")
        print(f"     Recovery Time:                {s['recovery_days']:>9} days")
    else:
        print(f"     Recovered:                    {'NO':>12}")
        print(f"     Still underwater for:         {s['recovery_days']:>9} days")
    
    print(f"\n  5. UNDERWATER CURVE STATISTICS")
    print(f"     % of time underwater:          {s['underwater_pct']:>11.1f}%")
    print(f"     Longest underwater period:     {s['longest_underwater']:>9} days")
    print(f"     Avg drawdown (when underwater):{s['avg_dd_when_underwater']:>11.1%}")
    print(f"     Avg rupee loss (underwater):   ₹{s['avg_dd_rupee']:>12,.0f}")
    print(f"     Median drawdown:              {s['median_dd']:>11.1%}")
    print(f"     Drawdowns >10%:               {s['significant_dd_count']:>12}")


def main():
    config = SystemConfig()
    initial_capital = config.portfolio.initial_capital
    
    print("=" * 65)
    print("  PORTFOLIO VALUE ANALYSIS — ACTUAL RUPEE VALUES")
    print(f"  Capital: ₹{initial_capital:,.0f}")
    print("=" * 65)
    
    # Load data
    print("\nLoading data...")
    stock_data = download_all_stocks(use_cache=True)
    if not stock_data:
        print("ERROR: No data.")
        return
    
    close_panel = build_price_panel(stock_data, "Close")
    open_panel = build_price_panel(stock_data, "Open")
    high_panel = build_price_panel(stock_data, "High")
    low_panel = build_price_panel(stock_data, "Low")
    volume_panel = build_price_panel(stock_data, "Volume")
    
    print(f"Loaded {len(close_panel)} dates x {len(close_panel.columns)} stocks")
    
    param_grid = [
        (5, "monthly"),
        (5, "quarterly"),
        (10, "monthly"),
        (10, "quarterly"),
    ]
    
    all_stats = []
    
    for n_stocks, freq in param_grid:
        label = f"{n_stocks} stocks / {freq}"
        print(f"\nRunning: {label}...")
        
        for apply_costs, cost_type in [(False, "gross"), (True, "net")]:
            result = run_pure_momentum_backtest(
                close_panel, open_panel, high_panel, low_panel, volume_panel,
                n_stocks=n_stocks,
                rebalance_freq=freq,
                initial_capital=initial_capital,
                config=config,
                apply_costs=apply_costs,
            )
            
            if result["equity_curve"].empty:
                continue
            
            stats = analyze_equity_curve(
                result["equity_curve"], label, cost_type,
            )
            stats["total_costs"] = result["total_costs"]
            all_stats.append(stats)
    
    # Print all results
    print("\n" + "=" * 65)
    print("  DETAILED RESULTS")
    print("=" * 65)
    
    for stats in all_stats:
        print_config_analysis(stats)
    
    # ── Summary comparison table ──
    print(f"\n\n{'='*130}")
    print(f"{'SUMMARY: ACTUAL RUPEE VALUES':^130}")
    print(f"{'='*130}")
    print(f"{'Config':<22} {'Type':<6} {'Initial':>12} {'Final':>12} {'Peak':>12} "
          f"{'At Max DD':>12} {'Loss':>12} {'DD%':>8} {'Recovery':>10} {'Costs':>12}")
    print(f"{'-'*130}")
    
    for s in all_stats:
        recovery_str = f"{s['recovery_days']}d" if s['recovered'] else f"{s['recovery_days']}d*"
        print(f"{s['label']:<22} {s['cost_type'].upper():<6} "
              f"₹{s['initial']:>10,.0f} ₹{s['final']:>10,.0f} ₹{s['peak_value']:>10,.0f} "
              f"₹{s['portfolio_at_max_dd']:>10,.0f} ₹{s['rupee_loss_at_dd']:>10,.0f} "
              f"{s['max_dd_pct']:>7.1%} {recovery_str:>10} "
              f"₹{s.get('total_costs',0):>10,.0f}")
    
    print(f"{'='*130}")
    print("  * = not yet recovered")
    print()


if __name__ == "__main__":
    main()
