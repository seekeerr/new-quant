"""
RESEARCH PROGRAM #2 — TRACK 2, EXPERIMENT 2B: VOLUME-CONFIRMED BREAKOUT.

PRE-REGISTERED (RESEARCH_PROGRAM_2_TRACK2_DESIGN.md). A trend-CONTINUATION style: buy
stocks breaking out to new highs ON A VOLUME SURGE, and hold them while they stay strong.
Unlike the pullback style (2C), this is LOW-turnover — you ride winners — so it is NOT
pre-doomed by the Indian cost wall that killed 2C.

WHY THIS IS NOT THE FAILED 52-WEEK-HIGH FACTOR. Standalone 52WH-proximity was already
tested (Sharpe ~0.50 standalone, but FAILED blended into low-vol — it degenerated to
low-vol-only). The NEW element here is (a) a VOLUME-SURGE confirmation filter — a breakout
on heavy volume is a conviction move, a breakout on thin volume is noise — and (b) testing
it as a standalone OFFENSIVE signal at its natural (monthly/quarterly) frequency, never
blended into the defensive leg. To isolate volume's marginal value, a NO-VOLUME breakout
cell is run as a 52WH sanity check (should reproduce the ~0.50-Sharpe prior).

SIGNAL (Class-R rank-native; scorer closes over the volume panel):
  candidate IF  close >= 0.95 * 252-day high (at/near a new high)
            AND 5-day avg volume >= VOL_SURGE * 50-day avg volume (the volume confirmation)
  score      =  proximity-to-high (closest to a fresh high ranks best)
  exit       =  Buffer20 (hold the trend through noise) — the RIGHT buffer for a
                continuation style (contrast 2C's tight swing exit).

WHAT VARIES: rebalance frequency {monthly, quarterly} x {volume-confirmed, no-volume}.
WHAT IS FROZEN: Top-10 / EW / whole-share / survivorship-free Liquid Top-500 / full Indian
cost model / NET. Reference = Mom+LowVol Top-500 quarterly (champion in this shell).

GATES (charter §4): CAGR>17.4%, Sharpe>=0.69, MaxDD>=-38.5%, no split-sample sign-flip,
roll3y-min>0, survives x5/x10 stress. Expensive stress+capacity battery runs only on cells
that clear the headline gates (1-3).

PRE-REGISTERED PRIOR: directional + low-turnover, so a coin-flip to clear the bar. The open
question is whether volume confirmation adds enough over plain 52WH to beat the champion.

Run:  py run_program2_breakout.py
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

from run_buffer_experiment import run_buffered_backtest, drawdown_analytics, rolling_3y_cagr
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK
from run_program2_smallcap_validation import (
    run_impact_aware_backtest, stressed_config, subperiod,
    CHAMP_CAGR, CHAMP_SHARPE, CHAMP_DD, DD_TOL, SPLIT_DATE, CAP_LADDER, STRESS_MULTS,
)

CAP_BASE = 100_000.0
N_STOCKS, BUFFER_TREND = 10, 20         # hold-the-trend buffer
TOP500 = (0, 500)
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "program2_breakout"
HIGH_LB, PROX, VOL_SURGE, VOL_FAST, VOL_SLOW = 252, 0.95, 1.5, 5, 50

# Cells: (label, rebalance_freq, volume_confirmed)
CELLS = [
    ("vol-monthly",   "monthly",   True),
    ("vol-quarterly", "quarterly", True),
    ("novol-quarterly", "quarterly", False),   # 52WH sanity check (isolates volume's value)
]


def make_breakout_scorer(volume_panel, need_volume=True):
    """Rank near-new-high names (optionally volume-confirmed) by proximity to their high."""
    def scorer(close_panel, date, universe):
        cols = [s for s in universe if s in close_panel.columns]
        prices = close_panel.loc[close_panel.index <= date, cols]
        if len(prices) < HIGH_LB + 2:
            return pd.Series(dtype=float)
        last = prices.iloc[-1]
        high_n = prices.tail(HIGH_LB).max()
        prox = (last / high_n).replace([np.inf, -np.inf], np.nan)
        df = pd.DataFrame({"prox": prox}).dropna()
        df = df[df["prox"] >= PROX]                       # at/near a fresh high
        if need_volume:
            vol = volume_panel.loc[volume_panel.index <= date, cols]
            if len(vol) >= VOL_SLOW + 1:
                surge = (vol.tail(VOL_FAST).mean() / vol.tail(VOL_SLOW).mean()).replace([np.inf, -np.inf], np.nan)
                ok = surge[surge >= VOL_SURGE].index
                df = df[df.index.isin(ok)]
        if df.empty:
            return pd.Series(dtype=float)
        return df["prox"].sort_values(ascending=False)
    return scorer


def _full_metrics(res, bench_ret, cap):
    m = compute_metrics(res["equity_curve"], res["returns"], benchmark_returns=bench_ret,
                        trades=res["trades"], total_costs=res["total_costs"], initial_capital=cap)
    roll = rolling_3y_cagr(res["returns"])
    h1 = subperiod(res["equity_curve"], res["returns"], bench_ret, res["equity_curve"].index[0], SPLIT_DATE)
    h2 = subperiod(res["equity_curve"], res["returns"], bench_ret, SPLIT_DATE, res["equity_curve"].index[-1])
    return m, roll, h1, h2


def _gates(m, roll, h1, h2, stress, bm_cagr):
    g = [("CAGR>17.4%", m.cagr > CHAMP_CAGR), ("Sharpe>=0.69", m.sharpe_ratio >= CHAMP_SHARPE),
         ("MaxDD>=-38.5%", m.max_drawdown >= CHAMP_DD - DD_TOL),
         ("no sign-flip", h1 is not None and h2 is not None and h1.alpha > 0 and h2.alpha > 0),
         ("roll3y min>0", (not roll.empty) and roll.min() > 0)]
    if stress is not None:
        g.append(("survives stress", all(s.cagr > bm_cagr for s in stress.values())))
    return g


def main():
    t0 = time.time()
    cfg = SystemConfig()
    start, end = cfg.backtest.start_date, cfg.backtest.end_date
    print("=" * 100)
    print("  PROGRAM #2 EXP 2B — VOLUME-CONFIRMED BREAKOUT — Liquid Top-500 — NET".center(100))
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

    def builder():
        return RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, TOP500[0], TOP500[1])

    print("\n[ref] Mom+LowVol Top-500 quarterly (champion reference) ...")
    refres = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq="quarterly",
        buffer=20, initial_capital=CAP_BASE, config=cfg, apply_costs=True, label="champ ref",
        scorer=make_mom_lowvol_scorer(0.5, VOL_LOOKBACK), universe_builder=builder())
    refm = compute_metrics(refres["equity_curve"], refres["returns"], benchmark_returns=bench_ret,
                           trades=refres["trades"], total_costs=refres["total_costs"], initial_capital=CAP_BASE)

    cells = {}
    for label, freq, need_vol in CELLS:
        print(f"\n[{label}] breakout net + gross ...")
        scorer = make_breakout_scorer(av, need_volume=need_vol)
        net = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=freq,
            buffer=BUFFER_TREND, initial_capital=CAP_BASE, config=cfg, apply_costs=True,
            label=f"bo {label}", scorer=scorer, universe_builder=builder())
        gross = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=freq,
            buffer=BUFFER_TREND, initial_capital=CAP_BASE, config=cfg, apply_costs=False,
            label=f"bo {label} (g)", scorer=scorer, universe_builder=builder())
        m, roll, h1, h2 = _full_metrics(net, bench_ret, CAP_BASE)
        gm = compute_metrics(gross["equity_curve"], gross["returns"], initial_capital=CAP_BASE)
        cells[label] = {"freq": freq, "need_vol": need_vol, "net": net, "m": m, "gm": gm,
                        "roll": roll, "h1": h1, "h2": h2, "scorer": scorer}
        print(f"    CAGR {m.cagr:.2%} (gross {gm.cagr:.2%}, drag {gm.cagr-m.cagr:.2%}) | "
              f"Sharpe {m.sharpe_ratio:.2f} | MaxDD {m.max_drawdown:.2%} | turn {net['avg_turnover']:.0%}")

    eq0 = cells[CELLS[0][0]]["net"]["equity_curve"]
    bstart, bend = str(eq0.index[0].date()), str(eq0.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, CAP_BASE)
    bm_cagr = compute_metrics(bench_eq, initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan

    for label, c in cells.items():
        m = c["m"]
        headline_ok = (m.cagr > CHAMP_CAGR and m.sharpe_ratio >= CHAMP_SHARPE
                       and m.max_drawdown >= CHAMP_DD - DD_TOL)
        c["headline_ok"] = headline_ok
        c["stress"] = None; c["capacity"] = None
        if headline_ok:
            print(f"\n  [{label}] clears headline gates -> x5/x10 stress + impact capacity ...")
            stress = {}
            for mult in STRESS_MULTS:
                sr = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=c["freq"],
                    buffer=BUFFER_TREND, initial_capital=CAP_BASE, config=stressed_config(cfg, mult),
                    apply_costs=True, label=f"bo {label} x{mult:.0f}", scorer=c["scorer"],
                    universe_builder=builder())
                stress[mult] = compute_metrics(sr["equity_curve"], sr["returns"], benchmark_returns=bench_ret,
                    trades=sr["trades"], total_costs=sr["total_costs"], initial_capital=CAP_BASE)
            c["stress"] = stress
            cap_rows = []
            for capital in CAP_LADDER:
                res = run_impact_aware_backtest(ac, ah, al, av, at, n_stocks=N_STOCKS, rebalance_freq=c["freq"],
                    buffer=BUFFER_TREND, initial_capital=capital, config=cfg, scorer=c["scorer"],
                    universe_builder=builder(), label=f"{label} Rs{capital/1e5:.0f}L")
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
    labels = [c[0] for c in CELLS]
    w("=" * 100)
    w("  PROGRAM #2 EXP 2B — VOLUME-CONFIRMED BREAKOUT (Liquid Top-500, NET)".center(100))
    w("=" * 100)
    w(f"Period {bstart}..{bend}   Shell Top{N_STOCKS}/EW/Buffer{BUFFER_TREND}   NIFTY500(px) {bm_cagr:.2%}")
    w(f"Champion ref (Mom+LowVol Top-500 quarterly): CAGR {refm.cagr:.2%} Sharpe {refm.sharpe_ratio:.2f} "
      f"MaxDD {refm.max_drawdown:.1%}")
    w(f"Breakout: close>={PROX:.0%} of {HIGH_LB}d-high" +
      f", volume {VOL_FAST}d/{VOL_SLOW}d >= {VOL_SURGE}x (where confirmed).")
    w("")
    hdr = (f"{'Cell':<17}{'Net CAGR':>10}{'Gross':>9}{'Drag':>8}{'Sharpe':>8}{'MaxDD':>9}"
           f"{'Turn':>7}{'roll3yMin':>11}{'H1 a':>8}{'H2 a':>8}")
    w(hdr); w("-" * 100)
    for label in labels:
        c = cells[label]; m = c["m"]
        rmin = c["roll"].min() if not c["roll"].empty else np.nan
        h1a = c["h1"].alpha if c["h1"] else np.nan
        h2a = c["h2"].alpha if c["h2"] else np.nan
        w(f"{label:<17}{m.cagr:>9.1%}{c['gm'].cagr:>9.1%}{c['gm'].cagr-m.cagr:>8.1%}"
          f"{m.sharpe_ratio:>8.2f}{m.max_drawdown:>9.1%}{c['net']['avg_turnover']:>6.0%}"
          f"{rmin:>10.1%}{h1a:>+8.1%}{h2a:>+8.1%}")
    w("-" * 100); w("")
    for label in labels:
        c = cells[label]; m = c["m"]
        gates = _gates(m, c["roll"], c["h1"], c["h2"], c["stress"], bm_cagr)
        passed = all(p for _, p in gates)
        w(f"[{label}]  {'ALL GATES PASS' if passed else 'FAILS: ' + ', '.join(n for n, p in gates if not p)}")
        if c["stress"] is not None:
            w("    stress: " + " ".join(f"x{int(k)} {v.cagr:.1%}" for k, v in c["stress"].items())
              + f"  (bm {bm_cagr:.1%})")
        if c["capacity"] is not None:
            w("    capacity: " + " ".join(f"Rs{r['capital']/1e5:.0f}L {r['cagr']:.1%}" for r in c["capacity"]))
    w("")
    vol_q = cells["vol-quarterly"]["m"].cagr
    novol_q = cells["novol-quarterly"]["m"].cagr
    w(f"Volume confirmation marginal value (quarterly): {vol_q-novol_q:+.1%} net CAGR "
      f"(vol {vol_q:.1%} vs no-vol {novol_q:.1%}).")
    any_pass = any(all(p for _, p in _gates(cells[l]["m"], cells[l]["roll"], cells[l]["h1"],
                       cells[l]["h2"], cells[l]["stress"], bm_cagr)) for l in labels)
    w("-" * 100)
    if any_pass:
        w("VERDICT: a breakout cell CLEARS all gates -> volume-confirmed breakout beats the champion.")
        w("  Promote for deeper validation (slice-robustness, OOS, parameter stability).")
    else:
        best = max(labels, key=lambda l: cells[l]["m"].sharpe_ratio)
        w(f"VERDICT: NO breakout cell clears all gates. Best = {best} "
          f"(Sharpe {cells[best]['m'].sharpe_ratio:.2f}, CAGR {cells[best]['m'].cagr:.1%}).")
        w("  Volume-confirmed breakout does NOT beat the frozen champion net of costs in this shell.")
    w("=" * 100)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")

    rows = []
    for label in labels:
        c = cells[label]; m = c["m"]
        rows.append({"cell": label, "freq": c["freq"], "volume_confirmed": c["need_vol"],
                     "cagr": m.cagr, "gross_cagr": c["gm"].cagr, "cost_drag": c["gm"].cagr - m.cagr,
                     "sharpe": m.sharpe_ratio, "max_dd": m.max_drawdown, "alpha": m.alpha,
                     "turnover": c["net"]["avg_turnover"],
                     "roll3y_min": c["roll"].min() if not c["roll"].empty else np.nan,
                     "h1_alpha": c["h1"].alpha if c["h1"] else np.nan,
                     "h2_alpha": c["h2"].alpha if c["h2"] else np.nan,
                     "headline_ok": c["headline_ok"]})
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


def _chart(cells, refres, bench_eq, bm_cagr):
    plt.style.use("dark_background")
    labels = [c[0] for c in CELLS]
    fig = plt.figure(figsize=(18, 11))
    gs = GridSpec(2, 2, figure=fig, hspace=0.32, wspace=0.22)
    fig.suptitle("Program #2 Exp 2B — Volume-Confirmed Breakout (Liquid Top-500, net)",
                 fontsize=15, fontweight="bold", color="#fff", y=0.97)
    palette = ["#00ff88", "#ffd93d", "#ff6b6b"]

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for i, label in enumerate(labels):
        eq = cells[label]["net"]["equity_curve"]
        ax1.plot(eq.index, eq/eq.iloc[0]*100, color=palette[i % len(palette)], lw=1.4, label=label)
    req = refres["equity_curve"]
    ax1.plot(req.index, req/req.iloc[0]*100, color="#4ecdc4", lw=1.4, ls="-.", label="champion ref")
    if not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.0, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, 0]); ax2.set_title("Net vs Gross CAGR", fontweight="bold")
    x = np.arange(len(labels))
    ax2.bar(x-0.2, [cells[l]["m"].cagr*100 for l in labels], 0.4, color="#00ff88", label="net")
    ax2.bar(x+0.2, [cells[l]["gm"].cagr*100 for l in labels], 0.4, color="#4ecdc4", label="gross")
    ax2.axhline(CHAMP_CAGR*100, color="#fff", ls=":", lw=1, label=f"champ {CHAMP_CAGR:.0%}")
    ax2.axhline(bm_cagr*100, color="#888", ls="--", lw=1, label=f"bm {bm_cagr:.0%}")
    ax2.set_xticks(x); ax2.set_xticklabels(labels, fontsize=7, rotation=10); ax2.set_ylabel("CAGR %")
    ax2.legend(framealpha=.3, fontsize=7); ax2.grid(True, alpha=.2, axis="y")

    ax3 = fig.add_subplot(gs[1, 1]); ax3.set_title("Sharpe vs champion", fontweight="bold")
    ax3.bar(x, [cells[l]["m"].sharpe_ratio for l in labels], color=palette[:len(labels)])
    ax3.axhline(CHAMP_SHARPE, color="#fff", ls=":", lw=1, label=f"champ {CHAMP_SHARPE}")
    ax3.set_xticks(x); ax3.set_xticklabels(labels, fontsize=7, rotation=10); ax3.set_ylabel("Sharpe")
    ax3.legend(framealpha=.3, fontsize=7); ax3.grid(True, alpha=.2, axis="y")

    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
