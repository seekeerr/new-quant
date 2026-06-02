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

from config import SystemConfig, RESULTS_DIR
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


def print_config_report(label, equity, initial_capital, emit):
    """Emit the human-readable report and return a flat dict for the CSV."""
    emit(f"\n{'='*65}")
    emit(f"  CONFIG: {label}")
    emit(f"{'='*65}")

    # 1. Initial Capital
    emit(f"\n  1. Initial Capital:          Rs {initial_capital:>14,.2f}")

    # 2. Final Portfolio Value
    final_value = equity.iloc[-1]
    total_return_pct = (final_value / initial_capital - 1) * 100
    emit(f"  2. Final Portfolio Value:    Rs {final_value:>14,.2f}  ({total_return_pct:+.1f}%)")

    # 3 & 4. Peak and Max Drawdown
    all_time_peak_value = equity.max()
    all_time_peak_date = equity.idxmax()
    emit(f"  3. Peak Portfolio Value:     Rs {all_time_peak_value:>14,.2f}  ({all_time_peak_date.date()})")

    mdd = analyze_max_drawdown(equity)
    emit(f"\n  4. Maximum Drawdown:")
    emit(f"     Peak before drawdown:     Rs {mdd['peak_value']:>14,.2f}  ({mdd['peak_date'].date()})")
    emit(f"     Portfolio at Trough:      Rs {mdd['trough_value']:>14,.2f}  ({mdd['trough_date'].date()})")
    emit(f"     Drawdown Amount:          Rs {mdd['peak_value'] - mdd['trough_value']:>14,.2f}  ({mdd['max_dd_pct']:.1%})")
    emit(f"     Peak-to-Trough Duration:  {mdd['drawdown_duration_days']} calendar days")

    # 5. Recovery Time
    emit(f"\n  5. Recovery After Max Drawdown:")
    if mdd['recovery_date']:
        emit(f"     Recovery Date:            {mdd['recovery_date'].date()}")
        emit(f"     Trough-to-Recovery:       {mdd['recovery_days']} calendar days")
        total_dd_cycle = mdd['drawdown_duration_days'] + mdd['recovery_days']
        emit(f"     Full DD Cycle (P->T->R):  {total_dd_cycle} calendar days")
    else:
        emit(f"     *** NOT YET RECOVERED as of backtest end ***")
        days_since_trough = (equity.index[-1] - mdd['trough_date']).days
        current_from_trough = (equity.iloc[-1] / mdd['trough_value'] - 1) * 100
        emit(f"     Days since trough:        {days_since_trough} calendar days")
        emit(f"     Recovery progress:        {current_from_trough:+.1f}% from trough")
        still_needed = (mdd['peak_value'] / equity.iloc[-1] - 1) * 100
        emit(f"     Still needs:              +{still_needed:.1f}% to reach prior peak")

    # 6. Underwater Curve Statistics
    uw = underwater_curve_stats(equity)
    if uw:
        emit(f"\n  6. Underwater Curve Statistics:")
        emit(f"     % Time Spent Underwater:  {uw['pct_time_underwater']:.1f}%")
        emit(f"     # Drawdown Periods:       {uw['num_dd_periods']}")
        emit(f"     Avg Depth:                {uw['avg_depth_pct']:.2%}")
        emit(f"     Median Depth:             {uw['median_depth_pct']:.2%}")
        emit(f"     Avg Duration (days):      {uw['avg_duration_days']:.0f} days")
        if uw['worst_5_drawdowns']:
            emit(f"     5 Worst Drawdowns:")
            for i, d in enumerate(uw['worst_5_drawdowns'], 1):
                emit(f"       #{i}: {d:.2%}")

    return {
        "config": label,
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return_pct": total_return_pct,
        "peak_value": all_time_peak_value,
        "peak_date": all_time_peak_date.date(),
        "maxdd_peak_value": mdd["peak_value"],
        "maxdd_peak_date": mdd["peak_date"].date(),
        "maxdd_trough_value": mdd["trough_value"],
        "maxdd_trough_date": mdd["trough_date"].date(),
        "max_dd_pct": mdd["max_dd_pct"],
        "peak_to_trough_days": mdd["drawdown_duration_days"],
        "recovery_days": mdd["recovery_days"],
        "pct_time_underwater": uw.get("pct_time_underwater") if uw else None,
        "num_dd_periods": uw.get("num_dd_periods") if uw else None,
        "avg_dd_depth_pct": uw.get("avg_depth_pct") if uw else None,
        "median_dd_depth_pct": uw.get("median_depth_pct") if uw else None,
        "avg_dd_duration_days": uw.get("avg_duration_days") if uw else None,
    }


def write_walkthrough(out_dir, rows, config):
    df = pd.DataFrame(rows)
    path = out_dir / "WALKTHROUGH.md"
    lines = []
    lines.append("# Pure 12-1 Momentum — Drawdown & Portfolio-Value Analysis\n")
    lines.append(f"_Generated by `analyze_drawdown_stats.py` — capital Rs "
                 f"{config.portfolio.initial_capital:,.0f}, period "
                 f"{config.backtest.start_date} to {config.backtest.end_date}._\n")
    lines.append("## What this is\n")
    lines.append(
        "Rupee-value portfolio statistics for the validated pure 12-1 momentum strategy "
        "(no risk overlays), net of all Indian transaction costs, across four configs.\n")
    lines.append("## Final & peak values by config\n")
    lines.append("| Config | Final Value | Peak Value | Peak Date | Max DD | Recovery |")
    lines.append("|---|---|---|---|---|---|")
    for _, r in df.iterrows():
        rec = f"{int(r['recovery_days'])}d" if pd.notna(r["recovery_days"]) else "not recovered"
        lines.append(f"| {r['config']} | Rs {r['final_value']:,.0f} | "
                     f"Rs {r['peak_value']:,.0f} | {r['peak_date']} | "
                     f"{r['max_dd_pct']:.1%} | {rec} |")
    lines.append("")
    lines.append("## Key takeaway\n")
    lines.append(
        "All four configs grew Rs 5L into the Rs 28L-82L range but carry brutal max drawdowns "
        "(-56% to -68%), and **all peaked in mid-to-late 2024 and remain in their deepest-ever "
        "drawdown at the backtest end (May 2026)** — none had recovered the prior peak. This is "
        "the risk that motivated the market-filter experiment (see "
        "`../market_filters/WALKTHROUGH.md`).\n")
    lines.append("## Files in this folder\n")
    lines.append("- `factor_report_*.png` — full gross-vs-net report per config (from "
                 "`run_pure_momentum.py`)\n"
                 "- `factor_comparison.png` — all configs on one chart\n"
                 "- `drawdown_stats.csv` — machine-readable version of the numbers below\n"
                 "- `drawdown_stats.txt` — full console output\n"
                 "- `WALKTHROUGH.md` — this file\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    config = SystemConfig()
    initial_capital = config.portfolio.initial_capital

    out_dir = RESULTS_DIR / "pure_momentum"
    out_dir.mkdir(parents=True, exist_ok=True)

    report_lines = []

    def emit(line=""):
        print(line)
        report_lines.append(line)

    emit("=" * 65)
    emit("  PURE MOMENTUM — RUPEE VALUE PORTFOLIO STATISTICS")
    emit(f"  Initial Capital: Rs {initial_capital:,.0f}")
    emit(f"  Period: {config.backtest.start_date} to {config.backtest.end_date}")
    emit("=" * 65)

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

    rows = []
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
        rows.append(print_config_report(label, equity, initial_capital, emit))

    emit(f"\n{'='*65}\n")

    # ── Save artifacts ──
    pd.DataFrame(rows).to_csv(out_dir / "drawdown_stats.csv", index=False)
    (out_dir / "drawdown_stats.txt").write_text("\n".join(report_lines), encoding="utf-8")
    write_walkthrough(out_dir, rows, config)

    print(f"\nArtifacts written to: {out_dir}")
    print("  - drawdown_stats.csv")
    print("  - drawdown_stats.txt")
    print("  - WALKTHROUGH.md")


if __name__ == "__main__":
    main()
