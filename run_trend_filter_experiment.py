"""
EXPERIMENT 1 — MARKET TREND FILTER (risk overlay) on the survivorship-free champion.

FIXED BASELINE (do NOT change — identical to the survivorship-free baseline):
  - Universe   : survivorship-free, full NSE bhavcopy cross-section, point-in-time
                 top-500-by-turnover (TopNTurnoverUniverseBuilder).
  - Signal     : pure 12-1 cross-sectional momentum.
  - Portfolio  : Top 5, equal weight, quarterly rebalance, Buffer20.
  - Costs      : same Indian-equity delivery cost model, same dates, same benchmark.

ONLY CHANGE per variant: a market-trend gate on the NIFTY 500 PRICE index. When the
index is in a downtrend the book is liquidated to cash; when the uptrend resumes the
*same* momentum book (most recent quarterly selection) is redeployed. The momentum
selection itself (which 5 names, Buffer20 retention) is computed every quarter exactly
as in the baseline, regardless of the gate — the gate only toggles 0/1 exposure.

  1. No Filter            — always invested  (reproduces the survivorship-free baseline)
  2. NIFTY 500 > 200 DMA  — daily 200-trading-day SMA, checked every day
  3. NIFTY 500 > 10-Month SMA — month-end close vs 10-month SMA, checked monthly
  4. NIFTY 500 > 12-Month SMA — month-end close vs 12-month SMA, checked monthly

Gate timing: 1-trading-day lag (decision uses the prior close, no lookahead). Switching
trades pay the full cost model on the liquidated / redeployed value.

All figures NET of costs. Benchmark = NIFTY 500 PRICE index (true TRI ~+1.3%/yr higher).
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
from tqdm import tqdm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

from config import SystemConfig, RESULTS_DIR
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns, load_tri_csv
from costs.cost_model import CostModel
from analytics.metrics import compute_metrics
from utils.helpers import get_rebalance_dates

from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import (
    select_with_buffer, drawdown_analytics, rolling_3y_cagr, annual_returns,
)
from run_survivorship_validation import TopNTurnoverUniverseBuilder

N_STOCKS, BUFFER, FREQ = 5, 20, "quarterly"
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"

PALETTE = {
    "No Filter": "#ff6b6b",
    "200 DMA": "#ffd93d",
    "10-Mo SMA": "#4ecdc4",
    "12-Mo SMA": "#00ff88",
}


# ─────────────────────────────────────────────────────────────────────
# TREND-GATE SIGNAL CONSTRUCTION  (on the NIFTY 500 price index)
# ─────────────────────────────────────────────────────────────────────

def build_trend_signals(trading_dates: pd.DatetimeIndex) -> dict:
    """
    Build daily boolean 'risk-on' signals (True = invested) aligned to the strategy's
    trading dates, for each trend-filter variant. 1-trading-day lag, no lookahead.
    Where history is insufficient (warm-up) the gate defaults to invested (True), so the
    early sample matches the baseline rather than sitting in cash on a NaN.
    """
    idx = load_tri_csv()["tri_value"].sort_index()
    idx = idx[~idx.index.duplicated(keep="last")]

    def to_daily(sig_native: pd.Series) -> pd.Series:
        """Reindex a signal (daily- or month-end-dated) onto trading_dates, ffill,
        lag one trading day, default-invested on warm-up NaNs."""
        s = sig_native.reindex(trading_dates.union(sig_native.index)).ffill()
        s = s.reindex(trading_dates)
        s = s.shift(1)                       # act on the *next* trading day
        return s.fillna(True).astype(bool)

    signals = {"No Filter": pd.Series(True, index=trading_dates)}

    # 200-day SMA — daily cadence
    sma200 = idx.rolling(200).mean()
    signals["200 DMA"] = to_daily(idx > sma200)

    # 10/12-month SMA — month-end cadence (Faber GTAA construction)
    me = idx.resample("M").last()
    signals["10-Mo SMA"] = to_daily(me > me.rolling(10).mean())
    signals["12-Mo SMA"] = to_daily(me > me.rolling(12).mean())

    return signals


# ─────────────────────────────────────────────────────────────────────
# TREND-FILTERED BACKTEST
#   Identical to run_buffered_backtest except an exposure gate (signal_on)
#   toggles the book between fully-invested and 100% cash. The momentum
#   *selection* (paper book) still rebalances every quarter with Buffer20,
#   independent of the gate, so "Top5 / Buffer20 / quarterly / 12-1" is intact.
#   With signal_on == all True this reduces EXACTLY to the baseline engine.
# ─────────────────────────────────────────────────────────────────────

def _build_targets(selected, today_close, portfolio_value, n_stocks):
    per_stock = portfolio_value / n_stocks
    targets = {}
    for sym in selected:
        price = today_close.get(sym, np.nan)
        if np.isnan(price) or price <= 0:
            continue
        shares = int(per_stock / price)
        if shares > 0:
            targets[sym] = shares
    return targets


def run_trend_filtered_backtest(
    close_panel, high_panel, low_panel, volume_panel,
    n_stocks, rebalance_freq, buffer, initial_capital, config,
    signal_on: pd.Series, apply_costs=True, label="", universe_builder=None,
):
    cfg = config
    start = pd.Timestamp(cfg.backtest.start_date)
    end = pd.Timestamp(cfg.backtest.end_date)
    data_start, data_end = close_panel.index.min(), close_panel.index.max()
    start = max(start, data_start + pd.Timedelta(days=365))
    end = min(end, data_end)

    all_dates = close_panel.index[(close_panel.index >= start) & (close_panel.index <= end)]
    if all_dates.empty:
        return {"equity_curve": pd.Series(dtype=float), "returns": pd.Series(dtype=float)}

    rebal_set = set(get_rebalance_dates(all_dates, rebalance_freq))
    valuation_panel = close_panel.ffill()   # daily valuation only (see baseline note)
    gate = signal_on.reindex(all_dates).fillna(True).astype(bool)

    if universe_builder is None:
        from universe.universe_builder import UniverseBuilder
        universe_builder = UniverseBuilder(close_panel, high_panel, low_panel, volume_panel, cfg.universe)
    cost_model = CostModel(cfg.costs)

    cash = initial_capital
    current_holdings = {}        # ACTUAL book (gate-applied)
    paper_holdings = {}          # INTENDED book — buffer memory, gate-independent
    last_selected = None         # most recent quarterly momentum selection
    last_tiers = {}              # liquidity tiers from the most recent universe build

    equity_values, trades_history = [], []
    total_costs = 0.0
    total_rebalances = 0
    total_turnover = 0.0
    days_in_cash = 0
    n_switches = 0
    prev_gate = True

    desc = f"[{'net' if apply_costs else 'gross'}] {label}"
    for date in tqdm(all_dates, desc=desc, unit="day"):
        today_close = close_panel.loc[date]
        today_value = valuation_panel.loc[date]

        holdings_value = sum(
            qty * today_value.get(sym, 0)
            for sym, qty in current_holdings.items()
            if not np.isnan(today_value.get(sym, np.nan))
        )
        portfolio_value = cash + holdings_value
        equity_values.append({"date": date, "portfolio_value": portfolio_value})

        g = bool(gate.loc[date])
        if not g:
            days_in_cash += 1

        is_rebal = date in rebal_set

        # ── Quarterly: refresh the momentum selection + paper book (gate-independent) ──
        if is_rebal:
            universe = universe_builder.build_universe(date)
            if universe.symbols:
                scores = compute_12_1_momentum(close_panel, date, universe.symbols)
                if not scores.empty and len(scores) >= n_stocks:
                    last_selected = select_with_buffer(scores, paper_holdings, n_stocks, buffer)
                    last_tiers = universe.liquidity_tiers
                    paper_holdings = _build_targets(last_selected, today_close, portfolio_value, n_stocks)
                    total_rebalances += 1

        # ── Decide whether to trade today ──
        gate_flip = (g != prev_gate)
        if gate_flip:
            n_switches += 1
        should_trade = (is_rebal and last_selected is not None) or gate_flip
        if should_trade:
            if g and last_selected is not None:
                target_shares = _build_targets(last_selected, today_close, portfolio_value, n_stocks)
            else:
                target_shares = {}    # risk-off → all cash

            sells_value = buys_value = 0.0

            # SELL everything not in target (or trimmed)
            for sym, qty in list(current_holdings.items()):
                sell_qty = qty - target_shares.get(sym, 0)
                if sell_qty <= 0:
                    continue
                price = today_close.get(sym, np.nan)
                if not (price > 0):
                    price = today_value.get(sym, np.nan)   # delisted: exit at last mark
                if not (price > 0):
                    del current_holdings[sym]
                    continue
                sell_value = sell_qty * price
                cost = 0.0
                if apply_costs:
                    tier = last_tiers.get(sym, 2)
                    cost = cost_model.calculate_trade_cost(sym, "SELL", sell_qty, price, liquidity_tier=tier).total_cost
                cash += sell_value - cost
                total_costs += cost
                sells_value += sell_value
                current_holdings[sym] = qty - sell_qty
                if current_holdings[sym] <= 0:
                    del current_holdings[sym]
                trades_history.append({"date": date, "symbol": sym, "side": "SELL",
                                       "shares": sell_qty, "price": price, "value": sell_value, "cost": cost})

            # BUY toward target
            for sym, target_qty in target_shares.items():
                buy_qty = target_qty - current_holdings.get(sym, 0)
                if buy_qty <= 0:
                    continue
                price = today_close.get(sym, np.nan)
                if not (price > 0):
                    continue
                buy_value = buy_qty * price
                cost = 0.0
                tier = last_tiers.get(sym, 2)
                if apply_costs:
                    cost = cost_model.calculate_trade_cost(sym, "BUY", buy_qty, price, liquidity_tier=tier).total_cost
                total_buy_cost = buy_value + cost
                if total_buy_cost > cash:
                    affordable = int((cash - cost) / price) if price > 0 else 0
                    if affordable <= 0:
                        continue
                    buy_qty = affordable
                    buy_value = buy_qty * price
                    if apply_costs:
                        cost = cost_model.calculate_trade_cost(sym, "BUY", buy_qty, price, liquidity_tier=tier).total_cost
                    total_buy_cost = buy_value + cost
                cash -= total_buy_cost
                total_costs += cost
                buys_value += buy_value
                current_holdings[sym] = current_holdings.get(sym, 0) + buy_qty
                trades_history.append({"date": date, "symbol": sym, "side": "BUY",
                                       "shares": buy_qty, "price": price, "value": buy_value, "cost": cost})

            if portfolio_value > 0:
                total_turnover += max(sells_value, buys_value) / portfolio_value

        prev_gate = g

    eq_df = pd.DataFrame(equity_values).set_index("date")
    equity_curve = eq_df["portfolio_value"]
    returns = equity_curve.pct_change().fillna(0)
    return {
        "equity_curve": equity_curve, "returns": returns, "trades": trades_history,
        "total_costs": total_costs, "total_rebalances": total_rebalances,
        "total_trades": len(trades_history),
        "avg_turnover": total_turnover / total_rebalances if total_rebalances else 0,
        "pct_in_cash": days_in_cash / len(all_dates) if len(all_dates) else 0,
        "n_switches": n_switches,
    }


# ─────────────────────────────────────────────────────────────────────
# RUN ONE VARIANT (net + gross for honest cost drag)
# ─────────────────────────────────────────────────────────────────────

def run_variant(panels, cfg, cap, bench_ret, signal_on, label, builder):
    c, h, l, v = panels
    net = run_trend_filtered_backtest(c, h, l, v, N_STOCKS, FREQ, BUFFER, cap, cfg,
        signal_on=signal_on, apply_costs=True, label=label, universe_builder=builder)
    gross = run_trend_filtered_backtest(c, h, l, v, N_STOCKS, FREQ, BUFFER, cap, cfg,
        signal_on=signal_on, apply_costs=False, label=label + "(g)", universe_builder=builder)
    m = compute_metrics(net["equity_curve"], net["returns"], benchmark_returns=bench_ret,
        trades=net["trades"], total_costs=net["total_costs"], initial_capital=cap)
    gm = compute_metrics(gross["equity_curve"], gross["returns"], initial_capital=cap)
    net["_m"] = m
    net["_gross_cagr"] = gm.cagr
    net["_extra"] = drawdown_analytics(net["equity_curve"])
    net["_annual"] = annual_returns(net["equity_curve"])
    net["_roll3y"] = rolling_3y_cagr(net["returns"])
    return net


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("=" * 80)
    print("  EXPERIMENT 1 — MARKET TREND FILTER  (survivorship-free champion)")
    print("  Top5 / Quarterly / EW / Buffer20 / 12-1 momentum / net of costs")
    print("=" * 80)

    bench_ret = get_benchmark_returns(start, end)
    bench_eq = get_benchmark_equity_curve(start, end, cap)
    bm_annual = annual_returns(bench_eq) if not bench_eq.empty else pd.Series(dtype=float)
    bm_cagr = compute_metrics(bench_eq, initial_capital=cap).cagr if not bench_eq.empty else np.nan

    print("\nLoading survivorship-free bhavcopy panels ...")
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    print(f"  panel: {ac.shape[0]} dates x {ac.shape[1]} symbols")
    builder = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)

    # Trading dates the engine will actually iterate (mirror the engine's windowing).
    s0 = max(pd.Timestamp(start), ac.index.min() + pd.Timedelta(days=365))
    e0 = min(pd.Timestamp(end), ac.index.max())
    trading_dates = ac.index[(ac.index >= s0) & (ac.index <= e0)]
    signals = build_trend_signals(trading_dates)

    panels = (ac, ah, al, av)
    order = ["No Filter", "200 DMA", "10-Mo SMA", "12-Mo SMA"]
    variants = {}
    for name in order:
        print(f"\n{'-'*80}\n  {name}\n{'-'*80}")
        on = signals[name]
        variants[name] = run_variant(panels, cfg, cap, bench_ret, on, name, builder)
        v = variants[name]
        print(f"  CAGR {v['_m'].cagr:.2%} | MaxDD {v['_m'].max_drawdown:.2%} | "
              f"Sharpe {v['_m'].sharpe_ratio:.2f} | Calmar {v['_m'].calmar_ratio:.2f} | "
              f"Alpha {v['_m'].alpha:+.2%} | in-cash {v['pct_in_cash']:.0%} | "
              f"switches {v['n_switches']} | Final Rs {v['equity_curve'].iloc[-1]:,.0f}")

    rdir = RESULTS_DIR / "trend_filter"
    rdir.mkdir(parents=True, exist_ok=True)
    make_charts(variants, order, bench_eq, bm_annual, rdir / "report.png")
    write_report(variants, order, cap, bm_cagr, bm_annual, bench_eq, rdir)
    print(f"\n  All outputs in: {rdir}/")


# ─────────────────────────────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────────────────────────────

def make_charts(variants, names, bench_eq, bm_annual, save_path):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 24)); gs = GridSpec(5, 2, figure=fig, hspace=0.40, wspace=0.22)
    fig.suptitle("Experiment 1 — Market Trend Filter on the Survivorship-Free Champion\n"
                 "Top5 / Quarterly / EW / Buffer20 / 12-1 Momentum (Net)  —  gate on NIFTY 500 price index",
                 fontsize=15, fontweight="bold", y=0.995, color="#fff")

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; ax1.plot(eq.index, eq / eq.iloc[0] * 100, color=PALETTE[n], lw=1.8, label=n)
    if bench_eq is not None and not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq / bench_eq.iloc[0] * 100, color="#888", lw=1.3, ls="--", label="NIFTY 500 (price)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, :]); ax2.set_title("Drawdown", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; dd = (eq - eq.cummax()) / eq.cummax() * 100
        ax2.plot(dd.index, dd, color=PALETTE[n], lw=1.1, label=n)
    ax2.legend(loc="lower left", framealpha=.3); ax2.grid(True, alpha=.2); ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax3 = fig.add_subplot(gs[2, 0]); ax3.set_title("CAGR vs Max DD", fontweight="bold")
    cagrs = [variants[n]["_m"].cagr * 100 for n in names]; dds = [abs(variants[n]["_m"].max_drawdown) * 100 for n in names]
    b = ax3.bar(names, cagrs, color=[PALETTE[n] for n in names])
    for bb, cc in zip(b, cagrs): ax3.text(bb.get_x() + bb.get_width() / 2, bb.get_height(), f"{cc:.1f}%", ha="center", va="bottom", color="#fff", fontweight="bold")
    a3 = ax3.twinx(); a3.plot(names, dds, color="#ff6b6b", marker="o", lw=1.6); a3.set_ylabel("Max DD %", color="#ff6b6b")
    ax3.set_ylabel("CAGR %"); ax3.tick_params(axis="x", rotation=12); ax3.grid(True, alpha=.2, axis="y")

    ax4 = fig.add_subplot(gs[2, 1]); ax4.set_title("Sharpe / Sortino / Calmar", fontweight="bold")
    x = np.arange(len(names))
    ax4.bar(x - .25, [variants[n]["_m"].sharpe_ratio for n in names], .25, color="#4ecdc4", label="Sharpe")
    ax4.bar(x, [variants[n]["_m"].sortino_ratio for n in names], .25, color="#ffd93d", label="Sortino")
    ax4.bar(x + .25, [variants[n]["_m"].calmar_ratio for n in names], .25, color="#00ff88", label="Calmar")
    ax4.set_xticks(x); ax4.set_xticklabels(names, rotation=12); ax4.legend(framealpha=.3); ax4.grid(True, alpha=.2, axis="y")

    ax5 = fig.add_subplot(gs[3, :]); ax5.set_title("Rolling 3-Year CAGR", fontweight="bold")
    for n in names:
        r = variants[n]["_roll3y"]
        if not r.empty: ax5.plot(r.index, r * 100, color=PALETTE[n], lw=1.4, label=n)
    ax5.axhline(6.5, color="#ff6b6b", ls="--", lw=1, alpha=.6, label="FD 6.5%"); ax5.axhline(0, color="white", lw=.5, ls="--", alpha=.3)
    ax5.legend(loc="upper right", framealpha=.3); ax5.grid(True, alpha=.2); ax5.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax6 = fig.add_subplot(gs[4, :]); ax6.set_title("Year-wise Returns vs Benchmark", fontweight="bold")
    yrs = sorted(set().union(*[set(variants[n]["_annual"].index) for n in names]))
    xp = np.arange(len(yrs)); w = 0.8 / (len(names) + 1)
    for i, n in enumerate(names):
        ax6.bar(xp + i * w, [variants[n]["_annual"].get(y, np.nan) * 100 for y in yrs], w, color=PALETTE[n], label=n)
    if bm_annual is not None and not bm_annual.empty:
        ax6.bar(xp + len(names) * w, [bm_annual.get(y, np.nan) * 100 for y in yrs], w, color="#888", label="NIFTY500(px)")
    ax6.axhline(0, color="white", lw=.5, alpha=.3); ax6.set_xticks(xp + w * len(names) / 2); ax6.set_xticklabels(yrs, rotation=45)
    ax6.legend(framealpha=.3, ncol=5); ax6.grid(True, alpha=.2, axis="y")

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor()); plt.close(fig)
    print(f"  Chart saved: {save_path}")


# ─────────────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────────────

def write_report(variants, names, cap, bm_cagr, bm_annual, bench_eq, rdir):
    bm = not bench_eq.empty
    L = []; w = L.append
    def row(lbl, fmt):
        s = f"{lbl:<26}"
        for n in names: s += f"{fmt(variants[n]):>15}"
        return s

    w("=" * 96); w("EXPERIMENT 1 — MARKET TREND FILTER (RISK OVERLAY)".center(96))
    w("Survivorship-Free Champion: Top5 / Quarterly / EW / Buffer20 / 12-1 Momentum / Net".center(96)); w("=" * 96)
    w(f"Initial Capital: Rs {cap:,.0f}   Period: {variants[names[0]]['_m'].start_date}..{variants[names[0]]['_m'].end_date}")
    w("Gate on NIFTY 500 PRICE index, 1-day lag, no lookahead. Risk-off => 100% cash (0% interest).")
    w("200 DMA = daily 200-trading-day SMA. 10/12-Mo SMA = month-end close vs 10/12-month SMA.")
    w("Benchmark: NIFTY 500 PRICE index (true TRI ~ +1.3%/yr higher).")
    w("")
    w(f"{'Metric':<26}" + "".join(f"{n:>15}" for n in names)); w("-" * 96)
    w(row("CAGR", lambda v: f"{v['_m'].cagr:.2%}"))
    w(row("Total Return", lambda v: f"{v['_m'].total_return:.0%}"))
    w(row("Max Drawdown", lambda v: f"{v['_m'].max_drawdown:.2%}"))
    w(row("Sharpe", lambda v: f"{v['_m'].sharpe_ratio:.2f}"))
    w(row("Sortino", lambda v: f"{v['_m'].sortino_ratio:.2f}"))
    w(row("Calmar", lambda v: f"{v['_m'].calmar_ratio:.2f}"))
    w(row("Annual Vol", lambda v: f"{v['_m'].annualised_volatility:.2%}"))
    if bm:
        w(row("Alpha (Jensen ann.)", lambda v: f"{v['_m'].alpha:+.2%}"))
        w(row("Beta", lambda v: f"{v['_m'].beta:.2f}"))
        w(row("Excess vs Bmk (CAGR)", lambda v: f"{v['_m'].cagr - bm_cagr:+.2%}"))
    w(row("Final Value (Rs)", lambda v: f"{v['equity_curve'].iloc[-1]:,.0f}"))
    w(row("Time Underwater", lambda v: f"{v['_extra']['time_underwater_pct']:.1%}"))
    w(row("Recovery (deepest DD)", lambda v: f"{v['_extra']['recovery_days'] if v['_extra']['recovery_days'] is not None else 'none'}"))
    w(row("Pct Time in Cash", lambda v: f"{v['pct_in_cash']:.1%}"))
    w(row("Gate Switches", lambda v: f"{v['n_switches']}"))
    w(row("Trades (exec)", lambda v: f"{v['total_trades']}"))
    w(row("Avg Turnover/Rebal", lambda v: f"{v['avg_turnover']:.1%}"))
    w(row("Txn Costs (Rs)", lambda v: f"{v['total_costs']:,.0f}"))
    w(row("Cost Drag (CAGR pts)", lambda v: f"{v['_gross_cagr'] - v['_m'].cagr:.2%}"))
    w("-" * 96)
    if bm: w(f"NIFTY 500 price-index CAGR over period: {bm_cagr:.2%}  (true TRI ~ {bm_cagr + 0.013:.2%})")
    w("")
    w("RECOVERY TIME (deepest drawdown trough -> prior peak):")
    for n in names:
        e = variants[n]["_extra"]; w(f"   {n:<12}: trough {e['trough_date'].date()} -> {e['recovery_str']}")
    w("")
    w("ROLLING 3Y CAGR (min/median/max):")
    for n in names:
        r = variants[n]["_roll3y"]
        if not r.empty: w(f"   {n:<12}: min {r.min():.1%} | median {r.median():.1%} | max {r.max():.1%}")
    w("")
    w("YEAR-WISE RETURNS"); w("-" * 96)
    w(f"{'Year':<8}" + "".join(f"{n:>15}" for n in names) + (f"{'NIFTY500(px)':>15}" if bm else ""))
    yrs = sorted(set().union(*[set(variants[n]["_annual"].index) for n in names]))
    for y in yrs:
        ln = f"{y:<8}"
        for n in names:
            vv = variants[n]["_annual"].get(y, np.nan); ln += f"{'N/A':>15}" if pd.isna(vv) else f"{vv:>14.1%} "
        if bm:
            bv = bm_annual.get(y, np.nan); ln += f"{'N/A':>15}" if pd.isna(bv) else f"{bv:>14.1%} "
        w(ln)
    w("=" * 96)

    # ── Verdict vs baseline ──
    base = variants["No Filter"]["_m"]
    w("VERDICT".center(96, "-"))
    w(f"  Baseline (No Filter): CAGR {base.cagr:.2%} | MaxDD {base.max_drawdown:.2%} | "
      f"Sharpe {base.sharpe_ratio:.2f} | Calmar {base.calmar_ratio:.2f} | Alpha {base.alpha:+.2%}")
    w("")
    for n in names:
        if n == "No Filter": continue
        m = variants[n]["_m"]
        dd_imp = m.max_drawdown - base.max_drawdown          # + = shallower
        w(f"  {n} vs Baseline:")
        w(f"     CAGR   {m.cagr:>7.2%}  ({m.cagr - base.cagr:+.2%}, retains {m.cagr / base.cagr:.0%})")
        w(f"     MaxDD  {m.max_drawdown:>7.2%}  ({dd_imp:+.2%}, {'shallower' if dd_imp > 0 else 'deeper'})")
        w(f"     Sharpe {m.sharpe_ratio:>7.2f}  ({m.sharpe_ratio - base.sharpe_ratio:+.2f})")
        w(f"     Sortino{m.sortino_ratio:>7.2f}  ({m.sortino_ratio - base.sortino_ratio:+.2f})")
        w(f"     Calmar {m.calmar_ratio:>7.2f}  ({m.calmar_ratio - base.calmar_ratio:+.2f})")
        w(f"     Alpha  {m.alpha:>+7.2%}  ({'POSITIVE' if m.alpha > 0 else 'still negative'})")
        # success test
        success = (dd_imp > 0.05) and (m.sharpe_ratio > base.sharpe_ratio + 0.05) and \
                  (m.calmar_ratio > base.calmar_ratio) and (m.alpha > 0)
        w(f"     => Success criteria (DD↓ materially + Sharpe↑ + Calmar↑ + Alpha>0): "
          f"{'MET' if success else 'NOT fully met'}")
        w("")
    w("=" * 96)

    txt = "\n".join(L); print("\n" + txt)
    (rdir / "report.txt").write_text(txt, encoding="utf-8")

    rows = []
    for n in names:
        v = variants[n]; m = v["_m"]; e = v["_extra"]; r = v["_roll3y"]
        rows.append({"variant": n, "cagr": m.cagr, "total_return": m.total_return, "max_drawdown": m.max_drawdown,
            "sharpe": m.sharpe_ratio, "sortino": m.sortino_ratio, "calmar": m.calmar_ratio,
            "annual_vol": m.annualised_volatility, "alpha": m.alpha, "beta": m.beta,
            "excess_vs_bm": m.cagr - bm_cagr if bm else np.nan, "final_value": v["equity_curve"].iloc[-1],
            "time_underwater": e["time_underwater_pct"], "recovery_days": e["recovery_days"],
            "pct_in_cash": v["pct_in_cash"], "n_switches": v["n_switches"],
            "trades": v["total_trades"], "avg_turnover": v["avg_turnover"], "total_costs": v["total_costs"],
            "gross_cagr": v["_gross_cagr"], "roll3y_min": r.min() if not r.empty else np.nan,
            "roll3y_med": r.median() if not r.empty else np.nan, "roll3y_max": r.max() if not r.empty else np.nan})
    pd.DataFrame(rows).to_csv(rdir / "comparison.csv", index=False)
    ydf = pd.DataFrame({n: variants[n]["_annual"] for n in names})
    if bm and not bm_annual.empty: ydf["NIFTY500_price"] = bm_annual
    ydf.index.name = "year"; ydf.to_csv(rdir / "yearwise_returns.csv")
    print(f"  Report + CSVs saved to {rdir}")


if __name__ == "__main__":
    main()
