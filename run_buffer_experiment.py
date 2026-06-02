"""
RANKING-BUFFER TURNOVER EXPERIMENT.

Question: Does holding existing positions until their momentum rank decays past
a buffer (10 / 15 / 20) — instead of selling the moment they leave the Top 5 —
improve risk-adjusted returns by cutting turnover, without sacrificing alpha?

FIXED BASELINE (unchanged from the validated pure-momentum strategy):
  - Universe: same point-in-time liquidity/quality filters
  - Signal: pure 12-1 cross-sectional momentum
  - Portfolio: Top 5, equal weight, quarterly rebalance
  - No stops / no DD liquidation / no cooldown / no regime / no blending
  - Same Indian-equity transaction cost model, same dates

ONLY CHANGE per variant: the ranking buffer.
  - Baseline  : sell a holding as soon as it leaves the Top 5      (buffer = 5)
  - Buffer 10 : keep a holding until its rank falls past 10
  - Buffer 15 : keep a holding until its rank falls past 15
  - Buffer 20 : keep a holding until its rank falls past 20
  Portfolio size stays fixed at 5; empty slots are filled with the best-ranked
  stocks not already held.

All reported figures are NET of costs (the baseline numbers the user quoted are net).
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
from tqdm import tqdm

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

from config import SystemConfig, RESULTS_DIR
from data.downloader import download_all_stocks, build_price_panel
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from universe.universe_builder import UniverseBuilder
from costs.cost_model import CostModel
from analytics.metrics import compute_metrics
from utils.helpers import get_rebalance_dates

# Reuse the exact 12-1 momentum scorer from the validated strategy.
from run_pure_momentum import compute_12_1_momentum


# ─────────────────────────────────────────────────────────────────────
# BUFFERED SELECTION  (the ONLY logic that differs from baseline)
# ─────────────────────────────────────────────────────────────────────

def select_with_buffer(
    momentum_scores: pd.Series,
    current_holdings: dict,
    n_stocks: int,
    buffer: int,
) -> list:
    """
    Pick the target Top-N with a ranking buffer.

    1. Retain each currently-held stock whose momentum rank is within `buffer`
       (rank 1 = best). A holding that left the universe entirely has rank = inf
       and is therefore dropped.
    2. Fill the remaining slots (up to n_stocks) with the highest-ranked stocks
       not already retained.

    With buffer == n_stocks this reduces to the plain Top-N selection (baseline):
    a held stock is kept only if it is still inside the Top-N, which is exactly
    "sell when it leaves the Top-N".
    """
    ranked = list(momentum_scores.index)           # already sorted best→worst
    rank_of = {sym: i + 1 for i, sym in enumerate(ranked)}

    # 1. Retain in-buffer holdings, ordered best-rank first.
    retained = sorted(
        (s for s in current_holdings if rank_of.get(s, np.inf) <= buffer),
        key=lambda s: rank_of[s],
    )[:n_stocks]

    # 2. Fill empty slots from the top of the ranking.
    selected = list(retained)
    retained_set = set(retained)
    for sym in ranked:
        if len(selected) >= n_stocks:
            break
        if sym not in retained_set:
            selected.append(sym)

    return selected


# ─────────────────────────────────────────────────────────────────────
# BACKTEST  (identical to run_pure_momentum, buffer-aware selection only)
# ─────────────────────────────────────────────────────────────────────

def run_buffered_backtest(
    close_panel, high_panel, low_panel, volume_panel,
    n_stocks: int,
    rebalance_freq: str,
    buffer: int,
    initial_capital: float,
    config: SystemConfig,
    apply_costs: bool = True,
    label: str = "",
) -> dict:
    cfg = config
    start = pd.Timestamp(cfg.backtest.start_date)
    end = pd.Timestamp(cfg.backtest.end_date)

    data_start = close_panel.index.min()
    data_end = close_panel.index.max()
    start = max(start, data_start + pd.Timedelta(days=365))
    end = min(end, data_end)

    all_dates = close_panel.index[(close_panel.index >= start) & (close_panel.index <= end)]
    if all_dates.empty:
        return {"equity_curve": pd.Series(dtype=float), "returns": pd.Series(dtype=float)}

    rebal_set = set(get_rebalance_dates(all_dates, rebalance_freq))

    # Forward-filled prices for DAILY VALUATION ONLY. A held stock with a missing
    # close on a partial-data date (e.g. the one-off incomplete date 2026-05-28,
    # the only <90%-coverage day in the sample) must not be marked to zero — that
    # injects a fake one-day crash-and-recover into the drawdown. Signals and
    # trade-execution prices still use the raw close_panel, so baseline mechanics
    # are unchanged.
    valuation_panel = close_panel.ffill()

    universe_builder = UniverseBuilder(
        close_panel, high_panel, low_panel, volume_panel, cfg.universe,
    )
    cost_model = CostModel(cfg.costs)

    cash = initial_capital
    current_holdings = {}
    equity_values = []
    trades_history = []
    total_costs = 0.0
    total_rebalances = 0
    total_turnover = 0.0

    desc = f"[{'net' if apply_costs else 'gross'}] {label}"

    for date in tqdm(all_dates, desc=desc, unit="day"):
        today_close = close_panel.loc[date]
        today_value = valuation_panel.loc[date]   # ffilled, for valuation only

        holdings_value = sum(
            qty * today_value.get(sym, 0)
            for sym, qty in current_holdings.items()
            if not np.isnan(today_value.get(sym, np.nan))
        )
        portfolio_value = cash + holdings_value

        equity_values.append({"date": date, "portfolio_value": portfolio_value})

        if date not in rebal_set:
            continue

        total_rebalances += 1

        universe = universe_builder.build_universe(date)
        if not universe.symbols:
            continue

        momentum_scores = compute_12_1_momentum(close_panel, date, universe.symbols)
        if momentum_scores.empty or len(momentum_scores) < n_stocks:
            continue

        # ── ONLY DIFFERENCE FROM BASELINE: buffered selection ──
        selected = select_with_buffer(momentum_scores, current_holdings, n_stocks, buffer)

        per_stock = portfolio_value / n_stocks
        target_shares = {}
        for sym in selected:
            price = today_close.get(sym, np.nan)
            if np.isnan(price) or price <= 0:
                continue
            shares = int(per_stock / price)
            if shares > 0:
                target_shares[sym] = shares

        sells_value = 0.0
        buys_value = 0.0

        # SELL everything not in target (or trimmed)
        for sym, qty in list(current_holdings.items()):
            target_qty = target_shares.get(sym, 0)
            sell_qty = qty - target_qty
            if sell_qty <= 0:
                continue
            price = today_close.get(sym, 0)
            if price <= 0:
                continue
            sell_value = sell_qty * price
            cost = 0.0
            if apply_costs:
                tier = universe.liquidity_tiers.get(sym, 2)
                cost = cost_model.calculate_trade_cost(
                    sym, "SELL", sell_qty, price, liquidity_tier=tier).total_cost
            cash += sell_value - cost
            total_costs += cost
            sells_value += sell_value
            current_holdings[sym] = qty - sell_qty
            if current_holdings[sym] <= 0:
                del current_holdings[sym]
            trades_history.append({"date": date, "symbol": sym, "side": "SELL",
                                   "shares": sell_qty, "price": price,
                                   "value": sell_value, "cost": cost})

        # BUY toward target
        for sym, target_qty in target_shares.items():
            buy_qty = target_qty - current_holdings.get(sym, 0)
            if buy_qty <= 0:
                continue
            price = today_close.get(sym, 0)
            if price <= 0:
                continue
            buy_value = buy_qty * price
            cost = 0.0
            tier = universe.liquidity_tiers.get(sym, 2)
            if apply_costs:
                cost = cost_model.calculate_trade_cost(
                    sym, "BUY", buy_qty, price, liquidity_tier=tier).total_cost
            total_buy_cost = buy_value + cost
            if total_buy_cost > cash:
                affordable = int((cash - cost) / price) if price > 0 else 0
                if affordable <= 0:
                    continue
                buy_qty = affordable
                buy_value = buy_qty * price
                if apply_costs:
                    cost = cost_model.calculate_trade_cost(
                        sym, "BUY", buy_qty, price, liquidity_tier=tier).total_cost
                total_buy_cost = buy_value + cost
            cash -= total_buy_cost
            total_costs += cost
            buys_value += buy_value
            current_holdings[sym] = current_holdings.get(sym, 0) + buy_qty
            trades_history.append({"date": date, "symbol": sym, "side": "BUY",
                                   "shares": buy_qty, "price": price,
                                   "value": buy_value, "cost": cost})

        rebal_turnover = max(sells_value, buys_value) / portfolio_value if portfolio_value > 0 else 0
        total_turnover += rebal_turnover

    eq_df = pd.DataFrame(equity_values).set_index("date")
    equity_curve = eq_df["portfolio_value"]
    returns = equity_curve.pct_change().fillna(0)

    return {
        "equity_curve": equity_curve,
        "returns": returns,
        "trades": trades_history,
        "total_costs": total_costs,
        "total_rebalances": total_rebalances,
        "total_trades": len(trades_history),
        "avg_turnover": total_turnover / total_rebalances if total_rebalances else 0,
    }


# ─────────────────────────────────────────────────────────────────────
# EXTENDED DRAWDOWN / RECOVERY ANALYTICS
# ─────────────────────────────────────────────────────────────────────

def drawdown_analytics(equity_curve: pd.Series) -> dict:
    """Peak value, value at trough, time underwater, recovery time."""
    eq = equity_curve.dropna()
    cummax = eq.cummax()
    dd = (eq - cummax) / cummax

    trough_date = dd.idxmin()
    trough_value = eq.loc[trough_date]
    peak_value = float(eq.max())

    # Peak that preceded the deepest trough.
    pre = eq.loc[:trough_date]
    peak_before_trough = float(pre.max())
    peak_date = pre.idxmax()

    # Time underwater: % of days where equity sits below its running peak.
    time_underwater = float((dd < 0).mean())

    # Recovery: first date after the trough where equity regains the prior peak.
    after = eq.loc[trough_date:]
    recovered = after[after >= peak_before_trough]
    if len(recovered) > 0:
        recovery_date = recovered.index[0]
        recovery_days = (recovery_date - trough_date).days
        drawdown_days = (recovery_date - peak_date).days
        recovery_str = f"{recovery_days} days (recovered {recovery_date.date()})"
    else:
        recovery_days = None
        drawdown_days = (eq.index[-1] - peak_date).days
        recovery_str = "Not recovered by end of sample"

    return {
        "peak_value": peak_value,
        "trough_value": float(trough_value),
        "trough_date": trough_date,
        "time_underwater_pct": time_underwater,
        "recovery_str": recovery_str,
        "recovery_days": recovery_days,
        "full_dd_episode_days": drawdown_days,
    }


def rolling_3y_cagr(returns: pd.Series) -> pd.Series:
    window = 252 * 3
    if len(returns) <= window:
        return pd.Series(dtype=float)
    roll = (1 + returns).rolling(window).apply(
        lambda x: x.prod() ** (252 / window) - 1, raw=True)
    return roll.dropna()


def annual_returns(equity_curve: pd.Series) -> pd.Series:
    yearly = equity_curve.groupby(equity_curve.index.year).agg(["first", "last"])
    return (yearly["last"] / yearly["first"]) - 1


# ─────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────

PALETTE = {
    "Baseline": "#ff6b6b",
    "Buffer10": "#ffd93d",
    "Buffer15": "#4ecdc4",
    "Buffer20": "#00ff88",
}


def make_charts(variants: dict, benchmark_equity: pd.Series, save_path: Path):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 22))
    gs = GridSpec(4, 2, figure=fig, hspace=0.32, wspace=0.22)
    fig.suptitle("Ranking-Buffer Turnover Experiment — Top 5 / Quarterly / 12-1 Momentum (Net)",
                 fontsize=16, fontweight="bold", y=0.995, color="#fff")

    # 1. Equity curves (log scale)
    ax1 = fig.add_subplot(gs[0, :])
    ax1.set_title("Equity Curve (base 100, log scale)", fontweight="bold")
    for name, v in variants.items():
        eq = v["equity_curve"]
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
    for name, v in variants.items():
        eq = v["equity_curve"]
        dd = (eq - eq.cummax()) / eq.cummax() * 100
        ax2.plot(dd.index, dd.values, color=PALETTE[name], linewidth=1.0, label=name)
    ax2.set_ylabel("Drawdown (%)")
    ax2.legend(loc="lower left", framealpha=0.3)
    ax2.grid(True, alpha=0.2)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # 3. Trade count
    ax3 = fig.add_subplot(gs[2, 0])
    ax3.set_title("Total Trades", fontweight="bold")
    names = list(variants.keys())
    trades = [variants[n]["total_trades"] for n in names]
    bars = ax3.bar(names, trades, color=[PALETTE[n] for n in names])
    for b, t in zip(bars, trades):
        ax3.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{t}",
                 ha="center", va="bottom", color="#fff", fontweight="bold")
    ax3.set_ylabel("Trades")
    ax3.grid(True, alpha=0.2, axis="y")

    # 4. Transaction costs
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.set_title("Total Transaction Costs (₹)", fontweight="bold")
    costs = [variants[n]["total_costs"] for n in names]
    bars = ax4.bar(names, costs, color=[PALETTE[n] for n in names])
    for b, c in zip(bars, costs):
        ax4.text(b.get_x() + b.get_width() / 2, b.get_height(), f"₹{c/1000:.0f}k",
                 ha="center", va="bottom", color="#fff", fontweight="bold")
    ax4.set_ylabel("Cost (₹)")
    ax4.grid(True, alpha=0.2, axis="y")

    # 5. Rolling 3Y CAGR
    ax5 = fig.add_subplot(gs[3, :])
    ax5.set_title("Rolling 3-Year CAGR", fontweight="bold")
    for name, v in variants.items():
        roll = rolling_3y_cagr(v["returns"])
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
    N_STOCKS = 5
    FREQ = "quarterly"

    print("=" * 72)
    print("  RANKING-BUFFER TURNOVER EXPERIMENT")
    print(f"  Top {N_STOCKS} / {FREQ} / equal weight / 12-1 momentum / net of costs")
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
    print(f"  Loaded {len(close_panel)} dates x {len(close_panel.columns)} stocks in {time.time()-t0:.1f}s")

    benchmark_returns = get_benchmark_returns(config.backtest.start_date, config.backtest.end_date)
    benchmark_equity = get_benchmark_equity_curve(
        config.backtest.start_date, config.backtest.end_date, initial_capital)

    # buffer == 5 reproduces the baseline (sell on leaving Top 5)
    configs = [("Baseline", 5), ("Buffer10", 10), ("Buffer15", 15), ("Buffer20", 20)]

    variants = {}
    metrics = {}
    extra = {}
    annuals = {}
    cost_drag = {}   # true cost drag = gross CAGR - net CAGR

    for name, buffer in configs:
        print(f"\n{'-'*72}\n  {name}  (buffer = {buffer})\n{'-'*72}")
        res = run_buffered_backtest(
            close_panel, high_panel, low_panel, volume_panel,
            n_stocks=N_STOCKS, rebalance_freq=FREQ, buffer=buffer,
            initial_capital=initial_capital, config=config,
            apply_costs=True, label=name,
        )
        gross = run_buffered_backtest(
            close_panel, high_panel, low_panel, volume_panel,
            n_stocks=N_STOCKS, rebalance_freq=FREQ, buffer=buffer,
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
        variants[name] = res
        metrics[name] = m
        extra[name] = drawdown_analytics(res["equity_curve"])
        annuals[name] = annual_returns(res["equity_curve"])
        cost_drag[name] = gross_m.cagr - m.cagr   # CAGR points lost to costs
        print(f"  CAGR {m.cagr:.2%} (gross {gross_m.cagr:.2%}) | MaxDD {m.max_drawdown:.2%} | "
              f"Final ₹{res['equity_curve'].iloc[-1]:,.0f} | Trades {res['total_trades']} | "
              f"Costs ₹{res['total_costs']:,.0f}")

    results_dir = RESULTS_DIR / "ranking_buffer"
    results_dir.mkdir(parents=True, exist_ok=True)

    # ── Charts ──
    make_charts(variants, benchmark_equity, results_dir / "report.png")

    # ── Build the comparison report text ──
    names = list(variants.keys())
    lines = []

    def w(s=""):
        lines.append(s)

    w("=" * 100)
    w("RANKING-BUFFER TURNOVER EXPERIMENT — COMPARISON REPORT".center(100))
    w("Top 5 / Quarterly / Equal Weight / 12-1 Momentum / Net of Costs".center(100))
    w("=" * 100)
    w(f"Initial Capital: ₹{initial_capital:,.0f}")
    w(f"Period: {metrics[names[0]].start_date} to {metrics[names[0]].end_date}")
    w("NOTE: Daily valuation forward-fills a missing close so a held stock is not")
    w("      marked to zero on the one partial-data date (2026-05-28, the only")
    w("      <90%-coverage day). Without this, that single day fabricated a ~-68%")
    w("      one-day crash-and-recover and dominated every drawdown number.")
    w("      Signals and trade prices are unchanged; the baseline strategy is intact.")
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
    w(row("2. Total Return", lambda n: f"{metrics[n].total_return:.1%}"))
    w(row("3. Final Value (₹)", lambda n: f"{variants[n]['equity_curve'].iloc[-1]:,.0f}"))
    w(row("4. Max Drawdown", lambda n: f"{metrics[n].max_drawdown:.2%}"))
    w(row("5. Sharpe Ratio", lambda n: f"{metrics[n].sharpe_ratio:.2f}"))
    w(row("6. Calmar Ratio", lambda n: f"{metrics[n].calmar_ratio:.2f}"))
    w(row("7. Annual Volatility", lambda n: f"{metrics[n].annualised_volatility:.2%}"))
    w(row("8. Total Trades (exec)", lambda n: f"{variants[n]['total_trades']}"))
    w(row("9. Total Txn Costs (₹)", lambda n: f"{variants[n]['total_costs']:,.0f}"))
    w(row("10. Cost Drag (CAGR pts)", lambda n: f"{cost_drag[n]:.2%}"))
    w(row("11. Peak Value (₹)", lambda n: f"{extra[n]['peak_value']:,.0f}"))
    w(row("12. Value @ Max DD (₹)", lambda n: f"{extra[n]['trough_value']:,.0f}"))
    w(row("13. Time Underwater", lambda n: f"{extra[n]['time_underwater_pct']:.1%}"))
    w(row("14. Avg Turnover/Rebal", lambda n: f"{variants[n]['avg_turnover']:.1%}"))
    w("-" * 100)
    w("")

    # Recovery time (longer text, list form)
    w("14b. RECOVERY TIME (from deepest drawdown trough back to prior peak):")
    for n in names:
        w(f"     {n:<10}: trough {extra[n]['trough_date'].date()} → {extra[n]['recovery_str']}")
    w("")

    # Rolling 3Y CAGR summary
    w("15. ROLLING 3-YEAR CAGR (min / median / max across all 3Y windows):")
    for n in names:
        roll = rolling_3y_cagr(variants[n]["returns"])
        if not roll.empty:
            w(f"     {n:<10}: min {roll.min():.1%}  |  median {roll.median():.1%}  |  max {roll.max():.1%}")
    w("")

    # Year-wise returns table
    w("16. YEAR-WISE RETURNS")
    w("-" * 100)
    yhead = f"{'Year':<8}"
    for n in names:
        yhead += f"{n:>17}"
    yhead += f"{'NIFTY500':>17}"
    w(yhead)
    bm_annual = annual_returns(benchmark_equity) if benchmark_equity is not None and not benchmark_equity.empty else pd.Series(dtype=float)
    all_years = sorted(set().union(*[set(annuals[n].index) for n in names]))
    for yr in all_years:
        line = f"{yr:<8}"
        for n in names:
            v = annuals[n].get(yr, np.nan)
            line += f"{'N/A':>17}" if pd.isna(v) else f"{v:>16.1%} "
        bv = bm_annual.get(yr, np.nan)
        line += f"{'N/A':>17}" if pd.isna(bv) else f"{bv:>16.1%} "
        w(line)
    w("-" * 100)
    avg_line = f"{'Avg':<8}"
    for n in names:
        avg_line += f"{annuals[n].mean():>16.1%} "
    w(avg_line)
    w("=" * 100)

    # ── Recommendation ──
    base = "Baseline"
    w("")
    w("RECOMMENDATION".center(100, "─"))
    w("")
    bcagr = metrics[base].cagr
    bdd = metrics[base].max_drawdown
    btr = variants[base]["total_trades"]
    bcost = variants[base]["total_costs"]

    for n in names:
        if n == base:
            continue
        d_cagr = metrics[n].cagr - bcagr
        d_dd = metrics[n].max_drawdown - bdd  # positive = shallower DD (improvement)
        d_tr = (variants[n]["total_trades"] - btr) / btr if btr else 0
        d_cost = (variants[n]["total_costs"] - bcost) / bcost if bcost else 0
        w(f"{n} vs Baseline:")
        w(f"   CAGR delta        : {d_cagr:+.2%}  (retains {metrics[n].cagr/bcagr:.0%} of baseline CAGR)")
        w(f"   Max DD delta      : {d_dd:+.2%}  ({'shallower' if d_dd > 0 else 'deeper'})")
        w(f"   Calmar            : {metrics[n].calmar_ratio:.2f} vs {metrics[base].calmar_ratio:.2f}")
        w(f"   Sharpe            : {metrics[n].sharpe_ratio:.2f} vs {metrics[base].sharpe_ratio:.2f}")
        w(f"   Trades (exec)     : {variants[n]['total_trades']} ({d_tr:+.0%})")
        w(f"   Avg turnover      : {variants[n]['avg_turnover']:.1%} vs {variants[base]['avg_turnover']:.1%}")
        w(f"   Costs             : ₹{variants[n]['total_costs']:,.0f} ({d_cost:+.0%})")
        w("")

    # Pick winner: best Calmar among variants that retain >=95% of baseline CAGR,
    # else best risk-adjusted (Calmar) overall, with turnover as tiebreak signal.
    def score(n):
        return metrics[n].calmar_ratio
    candidates = [n for n in names if n != base]
    retainers = [n for n in candidates if metrics[n].cagr >= 0.95 * bcagr]
    pool = retainers if retainers else candidates
    best = max(pool, key=score)

    w("VERDICT".center(100, "─"))
    w(f"  Best balance of CAGR retention / drawdown / turnover / costs: {best}")
    w(f"    CAGR {metrics[best].cagr:.2%} (baseline {bcagr:.2%}), "
      f"MaxDD {metrics[best].max_drawdown:.2%} (baseline {bdd:.2%}),")
    w(f"    Calmar {metrics[best].calmar_ratio:.2f} (baseline {metrics[base].calmar_ratio:.2f}), "
      f"Trades {variants[best]['total_trades']} vs {btr}, "
      f"turnover {variants[best]['avg_turnover']:.1%} vs {variants[base]['avg_turnover']:.1%}, "
      f"Costs ₹{variants[best]['total_costs']:,.0f} vs ₹{bcost:,.0f}.")
    w("=" * 100)

    report_txt = "\n".join(lines)
    print("\n" + report_txt)
    (results_dir / "report.txt").write_text(report_txt, encoding="utf-8")
    print(f"\n  Report saved: {results_dir / 'report.txt'}")

    # ── CSV (machine-readable comparison) ──
    rows = []
    for n in names:
        m = metrics[n]
        e = extra[n]
        roll = rolling_3y_cagr(variants[n]["returns"])
        rows.append({
            "variant": n,
            "cagr": m.cagr,
            "total_return": m.total_return,
            "final_value": variants[n]["equity_curve"].iloc[-1],
            "max_drawdown": m.max_drawdown,
            "sharpe": m.sharpe_ratio,
            "calmar": m.calmar_ratio,
            "annual_vol": m.annualised_volatility,
            "total_trades_exec": variants[n]["total_trades"],
            "total_costs": variants[n]["total_costs"],
            "cost_drag_cagr_pts": cost_drag[n],
            "peak_value": e["peak_value"],
            "value_at_maxdd": e["trough_value"],
            "time_underwater_pct": e["time_underwater_pct"],
            "recovery": e["recovery_str"],
            "avg_turnover": variants[n]["avg_turnover"],
            "rolling3y_cagr_min": roll.min() if not roll.empty else np.nan,
            "rolling3y_cagr_median": roll.median() if not roll.empty else np.nan,
            "rolling3y_cagr_max": roll.max() if not roll.empty else np.nan,
        })
    pd.DataFrame(rows).to_csv(results_dir / "comparison.csv", index=False)
    print(f"  CSV saved: {results_dir / 'comparison.csv'}")

    # Year-wise CSV
    ydf = pd.DataFrame({n: annuals[n] for n in names})
    if not bm_annual.empty:
        ydf["NIFTY500_TRI"] = bm_annual
    ydf.index.name = "year"
    ydf.to_csv(results_dir / "yearwise_returns.csv")
    print(f"  CSV saved: {results_dir / 'yearwise_returns.csv'}")

    print(f"\n  All outputs in: {results_dir}/")


if __name__ == "__main__":
    main()
