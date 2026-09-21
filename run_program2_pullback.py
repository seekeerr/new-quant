"""
RESEARCH PROGRAM #2 — TRACK 2, EXPERIMENT 2C: PULLBACK-IN-UPTREND (swing style).

PRE-REGISTERED (RESEARCH_PROGRAM_2_TRACK2_DESIGN.md, the Track-2 LEAD). A genuinely
different STYLE from the frozen momentum/low-vol champion: a short-horizon swing system
that buys temporary WEAKNESS in confirmed STRONG stocks.

WHY THIS IS NOT THE DEAD REVERSAL STYLE. Standalone short-term reversal (buy the 21-day
losers) was catastrophic — negative even gross, -82% DD — because it bought absolute
losers: distressed, high-beta, falling-knife micro-caps. Pullback-in-uptrend buys the
SAME kind of contrarian dip but ONLY in names that are (a) above their 200-day SMA and
(b) have positive 12-1 momentum. Same entry shape, opposite quality of name. This directly
tests whether the reversal failure was the STYLE or the POPULATION it selected.

SIGNAL (Class-R rank-native; drop-in scorer, engine reused verbatim):
  candidate IF  close > SMA200  AND  12-1 momentum > 0  AND  5-day return < 0 (a real dip)
  score      =  -(5-day return)         # deepest dip in a strong uptrend ranks best
  exit       =  plain Top-N (no buffer) -> a name is dropped once it is no longer a top
                pullback candidate (i.e. after it bounces). This tight exit is INTRINSIC to
                a swing style, not a tuned knob; stated up front.

WHAT VARIES (the only independent variable): rebalance frequency = weekly / biweekly /
monthly (the swing horizon). Faster = more bounces captured but more turnover/cost.
WHAT IS FROZEN: Top-10 / EW / whole-share / survivorship-free Liquid Top-500 universe
(the champion's own slice -> isolates STYLE from universe; realistic fills) / full Indian
cost model / NET of costs. Reference = Mom+LowVol Top-500 quarterly (champion in this shell).

GATES (charter §4, identical): CAGR > 17.4%, Sharpe >= 0.69, MaxDD >= -38.5%, no
split-sample sign-flip (alpha>0 both halves), survives x5/x10 cost stress vs benchmark,
rolling 3y min CAGR > 0. A cell is judged on ALL six. The expensive stress + impact-aware
capacity battery runs ONLY on cells that clear the headline gates (1-3) — no point
cost-stressing a style that already misses on raw return.

PRE-REGISTERED PRIOR: most promising new style (fixes reversal's failure), but weekly
turnover is a steep cost headwind; the cost gates decide it. Honest expectation: a
coin-flip to clear gate 1, likely fails on cost drag at weekly cadence.

Run:  py run_program2_pullback.py
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

from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import run_buffered_backtest, drawdown_analytics, rolling_3y_cagr
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK
# Reuse the validated tools from Exp 1 so the cost-realism + capacity tests are IDENTICAL.
from run_program2_smallcap_validation import (
    run_impact_aware_backtest, stressed_config, subperiod,
    CHAMP_CAGR, CHAMP_SHARPE, CHAMP_DD, DD_TOL, SPLIT_DATE, CAP_LADDER, STRESS_MULTS,
)

CAP_BASE = 100_000.0
N_STOCKS, BUFFER_SWING = 10, 10        # buffer == N -> plain Top-N (tight swing exit)
TOP500 = (0, 500)
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "program2_pullback"
FREQS = ["weekly", "biweekly", "monthly"]


def make_pullback_scorer(trend_lb=200, pullback_lb=5, mom_gate=0.0):
    """Buy the deepest short-term dip among confirmed-strong uptrending names.
    candidate: close>SMA(trend_lb) AND 12-1 momentum>mom_gate AND pullback_lb-day return<0.
    score = -(pullback return) so the deepest dip ranks first."""
    def scorer(close_panel, date, universe):
        cols = [s for s in universe if s in close_panel.columns]
        prices = close_panel.loc[close_panel.index <= date, cols]
        if len(prices) < max(trend_lb, 252) + 2:
            return pd.Series(dtype=float)
        last = prices.iloc[-1]
        sma = prices.tail(trend_lb).mean()
        st = last / prices.iloc[-(pullback_lb + 1)] - 1            # short-term return
        mom = compute_12_1_momentum(close_panel, date, universe)   # raw 12-1 momentum
        strong = set(mom[mom > mom_gate].index)
        df = pd.DataFrame({"last": last, "sma": sma, "st": st}).replace([np.inf, -np.inf], np.nan).dropna()
        cand = df[(df["last"] > df["sma"]) & (df["st"] < 0) & (df.index.to_series().isin(strong))]
        if cand.empty:
            return pd.Series(dtype=float)
        return (-cand["st"]).sort_values(ascending=False)
    return scorer


def _full_metrics(res, bench_ret, cap):
    m = compute_metrics(res["equity_curve"], res["returns"], benchmark_returns=bench_ret,
                        trades=res["trades"], total_costs=res["total_costs"], initial_capital=cap)
    roll = rolling_3y_cagr(res["returns"])
    h1 = subperiod(res["equity_curve"], res["returns"], bench_ret, res["equity_curve"].index[0], SPLIT_DATE)
    h2 = subperiod(res["equity_curve"], res["returns"], bench_ret, SPLIT_DATE, res["equity_curve"].index[-1])
    return m, roll, h1, h2


def _gates(m, roll, h1, h2, stress, bm_cagr):
    g = []
    g.append(("CAGR>17.4%", m.cagr > CHAMP_CAGR))
    g.append(("Sharpe>=0.69", m.sharpe_ratio >= CHAMP_SHARPE))
    g.append(("MaxDD>=-38.5%", m.max_drawdown >= CHAMP_DD - DD_TOL))
    g.append(("no sign-flip", h1 is not None and h2 is not None and h1.alpha > 0 and h2.alpha > 0))
    g.append(("roll3y min>0", (not roll.empty) and roll.min() > 0))
    if stress is not None:
        g.append(("survives stress", all(s.cagr > bm_cagr for s in stress.values())))
    return g


def main():
    t0 = time.time()
    cfg = SystemConfig()
    start, end = cfg.backtest.start_date, cfg.backtest.end_date
    print("=" * 100)
    print("  PROGRAM #2 EXP 2C — PULLBACK-IN-UPTREND (swing) — Liquid Top-500 — NET".center(100))
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

    scorer = make_pullback_scorer()

    def builder():
        return RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, TOP500[0], TOP500[1])

    # ── Reference: champion (Mom+LowVol Top-500 quarterly Buffer20) in this shell ──
    print("\n[ref] Mom+LowVol Top-500 quarterly (champion reference) ...")
    refres = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq="quarterly",
        buffer=20, initial_capital=CAP_BASE, config=cfg, apply_costs=True, label="champ ref",
        scorer=make_mom_lowvol_scorer(0.5, VOL_LOOKBACK), universe_builder=builder())
    refm = compute_metrics(refres["equity_curve"], refres["returns"], benchmark_returns=bench_ret,
                           trades=refres["trades"], total_costs=refres["total_costs"], initial_capital=CAP_BASE)

    # ── Pullback cells: net + gross at each frequency ──
    cells = {}
    for freq in FREQS:
        print(f"\n[{freq}] pullback net + gross ...")
        net = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=freq,
            buffer=BUFFER_SWING, initial_capital=CAP_BASE, config=cfg, apply_costs=True,
            label=f"pullback {freq}", scorer=scorer, universe_builder=builder())
        gross = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=freq,
            buffer=BUFFER_SWING, initial_capital=CAP_BASE, config=cfg, apply_costs=False,
            label=f"pullback {freq} (g)", scorer=scorer, universe_builder=builder())
        m, roll, h1, h2 = _full_metrics(net, bench_ret, CAP_BASE)
        gm = compute_metrics(gross["equity_curve"], gross["returns"], initial_capital=CAP_BASE)
        cells[freq] = {"net": net, "m": m, "gm": gm, "roll": roll, "h1": h1, "h2": h2,
                       "extra": drawdown_analytics(net["equity_curve"])}
        print(f"    CAGR {m.cagr:.2%} (gross {gm.cagr:.2%}, drag {gm.cagr-m.cagr:.2%}) | "
              f"Sharpe {m.sharpe_ratio:.2f} | MaxDD {m.max_drawdown:.2%} | turn {net['avg_turnover']:.0%}")

    # benchmark aligned
    eq0 = cells[FREQS[0]]["net"]["equity_curve"]
    bstart, bend = str(eq0.index[0].date()), str(eq0.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, CAP_BASE)
    bm_cagr = compute_metrics(bench_eq, initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan

    # ── Headline gate (1-3) decides which cells get the expensive battery ──
    for freq, c in cells.items():
        m = c["m"]
        headline_ok = (m.cagr > CHAMP_CAGR and m.sharpe_ratio >= CHAMP_SHARPE
                       and m.max_drawdown >= CHAMP_DD - DD_TOL)
        c["headline_ok"] = headline_ok
        c["stress"] = None
        c["capacity"] = None
        if headline_ok:
            print(f"\n  [{freq}] clears headline gates -> running x5/x10 stress + impact capacity ...")
            stress = {}
            for mult in STRESS_MULTS:
                sr = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=freq,
                    buffer=BUFFER_SWING, initial_capital=CAP_BASE, config=stressed_config(cfg, mult),
                    apply_costs=True, label=f"pullback {freq} x{mult:.0f}", scorer=scorer,
                    universe_builder=builder())
                stress[mult] = compute_metrics(sr["equity_curve"], sr["returns"], benchmark_returns=bench_ret,
                    trades=sr["trades"], total_costs=sr["total_costs"], initial_capital=CAP_BASE)
            c["stress"] = stress
            cap_rows = []
            for capital in CAP_LADDER:
                res = run_impact_aware_backtest(ac, ah, al, av, at, n_stocks=N_STOCKS, rebalance_freq=freq,
                    buffer=BUFFER_SWING, initial_capital=capital, config=cfg, scorer=scorer,
                    universe_builder=builder(), label=f"{freq} Rs{capital/1e5:.0f}L")
                cm = compute_metrics(res["equity_curve"], res["returns"], benchmark_returns=bench_ret,
                    trades=res["trades"], total_costs=res["total_costs"], initial_capital=capital)
                cap_rows.append({"capital": capital, "cagr": cm.cagr, "sharpe": cm.sharpe_ratio,
                                 "impact": res.get("total_impact", 0.0)})
            c["capacity"] = cap_rows

    RDIR.mkdir(parents=True, exist_ok=True)
    _report(cells, refm, bm_cagr, bstart, bend, bench_eq)
    _chart(cells, refres, bench_eq, bm_cagr)
    print(f"\n  Saved to {RDIR}/   (total {time.time()-t0:.0f}s)")


def _report(cells, refm, bm_cagr, bstart, bend, bench_eq):
    L = []; w = L.append
    w("=" * 100)
    w("  PROGRAM #2 EXP 2C — PULLBACK-IN-UPTREND (Liquid Top-500, NET of costs)".center(100))
    w("=" * 100)
    w(f"Period {bstart}..{bend}   Shell Top{N_STOCKS}/EW/swing-exit   NIFTY500(px) {bm_cagr:.2%}")
    w(f"Champion ref (Mom+LowVol Top-500 quarterly): CAGR {refm.cagr:.2%} Sharpe {refm.sharpe_ratio:.2f} "
      f"MaxDD {refm.max_drawdown:.1%}")
    w(f"Gate bar: CAGR>{CHAMP_CAGR:.1%}, Sharpe>={CHAMP_SHARPE}, MaxDD>=-38.5%, no sign-flip, "
      f"roll3y-min>0, survives stress.")
    w("")
    hdr = (f"{'Freq':<10}{'Net CAGR':>10}{'Gross':>9}{'Drag':>8}{'Sharpe':>8}{'MaxDD':>9}"
           f"{'Turn/reb':>9}{'roll3yMin':>11}{'H1 a':>8}{'H2 a':>8}")
    w(hdr); w("-" * 100)
    for freq in FREQS:
        c = cells[freq]; m = c["m"]
        rmin = c["roll"].min() if not c["roll"].empty else np.nan
        h1a = c["h1"].alpha if c["h1"] else np.nan
        h2a = c["h2"].alpha if c["h2"] else np.nan
        w(f"{freq:<10}{m.cagr:>9.1%}{c['gm'].cagr:>9.1%}{c['gm'].cagr-m.cagr:>8.1%}"
          f"{m.sharpe_ratio:>8.2f}{m.max_drawdown:>9.1%}{c['net']['avg_turnover']:>8.0%}"
          f"{rmin:>10.1%}{h1a:>+8.1%}{h2a:>+8.1%}")
    w("-" * 100)
    w("")
    for freq in FREQS:
        c = cells[freq]; m = c["m"]
        gates = _gates(m, c["roll"], c["h1"], c["h2"], c["stress"], bm_cagr)
        passed = all(p for _, p in gates)
        w(f"[{freq}]  {'ALL GATES PASS' if passed else 'FAILS: ' + ', '.join(n for n, p in gates if not p)}")
        if c["stress"] is not None:
            w("    stress: " + " ".join(f"x{int(k)} {v.cagr:.1%}" for k, v in c["stress"].items())
              + f"  (bm {bm_cagr:.1%})")
        if c["capacity"] is not None:
            w("    capacity: " + " ".join(f"Rs{r['capital']/1e5:.0f}L {r['cagr']:.1%}" for r in c["capacity"]))
    w("")
    any_pass = any(all(p for _, p in _gates(cells[f]["m"], cells[f]["roll"], cells[f]["h1"],
                       cells[f]["h2"], cells[f]["stress"], bm_cagr)) for f in FREQS)
    w("-" * 100)
    if any_pass:
        w("VERDICT: at least one pullback cadence CLEARS all gates -> a genuinely different style")
        w("  beats the champion. Promote for deeper validation (slice-robustness, OOS).")
    else:
        best = max(FREQS, key=lambda f: cells[f]["m"].sharpe_ratio)
        bm = cells[best]["m"]
        w(f"VERDICT: NO pullback cadence clears all gates. Best = {best} "
          f"(CAGR {bm.cagr:.1%}, Sharpe {bm.sharpe_ratio:.2f}, drag {cells[best]['gm'].cagr-bm.cagr:.1%}).")
        w("  Pullback-in-uptrend does NOT beat the frozen champion net of Indian costs in this shell.")
        w("  (Whether the loss is cost-drag or raw edge is shown by the gross/drag columns.) -> 2B next.")
    w("=" * 100)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")

    rows = []
    for freq in FREQS:
        c = cells[freq]; m = c["m"]
        rows.append({"freq": freq, "cagr": m.cagr, "gross_cagr": c["gm"].cagr,
                     "cost_drag": c["gm"].cagr - m.cagr, "sharpe": m.sharpe_ratio,
                     "max_dd": m.max_drawdown, "alpha": m.alpha, "turnover": c["net"]["avg_turnover"],
                     "roll3y_min": c["roll"].min() if not c["roll"].empty else np.nan,
                     "h1_alpha": c["h1"].alpha if c["h1"] else np.nan,
                     "h2_alpha": c["h2"].alpha if c["h2"] else np.nan,
                     "headline_ok": c["headline_ok"]})
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


def _chart(cells, refres, bench_eq, bm_cagr):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 11))
    gs = GridSpec(2, 2, figure=fig, hspace=0.32, wspace=0.22)
    fig.suptitle("Program #2 Exp 2C — Pullback-in-Uptrend (Liquid Top-500, net)",
                 fontsize=15, fontweight="bold", color="#fff", y=0.97)
    cols = {"weekly": "#ff6b6b", "biweekly": "#ffd93d", "monthly": "#00ff88"}

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for freq in FREQS:
        eq = cells[freq]["net"]["equity_curve"]
        ax1.plot(eq.index, eq/eq.iloc[0]*100, color=cols[freq], lw=1.4, label=f"pullback {freq}")
    req = refres["equity_curve"]
    ax1.plot(req.index, req/req.iloc[0]*100, color="#4ecdc4", lw=1.4, ls="-.", label="champion ref")
    if not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.0, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, 0]); ax2.set_title("Net vs Gross CAGR (cost drag)", fontweight="bold")
    x = np.arange(len(FREQS))
    ax2.bar(x-0.2, [cells[f]["m"].cagr*100 for f in FREQS], 0.4, color="#00ff88", label="net")
    ax2.bar(x+0.2, [cells[f]["gm"].cagr*100 for f in FREQS], 0.4, color="#4ecdc4", label="gross")
    ax2.axhline(CHAMP_CAGR*100, color="#fff", ls=":", lw=1, label=f"champ {CHAMP_CAGR:.0%}")
    ax2.axhline(bm_cagr*100, color="#888", ls="--", lw=1, label=f"bm {bm_cagr:.0%}")
    ax2.set_xticks(x); ax2.set_xticklabels(FREQS); ax2.set_ylabel("CAGR %")
    ax2.legend(framealpha=.3, fontsize=7); ax2.grid(True, alpha=.2, axis="y")

    ax3 = fig.add_subplot(gs[1, 1]); ax3.set_title("Turnover per rebalance", fontweight="bold")
    ax3.bar(x, [cells[f]["net"]["avg_turnover"]*100 for f in FREQS], color=[cols[f] for f in FREQS])
    ax3.set_xticks(x); ax3.set_xticklabels(FREQS); ax3.set_ylabel("Turnover %/reb")
    ax3.grid(True, alpha=.2, axis="y")

    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
