"""
RESEARCH PROGRAM #2 — HARDENING THE A+B ENSEMBLE (2nd production candidate).

USER DECISION (2026-07-06): A+C(w=0.3) has earned paper trading (passed all six gates). Before
the FINAL production choice, apply the IDENTICAL validation protocol to A+B — champion +
small-cap-tail — which showed higher Sharpe (0.95) and removes the breakout sleeve that the
A+C hardening identified as the source of parameter-sensitivity and cost-fragility. Both
candidates must clear the SAME bar so the production decision is evidence-based, not an artifact
of unequal validation.

A+B sleeves (net, survivorship-free, Top-10/Buffer20, Rs 1L):
  A = Mom+LowVol, Liquid Top-500, quarterly            (the champion sleeve, identical to A+C)
  B = Mom+LowVol, SmallCap rank-band 300-1000, quarterly (the validated-but-cyclical tail)

IDENTICAL PROTOCOL to `run_program2_ensemble_validation.py` (same helpers reused):
  1a. Blend-weight stability: w_B in {0.3..0.7} (base 0.5).
  1b. Parameter stability of the B sleeve, one-at-a-time around base (Mom/LowVol blend 0.5,
      vol-lookback 252, band 300-1000): blend {0.4,0.6}, vol-lb {126,378}, band-start {200,400}.
  2.  Realistic implementation: idealised daily vs drift / monthly-rebal / quarterly-rebal with
      the same inter-sleeve transfer cost.
  3.  Cost stress: re-run both sleeves under x5/x10 slippage, re-blend.
  4.  Consistency: split-sample alpha, rolling-3y min.
Judged on the same six gates vs the champion bar (17.4%/0.69).

Run:  py run_program2_ab_hardening.py
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

from run_buffer_experiment import run_buffered_backtest, rolling_3y_cagr
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK
from run_program2_smallcap_validation import (
    stressed_config, CHAMP_CAGR, CHAMP_SHARPE, CHAMP_DD, DD_TOL,
)
# Reuse the EXACT hardening helpers so the protocol is provably identical to A+C.
from run_program2_ensemble_validation import (
    blend_daily, blend_rebalanced, metrics_of, gate_str,
)

CAP_BASE = 100_000.0
N_STOCKS, BUFFER = 10, 20
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "program2_ab_hardening"
# B sleeve base params.
BASE_WMOM, BASE_VOLLB, BASE_LO, BASE_HI = 0.5, VOL_LOOKBACK, 300, 1000


def sleeve_band(ac, ah, al, av, at, cfg, scorer, freq, lo, hi):
    bld = RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, lo, hi)
    res = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=freq,
        buffer=BUFFER, initial_capital=CAP_BASE, config=cfg, apply_costs=True, label="sleeve",
        scorer=scorer, universe_builder=bld)
    return res["returns"]


def b_sleeve(ac, ah, al, av, at, cfg, wmom=BASE_WMOM, vollb=BASE_VOLLB, lo=BASE_LO, hi=BASE_HI):
    return sleeve_band(ac, ah, al, av, at, cfg, make_mom_lowvol_scorer(wmom, vollb), "quarterly", lo, hi)


def main():
    t0 = time.time()
    cfg = SystemConfig()
    start, end = cfg.backtest.start_date, cfg.backtest.end_date
    print("=" * 100)
    print("  PROGRAM #2 — HARDENING THE A+B ENSEMBLE (identical protocol to A+C)".center(100))
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
    print(f"  equity universe: {ac.shape[1]} symbols x {ac.shape[0]} dates\n")

    print("Base sleeves (net): A=Mom+LowVol Top-500 qtrly, B=Mom+LowVol 300-1000 qtrly ...")
    rA = sleeve_band(ac, ah, al, av, at, cfg, make_mom_lowvol_scorer(0.5, VOL_LOOKBACK), "quarterly", 0, 500)
    rB = b_sleeve(ac, ah, al, av, at, cfg)

    common = rA.index.intersection(rB.index)
    bstart, bend = str(common[0].date()), str(common[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, CAP_BASE)
    bm_cagr = compute_metrics(bench_eq, initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan

    base_eq, base_m, base_roll, base_h1, base_h2 = metrics_of(blend_daily(rA, rB, 0.5), bench_ret)

    weight_rows = []
    for w in [0.3, 0.4, 0.5, 0.6, 0.7]:
        _, m, roll, h1, h2 = metrics_of(blend_daily(rA, rB, w), bench_ret)
        weight_rows.append((w, m, roll, h1, h2))

    param_variants = [("base", dict()),
                      ("wmom0.4", dict(wmom=0.4)), ("wmom0.6", dict(wmom=0.6)),
                      ("vollb126", dict(vollb=126)), ("vollb378", dict(vollb=378)),
                      ("band200", dict(lo=200)), ("band400", dict(lo=400))]
    param_rows = []
    for name, kw in param_variants:
        rb = rB if name == "base" else b_sleeve(ac, ah, al, av, at, cfg, **kw)
        _, m, roll, h1, h2 = metrics_of(blend_daily(rA, rb, 0.5), bench_ret)
        param_rows.append((name, m, roll))

    impl_rows = []
    for label, freq in [("daily (idealised)", "daily"), ("drift 50/50", None),
                        ("monthly-rebal", "monthly"), ("quarterly-rebal", "quarterly")]:
        r = blend_daily(rA, rB, 0.5) if freq == "daily" else blend_rebalanced(rA, rB, 0.5, freq)
        _, m, roll, h1, h2 = metrics_of(r, bench_ret)
        impl_rows.append((label, m, roll, h1, h2))

    stress_rows = []
    for mult in [5.0, 10.0]:
        scfg = stressed_config(cfg, mult)
        rAs = sleeve_band(ac, ah, al, av, at, scfg, make_mom_lowvol_scorer(0.5, VOL_LOOKBACK), "quarterly", 0, 500)
        rBs = b_sleeve(ac, ah, al, av, at, scfg)
        _, m, roll, _, _ = metrics_of(blend_daily(rAs, rBs, 0.5), bench_ret)
        stress_rows.append((mult, m, roll))

    RDIR.mkdir(parents=True, exist_ok=True)
    _report(base_m, base_roll, base_h1, base_h2, weight_rows, param_rows, impl_rows, stress_rows,
            bm_cagr, bstart, bend, base_eq)
    _chart(base_eq, bench_eq, weight_rows, param_rows, impl_rows)
    print(f"\n  Saved to {RDIR}/   (total {time.time()-t0:.0f}s)")


def _report(base_m, base_roll, base_h1, base_h2, weight_rows, param_rows, impl_rows, stress_rows,
            bm_cagr, bstart, bend, base_eq):
    L = []; w = L.append
    w("=" * 100)
    w("  PROGRAM #2 — A+B ENSEMBLE HARDENING (net, Rs 1,00,000)".center(100))
    w("=" * 100)
    w(f"Period {bstart}..{bend}   NIFTY500(px) {bm_cagr:.2%}   Champion bar 17.4%/0.69")
    w(f"Base A+B (idealised daily 50/50): CAGR {base_m.cagr:.2%} | Sharpe {base_m.sharpe_ratio:.2f} | "
      f"MaxDD {base_m.max_drawdown:.2%} | roll3y-min {base_roll.min():.1%}")
    w(f"  split-sample alpha: H1 {base_h1.alpha:+.1%} / H2 {base_h2.alpha:+.1%} (both +ve = no flip)")
    w("")
    w("1a. BLEND-WEIGHT STABILITY (w_B = small-cap-tail weight):")
    w(f"    {'w_B':>6}{'CAGR':>9}{'Sharpe':>8}{'MaxDD':>9}{'roll3yMin':>11}   gates")
    for wb, m, roll, h1, h2 in weight_rows:
        w(f"    {wb:>6.1f}{m.cagr:>8.1%}{m.sharpe_ratio:>8.2f}{m.max_drawdown:>9.1%}"
          f"{roll.min():>10.1%}   {gate_str(m, roll, h1, h2, bm_cagr)}")
    w("")
    w("1b. B-SLEEVE PARAMETER STABILITY (one-at-a-time, blended 50/50 with A):")
    w(f"    {'variant':<12}{'CAGR':>9}{'Sharpe':>8}{'MaxDD':>9}{'roll3yMin':>11}")
    for name, m, roll in param_rows:
        w(f"    {name:<12}{m.cagr:>8.1%}{m.sharpe_ratio:>8.2f}{m.max_drawdown:>9.1%}{roll.min():>10.1%}")
    w("")
    w("2. REALISTIC IMPLEMENTATION (idealised vs actual two-sleeve rebalancing + cost):")
    w(f"    {'scheme':<20}{'CAGR':>9}{'Sharpe':>8}{'MaxDD':>9}{'roll3yMin':>11}   gates")
    for label, m, roll, h1, h2 in impl_rows:
        w(f"    {label:<20}{m.cagr:>8.1%}{m.sharpe_ratio:>8.2f}{m.max_drawdown:>9.1%}"
          f"{roll.min():>10.1%}   {gate_str(m, roll, h1, h2, bm_cagr)}")
    w("")
    w("3. COST STRESS (both sleeves stressed, re-blended 50/50):")
    for mult, m, roll in stress_rows:
        w(f"    x{int(mult):>2} slippage: CAGR {m.cagr:.1%} | Sharpe {m.sharpe_ratio:.2f} | "
          f"roll3y-min {roll.min():.1%}  (bm {bm_cagr:.1%})")
    w("")
    w("-" * 100)
    cagrs = [m.cagr for _, m, _, _, _ in weight_rows] + [m.cagr for _, m, _ in param_rows]
    impl_cagrs = [m.cagr for _, m, _, _, _ in impl_rows]
    sharpes = [m.sharpe_ratio for _, m, _ in param_rows]
    all_pass_weights = [wb for wb, m, roll, h1, h2 in weight_rows if gate_str(m, roll, h1, h2, bm_cagr) == "PASS-all"]
    w("ASSESSMENT:")
    w(f"  Param/weight CAGR range {min(cagrs):.1%}..{max(cagrs):.1%} (spread {max(cagrs)-min(cagrs):.1%}) "
      f"-> {'STABLE' if max(cagrs)-min(cagrs) < 0.06 else 'SENSITIVE'} to reasonable parameter choices.")
    w(f"  Param Sharpe range {min(sharpes):.2f}..{max(sharpes):.2f}.")
    w(f"  Realistic implementation CAGR {min(impl_cagrs):.1%}..{max(impl_cagrs):.1%} "
      f"(idealised {impl_rows[0][1].cagr:.1%}) -> realism cost {impl_rows[0][1].cagr-min(impl_cagrs):.1%} pts.")
    w(f"  Cost stress: x5 {stress_rows[0][1].cagr:.1%}, x10 {stress_rows[1][1].cagr:.1%} "
      f"(x10 {'>' if stress_rows[1][1].cagr > bm_cagr else '<'} benchmark {bm_cagr:.1%}).")
    w(f"  All-gate-passing weights w_B: {all_pass_weights if all_pass_weights else 'NONE'}.")
    w("  (Compare vs A+C hardening: A+C was param-sensitive on breakout + failed x10 stress; "
      "A+C w=0.3 passed all gates at 18.9%.)")
    w("=" * 100)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")

    rows = [{"test": "weight", "variant": f"wB={wb}", "cagr": m.cagr, "sharpe": m.sharpe_ratio,
             "max_dd": m.max_drawdown, "roll3y_min": roll.min(),
             "gates": gate_str(m, roll, h1, h2, bm_cagr)} for wb, m, roll, h1, h2 in weight_rows]
    rows += [{"test": "param", "variant": n, "cagr": m.cagr, "sharpe": m.sharpe_ratio,
              "max_dd": m.max_drawdown, "roll3y_min": roll.min(), "gates": ""} for n, m, roll in param_rows]
    rows += [{"test": "impl", "variant": l, "cagr": m.cagr, "sharpe": m.sharpe_ratio,
              "max_dd": m.max_drawdown, "roll3y_min": roll.min(),
              "gates": gate_str(m, roll, h1, h2, bm_cagr)} for l, m, roll, h1, h2 in impl_rows]
    rows += [{"test": "stress", "variant": f"x{int(k)}", "cagr": m.cagr, "sharpe": m.sharpe_ratio,
              "max_dd": m.max_drawdown, "roll3y_min": roll.min(), "gates": ""} for k, m, roll in stress_rows]
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


def _chart(base_eq, bench_eq, weight_rows, param_rows, impl_rows):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 11)); gs = GridSpec(2, 2, figure=fig, hspace=0.32, wspace=0.22)
    fig.suptitle("Program #2 — A+B Ensemble Hardening (net)", fontsize=15, fontweight="bold",
                 color="#fff", y=0.97)

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Base A+B equity (base 100, log)", fontweight="bold")
    ax1.plot(base_eq.index, base_eq/base_eq.iloc[0]*100, color="#b388ff", lw=1.5, label="A+B 50/50")
    if not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.0, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, 0]); ax2.set_title("Weight stability (CAGR & Sharpe vs w_B)", fontweight="bold")
    wbs = [wb for wb, *_ in weight_rows]
    ax2.plot(wbs, [m.cagr*100 for _, m, _, _, _ in weight_rows], color="#b388ff", marker="o", label="CAGR %")
    ax2.axhline(CHAMP_CAGR*100, color="#fff", ls=":", lw=1)
    a2 = ax2.twinx(); a2.plot(wbs, [m.sharpe_ratio for _, m, _, _, _ in weight_rows], color="#ff6b6b", marker="s")
    a2.set_ylabel("Sharpe", color="#ff6b6b"); ax2.set_xlabel("small-cap-tail weight w_B"); ax2.set_ylabel("CAGR %")
    ax2.grid(True, alpha=.2)

    ax3 = fig.add_subplot(gs[1, 1]); ax3.set_title("Param stability & implementation (CAGR)", fontweight="bold")
    names = [n for n, *_ in param_rows] + [l for l, *_ in impl_rows]
    vals = [m.cagr*100 for _, m, _ in param_rows] + [m.cagr*100 for _, m, _, _, _ in impl_rows]
    cols = ["#4ecdc4"]*len(param_rows) + ["#ffd93d"]*len(impl_rows)
    ax3.bar(range(len(vals)), vals, color=cols)
    ax3.axhline(CHAMP_CAGR*100, color="#fff", ls=":", lw=1, label=f"champ {CHAMP_CAGR:.0%}")
    ax3.set_xticks(range(len(names))); ax3.set_xticklabels(names, fontsize=6, rotation=40, ha="right")
    ax3.set_ylabel("CAGR %"); ax3.legend(framealpha=.3, fontsize=7); ax3.grid(True, alpha=.2, axis="y")

    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
