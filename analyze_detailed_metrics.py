"""
Detailed Portfolio Metrics Analysis — Rupee Values

For each pure momentum configuration, computes:
1. Initial Capital
2. Final Portfolio Value
3. Peak Portfolio Value & Date
4. Portfolio Value at Maximum Drawdown & Date
5. Recovery Time After Maximum Drawdown
6. Underwater Curve Statistics
"""

import sys
import io
import warnings
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from datetime import timedelta

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Fix Windows console encoding
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
from tqdm import tqdm

from config import SystemConfig, RESULTS_DIR, CACHE_DIR
from data.downloader import download_all_stocks, download_market_proxy, build_price_panel
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from run_pure_momentum import run_pure_momentum_backtest


# ─────────────────────────────────────────────────────────────────────
# DETAILED METRICS COMPUTATION
# ─────────────────────────────────────────────────────────────────────

@dataclass
class DetailedMetrics:
    config_name: str
    cost_type: str  # GROSS or NET
    
    # 1. Initial Capital
    initial_capital: float
    
    # 2. Final Portfolio Value
    final_value: float
    final_date: str
    
    # 3. Peak Portfolio Value
    peak_value: float
    peak_date: str
    
    # 4. Maximum Drawdown details
    max_dd_pct: float
    dd_trough_value: float
    dd_trough_date: str
    dd_peak_value: float       # peak BEFORE the max drawdown
    dd_peak_date: str          # date of that peak
    dd_rupee_loss: float       # peak - trough in ₹
    
    # 5. Recovery
    recovery_date: Optional[str]
    recovery_days: Optional[int]
    recovered: bool
    
    # 6. Underwater stats
    total_days: int
    days_underwater: int
    pct_time_underwater: float
    avg_underwater_depth_pct: float
    avg_underwater_depth_rupees: float
    median_underwater_depth_pct: float
    longest_underwater_days: int
    longest_underwater_start: str
    longest_underwater_end: str
    num_drawdown_episodes: int  # distinct drawdown periods


def compute_detailed_metrics(
    equity_curve: pd.Series,
    initial_capital: float,
    config_name: str,
    cost_type: str,
) -> DetailedMetrics:
    """Compute all detailed metrics from an equity curve."""
    
    eq = equity_curve.copy()
    eq.index = pd.to_datetime(eq.index)
    
    # ── 1. Initial Capital ──
    # (passed in)
    
    # ── 2. Final Portfolio Value ──
    final_value = eq.iloc[-1]
    final_date = eq.index[-1].strftime("%Y-%m-%d")
    
    # ── 3. Peak Portfolio Value ──
    cummax = eq.cummax()
    peak_idx = eq.idxmax()
    peak_value = eq[peak_idx]
    peak_date = peak_idx.strftime("%Y-%m-%d")
    
    # ── 4. Maximum Drawdown ──
    drawdown = (eq - cummax) / cummax
    dd_trough_idx = drawdown.idxmin()
    max_dd_pct = drawdown[dd_trough_idx]
    dd_trough_value = eq[dd_trough_idx]
    dd_trough_date = dd_trough_idx.strftime("%Y-%m-%d")
    
    # Peak BEFORE the trough (the peak that starts this drawdown)
    pre_trough_cummax = cummax.loc[:dd_trough_idx]
    dd_peak_value = pre_trough_cummax.iloc[-1]
    # Find the date where the equity curve actually hit this peak value
    dd_peak_candidates = eq.loc[:dd_trough_idx]
    dd_peak_idx = dd_peak_candidates.idxmax()
    dd_peak_date = dd_peak_idx.strftime("%Y-%m-%d")
    dd_peak_value_actual = eq[dd_peak_idx]
    
    dd_rupee_loss = dd_peak_value_actual - dd_trough_value
    
    # ── 5. Recovery ──
    # Did the equity curve recover to the pre-drawdown peak after the trough?
    post_trough = eq.loc[dd_trough_idx:]
    recovery_mask = post_trough >= dd_peak_value_actual
    
    if recovery_mask.any():
        recovery_idx = recovery_mask.idxmax()
        recovery_date = recovery_idx.strftime("%Y-%m-%d")
        recovery_days = (recovery_idx - dd_trough_idx).days
        recovered = True
    else:
        recovery_date = None
        recovery_days = None
        recovered = False
    
    # ── 6. Underwater Statistics ──
    underwater = drawdown < 0  # True when below previous peak
    
    total_days = len(eq)
    days_underwater = underwater.sum()
    pct_time_underwater = days_underwater / total_days if total_days > 0 else 0
    
    # Depth stats (only when underwater)
    underwater_depths = drawdown[underwater]
    underwater_depths_rupees = (eq[underwater] - cummax[underwater])
    
    if len(underwater_depths) > 0:
        avg_underwater_depth_pct = underwater_depths.mean()
        avg_underwater_depth_rupees = underwater_depths_rupees.mean()
        median_underwater_depth_pct = underwater_depths.median()
    else:
        avg_underwater_depth_pct = 0.0
        avg_underwater_depth_rupees = 0.0
        median_underwater_depth_pct = 0.0
    
    # Longest underwater period & number of episodes
    # An episode starts when drawdown goes below 0 and ends when it returns to 0
    in_dd = underwater.astype(int)
    # Find transitions: 0->1 = start, 1->0 = end
    transitions = in_dd.diff().fillna(0)
    
    episode_starts = eq.index[transitions == 1].tolist()
    episode_ends = eq.index[transitions == -1].tolist()
    
    # Handle case where we start underwater
    if len(in_dd) > 0 and in_dd.iloc[0] == 1:
        episode_starts.insert(0, eq.index[0])
    
    # Handle case where we end underwater (no recovery)
    if len(episode_starts) > len(episode_ends):
        episode_ends.append(eq.index[-1])
    
    num_episodes = len(episode_starts)
    
    longest_duration = 0
    longest_start = eq.index[0]
    longest_end = eq.index[0]
    
    for s, e in zip(episode_starts, episode_ends):
        duration = (e - s).days
        if duration > longest_duration:
            longest_duration = duration
            longest_start = s
            longest_end = e
    
    return DetailedMetrics(
        config_name=config_name,
        cost_type=cost_type,
        initial_capital=initial_capital,
        final_value=final_value,
        final_date=final_date,
        peak_value=peak_value,
        peak_date=peak_date,
        max_dd_pct=max_dd_pct,
        dd_trough_value=dd_trough_value,
        dd_trough_date=dd_trough_date,
        dd_peak_value=dd_peak_value_actual,
        dd_peak_date=dd_peak_date,
        dd_rupee_loss=dd_rupee_loss,
        recovery_date=recovery_date,
        recovery_days=recovery_days,
        recovered=recovered,
        total_days=total_days,
        days_underwater=days_underwater,
        pct_time_underwater=pct_time_underwater,
        avg_underwater_depth_pct=avg_underwater_depth_pct,
        avg_underwater_depth_rupees=avg_underwater_depth_rupees,
        median_underwater_depth_pct=median_underwater_depth_pct,
        longest_underwater_days=longest_duration,
        longest_underwater_start=longest_start.strftime("%Y-%m-%d"),
        longest_underwater_end=longest_end.strftime("%Y-%m-%d"),
        num_drawdown_episodes=num_episodes,
    )


def print_detailed_report(m: DetailedMetrics):
    """Print a detailed report for one configuration."""
    
    w = 45  # label width
    
    print(f"\n{'━' * 75}")
    print(f"  {m.config_name} — {m.cost_type}")
    print(f"{'━' * 75}")
    
    # 1. Initial Capital
    print(f"\n  {'1. INITIAL CAPITAL'}")
    print(f"  {'─' * 40}")
    print(f"  {'Initial Capital':<{w}} ₹{m.initial_capital:>14,.2f}")
    
    # 2. Final Portfolio Value
    print(f"\n  {'2. FINAL PORTFOLIO VALUE'}")
    print(f"  {'─' * 40}")
    print(f"  {'Final Value':<{w}} ₹{m.final_value:>14,.2f}")
    print(f"  {'Final Date':<{w}} {m.final_date}")
    total_pnl = m.final_value - m.initial_capital
    total_return = (m.final_value / m.initial_capital - 1) * 100
    print(f"  {'Total P&L':<{w}} ₹{total_pnl:>14,.2f}")
    print(f"  {'Total Return':<{w}} {total_return:>14.1f}%")
    multiplier = m.final_value / m.initial_capital
    print(f"  {'Money Multiplier':<{w}} {multiplier:>14.2f}x")
    
    # 3. Peak Portfolio Value
    print(f"\n  {'3. PEAK PORTFOLIO VALUE'}")
    print(f"  {'─' * 40}")
    print(f"  {'Peak Value':<{w}} ₹{m.peak_value:>14,.2f}")
    print(f"  {'Peak Date':<{w}} {m.peak_date}")
    peak_gain = m.peak_value - m.initial_capital
    print(f"  {'Gain at Peak (from initial)':<{w}} ₹{peak_gain:>14,.2f}")
    peak_return = (m.peak_value / m.initial_capital - 1) * 100
    print(f"  {'Return at Peak':<{w}} {peak_return:>14.1f}%")
    
    # 4. Maximum Drawdown
    print(f"\n  {'4. MAXIMUM DRAWDOWN'}")
    print(f"  {'─' * 40}")
    print(f"  {'Pre-DD Peak Value':<{w}} ₹{m.dd_peak_value:>14,.2f}")
    print(f"  {'Pre-DD Peak Date':<{w}} {m.dd_peak_date}")
    print(f"  {'Trough Value':<{w}} ₹{m.dd_trough_value:>14,.2f}")
    print(f"  {'Trough Date':<{w}} {m.dd_trough_date}")
    print(f"  {'Drawdown (₹)':<{w}} ₹{m.dd_rupee_loss:>14,.2f}")
    print(f"  {'Drawdown (%)':<{w}} {m.max_dd_pct * 100:>14.1f}%")
    
    # 5. Recovery
    print(f"\n  {'5. RECOVERY AFTER MAX DRAWDOWN'}")
    print(f"  {'─' * 40}")
    if m.recovered:
        print(f"  {'Recovered?':<{w}} {'YES ✅'}")
        print(f"  {'Recovery Date':<{w}} {m.recovery_date}")
        print(f"  {'Recovery Time':<{w}} {m.recovery_days:>14,d} calendar days")
        months = m.recovery_days / 30.44
        print(f"  {'Recovery Time (approx)':<{w}} {months:>14.1f} months")
    else:
        print(f"  {'Recovered?':<{w}} {'NO ❌ (still underwater)'}")
        # How far from recovery?
        shortfall = m.dd_peak_value - m.final_value
        shortfall_pct = (shortfall / m.dd_peak_value) * 100
        print(f"  {'Shortfall from Peak':<{w}} ₹{shortfall:>14,.2f}")
        print(f"  {'Shortfall (%)':<{w}} {shortfall_pct:>14.1f}%")
    
    # 6. Underwater Statistics
    print(f"\n  {'6. UNDERWATER CURVE STATISTICS'}")
    print(f"  {'─' * 40}")
    print(f"  {'Total Trading Days':<{w}} {m.total_days:>14,d}")
    print(f"  {'Days Underwater':<{w}} {m.days_underwater:>14,d}")
    print(f"  {'% Time Underwater':<{w}} {m.pct_time_underwater * 100:>14.1f}%")
    print(f"  {'Days Above Water':<{w}} {m.total_days - m.days_underwater:>14,d}")
    print(f"  {'% Time Above Water':<{w}} {(1 - m.pct_time_underwater) * 100:>14.1f}%")
    print(f"  {'Avg Underwater Depth (%)':<{w}} {m.avg_underwater_depth_pct * 100:>14.2f}%")
    print(f"  {'Avg Underwater Depth (₹)':<{w}} ₹{m.avg_underwater_depth_rupees:>14,.2f}")
    print(f"  {'Median Underwater Depth (%)':<{w}} {m.median_underwater_depth_pct * 100:>14.2f}%")
    print(f"  {'Longest Underwater Period':<{w}} {m.longest_underwater_days:>14,d} calendar days")
    months = m.longest_underwater_days / 30.44
    print(f"  {'Longest Underwater (approx)':<{w}} {months:>14.1f} months")
    print(f"  {'Longest UW Start':<{w}} {m.longest_underwater_start}")
    print(f"  {'Longest UW End':<{w}} {m.longest_underwater_end}")
    print(f"  {'Number of DD Episodes':<{w}} {m.num_drawdown_episodes:>14,d}")
    
    print(f"{'━' * 75}")


def print_comparison_table(all_metrics: list):
    """Print a compact comparison table of all configs."""
    
    print(f"\n\n{'═' * 130}")
    print(f"{'COMPARISON TABLE — ALL CONFIGURATIONS (₹ VALUES)':^130}")
    print(f"{'═' * 130}")
    
    header = (
        f"{'Config':<28} {'Type':<5} "
        f"{'Initial':>12} {'Final':>14} {'Peak':>14} "
        f"{'DD Trough':>14} {'DD Loss ₹':>14} {'DD %':>8} "
        f"{'Recovery':>10} {'% UW':>7}"
    )
    print(header)
    print(f"{'─' * 130}")
    
    for m in all_metrics:
        recovery_str = f"{m.recovery_days}d" if m.recovered else "NOT YET"
        print(
            f"{m.config_name:<28} {m.cost_type:<5} "
            f"₹{m.initial_capital:>10,.0f} ₹{m.final_value:>12,.0f} ₹{m.peak_value:>12,.0f} "
            f"₹{m.dd_trough_value:>12,.0f} ₹{m.dd_rupee_loss:>12,.0f} {m.max_dd_pct*100:>7.1f}% "
            f"{recovery_str:>10} {m.pct_time_underwater*100:>6.1f}%"
        )
    
    print(f"{'═' * 130}")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    config = SystemConfig()
    initial_capital = config.portfolio.initial_capital
    
    print("=" * 75)
    print("  DETAILED PORTFOLIO METRICS — RUPEE VALUES")
    print(f"  Initial Capital: ₹{initial_capital:,.0f}")
    print("=" * 75)
    
    # ── Load Data ──
    print("\n📦 Loading data from cache...")
    t0 = time.time()
    
    stock_data = download_all_stocks(use_cache=True)
    if not stock_data:
        print("ERROR: No stock data. Run 'python main.py download' first.")
        return
    
    close_panel = build_price_panel(stock_data, "Close")
    open_panel = build_price_panel(stock_data, "Open")
    high_panel = build_price_panel(stock_data, "High")
    low_panel = build_price_panel(stock_data, "Low")
    volume_panel = build_price_panel(stock_data, "Volume")
    
    print(f"  Loaded {len(close_panel)} dates × {len(close_panel.columns)} stocks "
          f"in {time.time()-t0:.1f}s")
    
    # ── Test Grid ──
    param_grid = [
        (5, "monthly"),
        (5, "quarterly"),
        (10, "monthly"),
        (10, "quarterly"),
    ]
    
    all_detailed_metrics = []
    
    for n_stocks, freq in param_grid:
        label = f"{n_stocks} stocks / {freq}"
        
        print(f"\n{'=' * 75}")
        print(f"  Running: {label}")
        print(f"{'=' * 75}")
        
        # Run GROSS
        gross_result = run_pure_momentum_backtest(
            close_panel, open_panel, high_panel, low_panel, volume_panel,
            n_stocks=n_stocks,
            rebalance_freq=freq,
            initial_capital=initial_capital,
            config=config,
            apply_costs=False,
        )
        
        # Run NET
        net_result = run_pure_momentum_backtest(
            close_panel, open_panel, high_panel, low_panel, volume_panel,
            n_stocks=n_stocks,
            rebalance_freq=freq,
            initial_capital=initial_capital,
            config=config,
            apply_costs=True,
        )
        
        if gross_result["equity_curve"].empty:
            print(f"  No results for {label}")
            continue
        
        # Compute detailed metrics
        gross_metrics = compute_detailed_metrics(
            gross_result["equity_curve"], initial_capital, label, "GROSS"
        )
        net_metrics = compute_detailed_metrics(
            net_result["equity_curve"], initial_capital, label, "NET"
        )
        
        # Print individual reports
        print_detailed_report(gross_metrics)
        print_detailed_report(net_metrics)
        
        all_detailed_metrics.append(gross_metrics)
        all_detailed_metrics.append(net_metrics)
    
    # ── Comparison Table ──
    if all_detailed_metrics:
        print_comparison_table(all_detailed_metrics)
    
    print("\n✅ Analysis complete.")


if __name__ == "__main__":
    main()
