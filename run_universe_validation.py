"""
UNIVERSE VALIDATION EXPERIMENT.

Question: The champion strategy was (accidentally) validated on a 49-stock
large-cap fallback universe because data/nifty500_constituents.csv was missing
and load_nifty500_symbols() fell back to a hardcoded 50-name sample. Does the
momentum alpha SURVIVE when the same, completely unchanged champion is run on
the full NIFTY 500 universe?

CHAMPION STRATEGY — HELD 100% FIXED (the validated Buffer20 winner):
  - Signal    : pure 12-1 cross-sectional momentum
  - Portfolio : Top 5, equal weight
  - Rebalance : quarterly
  - Exit       : ranking buffer 20 (hold until momentum rank decays past 20)
  - Risk mgmt : NONE (no stops, no DD liquidation, no cooldown, no regime, no blend)
  - Costs     : same Indian-equity delivery cost model, same dates

ONLY thing that changes between the two runs: the investable universe.
  A) Fallback  : the hardcoded 49-stock large-cap sample (what prior runs used)
  B) NIFTY 500 : the full constituent list from data/nifty500_constituents.csv

This is a VALIDATION experiment. Nothing is optimized. No parameters change.

Benchmark: NIFTY 500 PRICE index (^CRSLDX) saved to data/nifty500_tri.csv.
This is a PRICE-return proxy, NOT the true Total-Return Index — it understates
the real NIFTY 500 TRI by the index dividend yield (~1.2-1.5%/yr). Stated openly.
"""

import sys, io, time, warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import logging
logging.basicConfig(level=logging.ERROR)
for _n in logging.root.manager.loggerDict:
    logging.getLogger(_n).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

from config import SystemConfig, RESULTS_DIR
from data.downloader import (
    download_all_stocks, build_price_panel,
    load_nifty500_symbols, _get_sample_symbols,
)
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from analytics.metrics import compute_metrics

# Reuse the EXACT validated champion engine + analytics. Nothing changes here.
from run_buffer_experiment import (
    run_buffered_backtest, drawdown_analytics, rolling_3y_cagr, annual_returns,
)

# ── FIXED CHAMPION SETTINGS (never vary) ──
N_STOCKS = 5
BUFFER   = 20
FREQ     = "quarterly"

PALETTE = {"Fallback (49)": "#ff6b6b", "NIFTY 500": "#00ff88"}


def load_panels(symbols, label):
    """Load OHLCV panels for exactly the given symbol list (from cache)."""
    t0 = time.time()
    data = download_all_stocks(symbols=symbols, use_cache=True)
    close = build_price_panel(data, "Close")
    high  = build_price_panel(data, "High")
    low   = build_price_panel(data, "Low")
    vol   = build_price_panel(data, "Volume")
    print(f"  [{label}] loaded {len(close.columns)} stocks x {len(close)} dates "
          f"({time.time()-t0:.1f}s)")
    return data, close, high, low, vol


def coverage_stats(data, close_panel):
    """Universe diagnostics for the loaded data."""
    n = len(data)
    rows = [len(df) for df in data.values()]
    spans = [(df.index.min(), df.index.max()) for df in data.values()]
    full_hist = sum(1 for d in spans if d[0] <= pd.Timestamp("2011-06-01"))
    # per-date coverage (fraction of symbols with a non-NaN close)
    cov = close_panel.notna().mean(axis=1)
    return {
        "n_loaded": n,
        "median_rows": int(np.median(rows)) if rows else 0,
        "min_rows": int(np.min(rows)) if rows else 0,
        "max_rows": int(np.max(rows)) if rows else 0,
        "full_history_since_2011": full_hist,
        "avg_date_coverage": float(cov.mean()),
        "first_date": str(close_panel.index.min().date()),
        "last_date": str(close_panel.index.max().date()),
    }


def run_champion(close, high, low, vol, config, initial_capital, benchmark_returns, label):
    """Run the fixed champion (net + gross) and return packaged results."""
    net = run_buffered_backtest(
        close, high, low, vol, n_stocks=N_STOCKS, rebalance_freq=FREQ, buffer=BUFFER,
        initial_capital=initial_capital, config=config, apply_costs=True, label=label)
    gross = run_buffered_backtest(
        close, high, low, vol, n_stocks=N_STOCKS, rebalance_freq=FREQ, buffer=BUFFER,
        initial_capital=initial_capital, config=config, apply_costs=False,
        label=label + "(gross)")
    m = compute_metrics(net["equity_curve"], net["returns"],
                        benchmark_returns=benchmark_returns, trades=net["trades"],
                        total_costs=net["total_costs"], initial_capital=initial_capital)
    gm = compute_metrics(gross["equity_curve"], gross["returns"],
                         initial_capital=initial_capital)
    net["_metrics"] = m
    net["_gross_cagr"] = gm.cagr
    net["_extra"] = drawdown_analytics(net["equity_curve"])
    net["_annual"] = annual_returns(net["equity_curve"])
    net["_roll3y"] = rolling_3y_cagr(net["returns"])
    return net


# ─────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────
def make_charts(variants, benchmark_equity, bm_annual, save_path):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 24))
    gs = GridSpec(5, 2, figure=fig, hspace=0.38, wspace=0.22)
    fig.suptitle(
        "Universe Validation — Champion (Top5 / EW / Quarterly / Buffer20 / 12-1 Momentum, Net)\n"
        "49-stock Fallback  vs  Full NIFTY 500",
        fontsize=15, fontweight="bold", y=0.995, color="#fff")
    names = list(variants.keys())

    # 1. Equity curve (log)
    ax1 = fig.add_subplot(gs[0, :])
    ax1.set_title("Equity Curve (base 100, log scale)", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; norm = eq / eq.iloc[0] * 100
        ax1.plot(norm.index, norm.values, color=PALETTE[n], linewidth=1.8, label=n)
    if benchmark_equity is not None and not benchmark_equity.empty:
        bm = benchmark_equity / benchmark_equity.iloc[0] * 100
        ax1.plot(bm.index, bm.values, color="#888", linewidth=1.3, linestyle="--",
                 label="NIFTY 500 (price proxy)", alpha=0.85)
    ax1.set_yscale("log"); ax1.set_ylabel("Value (base 100)")
    ax1.legend(loc="upper left", framealpha=0.3); ax1.grid(True, alpha=0.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 2. Drawdown
    ax2 = fig.add_subplot(gs[1, :])
    ax2.set_title("Drawdown Curve", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; dd = (eq - eq.cummax()) / eq.cummax() * 100
        ax2.plot(dd.index, dd.values, color=PALETTE[n], linewidth=1.1, label=n)
    ax2.set_ylabel("Drawdown (%)"); ax2.legend(loc="lower left", framealpha=0.3)
    ax2.grid(True, alpha=0.2); ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 3. CAGR / MaxDD bars
    ax3 = fig.add_subplot(gs[2, 0])
    ax3.set_title("CAGR (bars) vs Max Drawdown (line)", fontweight="bold")
    cagrs = [variants[n]["_metrics"].cagr * 100 for n in names]
    dds = [abs(variants[n]["_metrics"].max_drawdown) * 100 for n in names]
    bars = ax3.bar(names, cagrs, color=[PALETTE[n] for n in names])
    for b, c in zip(bars, cagrs):
        ax3.text(b.get_x() + b.get_width()/2, b.get_height(), f"{c:.1f}%",
                 ha="center", va="bottom", color="#fff", fontweight="bold")
    ax3b = ax3.twinx()
    ax3b.plot(names, dds, color="#ff6b6b", marker="o", linewidth=1.6)
    ax3b.set_ylabel("Max Drawdown (%)", color="#ff6b6b")
    ax3.set_ylabel("CAGR (%)"); ax3.grid(True, alpha=0.2, axis="y")

    # 4. Sharpe & Calmar
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.set_title("Risk-Adjusted: Sharpe & Calmar", fontweight="bold")
    x = np.arange(len(names))
    ax4.bar(x - 0.2, [variants[n]["_metrics"].sharpe_ratio for n in names],
            width=0.4, color="#4ecdc4", label="Sharpe")
    ax4.bar(x + 0.2, [variants[n]["_metrics"].calmar_ratio for n in names],
            width=0.4, color="#ffd93d", label="Calmar")
    ax4.set_xticks(x); ax4.set_xticklabels(names)
    ax4.legend(framealpha=0.3); ax4.grid(True, alpha=0.2, axis="y")

    # 5. Rolling 3Y CAGR
    ax5 = fig.add_subplot(gs[3, :])
    ax5.set_title("Rolling 3-Year CAGR", fontweight="bold")
    for n in names:
        roll = variants[n]["_roll3y"]
        if not roll.empty:
            ax5.plot(roll.index, roll.values * 100, color=PALETTE[n], linewidth=1.4, label=n)
    ax5.axhline(6.5, color="#ff6b6b", linewidth=1, linestyle="--", alpha=0.6, label="FD 6.5%")
    ax5.axhline(0, color="white", linewidth=0.5, linestyle="--", alpha=0.3)
    ax5.set_ylabel("Rolling 3Y CAGR (%)")
    ax5.legend(loc="upper right", framealpha=0.3); ax5.grid(True, alpha=0.2)
    ax5.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 6. Year-wise returns (grouped bars) + benchmark
    ax6 = fig.add_subplot(gs[4, :])
    ax6.set_title("Year-wise Returns vs Benchmark", fontweight="bold")
    all_years = sorted(set().union(*[set(variants[n]["_annual"].index) for n in names]))
    xpos = np.arange(len(all_years))
    width = 0.8 / (len(names) + 1)
    for i, n in enumerate(names):
        vals = [variants[n]["_annual"].get(y, np.nan) * 100 for y in all_years]
        ax6.bar(xpos + i*width, vals, width=width, color=PALETTE[n], label=n)
    if bm_annual is not None and not bm_annual.empty:
        vals = [bm_annual.get(y, np.nan) * 100 for y in all_years]
        ax6.bar(xpos + len(names)*width, vals, width=width, color="#888",
                label="NIFTY 500 (price)")
    ax6.axhline(0, color="white", linewidth=0.5, alpha=0.3)
    ax6.set_xticks(xpos + width*len(names)/2); ax6.set_xticklabels(all_years, rotation=45)
    ax6.set_ylabel("Annual Return (%)"); ax6.legend(framealpha=0.3, ncol=3)
    ax6.grid(True, alpha=0.2, axis="y")

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
    start, end = config.backtest.start_date, config.backtest.end_date

    print("=" * 78)
    print("  UNIVERSE VALIDATION — does momentum alpha survive on full NIFTY 500?")
    print(f"  Champion fixed: Top{N_STOCKS} / {FREQ} / equal weight / Buffer{BUFFER} / 12-1 momentum")
    print("=" * 78)

    # Benchmark (price proxy)
    benchmark_returns = get_benchmark_returns(start, end)
    benchmark_equity = get_benchmark_equity_curve(start, end, initial_capital)
    bm_annual = annual_returns(benchmark_equity) if not benchmark_equity.empty else pd.Series(dtype=float)
    bm_available = not benchmark_equity.empty
    bm_cagr = np.nan
    if bm_available:
        m_bm = compute_metrics(benchmark_equity, initial_capital=initial_capital)
        bm_cagr = m_bm.cagr

    # ── Universe A: 49-stock fallback ──
    print("\nLoading FALLBACK (49-stock) universe...")
    fb_syms = _get_sample_symbols()
    fb_data, fbc, fbh, fbl, fbv = load_panels(fb_syms, "Fallback")
    fb_cov = coverage_stats(fb_data, fbc)

    # ── Universe B: full NIFTY 500 ──
    print("\nLoading FULL NIFTY 500 universe...")
    n500_syms = load_nifty500_symbols()
    n5_data, n5c, n5h, n5l, n5v = load_panels(n500_syms, "NIFTY500")
    n5_cov = coverage_stats(n5_data, n5c)
    n5_failed = sorted(set(s for s in n500_syms) - set(n5_data.keys()))

    # ── Run the fixed champion on both ──
    print("\nRunning champion on FALLBACK (49)...")
    fb = run_champion(fbc, fbh, fbl, fbv, config, initial_capital, benchmark_returns, "Fallback")
    print("\nRunning champion on NIFTY 500...")
    n5 = run_champion(n5c, n5h, n5l, n5v, config, initial_capital, benchmark_returns, "NIFTY 500")

    variants = {"Fallback (49)": fb, "NIFTY 500": n5}
    names = list(variants.keys())

    results_dir = RESULTS_DIR / "universe_validation"
    results_dir.mkdir(parents=True, exist_ok=True)

    make_charts(variants, benchmark_equity, bm_annual, results_dir / "report.png")

    # ── Report text ──
    lines = []
    def w(s=""): lines.append(s)

    w("=" * 100)
    w("UNIVERSE VALIDATION — 49-STOCK FALLBACK vs FULL NIFTY 500".center(100))
    w("Champion: Top5 / Quarterly / Equal Weight / Buffer20 / 12-1 Momentum / Net of Costs".center(100))
    w("=" * 100)
    w(f"Initial Capital : Rs {initial_capital:,.0f}")
    w(f"Period          : {fb['_metrics'].start_date} to {fb['_metrics'].end_date}")
    w("Strategy is byte-for-byte identical across both runs (same engine, signal,")
    w("buffer, costs, dates). The ONLY difference is the investable universe.")
    w("")
    w("CAVEATS (read before trusting the NIFTY 500 numbers):")
    w("  * SURVIVORSHIP BIAS: the universe is TODAY's NIFTY 500 membership applied")
    w("    across all history. Stocks dropped from the index over 2011-2026 (often")
    w("    laggards) are absent -> an upward bias in the NIFTY 500 result. A true")
    w("    point-in-time membership history would lower these returns somewhat.")
    w("  * BENCHMARK is ^CRSLDX, the NIFTY 500 PRICE index (no dividends). It")
    w("    understates the true Total-Return Index by ~1.2-1.5%/yr dividend yield.")
    w("")

    # ── Universe diagnostics ──
    w("-" * 100)
    w("1. UNIVERSE DIAGNOSTICS")
    w("-" * 100)
    def covrow(label, fmt):
        return f"{label:<34}{fmt(fb_cov):>30}{fmt(n5_cov):>30}"
    w(f"{'Metric':<34}{'Fallback (49)':>30}{'NIFTY 500':>30}")
    w(covrow("Symbols requested",       lambda c: f"{len(fb_syms) if c is fb_cov else len(n500_syms)}"))
    w(covrow("Symbols loaded (data ok)", lambda c: f"{c['n_loaded']}"))
    w(f"{'Symbols failed / no data':<34}{0:>30}{len(n5_failed):>30}")
    w(covrow("Full history since 2011-06", lambda c: f"{c['full_history_since_2011']}"))
    w(covrow("Median bars/stock",        lambda c: f"{c['median_rows']}"))
    w(covrow("Min / Max bars",           lambda c: f"{c['min_rows']} / {c['max_rows']}"))
    w(covrow("Avg per-date coverage",    lambda c: f"{c['avg_date_coverage']:.1%}"))
    w(covrow("Data span",                lambda c: f"{c['first_date']}..{c['last_date']}"))
    w("")
    if n5_failed:
        w(f"Failed / no-data NIFTY 500 symbols ({len(n5_failed)}):")
        for i in range(0, len(n5_failed), 8):
            w("   " + ", ".join(n5_failed[i:i+8]))
        w("")

    # ── Performance side-by-side ──
    def row(label, fmt):
        line = f"{label:<34}"
        for n in names:
            line += f"{fmt(variants[n]):>30}"
        return line

    w("-" * 100)
    w("2. PERFORMANCE  (NET of costs)")
    w("-" * 100)
    w(f"{'Metric':<34}{names[0]:>30}{names[1]:>30}")
    w("-" * 100)
    w(row("CAGR",                 lambda v: f"{v['_metrics'].cagr:.2%}"))
    w(row("Total Return",         lambda v: f"{v['_metrics'].total_return:.1%}"))
    w(row("Max Drawdown",         lambda v: f"{v['_metrics'].max_drawdown:.2%}"))
    w(row("Sharpe Ratio",         lambda v: f"{v['_metrics'].sharpe_ratio:.2f}"))
    w(row("Sortino Ratio",        lambda v: f"{v['_metrics'].sortino_ratio:.2f}"))
    w(row("Calmar Ratio",         lambda v: f"{v['_metrics'].calmar_ratio:.2f}"))
    w(row("Annual Volatility",    lambda v: f"{v['_metrics'].annualised_volatility:.2%}"))
    w(row("Final Value (Rs)",     lambda v: f"{v['equity_curve'].iloc[-1]:,.0f}"))
    w(row("Peak Value (Rs)",      lambda v: f"{v['_extra']['peak_value']:,.0f}"))
    w(row("Value @ Max DD (Rs)",  lambda v: f"{v['_extra']['trough_value']:,.0f}"))
    w(row("Time Underwater",      lambda v: f"{v['_extra']['time_underwater_pct']:.1%}"))
    w(row("Recovery (deepest DD)", lambda v: v['_extra']['recovery_str']))
    w("")

    w("-" * 100)
    w("3. TRADING STATISTICS")
    w("-" * 100)
    w(f"{'Metric':<34}{names[0]:>30}{names[1]:>30}")
    w("-" * 100)
    w(row("Rebalances",           lambda v: f"{v['total_rebalances']}"))
    w(row("Trades (executed)",    lambda v: f"{v['total_trades']}"))
    w(row("Avg Turnover / Rebal", lambda v: f"{v['avg_turnover']:.1%}"))
    w(row("Transaction Costs (Rs)", lambda v: f"{v['total_costs']:,.0f}"))
    w(row("Cost Drag (CAGR pts)", lambda v: f"{v['_gross_cagr'] - v['_metrics'].cagr:.2%}"))
    w(row("Gross CAGR",           lambda v: f"{v['_gross_cagr']:.2%}"))
    w("")

    # ── Benchmark comparison ──
    w("-" * 100)
    w("4. BENCHMARK COMPARISON  (vs ^CRSLDX NIFTY 500 PRICE index, NOT TRI)")
    w("-" * 100)
    if bm_available:
        w(f"NIFTY 500 price-index CAGR : {bm_cagr:.2%}   "
          f"(true TRI ~ {bm_cagr+0.013:.2%} after adding ~1.3%/yr dividends)")
        w(f"{'Metric':<34}{names[0]:>30}{names[1]:>30}")
        w(row("Strategy CAGR",        lambda v: f"{v['_metrics'].cagr:.2%}"))
        w(row("Excess Return vs Bmk",  lambda v: f"{v['_metrics'].cagr - bm_cagr:+.2%}"))
        w(row("Alpha (Jensen, ann.)",  lambda v: f"{v['_metrics'].alpha:+.2%}"))
        w(row("Beta",                  lambda v: f"{v['_metrics'].beta:.2f}"))
        w(row("Information Ratio",      lambda v: f"{v['_metrics'].information_ratio:.2f}"))
        w(row("Tracking Error",         lambda v: f"{v['_metrics'].tracking_error:.2%}"))
    else:
        w("Benchmark unavailable — no comparison produced.")
    w("")

    # ── Rolling 3Y CAGR ──
    w("-" * 100)
    w("5. ROLLING 3-YEAR CAGR (min / median / max across all windows)")
    w("-" * 100)
    for n in names:
        roll = variants[n]["_roll3y"]
        if not roll.empty:
            w(f"   {n:<16}: min {roll.min():.1%}  |  median {roll.median():.1%}  |  max {roll.max():.1%}")
    w("")

    # ── Year-wise ──
    w("-" * 100)
    w("6. YEAR-WISE RETURNS")
    w("-" * 100)
    yhead = f"{'Year':<8}{names[0]:>20}{names[1]:>20}"
    if bm_available: yhead += f"{'NIFTY500(px)':>20}"
    w(yhead)
    all_years = sorted(set().union(*[set(variants[n]["_annual"].index) for n in names]))
    for yr in all_years:
        line = f"{yr:<8}"
        for n in names:
            v = variants[n]["_annual"].get(yr, np.nan)
            line += f"{'N/A':>20}" if pd.isna(v) else f"{v:>19.1%} "
        if bm_available:
            bv = bm_annual.get(yr, np.nan)
            line += f"{'N/A':>20}" if pd.isna(bv) else f"{bv:>19.1%} "
        w(line)
    w("-" * 100)
    avg = f"{'Avg':<8}"
    for n in names:
        avg += f"{variants[n]['_annual'].mean():>19.1%} "
    if bm_available and not bm_annual.empty:
        avg += f"{bm_annual.mean():>19.1%} "
    w(avg)
    w("=" * 100)

    # ── Verdict ──
    w("")
    w("VERDICT".center(100, "-"))
    fb_cagr, n5_cagr = fb["_metrics"].cagr, n5["_metrics"].cagr
    survives = n5_cagr >= 0.12   # still a strong double-digit momentum return
    w(f"  Fallback (49)  CAGR {fb_cagr:.2%} | MaxDD {fb['_metrics'].max_drawdown:.2%} | "
      f"Sharpe {fb['_metrics'].sharpe_ratio:.2f} | Calmar {fb['_metrics'].calmar_ratio:.2f}")
    w(f"  NIFTY 500      CAGR {n5_cagr:.2%} | MaxDD {n5['_metrics'].max_drawdown:.2%} | "
      f"Sharpe {n5['_metrics'].sharpe_ratio:.2f} | Calmar {n5['_metrics'].calmar_ratio:.2f}")
    w(f"  CAGR change on widening universe: {n5_cagr - fb_cagr:+.2%}")
    if bm_available:
        w(f"  NIFTY 500 excess vs price index : {n5_cagr - bm_cagr:+.2%}  "
          f"(alpha {n5['_metrics'].alpha:+.2%})")
    w("")
    if survives:
        w("  => Momentum alpha SURVIVES the move to the full NIFTY 500. The champion")
        w("     remains a strong double-digit-CAGR strategy on the intended universe.")
    else:
        w("  => Momentum alpha DEGRADES materially on the full NIFTY 500. The prior")
        w("     numbers were inflated by the narrow 49-stock large-cap universe.")
    w("  (Remember the survivorship-bias and price-vs-TRI caveats above.)")
    w("=" * 100)

    report_txt = "\n".join(lines)
    print("\n" + report_txt)
    (results_dir / "report.txt").write_text(report_txt, encoding="utf-8")
    print(f"\n  Report saved: {results_dir / 'report.txt'}")

    # ── CSV ──
    rows = []
    for n in names:
        v = variants[n]; m = v["_metrics"]; e = v["_extra"]; roll = v["_roll3y"]
        rows.append({
            "universe": n,
            "n_stocks_universe": (fb_cov if n == names[0] else n5_cov)["n_loaded"],
            "cagr": m.cagr, "total_return": m.total_return,
            "max_drawdown": m.max_drawdown, "sharpe": m.sharpe_ratio,
            "sortino": m.sortino_ratio, "calmar": m.calmar_ratio,
            "annual_vol": m.annualised_volatility,
            "final_value": v["equity_curve"].iloc[-1],
            "peak_value": e["peak_value"], "value_at_maxdd": e["trough_value"],
            "time_underwater_pct": e["time_underwater_pct"],
            "recovery": e["recovery_str"],
            "total_rebalances": v["total_rebalances"],
            "total_trades": v["total_trades"], "avg_turnover": v["avg_turnover"],
            "total_costs": v["total_costs"],
            "gross_cagr": v["_gross_cagr"],
            "cost_drag_cagr_pts": v["_gross_cagr"] - m.cagr,
            "benchmark_price_cagr": bm_cagr,
            "excess_vs_benchmark": m.cagr - bm_cagr if bm_available else np.nan,
            "alpha": m.alpha, "beta": m.beta,
            "information_ratio": m.information_ratio,
            "rolling3y_min": roll.min() if not roll.empty else np.nan,
            "rolling3y_median": roll.median() if not roll.empty else np.nan,
            "rolling3y_max": roll.max() if not roll.empty else np.nan,
        })
    pd.DataFrame(rows).to_csv(results_dir / "comparison.csv", index=False)
    print(f"  CSV saved: {results_dir / 'comparison.csv'}")

    ydf = pd.DataFrame({n: variants[n]["_annual"] for n in names})
    if bm_available and not bm_annual.empty:
        ydf["NIFTY500_price"] = bm_annual
    ydf.index.name = "year"
    ydf.to_csv(results_dir / "yearwise_returns.csv")
    print(f"  CSV saved: {results_dir / 'yearwise_returns.csv'}")

    # diagnostics CSV
    pd.DataFrame([
        {"universe": names[0], **fb_cov, "failed": 0},
        {"universe": names[1], **n5_cov, "failed": len(n5_failed)},
    ]).to_csv(results_dir / "universe_diagnostics.csv", index=False)
    print(f"  CSV saved: {results_dir / 'universe_diagnostics.csv'}")

    print(f"\n  All outputs in: {results_dir}/")
    return fb, n5, fb_cov, n5_cov, n5_failed, bm_cagr, bm_available


if __name__ == "__main__":
    main()
