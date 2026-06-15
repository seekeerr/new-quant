"""
MOMENTUM + LOW VOLATILITY EXPERIMENT  (survivorship-free).

The next experiment recommended by results/factor_research/REPORT.md. We STOP all
parameter tuning of the single momentum signal and instead test whether blending a
SECOND, lowly-correlated factor — low volatility — onto 12-1 momentum lifts
risk-adjusted return and tames the momentum crash (the -62% drawdown we measured).

EVERYTHING is held identical to the validated champion so the ONLY change is the
signal / exposure rule:
  - Universe : survivorship-free full NSE cross-section from daily bhavcopy,
               corp-action adjusted, capped to the top-500 most liquid names per
               rebalance date (point-in-time, bias-free) — the honest universe.
  - Shell    : Top 5 / quarterly / equal weight / Buffer 20 / Indian cost model,
               gross AND net. (Reuses run_buffered_backtest unchanged.)

VARIANTS (the only thing that differs):
  1. Pure Momentum         — 12-1 momentum. The champion. Reference baseline.
  2. Mom + LowVol (50/50)   — blended rank = 0.5*momentum_pctile + 0.5*lowvol_pctile,
                              then Top-5 by the blend.            [report Variant A]
  3. Low-Vol only           — rank purely by low trailing volatility. A bookend that
                              shows how much momentum actually contributes.
  4. Vol-Managed Momentum   — pure-momentum selection, but scale total exposure to a
                              constant-volatility target (excess held as cash) to cut
                              the crash (Barroso-Santa-Clara 2015).  [report Variant B]

Low-vol signal : trailing 252-day (1y) realised volatility of daily returns. Lower
                 vol => higher score. (1y matches the 12-month momentum window.)
Vol-management : exposure = min(1.0, TARGET_VOL / trailing-126d strategy vol). The
                 126d (6mo) realised-vol window for the overlay follows Barroso; it is
                 the strategy's OWN return vol, not a cross-sectional signal. Long-only,
                 no leverage, so exposure is capped at 1.0.

Benchmark: NIFTY 500 PRICE index (data/nifty500_tri.csv). True TRI ~+1.3%/yr higher.
Success bar (per the report): NET alpha > 0 AND Sharpe materially above 0.20. Merely
fixing drawdown without lifting Sharpe/alpha is treated as another risk-overlay null.
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
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from universe.universe_builder import UniverseBuilder
from costs.cost_model import CostModel
from analytics.metrics import compute_metrics
from utils.helpers import get_rebalance_dates

from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import (
    run_buffered_backtest, select_with_buffer,
    drawdown_analytics, rolling_3y_cagr, annual_returns,
)
from run_survivorship_validation import TopNTurnoverUniverseBuilder

# Champion shell — frozen, identical to the survivorship-free validation.
N_STOCKS, BUFFER, FREQ = 5, 20, "quarterly"
VOL_LOOKBACK = 252      # cross-sectional low-vol signal window (1 year)
VM_VOL_WINDOW = 126     # vol-management overlay: strategy's own realised-vol window (6mo)
TARGET_VOL = 0.18       # vol-management annualised target (moderate equity vol)
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"


def load_equity_symbols():
    """Common-equity whitelist (ISIN 'INE'); excludes every ETF / gold / silver /
    liquid / index-fund unit (ISIN 'INF') and DVR/special (ISIN 'IN9'). Built by
    build_equity_universe.py. Returns None (keep all) only if the file is missing."""
    f = CACHE_BHAV / "symbols_equity.txt"
    return set(f.read_text().split()) if f.exists() else None

PALETTE = {
    "Pure Momentum":      "#ff6b6b",
    "Mom + LowVol 50/50": "#00ff88",
    "Low-Vol only":       "#4ecdc4",
    "Vol-Managed Mom":    "#ffd93d",
}


# ─────────────────────────────────────────────────────────────────────
# SIGNALS
# ─────────────────────────────────────────────────────────────────────

def compute_realized_vol(close_panel, date, universe, lookback=VOL_LOOKBACK):
    """Trailing annualised realised volatility of daily returns (raw, lower=safer)."""
    cols = [s for s in universe if s in close_panel.columns]
    prices = close_panel.loc[close_panel.index <= date, cols]
    if len(prices) < lookback + 1:
        return pd.Series(dtype=float)
    rets = prices.tail(lookback + 1).pct_change().tail(lookback)
    vol = rets.std() * np.sqrt(252)
    return vol.replace([np.inf, -np.inf], np.nan).dropna()


def make_lowvol_scorer(lookback=VOL_LOOKBACK):
    """Scorer: rank by LOW volatility (lowest vol => best). Sorted best->worst."""
    def scorer(close_panel, date, universe):
        vol = compute_realized_vol(close_panel, date, universe, lookback)
        if vol.empty:
            return pd.Series(dtype=float)
        return (-vol).sort_values(ascending=False)   # least volatile first
    return scorer


def make_mom_lowvol_scorer(w_mom=0.5, vol_lookback=VOL_LOOKBACK):
    """
    Scorer: blended cross-sectional rank = w_mom * momentum_pctile
                                         + (1 - w_mom) * lowvol_pctile.
    Both components are percentile-ranked over the SAME set of names (the
    intersection that has enough history for both signals), so the blend is on a
    common 0-1 scale. Returns the blend sorted best->worst.
    """
    def scorer(close_panel, date, universe):
        mom = compute_12_1_momentum(close_panel, date, universe)
        vol = compute_realized_vol(close_panel, date, universe, vol_lookback)
        common = mom.index.intersection(vol.index)
        if len(common) < 2:
            return pd.Series(dtype=float)
        mom_pct = mom[common].rank(pct=True)            # high momentum => high
        lowvol_pct = (-vol[common]).rank(pct=True)      # low vol      => high
        blend = w_mom * mom_pct + (1.0 - w_mom) * lowvol_pct
        return blend.sort_values(ascending=False)
    return scorer


# ─────────────────────────────────────────────────────────────────────
# VOL-MANAGED MOMENTUM BACKTEST  (Barroso-style exposure scaling)
# ─────────────────────────────────────────────────────────────────────
# Mirrors run_buffered_backtest mechanics exactly, with ONE addition: at each
# rebalance the target capital-at-risk is scaled by
#   exposure = min(1.0, TARGET_VOL / trailing realised vol of the strategy itself),
# and the un-invested remainder sits in cash. Selection is plain 12-1 momentum.

def run_volmanaged_backtest(close_panel, high_panel, low_panel, volume_panel,
                            n_stocks, rebalance_freq, buffer, initial_capital, config,
                            apply_costs=True, label="", universe_builder=None,
                            target_vol=TARGET_VOL, vol_window=VM_VOL_WINDOW):
    cfg = config
    start = pd.Timestamp(cfg.backtest.start_date)
    end = pd.Timestamp(cfg.backtest.end_date)
    start = max(start, close_panel.index.min() + pd.Timedelta(days=365))
    end = min(end, close_panel.index.max())

    all_dates = close_panel.index[(close_panel.index >= start) & (close_panel.index <= end)]
    if all_dates.empty:
        return {"equity_curve": pd.Series(dtype=float), "returns": pd.Series(dtype=float)}

    rebal_set = set(get_rebalance_dates(all_dates, rebalance_freq))
    valuation_panel = close_panel.ffill()   # daily valuation only (see buffer notes)

    if universe_builder is None:
        universe_builder = UniverseBuilder(close_panel, high_panel, low_panel, volume_panel, cfg.universe)
    cost_model = CostModel(cfg.costs)

    cash = initial_capital
    current_holdings = {}
    equity_values = []
    pv_series = []          # (date, portfolio_value) for trailing strategy-vol estimate
    trades_history = []
    total_costs = 0.0
    total_rebalances = 0
    total_turnover = 0.0
    exposure_log = []

    desc = f"[{'net' if apply_costs else 'gross'}] {label}"
    for date in tqdm(all_dates, desc=desc, unit="day"):
        today_close = close_panel.loc[date]
        today_value = valuation_panel.loc[date]
        holdings_value = sum(qty * today_value.get(sym, 0) for sym, qty in current_holdings.items()
                             if not np.isnan(today_value.get(sym, np.nan)))
        portfolio_value = cash + holdings_value
        equity_values.append({"date": date, "portfolio_value": portfolio_value})
        pv_series.append(portfolio_value)

        if date not in rebal_set:
            continue
        total_rebalances += 1

        universe = universe_builder.build_universe(date)
        if not universe.symbols:
            continue
        momentum_scores = compute_12_1_momentum(close_panel, date, universe.symbols)
        if momentum_scores.empty or len(momentum_scores) < n_stocks:
            continue
        selected = select_with_buffer(momentum_scores, current_holdings, n_stocks, buffer)

        # ── Vol-management: scale exposure by the strategy's own trailing vol ──
        exposure = 1.0
        if len(pv_series) > vol_window + 1:
            recent = pd.Series(pv_series[-(vol_window + 1):]).pct_change().dropna()
            realised = recent.std() * np.sqrt(252)
            if realised > 0:
                exposure = min(1.0, target_vol / realised)
        exposure_log.append(exposure)

        per_stock = (portfolio_value * exposure) / n_stocks
        target_shares = {}
        for sym in selected:
            price = today_close.get(sym, np.nan)
            if np.isnan(price) or price <= 0:
                continue
            shares = int(per_stock / price)
            if shares > 0:
                target_shares[sym] = shares

        sells_value = buys_value = 0.0
        for sym, qty in list(current_holdings.items()):
            target_qty = target_shares.get(sym, 0)
            sell_qty = qty - target_qty
            if sell_qty <= 0:
                continue
            price = today_close.get(sym, np.nan)
            if not (price > 0):
                price = today_value.get(sym, np.nan)
            if not (price > 0):
                del current_holdings[sym]
                continue
            sell_value = sell_qty * price
            cost = 0.0
            if apply_costs:
                tier = universe.liquidity_tiers.get(sym, 2)
                cost = cost_model.calculate_trade_cost(sym, "SELL", sell_qty, price, liquidity_tier=tier).total_cost
            cash += sell_value - cost
            total_costs += cost
            sells_value += sell_value
            current_holdings[sym] = qty - sell_qty
            if current_holdings[sym] <= 0:
                del current_holdings[sym]
            trades_history.append({"date": date, "symbol": sym, "side": "SELL", "shares": sell_qty,
                                   "price": price, "value": sell_value, "cost": cost})

        for sym, target_qty in target_shares.items():
            buy_qty = target_qty - current_holdings.get(sym, 0)
            if buy_qty <= 0:
                continue
            price = today_close.get(sym, np.nan)
            if not (price > 0):
                continue
            buy_value = buy_qty * price
            cost = 0.0
            tier = universe.liquidity_tiers.get(sym, 2)
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
            trades_history.append({"date": date, "symbol": sym, "side": "BUY", "shares": buy_qty,
                                   "price": price, "value": buy_value, "cost": cost})

        rebal_turnover = max(sells_value, buys_value) / portfolio_value if portfolio_value > 0 else 0
        total_turnover += rebal_turnover

    eq = pd.DataFrame(equity_values).set_index("date")["portfolio_value"]
    return {
        "equity_curve": eq, "returns": eq.pct_change().fillna(0), "trades": trades_history,
        "total_costs": total_costs, "total_rebalances": total_rebalances,
        "total_trades": len(trades_history),
        "avg_turnover": total_turnover / total_rebalances if total_rebalances else 0,
        "avg_exposure": float(np.mean(exposure_log)) if exposure_log else 1.0,
        "min_exposure": float(np.min(exposure_log)) if exposure_log else 1.0,
    }


# ─────────────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────────────

def run_variant(kind, scorer, c, h, l, v, cfg, cap, bench_ret, label, builder):
    """kind: 'buffered' (uses run_buffered_backtest+scorer) or 'volmanaged'."""
    common = dict(n_stocks=N_STOCKS, rebalance_freq=FREQ, buffer=BUFFER,
                  initial_capital=cap, config=cfg, universe_builder=builder)
    if kind == "buffered":
        net = run_buffered_backtest(c, h, l, v, apply_costs=True, label=label, scorer=scorer, **common)
        gross = run_buffered_backtest(c, h, l, v, apply_costs=False, label=label+"(g)", scorer=scorer, **common)
    else:
        net = run_volmanaged_backtest(c, h, l, v, apply_costs=True, label=label, **common)
        gross = run_volmanaged_backtest(c, h, l, v, apply_costs=False, label=label+"(g)", **common)
    m = compute_metrics(net["equity_curve"], net["returns"], benchmark_returns=bench_ret,
                        trades=net["trades"], total_costs=net["total_costs"], initial_capital=cap)
    gm = compute_metrics(gross["equity_curve"], gross["returns"], initial_capital=cap)
    net["_m"] = m
    net["_gross_cagr"] = gm.cagr
    net["_extra"] = drawdown_analytics(net["equity_curve"])
    net["_annual"] = annual_returns(net["equity_curve"])
    net["_roll3y"] = rolling_3y_cagr(net["returns"])
    return net


def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("=" * 80)
    print("  MOMENTUM + LOW VOLATILITY  (survivorship-free, Top5/quarterly/Buffer20)")
    print("=" * 80)

    bench_ret = get_benchmark_returns(start, end)
    # bench_eq / bm_cagr / bm_annual are computed AFTER the run, aligned to the
    # strategy's realized span (see benchmark-alignment fix below).

    print("\nLoading survivorship-free bhavcopy panels ...")
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    print(f"  panel: {ac.shape[0]} dates x {ac.shape[1]} symbols")
    # ── UNIVERSE CLEANING: keep common equity only; drop every ETF / gold / silver /
    #    liquid / index-fund unit (ISIN 'INF') and DVR/special (ISIN 'IN9'). The
    #    strategy, signals, costs, dates, and parameters are ALL UNCHANGED — only the
    #    instrument set the universe is drawn from is purged of non-equity. ──
    eq_syms = load_equity_symbols()
    if eq_syms is not None:
        keep = [c for c in ac.columns if c in eq_syms]
        dropped = ac.shape[1] - len(keep)
        ac, ah, al, av, at = (p[keep] for p in (ac, ah, al, av, at))
        print(f"  equity-only: kept {len(keep)} symbols, dropped {dropped} non-equity (ETF/fund) instruments")
    builder = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)

    specs = [
        ("Pure Momentum",      "buffered",   compute_12_1_momentum),
        ("Mom + LowVol 50/50", "buffered",   make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)),
        ("Low-Vol only",       "buffered",   make_lowvol_scorer(VOL_LOOKBACK)),
        ("Vol-Managed Mom",    "volmanaged", None),
    ]
    variants = {}
    for name, kind, scorer in specs:
        print(f"\n{'-'*80}\n  {name}\n{'-'*80}")
        variants[name] = run_variant(kind, scorer, ac, ah, al, av, cfg, cap, bench_ret, name, builder)
        m = variants[name]["_m"]
        print(f"  CAGR {m.cagr:.2%} | MaxDD {m.max_drawdown:.2%} | Sharpe {m.sharpe_ratio:.2f} | "
              f"Alpha {m.alpha:+.2%} | Final Rs {variants[name]['equity_curve'].iloc[-1]:,.0f}")

    # ── BENCHMARK ALIGNMENT FIX: measure the benchmark over the strategy's ACTUAL
    #    realized date span (warmup pushes the start to ~2012-01, not the 2011-06
    #    config start). Comparing mismatched windows previously flattered the
    #    'Excess vs Bmk (CAGR)' line by ~2 CAGR points. ──
    _eq = variants[specs[0][0]]["equity_curve"]
    bstart, bend = str(_eq.index[0].date()), str(_eq.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, cap)
    bm_annual = annual_returns(bench_eq) if not bench_eq.empty else pd.Series(dtype=float)
    bm_cagr = compute_metrics(bench_eq, initial_capital=cap).cagr if not bench_eq.empty else np.nan
    print(f"\n  benchmark aligned to strategy span {bstart}..{bend}: NIFTY500(px) CAGR {bm_cagr:.2%}")

    rdir = RESULTS_DIR / "momentum_lowvol"
    rdir.mkdir(parents=True, exist_ok=True)
    make_charts(variants, bench_eq, bm_annual, rdir / "report.png")
    write_report(variants, cap, bm_cagr, bm_annual, bench_eq, rdir)
    print(f"\n  All outputs in: {rdir}/")


# ─────────────────────────────────────────────────────────────────────
# CHARTS  (mirrors the survivorship-free report layout)
# ─────────────────────────────────────────────────────────────────────

def make_charts(variants, bench_eq, bm_annual, save_path):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 24))
    gs = GridSpec(5, 2, figure=fig, hspace=0.38, wspace=0.22)
    fig.suptitle("Momentum + Low Volatility — Survivorship-Free Universe\n"
                 "Top5 / Quarterly / Buffer20 / Equal Weight (Net of Indian costs)",
                 fontsize=15, fontweight="bold", y=0.995, color="#fff")
    names = list(variants.keys())

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; ax1.plot(eq.index, eq/eq.iloc[0]*100, color=PALETTE[n], lw=1.8, label=n)
    if bench_eq is not None and not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.3, ls="--", label="NIFTY 500 (price)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, :]); ax2.set_title("Drawdown", fontweight="bold")
    for n in names:
        eq = variants[n]["equity_curve"]; dd = (eq-eq.cummax())/eq.cummax()*100
        ax2.plot(dd.index, dd, color=PALETTE[n], lw=1.1, label=n)
    ax2.legend(loc="lower left", framealpha=.3); ax2.grid(True, alpha=.2); ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax3 = fig.add_subplot(gs[2, 0]); ax3.set_title("CAGR vs Max DD", fontweight="bold")
    cagrs = [variants[n]["_m"].cagr*100 for n in names]; dds = [abs(variants[n]["_m"].max_drawdown)*100 for n in names]
    b = ax3.bar(names, cagrs, color=[PALETTE[n] for n in names])
    for bb, cc in zip(b, cagrs):
        ax3.text(bb.get_x()+bb.get_width()/2, bb.get_height(), f"{cc:.1f}%", ha="center", va="bottom", color="#fff", fontweight="bold")
    a3 = ax3.twinx(); a3.plot(names, dds, color="#ff6b6b", marker="o", lw=1.6); a3.set_ylabel("Max DD %", color="#ff6b6b")
    ax3.set_ylabel("CAGR %"); ax3.tick_params(axis="x", rotation=15); ax3.grid(True, alpha=.2, axis="y")

    ax4 = fig.add_subplot(gs[2, 1]); ax4.set_title("Sharpe & Alpha", fontweight="bold")
    x = np.arange(len(names))
    ax4.bar(x-.2, [variants[n]["_m"].sharpe_ratio for n in names], .4, color="#4ecdc4", label="Sharpe")
    ax4.bar(x+.2, [variants[n]["_m"].alpha*100 for n in names], .4, color="#ffd93d", label="Alpha %")
    ax4.axhline(0, color="white", lw=.5, alpha=.4)
    ax4.set_xticks(x); ax4.set_xticklabels(names, rotation=15); ax4.legend(framealpha=.3); ax4.grid(True, alpha=.2, axis="y")

    ax5 = fig.add_subplot(gs[3, :]); ax5.set_title("Rolling 3-Year CAGR", fontweight="bold")
    for n in names:
        r = variants[n]["_roll3y"]
        if not r.empty: ax5.plot(r.index, r*100, color=PALETTE[n], lw=1.4, label=n)
    ax5.axhline(6.5, color="#ff6b6b", ls="--", lw=1, alpha=.6, label="FD 6.5%"); ax5.axhline(0, color="white", lw=.5, ls="--", alpha=.3)
    ax5.legend(loc="upper right", framealpha=.3); ax5.grid(True, alpha=.2); ax5.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax6 = fig.add_subplot(gs[4, :]); ax6.set_title("Year-wise Returns vs Benchmark", fontweight="bold")
    yrs = sorted(set().union(*[set(variants[n]["_annual"].index) for n in names]))
    xp = np.arange(len(yrs)); w = 0.8/(len(names)+1)
    for i, n in enumerate(names):
        ax6.bar(xp+i*w, [variants[n]["_annual"].get(y, np.nan)*100 for y in yrs], w, color=PALETTE[n], label=n)
    if bm_annual is not None and not bm_annual.empty:
        ax6.bar(xp+len(names)*w, [bm_annual.get(y, np.nan)*100 for y in yrs], w, color="#888", label="NIFTY500(px)")
    ax6.axhline(0, color="white", lw=.5, alpha=.3); ax6.set_xticks(xp+w*len(names)/2); ax6.set_xticklabels(yrs, rotation=45)
    ax6.legend(framealpha=.3, ncol=5); ax6.grid(True, alpha=.2, axis="y")

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor()); plt.close(fig)
    print(f"  Chart saved: {save_path}")


# ─────────────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────────────

def write_report(variants, cap, bm_cagr, bm_annual, bench_eq, rdir):
    bm = not bench_eq.empty
    names = list(variants.keys())
    L = []; w = L.append
    def row(lbl, fmt):
        s = f"{lbl:<26}"
        for n in names: s += f"{fmt(variants[n]):>20}"
        return s
    base = "Pure Momentum"

    w("=" * 106)
    w("MOMENTUM + LOW VOLATILITY — SURVIVORSHIP-FREE UNIVERSE".center(106))
    w("Top5 / Quarterly / Equal Weight / Buffer20 / Net of Indian costs".center(106))
    w("=" * 106)
    w(f"Initial Capital: Rs {cap:,.0f}   Period: {variants[base]['_m'].start_date}..{variants[base]['_m'].end_date}")
    w(f"Low-vol signal: trailing {VOL_LOOKBACK}-day realised vol (lower=better).")
    w(f"Vol-management: exposure = min(1.0, {TARGET_VOL:.0%} / trailing-{VM_VOL_WINDOW}d strategy vol).")
    w("Benchmark: NIFTY 500 PRICE index (true TRI ~+1.3%/yr higher).")
    w("")
    w(f"{'Metric':<26}" + "".join(f"{n:>20}" for n in names)); w("-" * 106)
    w(row("CAGR (net)",        lambda v: f"{v['_m'].cagr:.2%}"))
    w(row("CAGR (gross)",      lambda v: f"{v['_gross_cagr']:.2%}"))
    w(row("Total Return",      lambda v: f"{v['_m'].total_return:.0%}"))
    w(row("Max Drawdown",      lambda v: f"{v['_m'].max_drawdown:.2%}"))
    w(row("Sharpe",            lambda v: f"{v['_m'].sharpe_ratio:.2f}"))
    w(row("Sortino",           lambda v: f"{v['_m'].sortino_ratio:.2f}"))
    w(row("Calmar",            lambda v: f"{v['_m'].calmar_ratio:.2f}"))
    w(row("Annual Vol",        lambda v: f"{v['_m'].annualised_volatility:.2%}"))
    if bm:
        w(row("Alpha (Jensen ann.)", lambda v: f"{v['_m'].alpha:+.2%}"))
        w(row("Excess vs Bmk (CAGR)", lambda v: f"{v['_m'].cagr-bm_cagr:+.2%}"))
        w(row("Beta",              lambda v: f"{v['_m'].beta:.2f}"))
    w(row("Final Value (Rs)",  lambda v: f"{v['equity_curve'].iloc[-1]:,.0f}"))
    w(row("Time Underwater",   lambda v: f"{v['_extra']['time_underwater_pct']:.1%}"))
    w(row("Trades (exec)",     lambda v: f"{v['total_trades']}"))
    w(row("Avg Turnover/Reb",  lambda v: f"{v['avg_turnover']:.1%}"))
    w(row("Txn Costs (Rs)",    lambda v: f"{v['total_costs']:,.0f}"))
    w(row("Cost Drag (pts)",   lambda v: f"{v['_gross_cagr']-v['_m'].cagr:.2%}"))
    # Exposure only meaningful for the vol-managed variant.
    w(row("Avg Exposure",      lambda v: f"{v.get('avg_exposure', 1.0):.0%}"))
    w("-" * 106)
    if bm:
        w(f"NIFTY 500 price-index CAGR over period: {bm_cagr:.2%}  (true TRI ~ {bm_cagr+0.013:.2%})")
    w("")
    w("ROLLING 3Y CAGR (min / median / max):")
    for n in names:
        r = variants[n]["_roll3y"]
        if not r.empty:
            w(f"   {n:<20}: min {r.min():.1%} | median {r.median():.1%} | max {r.max():.1%}")
    w("")
    w("YEAR-WISE RETURNS"); w("-" * 106)
    w(f"{'Year':<8}" + "".join(f"{n:>20}" for n in names) + (f"{'NIFTY500':>16}" if bm else ""))
    yrs = sorted(set().union(*[set(variants[n]["_annual"].index) for n in names]))
    for y in yrs:
        ln = f"{y:<8}"
        for n in names:
            vv = variants[n]["_annual"].get(y, np.nan)
            ln += f"{'N/A':>20}" if pd.isna(vv) else f"{vv:>19.1%} "
        if bm:
            bv = bm_annual.get(y, np.nan)
            ln += f"{'N/A':>16}" if pd.isna(bv) else f"{bv:>15.1%} "
        w(ln)
    w("=" * 106)

    # ── Verdict against the report's pre-registered success bar ──
    w("VERDICT".center(106, "-"))
    bm_cagr_v = variants[base]["_m"]
    w(f"  Baseline (Pure Momentum): CAGR {bm_cagr_v.cagr:.2%} | MaxDD {bm_cagr_v.max_drawdown:.2%} | "
      f"Sharpe {bm_cagr_v.sharpe_ratio:.2f} | Alpha {bm_cagr_v.alpha:+.2%}")
    w("  Success bar (pre-registered): NET alpha > 0 AND Sharpe materially above 0.20.")
    w("")
    for n in names:
        if n == base:
            continue
        m = variants[n]["_m"]; b = bm_cagr_v
        passed = (m.alpha > 0) and (m.sharpe_ratio > b.sharpe_ratio + 0.10)
        tag = "PASSES bar" if passed else "does NOT clear bar"
        w(f"  {n} vs Pure Momentum:  [{tag}]")
        w(f"     dCAGR {m.cagr-b.cagr:+.2%} | dMaxDD {m.max_drawdown-b.max_drawdown:+.2%} "
          f"({'shallower' if m.max_drawdown>b.max_drawdown else 'deeper'}) | "
          f"dSharpe {m.sharpe_ratio-b.sharpe_ratio:+.2f} | dAlpha {m.alpha-b.alpha:+.2%}")
    w("")
    # Best by Sharpe among the non-baseline variants.
    cand = [n for n in names if n != base]
    best = max(cand, key=lambda n: variants[n]["_m"].sharpe_ratio)
    bestm = variants[best]["_m"]
    cleared = (bestm.alpha > 0) and (bestm.sharpe_ratio > bm_cagr_v.sharpe_ratio + 0.10)
    w(f"  Best non-baseline by Sharpe: {best} (Sharpe {bestm.sharpe_ratio:.2f}, Alpha {bestm.alpha:+.2%}).")
    if cleared:
        w("  => Low-vol blending CLEARS the bar: it lifts risk-adjusted return, not just drawdown.")
        w("     Justifies investing in a bias-free fundamentals panel for Mom+Quality / Mom+Value next.")
    else:
        w("  => Low-vol blending does NOT clear the bar (may improve risk metrics but not alpha/Sharpe")
        w("     materially). Treat as a risk-overlay result, like the trend filter; do NOT start tuning")
        w("     vol lookbacks. Re-evaluate whether the fundamentals-data track is worth it.")
    w("=" * 106)

    txt = "\n".join(L)
    print("\n" + txt)
    (rdir / "report.txt").write_text(txt, encoding="utf-8")

    rows = []
    for n in names:
        v = variants[n]; m = v["_m"]; e = v["_extra"]; r = v["_roll3y"]
        rows.append({"variant": n, "cagr": m.cagr, "gross_cagr": v["_gross_cagr"],
            "total_return": m.total_return, "max_drawdown": m.max_drawdown, "sharpe": m.sharpe_ratio,
            "sortino": m.sortino_ratio, "calmar": m.calmar_ratio, "annual_vol": m.annualised_volatility,
            "alpha": m.alpha, "beta": m.beta, "excess_vs_bm": m.cagr-bm_cagr if bm else np.nan,
            "final_value": v["equity_curve"].iloc[-1], "time_underwater": e["time_underwater_pct"],
            "trades": v["total_trades"], "avg_turnover": v["avg_turnover"], "total_costs": v["total_costs"],
            "avg_exposure": v.get("avg_exposure", 1.0),
            "roll3y_min": r.min() if not r.empty else np.nan, "roll3y_med": r.median() if not r.empty else np.nan,
            "roll3y_max": r.max() if not r.empty else np.nan})
    pd.DataFrame(rows).to_csv(rdir / "comparison.csv", index=False)
    ydf = pd.DataFrame({n: variants[n]["_annual"] for n in names})
    if bm and not bm_annual.empty:
        ydf["NIFTY500_price"] = bm_annual
    ydf.index.name = "year"; ydf.to_csv(rdir / "yearwise_returns.csv")
    print(f"  Report + CSVs saved to {rdir}")


if __name__ == "__main__":
    main()
