"""
SMALL-CAP UNIVERSE BREADTH STUDY — sized for a Rs 1,00,000 (1 lakh) book.

QUESTION (pre-registered): A tiny book has an edge a large book does not — it can
hold illiquid small/micro-caps without moving them. The frozen champion only ever
traded the top-500 most-liquid names (a NIFTY-500-sized liquidity head). For a Rs 1L
account, does EXTENDING the universe down into the small-cap tail — the names a big
book is forced to ignore — add NET return, or do costs/illiquidity eat the breadth?

WHAT VARIES (the only independent variable): the universe slice.
  A. Liquid Top-500      rank   0..500   -- the champion universe (baseline / bar)
  B. Broad Top-1000      rank   0..1000  -- add the next 500 smaller names
  C. SmallCap 300..1000  rank 300..1000  -- DROP the large-cap head; pure small-cap tail
                                            (the slice only a tiny book can actually reach)
  D. All-Equity filtered rank   0..inf   -- every equity name that passes the safety
                                            filters (liquidity floor + anti-manipulation)

WHAT IS FROZEN (identical to the validated champion — nothing tuned):
  - Engine ........ run_buffered_backtest (run_buffer_experiment.py), reused verbatim
  - Shell ......... Top-10 / quarterly / equal weight / Buffer20, whole-share rounding
  - Costs ......... full Indian delivery cost model incl. per-liquidity-tier slippage
                    (small-caps get tier-3 0.20%/side -> results are CONSERVATIVE for a
                    Rs 1L clip that barely moves the tape), NET of costs
  - Data .......... survivorship-free bhavcopy panels, corp-action adjusted, equity-only
                    (ISIN INE), point-in-time -- includes names that later delisted
  - Capital ....... Rs 1,00,000  (THE change vs the Rs 5L research base)

SIGNALS (both reused as drop-in scorers, no parameter search):
  1. PureMom     -- 12-1 cross-sectional momentum (the isolated factor)
  2. Mom+LowVol  -- the frozen 50/50 momentum+low-vol product the user will paper-trade

NOTE ON "ALL STOCKS": the safety filters (min ~Rs 50L ADTV, min price Rs 10, circuit /
spread / volume-CV anti-manipulation) are KEPT. "All stocks" here means the full
cross-section that clears a sane tradeability floor, NOT untradeable penny junk. To
relax the floor itself is a separate follow-up (stated, not silently assumed).

PRE-REGISTERED VERDICT (judged on NET CAGR and Sharpe, per signal):
  WORTH PURSuing the small-cap tail IF a wider slice (B/C/D) beats Liquid Top-500 (A)
  on net CAGR WITHOUT a materially worse drawdown (>5 pts deeper). Otherwise the tiny-
  book breadth edge is a mirage once costs/illiquidity are paid, and Top-500 stands.

Run:  py run_smallcap_universe.py
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
from data.benchmark import get_benchmark_returns, get_benchmark_equity_curve
from analytics.metrics import compute_metrics
from universe.universe_builder import UniverseSnapshot
from universe.filters import apply_all_filters, classify_liquidity_tier

from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import (
    run_buffered_backtest, drawdown_analytics, rolling_3y_cagr, annual_returns,
)
from run_survivorship_validation import TopNTurnoverUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK

# ── Frozen champion shell ───────────────────────────────────────────────
CAPITAL = 100_000.0
N_STOCKS, BUFFER, FREQ = 10, 20, "quarterly"
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "smallcap_universe"

# Universe slices: (label, min_rank, max_rank) by 20-day avg turnover, most-liquid=0.
SLICES = [
    ("Liquid Top-500",      0,    500),
    ("Broad Top-1000",      0,    1000),
    ("SmallCap 300-1000",   300,  1000),
    ("All-Equity filtered", 0,    10**9),
]
SIGNALS = [
    ("PureMom",    compute_12_1_momentum),
    ("Mom+LowVol", make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)),
]
# Drawdown tolerance for the "without materially worse drawdown" clause (pts).
DD_TOLERANCE = 0.05


class RankBandUniverseBuilder(TopNTurnoverUniverseBuilder):
    """Standard PIT safety filters, then keep names whose 20-day avg-turnover rank
    sits in [min_rank, max_rank) (most-liquid name = rank 0). min_rank>0 DROPS the
    large-cap head and keeps only the smaller-cap tail a tiny book can reach."""

    def __init__(self, close, high, low, volume, turnover, config, min_rank, max_rank):
        super().__init__(close, high, low, volume, turnover, config, max_size=max_rank)
        self.min_rank = min_rank
        self.max_rank = max_rank

    def build_universe(self, date):
        date = pd.Timestamp(date)
        if date in self._cache:
            return self._cache[date]
        fr = apply_all_filters(self.close, self.high, self.low, self.volume, date, self.config)
        syms = fr.passed_symbols
        m = self.turnover.index <= date
        cols = [s for s in syms if s in self.turnover.columns]
        adtv = self.turnover.loc[m].tail(self.config.turnover_lookback)[cols].mean()
        ranked = adtv.sort_values(ascending=False).index.tolist()   # most liquid first
        syms = ranked[self.min_rank:self.max_rank]
        tiers = classify_liquidity_tier(self.close, self.volume, date, syms)
        snap = UniverseSnapshot(date=date, symbols=syms, liquidity_tiers=tiers, filter_result=fr)
        self._cache[date] = snap
        return snap


def run_one(ac, ah, al, av, at, cfg, scorer, min_rank, max_rank, label):
    """One net + one gross backtest for a (signal, slice); returns enriched net dict."""
    builder = RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, min_rank, max_rank)
    net = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=FREQ,
        buffer=BUFFER, initial_capital=CAPITAL, config=cfg, apply_costs=True,
        label=label, scorer=scorer, universe_builder=builder)
    gross = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=FREQ,
        buffer=BUFFER, initial_capital=CAPITAL, config=cfg, apply_costs=False,
        label=label + "(g)", scorer=scorer, universe_builder=builder)
    return net, gross


def main():
    cfg = SystemConfig()
    cfg.portfolio.initial_capital = CAPITAL
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("=" * 96)
    print("  SMALL-CAP UNIVERSE BREADTH STUDY  (Rs 1,00,000 book)".center(96))
    print("  Top-10 / quarterly / Buffer20 / equal weight / NET of costs".center(96))
    print("=" * 96)

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
    print(f"  equity-only universe: {ac.shape[1]} symbols x {ac.shape[0]} dates")

    rows = []
    for sig_name, scorer in SIGNALS:
        for slice_name, lo, hi in SLICES:
            label = f"{sig_name} / {slice_name}"
            print(f"\n  running {label} ...")
            t0 = time.time()
            net, gross = run_one(ac, ah, al, av, at, cfg, scorer, lo, hi, label)
            m = compute_metrics(net["equity_curve"], net["returns"],
                                benchmark_returns=bench_ret, trades=net["trades"],
                                total_costs=net["total_costs"], initial_capital=CAPITAL)
            gm = compute_metrics(gross["equity_curve"], gross["returns"],
                                 initial_capital=CAPITAL)
            extra = drawdown_analytics(net["equity_curve"])
            roll = rolling_3y_cagr(net["returns"])
            rows.append({
                "signal": sig_name, "slice": slice_name,
                "cagr": m.cagr, "gross_cagr": gm.cagr,
                "cost_drag": gm.cagr - m.cagr,
                "max_dd": m.max_drawdown, "sharpe": m.sharpe_ratio,
                "calmar": m.calmar_ratio, "alpha": m.alpha,
                "vol": m.annualised_volatility,
                "final": net["equity_curve"].iloc[-1],
                "trades": net["total_trades"], "costs": net["total_costs"],
                "turnover": net["avg_turnover"],
                "tuw": extra["time_underwater_pct"],
                "roll3y_min": roll.min() if not roll.empty else np.nan,
                "roll3y_med": roll.median() if not roll.empty else np.nan,
                "eq": net["equity_curve"],
            })
            print(f"    CAGR {m.cagr:.2%} (gross {gm.cagr:.2%}, drag {gm.cagr-m.cagr:.2%}) | "
                  f"MaxDD {m.max_drawdown:.2%} | Sharpe {m.sharpe_ratio:.2f} | "
                  f"costs Rs {net['total_costs']:,.0f} | {time.time()-t0:.0f}s")

    # benchmark aligned to strategy span
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
    w("=" * 96)
    w("  SMALL-CAP UNIVERSE BREADTH STUDY — Rs 1,00,000 BOOK — NET OF COSTS".center(96))
    w("=" * 96)
    w(f"Capital: Rs {CAPITAL:,.0f}   Period: {bstart}..{bend}   "
      f"Shell: Top{N_STOCKS}/{FREQ}/Buffer{BUFFER}/EW")
    w(f"Only the universe slice varies. NIFTY500(px) CAGR over span: {bm_cagr:.2%}")
    w("")
    hdr = (f"{'Signal':<11}{'Slice':<20}{'CAGR':>8}{'Gross':>8}{'Drag':>7}{'MaxDD':>8}"
           f"{'Sharpe':>8}{'Calmar':>8}{'Alpha':>8}{'Trades':>8}{'Costs':>11}{'3yMin':>8}")
    w(hdr); w("-" * 96)
    for r in rows:
        w(f"{r['signal']:<11}{r['slice']:<20}{r['cagr']:>7.1%}{r['gross_cagr']:>8.1%}"
          f"{r['cost_drag']:>7.1%}{r['max_dd']:>8.1%}{r['sharpe']:>8.2f}{r['calmar']:>8.2f}"
          f"{r['alpha']:>+8.1%}{r['trades']:>8d}{r['costs']:>11,.0f}{r['roll3y_min']:>8.1%}")
    w("-" * 96)

    # Per-signal verdict: does any wider slice beat the Liquid Top-500 baseline?
    w("")
    for sig_name, _ in SIGNALS:
        sub = [r for r in rows if r["signal"] == sig_name]
        base = next(r for r in sub if r["slice"] == "Liquid Top-500")
        w(f"[{sig_name}] baseline Liquid Top-500: CAGR {base['cagr']:.2%}, "
          f"MaxDD {base['max_dd']:.1%}, Sharpe {base['sharpe']:.2f}")
        winners = [r for r in sub
                   if r["slice"] != "Liquid Top-500"
                   and r["cagr"] > base["cagr"]
                   and r["max_dd"] >= base["max_dd"] - DD_TOLERANCE]
        if winners:
            best = max(winners, key=lambda r: r["cagr"])
            w(f"   => WIDER SLICE WINS: {best['slice']} CAGR {best['cagr']:.2%} "
              f"(+{best['cagr']-base['cagr']:.2%}) at MaxDD {best['max_dd']:.1%}. "
              f"Small-cap breadth pays for a Rs 1L book.")
        else:
            w(f"   => NO wider slice beats Top-500 within drawdown tolerance. "
              f"Breadth edge is a mirage after costs; stay with Top-500.")
        w("")
    w("=" * 96)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")


def _make_chart(rows, bench_eq):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 12))
    gs = GridSpec(2, 2, figure=fig, hspace=0.3, wspace=0.22)
    fig.suptitle("Small-Cap Universe Breadth — Rs 1,00,000 book — Top10/Quarterly/Buffer20 (Net)",
                 fontsize=15, fontweight="bold", color="#fff", y=0.97)
    colors = ["#00ff88", "#4ecdc4", "#ffd93d", "#ff6b6b", "#b388ff",
              "#66d9ef", "#ff9f43", "#f368e0"]

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for i, r in enumerate(rows):
        eq = r["eq"]
        ax1.plot(eq.index, eq / eq.iloc[0] * 100, color=colors[i % len(colors)],
                 lw=1.5, label=f"{r['signal'][:3]}/{r['slice']}")
    if bench_eq is not None and not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq / bench_eq.iloc[0] * 100, color="#888",
                 lw=1.2, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3, ncol=2, fontsize=8)
    ax1.grid(True, alpha=.2); ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, 0]); ax2.set_title("Net CAGR by slice", fontweight="bold")
    labels = [f"{r['signal'][:3]}\n{r['slice'][:10]}" for r in rows]
    ax2.bar(range(len(rows)), [r["cagr"] * 100 for r in rows],
            color=[colors[i % len(colors)] for i in range(len(rows))])
    ax2.set_xticks(range(len(rows))); ax2.set_xticklabels(labels, rotation=0, fontsize=7)
    ax2.set_ylabel("Net CAGR %"); ax2.grid(True, alpha=.2, axis="y")

    ax3 = fig.add_subplot(gs[1, 1]); ax3.set_title("Cost drag (CAGR pts lost to costs)", fontweight="bold")
    ax3.bar(range(len(rows)), [r["cost_drag"] * 100 for r in rows],
            color=[colors[i % len(colors)] for i in range(len(rows))])
    ax3.set_xticks(range(len(rows))); ax3.set_xticklabels(labels, rotation=0, fontsize=7)
    ax3.set_ylabel("Cost drag (CAGR pts)"); ax3.grid(True, alpha=.2, axis="y")

    RDIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"  Chart saved: {RDIR / 'report.png'}")


if __name__ == "__main__":
    main()
