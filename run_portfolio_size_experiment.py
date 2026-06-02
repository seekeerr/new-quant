"""
PORTFOLIO-SIZE (CONCENTRATION) EXPERIMENT.

Question: How concentrated should the champion momentum book be? Holding fewer
names concentrates the strongest momentum signal (more alpha, more idiosyncratic
risk); holding more names diversifies (smoother ride, diluted edge). Where is the
sweet spot that preserves momentum alpha without taking on uncompensated single-
stock risk?

CHAMPION STRATEGY — HELD FIXED (the validated Buffer20 winner):
  - Universe : same point-in-time liquidity/quality filters
  - Signal   : pure 12-1 cross-sectional momentum
  - Rebalance: quarterly
  - Weighting: equal weight
  - Buffer   : 20  (hold a name until its momentum rank decays past 20)
  - No stops / no DD liquidation / no cooldown / no regime / no blending
  - Same Indian-equity transaction cost model, same dates

ONLY CHANGE per variant: the portfolio size N (number of stocks held).
  - Top 3, Top 5, Top 7, Top 10
  The ranking buffer stays at 20 for every variant; with N held names, empty
  slots are filled from the best-ranked stocks not already held, and a held
  name is retained only while its rank is within 20.

All reported figures are NET of costs.
"""

import sys
import time
import warnings
import io
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import logging
logging.basicConfig(level=logging.ERROR)
for name in logging.root.manager.loggerDict:
    logging.getLogger(name).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

from config import SystemConfig, RESULTS_DIR
from data.downloader import download_all_stocks, build_price_panel
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from analytics.metrics import compute_metrics

# Reuse the EXACT validated buffered backtest + analytics from the buffer experiment.
# Nothing about the engine, signal, costs, or buffer logic changes — only n_stocks.
from run_buffer_experiment import (
    run_buffered_backtest,
    drawdown_analytics,
    rolling_3y_cagr,
    annual_returns,
)


# ─────────────────────────────────────────────────────────────────────
# FIXED CHAMPION SETTINGS
# ─────────────────────────────────────────────────────────────────────

BUFFER = 20
FREQ = "quarterly"
SIZES = [3, 5, 7, 10]          # the ONLY thing that varies

PALETTE = {
    "Top3":  "#ff6b6b",
    "Top5":  "#ffd93d",
    "Top7":  "#4ecdc4",
    "Top10": "#00ff88",
}


# ─────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────

def make_charts(variants: dict, benchmark_equity: pd.Series, save_path: Path):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 22))
    gs = GridSpec(4, 2, figure=fig, hspace=0.32, wspace=0.22)
    fig.suptitle(
        "Portfolio-Size (Concentration) Experiment — Buffer20 / Quarterly / Equal Weight / 12-1 Momentum (Net)",
        fontsize=15, fontweight="bold", y=0.995, color="#fff",
    )
    names = list(variants.keys())

    # 1. Equity curves (log scale)
    ax1 = fig.add_subplot(gs[0, :])
    ax1.set_title("Equity Curve (base 100, log scale)", fontweight="bold")
    for name in names:
        eq = variants[name]["equity_curve"]
        norm = eq / eq.iloc[0] * 100
        ax1.plot(norm.index, norm.values, color=PALETTE[name], linewidth=1.7, label=name)
    if benchmark_equity is not None and not benchmark_equity.empty:
        bm = benchmark_equity / benchmark_equity.iloc[0] * 100
        ax1.plot(bm.index, bm.values, color="#888", linewidth=1.2, linestyle="--",
                 label="NIFTY 500 TRI", alpha=0.8)
    ax1.set_yscale("log")
    ax1.set_ylabel("Value (base 100)")
    ax1.legend(loc="upper left", framealpha=0.3)
    ax1.grid(True, alpha=0.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 2. Drawdown
    ax2 = fig.add_subplot(gs[1, :])
    ax2.set_title("Drawdown", fontweight="bold")
    for name in names:
        eq = variants[name]["equity_curve"]
        dd = (eq - eq.cummax()) / eq.cummax() * 100
        ax2.plot(dd.index, dd.values, color=PALETTE[name], linewidth=1.0, label=name)
    ax2.set_ylabel("Drawdown (%)")
    ax2.legend(loc="lower left", framealpha=0.3)
    ax2.grid(True, alpha=0.2)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 3. CAGR vs Max Drawdown bars
    ax3 = fig.add_subplot(gs[2, 0])
    ax3.set_title("CAGR (bars) vs Max Drawdown (line)", fontweight="bold")
    cagrs = [variants[n]["_metrics"].cagr * 100 for n in names]
    dds = [abs(variants[n]["_metrics"].max_drawdown) * 100 for n in names]
    bars = ax3.bar(names, cagrs, color=[PALETTE[n] for n in names])
    for b, c in zip(bars, cagrs):
        ax3.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{c:.1f}%",
                 ha="center", va="bottom", color="#fff", fontweight="bold")
    ax3b = ax3.twinx()
    ax3b.plot(names, dds, color="#ff6b6b", marker="o", linewidth=1.6, label="Max DD")
    ax3b.set_ylabel("Max Drawdown (%)", color="#ff6b6b")
    ax3.set_ylabel("CAGR (%)")
    ax3.grid(True, alpha=0.2, axis="y")

    # 4. Sharpe & Calmar
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.set_title("Risk-Adjusted: Sharpe & Calmar", fontweight="bold")
    x = np.arange(len(names))
    sharpes = [variants[n]["_metrics"].sharpe_ratio for n in names]
    calmars = [variants[n]["_metrics"].calmar_ratio for n in names]
    ax4.bar(x - 0.2, sharpes, width=0.4, color="#4ecdc4", label="Sharpe")
    ax4.bar(x + 0.2, calmars, width=0.4, color="#ffd93d", label="Calmar")
    ax4.set_xticks(x)
    ax4.set_xticklabels(names)
    ax4.legend(framealpha=0.3)
    ax4.grid(True, alpha=0.2, axis="y")

    # 5. Rolling 3Y CAGR
    ax5 = fig.add_subplot(gs[3, :])
    ax5.set_title("Rolling 3-Year CAGR", fontweight="bold")
    for name in names:
        roll = rolling_3y_cagr(variants[name]["returns"])
        if not roll.empty:
            ax5.plot(roll.index, roll.values * 100, color=PALETTE[name], linewidth=1.3, label=name)
    ax5.axhline(6.5, color="#ff6b6b", linewidth=1, linestyle="--", alpha=0.6, label="FD 6.5%")
    ax5.axhline(0, color="white", linewidth=0.5, linestyle="--", alpha=0.3)
    ax5.set_ylabel("Rolling 3Y CAGR (%)")
    ax5.legend(loc="upper right", framealpha=0.3)
    ax5.grid(True, alpha=0.2)
    ax5.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Chart saved: {save_path}")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    config = SystemConfig()
    initial_capital = config.portfolio.initial_capital

    print("=" * 72)
    print("  PORTFOLIO-SIZE (CONCENTRATION) EXPERIMENT")
    print(f"  Buffer{BUFFER} / {FREQ} / equal weight / 12-1 momentum / net of costs")
    print(f"  Sizes tested: {SIZES}")
    print("=" * 72)

    print("\nLoading data from cache...")
    t0 = time.time()
    stock_data = download_all_stocks(use_cache=True)
    if not stock_data:
        print("ERROR: No stock data. Run 'py main.py download' first.")
        return
    close_panel = build_price_panel(stock_data, "Close")
    high_panel = build_price_panel(stock_data, "High")
    low_panel = build_price_panel(stock_data, "Low")
    volume_panel = build_price_panel(stock_data, "Volume")
    print(f"  Loaded {len(close_panel)} dates x {len(close_panel.columns)} stocks "
          f"in {time.time()-t0:.1f}s")

    benchmark_returns = get_benchmark_returns(config.backtest.start_date, config.backtest.end_date)
    benchmark_equity = get_benchmark_equity_curve(
        config.backtest.start_date, config.backtest.end_date, initial_capital)

    variants = {}
    metrics = {}
    extra = {}
    annuals = {}
    cost_drag = {}

    for n in SIZES:
        name = f"Top{n}"
        print(f"\n{'-'*72}\n  {name}  (n_stocks = {n}, buffer = {BUFFER})\n{'-'*72}")
        res = run_buffered_backtest(
            close_panel, high_panel, low_panel, volume_panel,
            n_stocks=n, rebalance_freq=FREQ, buffer=BUFFER,
            initial_capital=initial_capital, config=config,
            apply_costs=True, label=name,
        )
        gross = run_buffered_backtest(
            close_panel, high_panel, low_panel, volume_panel,
            n_stocks=n, rebalance_freq=FREQ, buffer=BUFFER,
            initial_capital=initial_capital, config=config,
            apply_costs=False, label=name + "(gross)",
        )
        if res["equity_curve"].empty:
            print(f"  No results for {name}")
            continue
        m = compute_metrics(
            res["equity_curve"], res["returns"],
            benchmark_returns=benchmark_returns, trades=res["trades"],
            total_costs=res["total_costs"], initial_capital=initial_capital,
        )
        gross_m = compute_metrics(
            gross["equity_curve"], gross["returns"], initial_capital=initial_capital,
        )
        res["_metrics"] = m
        variants[name] = res
        metrics[name] = m
        extra[name] = drawdown_analytics(res["equity_curve"])
        annuals[name] = annual_returns(res["equity_curve"])
        cost_drag[name] = gross_m.cagr - m.cagr
        print(f"  CAGR {m.cagr:.2%} (gross {gross_m.cagr:.2%}) | MaxDD {m.max_drawdown:.2%} | "
              f"Sharpe {m.sharpe_ratio:.2f} | Calmar {m.calmar_ratio:.2f} | "
              f"Final ₹{res['equity_curve'].iloc[-1]:,.0f} | Trades {res['total_trades']} | "
              f"Costs ₹{res['total_costs']:,.0f}")

    results_dir = RESULTS_DIR / "portfolio_size"
    results_dir.mkdir(parents=True, exist_ok=True)

    make_charts(variants, benchmark_equity, results_dir / "report.png")

    # ── Comparison report text ──
    names = list(variants.keys())
    lines = []

    def w(s=""):
        lines.append(s)

    w("=" * 100)
    w("PORTFOLIO-SIZE (CONCENTRATION) EXPERIMENT — COMPARISON REPORT".center(100))
    w("Buffer20 / Quarterly / Equal Weight / 12-1 Momentum / Net of Costs".center(100))
    w("=" * 100)
    w(f"Initial Capital: ₹{initial_capital:,.0f}")
    w(f"Period: {metrics[names[0]].start_date} to {metrics[names[0]].end_date}")
    w("Champion settings held fixed: pure 12-1 momentum, quarterly rebalance,")
    w("equal weight, ranking buffer = 20. ONLY the portfolio size N varies.")
    w("NOTE: Daily valuation forward-fills a missing close so a held stock is not")
    w("      marked to zero on the one partial-data date (2026-05-28). Signals and")
    w("      trade prices are unchanged; the champion mechanics are intact.")
    w("")

    def row(label, fmt):
        line = f"{label:<28}"
        for n in names:
            line += f"{fmt(n):>17}"
        return line

    header = f"{'Metric':<28}"
    for n in names:
        header += f"{n:>17}"
    w(header)
    w("-" * 100)

    w(row("1. CAGR", lambda n: f"{metrics[n].cagr:.2%}"))
    w(row("2. Max Drawdown", lambda n: f"{metrics[n].max_drawdown:.2%}"))
    w(row("3. Sharpe Ratio", lambda n: f"{metrics[n].sharpe_ratio:.2f}"))
    w(row("4. Calmar Ratio", lambda n: f"{metrics[n].calmar_ratio:.2f}"))
    w(row("5. Annual Volatility", lambda n: f"{metrics[n].annualised_volatility:.2%}"))
    w(row("6. Total Trades (exec)", lambda n: f"{variants[n]['total_trades']}"))
    w(row("7. Transaction Costs (₹)", lambda n: f"{variants[n]['total_costs']:,.0f}"))
    w(row("8. Final Value (₹)", lambda n: f"{variants[n]['equity_curve'].iloc[-1]:,.0f}"))
    w(row("9. Time Underwater", lambda n: f"{extra[n]['time_underwater_pct']:.1%}"))
    w("-" * 100)
    w("")

    # Supporting metrics
    w("SUPPORTING METRICS")
    w("-" * 100)
    w(row("Total Return", lambda n: f"{metrics[n].total_return:.1%}"))
    w(row("Cost Drag (CAGR pts)", lambda n: f"{cost_drag[n]:.2%}"))
    w(row("Avg Turnover/Rebal", lambda n: f"{variants[n]['avg_turnover']:.1%}"))
    w(row("Peak Value (₹)", lambda n: f"{extra[n]['peak_value']:,.0f}"))
    w(row("Value @ Max DD (₹)", lambda n: f"{extra[n]['trough_value']:,.0f}"))
    w("-" * 100)
    w("")

    # Recovery time
    w("10. RECOVERY TIME (from deepest drawdown trough back to prior peak):")
    for n in names:
        w(f"     {n:<8}: trough {extra[n]['trough_date'].date()} → {extra[n]['recovery_str']}")
    w("")

    # Rolling 3Y CAGR
    w("11. ROLLING 3-YEAR CAGR (min / median / max across all 3Y windows):")
    for n in names:
        roll = rolling_3y_cagr(variants[n]["returns"])
        if not roll.empty:
            w(f"     {n:<8}: min {roll.min():.1%}  |  median {roll.median():.1%}  |  max {roll.max():.1%}")
    w("")

    # Year-wise
    w("12. YEAR-WISE RETURNS")
    w("-" * 100)
    yhead = f"{'Year':<8}"
    for n in names:
        yhead += f"{n:>17}"
    w(yhead)
    all_years = sorted(set().union(*[set(annuals[n].index) for n in names]))
    for yr in all_years:
        line = f"{yr:<8}"
        for n in names:
            v = annuals[n].get(yr, np.nan)
            line += f"{'N/A':>17}" if pd.isna(v) else f"{v:>16.1%} "
        w(line)
    w("-" * 100)
    avg_line = f"{'Avg':<8}"
    for n in names:
        avg_line += f"{annuals[n].mean():>16.1%} "
    w(avg_line)
    w("=" * 100)

    # ── Verdict ──
    w("")
    w("VERDICT".center(100, "─"))
    # Best Calmar (risk-adjusted), and best CAGR, both reported.
    best_calmar = max(names, key=lambda n: metrics[n].calmar_ratio)
    best_cagr = max(names, key=lambda n: metrics[n].cagr)
    best_sharpe = max(names, key=lambda n: metrics[n].sharpe_ratio)
    w(f"  Highest CAGR        : {best_cagr}  ({metrics[best_cagr].cagr:.2%})")
    w(f"  Best Calmar (risk-adj): {best_calmar}  (Calmar {metrics[best_calmar].calmar_ratio:.2f}, "
      f"MaxDD {metrics[best_calmar].max_drawdown:.2%})")
    w(f"  Best Sharpe         : {best_sharpe}  ({metrics[best_sharpe].sharpe_ratio:.2f})")
    w("  Note: smaller N concentrates momentum alpha (higher CAGR potential, deeper")
    w("        single-stock drawdowns); larger N diversifies (smoother, diluted edge).")
    w("=" * 100)

    report_txt = "\n".join(lines)
    print("\n" + report_txt)
    (results_dir / "report.txt").write_text(report_txt, encoding="utf-8")
    print(f"\n  Report saved: {results_dir / 'report.txt'}")

    # ── CSV ──
    rows = []
    for n in names:
        m = metrics[n]
        e = extra[n]
        roll = rolling_3y_cagr(variants[n]["returns"])
        rows.append({
            "variant": n,
            "n_stocks": int(n.replace("Top", "")),
            "buffer": BUFFER,
            "cagr": m.cagr,
            "max_drawdown": m.max_drawdown,
            "sharpe": m.sharpe_ratio,
            "calmar": m.calmar_ratio,
            "annual_vol": m.annualised_volatility,
            "total_trades_exec": variants[n]["total_trades"],
            "total_costs": variants[n]["total_costs"],
            "final_value": variants[n]["equity_curve"].iloc[-1],
            "time_underwater_pct": e["time_underwater_pct"],
            "recovery": e["recovery_str"],
            "recovery_days": e["recovery_days"],
            "total_return": m.total_return,
            "cost_drag_cagr_pts": cost_drag[n],
            "avg_turnover": variants[n]["avg_turnover"],
            "peak_value": e["peak_value"],
            "value_at_maxdd": e["trough_value"],
            "rolling3y_cagr_min": roll.min() if not roll.empty else np.nan,
            "rolling3y_cagr_median": roll.median() if not roll.empty else np.nan,
            "rolling3y_cagr_max": roll.max() if not roll.empty else np.nan,
        })
    pd.DataFrame(rows).to_csv(results_dir / "comparison.csv", index=False)
    print(f"  CSV saved: {results_dir / 'comparison.csv'}")

    ydf = pd.DataFrame({n: annuals[n] for n in names})
    ydf.index.name = "year"
    ydf.to_csv(results_dir / "yearwise_returns.csv")
    print(f"  CSV saved: {results_dir / 'yearwise_returns.csv'}")

    print(f"\n  All outputs in: {results_dir}/")


if __name__ == "__main__":
    main()
