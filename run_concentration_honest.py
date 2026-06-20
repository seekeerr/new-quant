"""
CONCENTRATION — HONEST (survivorship-free) TEST.

Question (pre-registered): the existing results/portfolio_size experiment showed
Top3 ~ 28% CAGR and looked like a path toward a 30% target. But its numbers are
IDENTICAL to the survivorship-BIASED 'Fallback-49' universe — it never ran on the
clean bhavcopy panel. This script re-runs the concentration sweep on the
SURVIVORSHIP-FREE universe to measure the TRUE effect of concentration, for two
signals: pure 12-1 momentum and the best honest blend (Mom + LowVol 50/50).

Everything is held identical to the validated champion shell (quarterly / equal
weight / Buffer20 / Indian cost model, NET of costs) EXCEPT the portfolio size N.
No parameter tuning of the signals — this is a clean read of the concentration knob.

Success bar (stated before running): can ANY honest config reach the user's 30% net
CAGR target without a worse-than-tolerable drawdown? Reported plainly, pass or fail.
"""
import sys, io, warnings
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

from config import SystemConfig, RESULTS_DIR
from data.benchmark import get_benchmark_returns, get_benchmark_equity_curve
from analytics.metrics import compute_metrics

from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import run_buffered_backtest, drawdown_analytics, rolling_3y_cagr
from run_survivorship_validation import TopNTurnoverUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK

BUFFER, FREQ = 20, "quarterly"
N_GRID = [3, 5, 10]
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"


def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("=" * 92)
    print("  CONCENTRATION — HONEST (survivorship-free bhavcopy universe)".center(92))
    print("=" * 92)

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
        print(f"  equity-only universe: {len(keep)} symbols")
    builder = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)

    signals = [
        ("PureMom", compute_12_1_momentum),
        ("Mom+LowVol", make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)),
    ]

    rows = []
    for sig_name, scorer in signals:
        for n in N_GRID:
            label = f"{sig_name}/Top{n}"
            print(f"\n  running {label} (net) ...")
            net = run_buffered_backtest(
                ac, ah, al, av, n_stocks=n, rebalance_freq=FREQ, buffer=BUFFER,
                initial_capital=cap, config=cfg, apply_costs=True, label=label,
                scorer=scorer, universe_builder=builder)
            m = compute_metrics(net["equity_curve"], net["returns"],
                                benchmark_returns=bench_ret, trades=net["trades"],
                                total_costs=net["total_costs"], initial_capital=cap)
            extra = drawdown_analytics(net["equity_curve"])
            roll = rolling_3y_cagr(net["returns"])
            rows.append({
                "signal": sig_name, "N": n, "cagr": m.cagr, "max_dd": m.max_drawdown,
                "sharpe": m.sharpe_ratio, "calmar": m.calmar_ratio, "alpha": m.alpha,
                "vol": m.annualised_volatility,
                "final": net["equity_curve"].iloc[-1],
                "tuw": extra["time_underwater_pct"],
                "roll3y_min": roll.min() if not roll.empty else np.nan,
                "roll3y_med": roll.median() if not roll.empty else np.nan,
                "eq": net["equity_curve"],
            })
            print(f"    CAGR {m.cagr:.2%} | MaxDD {m.max_drawdown:.2%} | "
                  f"Sharpe {m.sharpe_ratio:.2f} | Alpha {m.alpha:+.2%}")

    # benchmark aligned to strategy span
    _eq = rows[0]["eq"]
    bstart, bend = str(_eq.index[0].date()), str(_eq.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, cap)
    bm_cagr = compute_metrics(bench_eq, initial_capital=cap).cagr if not bench_eq.empty else np.nan

    # ── report ──
    L = []; w = L.append
    w("=" * 92)
    w("  CONCENTRATION ON THE HONEST (SURVIVORSHIP-FREE) UNIVERSE — NET OF COSTS".center(92))
    w("=" * 92)
    w(f"Initial Capital: Rs {cap:,.0f}   Period: {bstart}..{bend}")
    w(f"Shell: quarterly / equal weight / Buffer{BUFFER}. ONLY N varies. NIFTY500(px) CAGR {bm_cagr:.2%}")
    w(f"USER TARGET: 30% net CAGR.")
    w("")
    hdr = f"{'Signal':<12}{'N':>4}{'CAGR':>9}{'MaxDD':>9}{'Sharpe':>8}{'Calmar':>8}{'Alpha':>9}{'Vol':>8}{'3yMin':>8}"
    w(hdr); w("-" * 92)
    for r in rows:
        w(f"{r['signal']:<12}{r['N']:>4}{r['cagr']:>8.1%}{r['max_dd']:>9.1%}{r['sharpe']:>8.2f}"
          f"{r['calmar']:>8.2f}{r['alpha']:>+9.1%}{r['vol']:>8.1%}{r['roll3y_min']:>8.1%}")
    w("-" * 92)
    best = max(rows, key=lambda r: r["cagr"])
    w(f"Highest honest CAGR: {best['signal']}/Top{best['N']} = {best['cagr']:.2%} "
      f"(MaxDD {best['max_dd']:.1%}, Sharpe {best['sharpe']:.2f})")
    gap = 0.30 - best["cagr"]
    if best["cagr"] >= 0.30:
        w(f"=> Target MET honestly (rare — scrutinise for residual bias).")
    else:
        w(f"=> 30% target NOT reached on honest data. Best is {best['cagr']:.1%}; "
          f"gap to 30% = {gap*100:.1f} CAGR points.")
        w(f"   The ~28% Top3 in results/portfolio_size came from the BIASED universe, not this one.")
    w("=" * 92)

    txt = "\n".join(L)
    print("\n" + txt)
    rdir = RESULTS_DIR / "concentration_honest"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "report.txt").write_text(txt, encoding="utf-8")
    pd.DataFrame([{k: v for k, v in r.items() if k != "eq"} for r in rows]).to_csv(
        rdir / "comparison.csv", index=False)
    print(f"\n  Saved to {rdir}/")


if __name__ == "__main__":
    main()
