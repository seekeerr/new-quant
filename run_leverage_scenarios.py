"""
ROAD 2 — STEP 2 (the payoff): SAFE LEVERAGE on the smooth base.

Steps 1's job was to make the base SMOOTH (low drawdown / low vol). Leverage is the
only honest lever that lifts the headline CAGR: push a smooth, high-Sharpe strategy
a bit harder and borrow the difference. We model REAL borrowing cost (Indian margin
funding ~10%/yr) so the number is net of the cost of leverage.

Bases (both Top10 / quarterly / Buffer20 / NET of Indian costs, honest universe):
  C. PlainMom + LowVol   (CAGR ~17.4%, MaxDD ~-33%)
  D. SmartMom + LowVol   (CAGR ~16.2%, MaxDD ~-27%, smoothest)

For each base we apply constant leverage L in {1.0, 1.25, 1.5, 1.75, 2.0}:
    levered_daily_return = L * r_net - (L-1) * (borrow_rate / 252)
then recompute CAGR / MaxDD / Sharpe.

HONEST CAVEAT (printed in the report): this is IDEALISED leverage — constant daily
re-leveraging, NO margin-call / forced-liquidation modelling. In a real crash a
margin call would force selling at the bottom, so realised drawdowns would be WORSE
than shown. Leverage amplifies losses roughly in proportion to L. Treat these as an
optimistic upper bound on what leverage buys.
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
from run_pure_momentum import compute_12_1_momentum
from run_buffer_experiment import run_buffered_backtest, drawdown_analytics
from run_survivorship_validation import TopNTurnoverUniverseBuilder
from run_momentum_lowvol import load_equity_symbols
from run_smart_momentum import compute_residual_momentum, make_blend_scorer

N_STOCKS, BUFFER, FREQ = 10, 20, "quarterly"
BORROW = 0.10                 # Indian margin-funding cost ~10%/yr on the borrowed portion
RF = 0.065
LEVERS = [1.0, 1.25, 1.5, 1.75, 2.0]
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"


def lever_curve(rets, L, borrow=BORROW):
    daily = L * rets - (L - 1.0) * (borrow / 252.0)
    eq = (1.0 + daily).cumprod()
    return eq, daily


def stats(eq, daily):
    n = len(eq)
    cagr = eq.iloc[-1] ** (252.0 / n) - 1.0
    dd = (eq / eq.cummax() - 1.0).min()
    sharpe = (daily.mean() * 252 - RF) / (daily.std() * np.sqrt(252)) if daily.std() > 0 else np.nan
    return cagr, dd, sharpe


def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital

    print("=" * 86)
    print("  ROAD 2 / STEP 2 — SAFE LEVERAGE (net of ~10%/yr borrow cost)".center(86))
    print("=" * 86)
    print("\nLoading panels ...")
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    eq_syms = load_equity_symbols()
    if eq_syms is not None:
        keep = [c for c in ac.columns if c in eq_syms]
        ac, ah, al, av, at = (p[keep] for p in (ac, ah, al, av, at))
    builder = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)

    bases = [
        ("PlainMom+LowVol", make_blend_scorer(compute_12_1_momentum, 0.5)),
        ("SmartMom+LowVol", make_blend_scorer(compute_residual_momentum, 0.5)),
    ]

    L = []; w = L.append
    w("=" * 86)
    w("  SAFE-LEVERAGE SCENARIOS — honest universe, Top10, NET of costs & borrow".center(86))
    w("=" * 86)
    w(f"Borrow cost on leveraged portion: {BORROW:.0%}/yr.  Leverage applied to daily net returns.")
    w("CAVEAT: idealised (no margin-call liquidation). Real crash drawdowns would be WORSE.")
    w("")

    all_rows = []
    for name, scorer in bases:
        print(f"\n  running base {name} ...")
        net = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=FREQ,
                                    buffer=BUFFER, initial_capital=cap, config=cfg,
                                    apply_costs=True, label=name, scorer=scorer,
                                    universe_builder=builder)
        rets = net["returns"].dropna()
        w(f"BASE: {name}")
        w(f"{'Leverage':>10}{'CAGR':>9}{'MaxDD':>9}{'Sharpe':>8}   note")
        w("-" * 60)
        for lev in LEVERS:
            eq, daily = lever_curve(rets, lev)
            cagr, dd, sharpe = stats(eq, daily)
            note = ""
            if lev == 1.0:
                note = "(no leverage)"
            elif dd <= -0.50:
                note = "<- worst-case loss > 50%"
            w(f"{lev:>9.2f}x{cagr:>8.1%}{dd:>9.1%}{sharpe:>8.2f}   {note}")
            all_rows.append({"base": name, "leverage": lev, "cagr": cagr, "max_dd": dd, "sharpe": sharpe})
        w("")

    # pick best CAGR while keeping worst-case loss no worse than -45%
    ok = [r for r in all_rows if r["max_dd"] >= -0.45]
    best = max(ok, key=lambda r: r["cagr"]) if ok else None
    w("=" * 86)
    if best:
        w(f"Best CAGR keeping worst-case loss within -45%: {best['base']} at {best['leverage']:.2f}x")
        w(f"   => CAGR {best['cagr']:.1%} | MaxDD {best['max_dd']:.1%} | Sharpe {best['sharpe']:.2f}")
    w(f"Reminder: 30% would need ~2x leverage, which pushes worst-case loss past -50% "
      f"(and worse in a real margin call).")
    w("=" * 86)

    txt = "\n".join(L)
    print("\n" + txt)
    rdir = RESULTS_DIR / "leverage_scenarios"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "report.txt").write_text(txt, encoding="utf-8")
    pd.DataFrame(all_rows).to_csv(rdir / "comparison.csv", index=False)
    print(f"\n  Saved to {rdir}/")


if __name__ == "__main__":
    main()
