"""
FULL (UNFILTERED) UNIVERSE STRATEGY SEARCH — Rs 1,00,000 book.

USER ASK: stop filtering. Trade the ENTIRE NSE equity cross-section — penny stocks,
illiquid micro-caps, names that would normally be cut by the liquidity floor and the
anti-manipulation screens. Find a strategy that works there. A tiny Rs 1L book is the
only book that can even attempt this (it doesn't move illiquid names).

WHAT CHANGES vs every prior study: the universe is NO LONGER filtered.
  - Filtered-500    : champion universe (PIT safety filters + top-500 liquidity) -- REFERENCE
  - Unfiltered >=Rs1: EVERY equity name with a tradeable close >= Rs 1. No liquidity floor,
                      no circuit/spread/volume-CV anti-manipulation, no top-N cap.
  - Unfiltered >=Rs5: same, but a Rs 5 floor to keep sub-rupee data-artifact junk out.

SIGNALS (each at its natural horizon; drop-in scorers, no parameter search):
  - ShortRev-21 : buy the biggest 1-month LOSERS. The short-term-reversal anomaly is a
                  liquidity-provision premium and is STRONGEST exactly in illiquid micro-
                  caps -> the best-justified "whole universe" strategy. Monthly, no buffer.
  - PureMom     : 12-1 momentum. Quarterly, Buffer20. (Contrast: momentum in penny-land.)
  - Mom+LowVol  : the frozen 50/50 product. Quarterly, Buffer20. (Does dropping filters
                  help or wreck the validated champion?)

SHELL (otherwise frozen): Top-10 / equal weight / whole-share rounding / Rs 1L /
full Indian delivery cost model, NET of costs. Engine = run_buffered_backtest, verbatim.

THE CRUX — COST REALISM. The cost model caps slippage at 0.20%/side (tier-3) plus a
small impact term. For UNFILTERED micro-caps that is wildly optimistic: real bid-ask
spreads, circuit locks (you literally cannot trade), and impact make round-trips cost
multiples of that. So for every unfiltered cell we ALSO run a STRESS pass with slippage
and impact x5. If the edge does not survive the stress, it is a backtest artifact, not a
tradeable strategy. This is stated up front, not as an after-the-fact excuse.

PRE-REGISTERED VERDICT: an unfiltered strategy is REAL only if it (1) beats Filtered-500
on net CAGR AND (2) still beats the benchmark under the x5 cost stress. Otherwise the
filters were protecting us and "all stocks" is a mirage built on un-tradeable fills.

Run:  py run_full_universe.py
"""
import sys, io, time, warnings
from copy import deepcopy
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
from data.benchmark import get_benchmark_returns, get_benchmark_equity_curve
from analytics.metrics import compute_metrics
from universe.universe_builder import UniverseBuilder, UniverseSnapshot
from universe.filters import classify_liquidity_tier

from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import run_buffered_backtest, drawdown_analytics, rolling_3y_cagr
from run_survivorship_validation import TopNTurnoverUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK

CAPITAL = 100_000.0
N_STOCKS = 10
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "full_universe"
STRESS_MULT = 5.0   # slippage & impact multiplier for the cost-realism stress pass


# ── Short-term reversal scorer (buy the biggest losers) ─────────────────
def make_reversal_scorer(lookback=21):
    def scorer(close_panel, date, universe):
        cols = [s for s in universe if s in close_panel.columns]
        prices = close_panel.loc[close_panel.index <= date, cols]
        if len(prices) < lookback + 1:
            return pd.Series(dtype=float)
        ret = (prices.iloc[-1] / prices.iloc[-(lookback + 1)]) - 1
        ret = ret.replace([np.inf, -np.inf], np.nan).dropna()
        return (-ret).sort_values(ascending=False)   # most-negative return -> best rank
    return scorer


class FullUniverseBuilder(UniverseBuilder):
    """NO safety filters. Every symbol with a valid close >= min_price on `date`.
    Signals self-limit on history via their own dropna; cost model still assigns a
    liquidity tier so illiquid names are penalised (tier-3) as much as the model allows."""

    def __init__(self, close, high, low, volume, config, min_price=1.0):
        super().__init__(close, high, low, volume, config)
        self.min_price = min_price

    def build_universe(self, date):
        date = pd.Timestamp(date)
        if date in self._cache:
            return self._cache[date]
        last = self.close.loc[self.close.index <= date]
        if last.empty:
            snap = UniverseSnapshot(date, [], {}, None); self._cache[date] = snap; return snap
        row = last.iloc[-1]
        syms = row.index[(row.notna()) & (row >= self.min_price)].tolist()
        tiers = classify_liquidity_tier(self.close, self.volume, date, syms)
        snap = UniverseSnapshot(date=date, symbols=syms, liquidity_tiers=tiers, filter_result=None)
        self._cache[date] = snap
        return snap


def stressed_config(cfg, mult):
    """Copy of cfg with slippage tiers and impact-cost base multiplied (cost realism)."""
    c = deepcopy(cfg)
    c.costs.slippage_tier1 *= mult
    c.costs.slippage_tier2 *= mult
    c.costs.slippage_tier3 *= mult
    c.costs.impact_cost_base *= mult
    return c


def evaluate(ac, ah, al, av, builder, scorer, freq, buffer, cfg, bench_ret, label, stress=False):
    rcfg = stressed_config(cfg, STRESS_MULT) if stress else cfg
    net = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=freq,
        buffer=buffer, initial_capital=CAPITAL, config=rcfg, apply_costs=True,
        label=label, scorer=scorer, universe_builder=builder)
    m = compute_metrics(net["equity_curve"], net["returns"], benchmark_returns=bench_ret,
        trades=net["trades"], total_costs=net["total_costs"], initial_capital=CAPITAL)
    extra = drawdown_analytics(net["equity_curve"])
    roll = rolling_3y_cagr(net["returns"])
    # Unfiltered penny/micro-caps can drive the book to ~zero (falling-knife delistings).
    # compute_metrics returns NaN CAGR on a wiped-out curve; report it as -100% ("RUIN")
    # so the comparison table and verdicts stay well-defined.
    final_val = net["equity_curve"].iloc[-1]
    cagr = m.cagr if (final_val > 0 and np.isfinite(m.cagr)) else -1.0
    return {
        "cagr": cagr, "max_dd": m.max_drawdown, "sharpe": m.sharpe_ratio,
        "calmar": m.calmar_ratio, "alpha": m.alpha, "vol": m.annualised_volatility,
        "final": net["equity_curve"].iloc[-1], "trades": net["total_trades"],
        "costs": net["total_costs"], "turnover": net["avg_turnover"],
        "roll3y_min": roll.min() if not roll.empty else np.nan,
        "eq": net["equity_curve"],
    }


def main():
    cfg = SystemConfig()
    cfg.portfolio.initial_capital = CAPITAL
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("=" * 100)
    print("  FULL (UNFILTERED) UNIVERSE STRATEGY SEARCH — Rs 1,00,000 book".center(100))
    print("  Top-10 / equal weight / NET of costs (+ x5 cost-stress on unfiltered cells)".center(100))
    print("=" * 100)

    bench_ret = get_benchmark_returns(start, end)

    print("\nLoading survivorship-free bhavcopy panels ...")
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    eq_syms = load_equity_symbols()
    if eq_syms is not None:
        keep = [c for c in ac.columns if c in eq_syms]
        ac, ah, al, av, at = (p[keep] for p in (ac, ah, al, av, at))
    print(f"  equity universe: {ac.shape[1]} symbols x {ac.shape[0]} dates")

    # universe builders
    filtered500 = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)
    unfilt1 = FullUniverseBuilder(ac, ah, al, av, cfg.universe, min_price=1.0)
    unfilt5 = FullUniverseBuilder(ac, ah, al, av, cfg.universe, min_price=5.0)

    UNIVERSES = [
        ("Filtered-500",     filtered500, False),
        ("Unfiltered >=Rs1", unfilt1,     True),
        ("Unfiltered >=Rs5", unfilt5,     True),
    ]
    # (name, scorer, freq, buffer)
    SIGNALS = [
        ("ShortRev-21", make_reversal_scorer(21),                 "monthly",   N_STOCKS),
        ("PureMom",     compute_12_1_momentum,                    "quarterly", 20),
        ("Mom+LowVol",  make_mom_lowvol_scorer(0.5, VOL_LOOKBACK), "quarterly", 20),
    ]

    rows = []
    for sig_name, scorer, freq, buf in SIGNALS:
        for uni_name, builder, is_unfilt in UNIVERSES:
            label = f"{sig_name} / {uni_name}"
            print(f"\n  running {label} ({freq}) ...")
            t0 = time.time()
            r = evaluate(ac, ah, al, av, builder, scorer, freq, buf, cfg, bench_ret, label)
            r.update(signal=sig_name, universe=uni_name, freq=freq, stress=False)
            rows.append(r)
            print(f"    CAGR {r['cagr']:.2%} | MaxDD {r['max_dd']:.2%} | Sharpe {r['sharpe']:.2f} | "
                  f"turn {r['turnover']:.0%} | costs Rs {r['costs']:,.0f} | {time.time()-t0:.0f}s")
            if is_unfilt:
                rs = evaluate(ac, ah, al, av, builder, scorer, freq, buf, cfg, bench_ret,
                              label + " [x5]", stress=True)
                rs.update(signal=sig_name, universe=uni_name + " [x5 cost]", freq=freq, stress=True)
                rows.append(rs)
                print(f"    [x5 cost stress] CAGR {rs['cagr']:.2%} | MaxDD {rs['max_dd']:.2%} | "
                      f"Sharpe {rs['sharpe']:.2f} | costs Rs {rs['costs']:,.0f}")

    _eq = rows[0]["eq"]
    bstart, bend = str(_eq.index[0].date()), str(_eq.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, CAPITAL)
    bm_cagr = compute_metrics(bench_eq, initial_capital=CAPITAL).cagr if not bench_eq.empty else np.nan

    RDIR.mkdir(parents=True, exist_ok=True)
    _write_report(rows, bstart, bend, bm_cagr)
    _make_chart(rows, bench_eq)
    pd.DataFrame([{k: v for k, v in r.items() if k != "eq"} for r in rows]).to_csv(
        RDIR / "comparison.csv", index=False)
    print(f"\n  Saved to {RDIR}/")


def _write_report(rows, bstart, bend, bm_cagr):
    L = []; w = L.append
    w("=" * 104)
    w("  FULL (UNFILTERED) UNIVERSE STRATEGY SEARCH — Rs 1,00,000 — NET OF COSTS".center(104))
    w("=" * 104)
    w(f"Capital Rs {CAPITAL:,.0f}   Period {bstart}..{bend}   Shell Top{N_STOCKS}/EW. "
      f"NIFTY500(px) CAGR {bm_cagr:.2%}")
    w("[x5 cost] = slippage & impact x5 (micro-cap cost realism stress).")
    w("")
    hdr = (f"{'Signal':<12}{'Universe':<22}{'Freq':<10}{'CAGR':>8}{'MaxDD':>8}{'Sharpe':>8}"
           f"{'Calmar':>8}{'Alpha':>8}{'Turn':>7}{'Trades':>8}{'Costs':>11}")
    w(hdr); w("-" * 104)
    for r in rows:
        w(f"{r['signal']:<12}{r['universe']:<22}{r['freq']:<10}{r['cagr']:>7.1%}{r['max_dd']:>8.1%}"
          f"{r['sharpe']:>8.2f}{r['calmar']:>8.2f}{r['alpha']:>+8.1%}{r['turnover']:>7.0%}"
          f"{r['trades']:>8d}{r['costs']:>11,.0f}")
    w("-" * 104)
    w("")

    # Verdict per signal: did unfiltered beat Filtered-500, and survive the x5 stress?
    for sig_name in ["ShortRev-21", "PureMom", "Mom+LowVol"]:
        sub = [r for r in rows if r["signal"] == sig_name]
        base = next(r for r in sub if r["universe"] == "Filtered-500")
        w(f"[{sig_name}] Filtered-500 net CAGR {base['cagr']:.2%} (Sharpe {base['sharpe']:.2f}, MaxDD {base['max_dd']:.1%})")
        for floor in ["Unfiltered >=Rs1", "Unfiltered >=Rs5"]:
            plain = next((r for r in sub if r["universe"] == floor), None)
            stress = next((r for r in sub if r["universe"] == floor + " [x5 cost]"), None)
            if not plain:
                continue
            beats = plain["cagr"] > base["cagr"]
            survives = stress is not None and stress["cagr"] > bm_cagr
            tag = ("REAL: beats Filtered-500 AND survives x5 stress vs benchmark"
                   if (beats and survives) else
                   "beats Filtered-500 but DIES under x5 stress" if beats else
                   "does not beat Filtered-500")
            w(f"   {floor:<18} net {plain['cagr']:>6.1%}  ->  x5-stress "
              f"{stress['cagr'] if stress else float('nan'):>6.1%}  =>  {tag}")
        w("")
    w("=" * 104)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")


def _make_chart(rows, bench_eq):
    plt.style.use("dark_background")
    plain = [r for r in rows if not r["stress"]]
    fig = plt.figure(figsize=(18, 12))
    gs = GridSpec(2, 2, figure=fig, hspace=0.32, wspace=0.22)
    fig.suptitle("Full (Unfiltered) Universe Search — Rs 1,00,000 — net of costs",
                 fontsize=15, fontweight="bold", color="#fff", y=0.97)
    colors = ["#00ff88", "#4ecdc4", "#ffd93d", "#ff6b6b", "#b388ff",
              "#66d9ef", "#ff9f43", "#f368e0", "#a0e7e5"]

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log) — net (no stress)", fontweight="bold")
    for i, r in enumerate(plain):
        eq = np.maximum(r["eq"], 1.0)   # floor for log scale (wiped-out curves -> ~0)
        ax1.plot(eq.index, eq / eq.iloc[0] * 100, color=colors[i % len(colors)], lw=1.4,
                 label=f"{r['signal'][:9]}/{r['universe'][:11]}")
    if bench_eq is not None and not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq / bench_eq.iloc[0] * 100, color="#888", lw=1.2, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3, ncol=2, fontsize=8)
    ax1.grid(True, alpha=.2); ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, 0]); ax2.set_title("Net CAGR: plain vs x5 cost stress", fontweight="bold")
    sigs = ["ShortRev-21", "PureMom", "Mom+LowVol"]
    unis = ["Filtered-500", "Unfiltered >=Rs1", "Unfiltered >=Rs5"]
    x = np.arange(len(sigs)); wbar = 0.13
    for j, uni in enumerate(unis):
        vals = [next((r["cagr"] for r in rows if r["signal"] == s and r["universe"] == uni), np.nan) for s in sigs]
        ax2.bar(x + j * wbar, [v * 100 for v in vals], wbar, color=colors[j], label=uni)
        sv = [next((r["cagr"] for r in rows if r["signal"] == s and r["universe"] == uni + " [x5 cost]"), np.nan) for s in sigs]
        if any(not np.isnan(v) for v in sv):
            ax2.bar(x + j * wbar, [v * 100 for v in sv], wbar, color="none", edgecolor="#fff",
                    hatch="////", linewidth=0.6)
    ax2.set_xticks(x + wbar); ax2.set_xticklabels(sigs, fontsize=8); ax2.set_ylabel("Net CAGR %")
    ax2.legend(framealpha=.3, fontsize=7); ax2.grid(True, alpha=.2, axis="y")
    ax2.text(0.01, 0.97, "hatched = x5 cost stress", transform=ax2.transAxes, fontsize=7, color="#ccc", va="top")

    ax3 = fig.add_subplot(gs[1, 1]); ax3.set_title("Avg turnover per rebalance", fontweight="bold")
    for j, uni in enumerate(unis):
        vals = [next((r["turnover"] for r in plain if r["signal"] == s and r["universe"] == uni), np.nan) for s in sigs]
        ax3.bar(x + j * wbar, [v * 100 for v in vals], wbar, color=colors[j], label=uni)
    ax3.set_xticks(x + wbar); ax3.set_xticklabels(sigs, fontsize=8); ax3.set_ylabel("Turnover %/rebal")
    ax3.legend(framealpha=.3, fontsize=7); ax3.grid(True, alpha=.2, axis="y")

    RDIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Chart saved: {RDIR / 'report.png'}")


if __name__ == "__main__":
    main()
