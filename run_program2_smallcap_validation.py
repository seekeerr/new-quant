"""
RESEARCH PROGRAM #2 — EXPERIMENT 1: VALIDATE THE 21.8% SMALL-CAP-TAIL LEAD.

PRE-REGISTERED (see RESEARCH_PROGRAM_2_CHARTER.md). The smallcap_universe study found,
net of costs on survivorship-free data, that the frozen Mom+LowVol product on the
SmallCap 300-1000 turnover-rank tail returned 21.8% net CAGR / Sharpe 1.02 / MaxDD
-34.8% — +5.3 pts over the Liquid-Top-500 champion (16.5%) AT A BETTER SHARPE. Memory
flags it UNVALIDATED. This experiment subjects that single cell to the same discipline
that killed FIP (split-sample sign-flip) and the reversal mirage (cost realism), and
adds an HONEST capacity test the frozen engine cannot do on its own.

THE ONE CELL UNDER TEST (nothing tuned; frozen champion shell):
  signal  = Mom+LowVol 50/50  (make_mom_lowvol_scorer(0.5, 252))
  slice   = SmallCap 300-1000  (turnover-rank band, large-cap head dropped)
  shell   = Top-10 / quarterly / Buffer20 / equal weight / whole-share / NET of costs
  data    = survivorship-free bhavcopy, corp-action adj, equity-only (ISIN INE), PIT
  capital = Rs 1,00,000 (the tiny book the tail is supposed to need)
Reference = same signal/shell on Liquid Top-500 (the champion slice) for apples-to-apples.

THE FIVE VALIDATION GATES (charter §4). The cell PASSES only if it clears ALL:
  1. Net CAGR > champion 17.4%                    [headline]
  2. Sharpe >= champion 0.69                       [headline]
  3. MaxDD not worse than champion by >5 pts (>= -38.5%)
  4. NO split-sample sign-flip: alpha > 0 in BOTH 2012-2018 AND 2019-2026   << FIP-killer
  5. Survives cost realism: still beats the NIFTV500 benchmark under x5 (and x10) slippage stress
  6. Rolling 3-yr min CAGR > 0 (never a losing 3-yr window)

CAPACITY REALISM — why a naive "bump the capital" test is a TRAP here. run_buffered_backtest
calls the cost model WITHOUT avg_daily_value, so the impact-cost term is always 0 and costs
are ~proportional to trade value. Bumping initial_capital therefore shows NO decay — it is
structurally incapable of revealing the illiquidity wall a real small-cap book hits. So this
experiment adds run_impact_aware_backtest, an otherwise-identical engine copy that DOES pass
trailing 20-day ADTV so the sqrt impact term activates, and runs the cell at Rs 1L / 10L / 50L.
If net CAGR collapses as the book grows, the 21.8% is a tiny-book artifact, not a strategy.

Run:  py run_program2_smallcap_validation.py
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
from tqdm import tqdm

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

from config import SystemConfig, RESULTS_DIR
from data.benchmark import get_benchmark_returns, get_benchmark_equity_curve
from analytics.metrics import compute_metrics
from costs.cost_model import CostModel
from utils.helpers import get_rebalance_dates

from run_buffer_experiment import (
    run_buffered_backtest, select_with_buffer,
    drawdown_analytics, rolling_3y_cagr, annual_returns,
)
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import make_mom_lowvol_scorer, load_equity_symbols, VOL_LOOKBACK

# ── Frozen champion shell ────────────────────────────────────────────────
CAP_BASE = 100_000.0
N_STOCKS, BUFFER, FREQ = 10, 20, "quarterly"
SMALLCAP = (300, 1000)       # the tail under test
TOP500   = (0, 500)          # champion reference slice
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "program2_smallcap_validation"

# Champion benchmarks the gates compare against (PRICE_ONLY_FINAL_CONCLUSION.md).
CHAMP_CAGR, CHAMP_SHARPE, CHAMP_DD = 0.174, 0.69, -0.335
DD_TOL = 0.05

# Split-sample boundary (FIP-killer). FIP "won 2012-19, lost 2019-26" -> split at end-2018.
SPLIT_DATE = pd.Timestamp("2018-12-31")

# Capacity ladder (impact-aware pass only).
CAP_LADDER = [100_000.0, 1_000_000.0, 5_000_000.0]
STRESS_MULTS = [5.0, 10.0]


def stressed_config(cfg, mult):
    """Copy of cfg with the per-tier slippage rates multiplied (cost realism stress).
    NOTE: impact_cost_base is also scaled, but the verbatim engine never triggers impact
    (avg_daily_value not passed), so in run_buffered_backtest this is a pure slippage stress."""
    c = deepcopy(cfg)
    c.costs.slippage_tier1 *= mult
    c.costs.slippage_tier2 *= mult
    c.costs.slippage_tier3 *= mult
    c.costs.impact_cost_base *= mult
    return c


# ── Impact-aware engine copy: identical to run_buffered_backtest EXCEPT it passes
#    trailing 20-day ADTV into the cost model so the sqrt impact term activates. This
#    is the ONLY honest way to test capacity, because the frozen engine disables impact.
def run_impact_aware_backtest(close, high, low, volume, turnover, *, n_stocks, rebalance_freq,
                              buffer, initial_capital, config, scorer, universe_builder,
                              label=""):
    cfg = config
    start = pd.Timestamp(cfg.backtest.start_date)
    end = pd.Timestamp(cfg.backtest.end_date)
    start = max(start, close.index.min() + pd.Timedelta(days=365))
    end = min(end, close.index.max())
    all_dates = close.index[(close.index >= start) & (close.index <= end)]
    if all_dates.empty:
        return {"equity_curve": pd.Series(dtype=float), "returns": pd.Series(dtype=float)}
    rebal_set = set(get_rebalance_dates(all_dates, rebalance_freq))
    valuation = close.ffill()
    cost_model = CostModel(cfg.costs)
    lookback = cfg.universe.turnover_lookback

    cash = initial_capital
    holdings = {}
    equity_values, trades_history = [], []
    total_costs = total_rebalances = 0.0
    total_turnover = 0.0
    total_impact = 0.0

    def adtv_at(date):
        m = turnover.index <= date
        return turnover.loc[m].tail(lookback).mean()   # Series sym -> avg daily Rs value

    for date in tqdm(all_dates, desc=f"[impact] {label}", unit="day"):
        today_close = close.loc[date]
        today_value = valuation.loc[date]
        hv = sum(qty * today_value.get(s, 0) for s, qty in holdings.items()
                 if not np.isnan(today_value.get(s, np.nan)))
        pv = cash + hv
        equity_values.append({"date": date, "portfolio_value": pv})
        if date not in rebal_set:
            continue
        total_rebalances += 1
        universe = universe_builder.build_universe(date)
        if not universe.symbols:
            continue
        scores = scorer(close, date, universe.symbols)
        if scores.empty or len(scores) < n_stocks:
            continue
        selected = select_with_buffer(scores, holdings, n_stocks, buffer)
        adtv = adtv_at(date)
        per_stock = pv / n_stocks
        target_shares = {}
        for s in selected:
            p = today_close.get(s, np.nan)
            if np.isnan(p) or p <= 0:
                continue
            sh = int(per_stock / p)
            if sh > 0:
                target_shares[s] = sh

        sells_value = buys_value = 0.0
        for s, qty in list(holdings.items()):
            tq = target_shares.get(s, 0)
            sq = qty - tq
            if sq <= 0:
                continue
            p = today_close.get(s, np.nan)
            if not (p > 0):
                p = today_value.get(s, np.nan)
            if not (p > 0):
                del holdings[s]; continue
            sv = sq * p
            tier = universe.liquidity_tiers.get(s, 2)
            tc = cost_model.calculate_trade_cost(s, "SELL", sq, p, liquidity_tier=tier,
                                                 avg_daily_value=float(adtv.get(s, 0) or 0))
            cash += sv - tc.total_cost
            total_costs += tc.total_cost; total_impact += tc.impact_cost
            sells_value += sv
            holdings[s] = qty - sq
            if holdings[s] <= 0:
                del holdings[s]
            trades_history.append({"date": date, "symbol": s, "side": "SELL", "shares": sq,
                                   "price": p, "value": sv, "cost": tc.total_cost})
        for s, tq in target_shares.items():
            bq = tq - holdings.get(s, 0)
            if bq <= 0:
                continue
            p = today_close.get(s, np.nan)
            if not (p > 0):
                continue
            tier = universe.liquidity_tiers.get(s, 2)
            adv = float(adtv.get(s, 0) or 0)
            tc = cost_model.calculate_trade_cost(s, "BUY", bq, p, liquidity_tier=tier, avg_daily_value=adv)
            bv = bq * p
            total = bv + tc.total_cost
            if total > cash:
                aff = int((cash - tc.total_cost) / p) if p > 0 else 0
                if aff <= 0:
                    continue
                bq = aff; bv = bq * p
                tc = cost_model.calculate_trade_cost(s, "BUY", bq, p, liquidity_tier=tier, avg_daily_value=adv)
                total = bv + tc.total_cost
            cash -= total
            total_costs += tc.total_cost; total_impact += tc.impact_cost
            buys_value += bv
            holdings[s] = holdings.get(s, 0) + bq
            trades_history.append({"date": date, "symbol": s, "side": "BUY", "shares": bq,
                                   "price": p, "value": bv, "cost": tc.total_cost})
        if pv > 0:
            total_turnover += max(sells_value, buys_value) / pv

    eq = pd.DataFrame(equity_values).set_index("date")["portfolio_value"]
    return {"equity_curve": eq, "returns": eq.pct_change().fillna(0), "trades": trades_history,
            "total_costs": total_costs, "total_impact": total_impact,
            "total_rebalances": total_rebalances, "total_trades": len(trades_history),
            "avg_turnover": total_turnover / total_rebalances if total_rebalances else 0}


def subperiod(eq, ret, bench_ret, lo, hi):
    """Metrics over [lo, hi] of an already-run continuous strategy (sub-period slice)."""
    e = eq.loc[(eq.index >= lo) & (eq.index <= hi)]
    r = ret.loc[(ret.index >= lo) & (ret.index <= hi)]
    if len(e) < 30:
        return None
    return compute_metrics(e, r, benchmark_returns=bench_ret, initial_capital=e.iloc[0])


def run_cell(ac, ah, al, av, at, cfg, scorer, slice_band, capital, apply_costs=True, label=""):
    builder = RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, slice_band[0], slice_band[1])
    return run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=FREQ,
        buffer=BUFFER, initial_capital=capital, config=cfg, apply_costs=apply_costs,
        label=label, scorer=scorer, universe_builder=builder)


def main():
    t_start = time.time()
    cfg = SystemConfig()
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("=" * 100)
    print("  PROGRAM #2 — EXP 1: VALIDATE THE 21.8% SMALLCAP-TAIL MOM+LOWVOL LEAD".center(100))
    print("  Top-10 / quarterly / Buffer20 / EW / NET of costs / Rs 1,00,000".center(100))
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

    scorer = make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)

    # ── A. The cell under test: SmallCap 300-1000, net + gross, Rs 1L ──
    print("\n[A] SmallCap 300-1000 Mom+LowVol  (net + gross) ...")
    net = run_cell(ac, ah, al, av, at, cfg, scorer, SMALLCAP, CAP_BASE, True, "SmallCap net")
    gross = run_cell(ac, ah, al, av, at, cfg, scorer, SMALLCAP, CAP_BASE, False, "SmallCap gross")
    m = compute_metrics(net["equity_curve"], net["returns"], benchmark_returns=bench_ret,
                        trades=net["trades"], total_costs=net["total_costs"], initial_capital=CAP_BASE)
    gm = compute_metrics(gross["equity_curve"], gross["returns"], initial_capital=CAP_BASE)
    extra = drawdown_analytics(net["equity_curve"])
    roll = rolling_3y_cagr(net["returns"])

    # ── B. Reference: Liquid Top-500 (champion slice), same shell, Rs 1L ──
    print("\n[B] Liquid Top-500 Mom+LowVol  (reference) ...")
    refnet = run_cell(ac, ah, al, av, at, cfg, scorer, TOP500, CAP_BASE, True, "Top500 net")
    rm = compute_metrics(refnet["equity_curve"], refnet["returns"], benchmark_returns=bench_ret,
                         trades=refnet["trades"], total_costs=refnet["total_costs"], initial_capital=CAP_BASE)

    # ── C. Split-sample (FIP-killer): does the tail edge persist or sign-flip? ──
    print("\n[C] Split-sample 2012-2018 vs 2019-2026 ...")
    h1 = subperiod(net["equity_curve"], net["returns"], bench_ret, net["equity_curve"].index[0], SPLIT_DATE)
    h2 = subperiod(net["equity_curve"], net["returns"], bench_ret, SPLIT_DATE, net["equity_curve"].index[-1])

    # ── D. Cost-realism stress: x5, x10 slippage ──
    print("\n[D] Cost-realism stress (x5, x10 slippage) ...")
    stress = {}
    for mult in STRESS_MULTS:
        sn = run_cell(ac, ah, al, av, at, stressed_config(cfg, mult), scorer, SMALLCAP, CAP_BASE,
                      True, f"SmallCap x{mult:.0f}")
        stress[mult] = compute_metrics(sn["equity_curve"], sn["returns"], benchmark_returns=bench_ret,
                                       trades=sn["trades"], total_costs=sn["total_costs"], initial_capital=CAP_BASE)

    # ── E. Honest capacity: impact-aware engine at Rs 1L / 10L / 50L ──
    print("\n[E] Impact-aware capacity ladder (Rs 1L / 10L / 50L) ...")
    cap_rows = []
    for capital in CAP_LADDER:
        builder = RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, SMALLCAP[0], SMALLCAP[1])
        res = run_impact_aware_backtest(ac, ah, al, av, at, n_stocks=N_STOCKS, rebalance_freq=FREQ,
            buffer=BUFFER, initial_capital=capital, config=cfg, scorer=scorer,
            universe_builder=builder, label=f"Rs{capital/1e5:.0f}L")
        cm = compute_metrics(res["equity_curve"], res["returns"], benchmark_returns=bench_ret,
                             trades=res["trades"], total_costs=res["total_costs"], initial_capital=capital)
        cap_rows.append({"capital": capital, "cagr": cm.cagr, "sharpe": cm.sharpe_ratio,
                         "max_dd": cm.max_drawdown, "costs": res["total_costs"],
                         "impact": res.get("total_impact", 0.0), "final": res["equity_curve"].iloc[-1]})
        print(f"    Rs {capital/1e5:>4.0f}L : CAGR {cm.cagr:>6.1%} | Sharpe {cm.sharpe_ratio:.2f} | "
              f"impact Rs {res.get('total_impact', 0.0):>12,.0f}")

    # benchmark aligned to span
    eq = net["equity_curve"]
    bstart, bend = str(eq.index[0].date()), str(eq.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, CAP_BASE)
    bm_cagr = compute_metrics(bench_eq, initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan
    bm_h1 = compute_metrics(bench_eq.loc[:SPLIT_DATE], initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan
    bm_h2 = compute_metrics(bench_eq.loc[SPLIT_DATE:], initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan

    RDIR.mkdir(parents=True, exist_ok=True)
    ctx = dict(m=m, gm=gm, extra=extra, roll=roll, rm=rm, h1=h1, h2=h2, stress=stress,
               cap_rows=cap_rows, bm_cagr=bm_cagr, bm_h1=bm_h1, bm_h2=bm_h2,
               bstart=bstart, bend=bend, net=net, refnet=refnet, bench_eq=bench_eq)
    _write_report(ctx)
    _make_chart(ctx)
    print(f"\n  Saved to {RDIR}/   (total {time.time()-t_start:.0f}s)")


def _gate(ctx):
    """Evaluate the six pre-registered gates; return list of (name, passed, detail)."""
    m, h1, h2, stress, cap_rows, bm_cagr = (ctx["m"], ctx["h1"], ctx["h2"], ctx["stress"],
                                            ctx["cap_rows"], ctx["bm_cagr"])
    gates = []
    gates.append(("1. Net CAGR > champion 17.4%", m.cagr > CHAMP_CAGR, f"{m.cagr:.2%}"))
    gates.append(("2. Sharpe >= champion 0.69", m.sharpe_ratio >= CHAMP_SHARPE, f"{m.sharpe_ratio:.2f}"))
    gates.append(("3. MaxDD >= -38.5% (not >5pts worse)", m.max_drawdown >= CHAMP_DD - DD_TOL,
                  f"{m.max_drawdown:.1%}"))
    flip_ok = (h1 is not None and h2 is not None and h1.alpha > 0 and h2.alpha > 0)
    gates.append(("4. No split-sample sign-flip (alpha>0 both halves)", flip_ok,
                  f"H1 {h1.alpha:+.1%} / H2 {h2.alpha:+.1%}" if h1 and h2 else "n/a"))
    stress_ok = all(s.cagr > bm_cagr for s in stress.values())
    gates.append(("5. Survives x5/x10 stress vs benchmark", stress_ok,
                  " / ".join(f"x{int(k)} {v.cagr:.1%}" for k, v in stress.items()) + f"  (bm {bm_cagr:.1%})"))
    rmin = ctx["roll"].min() if not ctx["roll"].empty else np.nan
    gates.append(("6. Rolling 3y min CAGR > 0", (rmin > 0) if not np.isnan(rmin) else False, f"{rmin:.1%}"))
    return gates


def _write_report(ctx):
    m, gm, extra, roll, rm = ctx["m"], ctx["gm"], ctx["extra"], ctx["roll"], ctx["rm"]
    h1, h2, stress, cap_rows = ctx["h1"], ctx["h2"], ctx["stress"], ctx["cap_rows"]
    L = []; w = L.append
    w("=" * 100)
    w("  PROGRAM #2 EXP 1 — VALIDATION OF SMALLCAP 300-1000 MOM+LOWVOL (Rs 1,00,000, NET)".center(100))
    w("=" * 100)
    w(f"Period {ctx['bstart']}..{ctx['bend']}   Shell Top{N_STOCKS}/{FREQ}/Buffer{BUFFER}/EW")
    w(f"NIFTY500(px) CAGR {ctx['bm_cagr']:.2%}   Champion ref (Liquid Top-500, same shell) "
      f"CAGR {rm.cagr:.2%} Sharpe {rm.sharpe_ratio:.2f}")
    w("")
    w("HEADLINE (the cell under test):")
    w(f"  Net CAGR {m.cagr:.2%} (gross {gm.cagr:.2%}, cost drag {gm.cagr-m.cagr:.2%}) | "
      f"Sharpe {m.sharpe_ratio:.2f} | Sortino {m.sortino_ratio:.2f} | Calmar {m.calmar_ratio:.2f}")
    w(f"  MaxDD {m.max_drawdown:.2%} | Vol {m.annualised_volatility:.2%} | Alpha {m.alpha:+.2%} | "
      f"Beta {m.beta:.2f} | Final Rs {ctx['net']['equity_curve'].iloc[-1]:,.0f}")
    w(f"  Rolling 3y CAGR: min {roll.min():.1%} | median {roll.median():.1%} | max {roll.max():.1%}"
      if not roll.empty else "  Rolling 3y CAGR: n/a")
    w("")
    w("[C] SPLIT-SAMPLE (FIP-killer — the edge must NOT sign-flip):")
    if h1 and h2:
        w(f"   2012-2018 : CAGR {h1.cagr:>6.1%}  Sharpe {h1.sharpe_ratio:>5.2f}  Alpha {h1.alpha:>+6.1%}  "
          f"(bm {ctx['bm_h1']:.1%})")
        w(f"   2019-2026 : CAGR {h2.cagr:>6.1%}  Sharpe {h2.sharpe_ratio:>5.2f}  Alpha {h2.alpha:>+6.1%}  "
          f"(bm {ctx['bm_h2']:.1%})")
    w("")
    w("[D] COST-REALISM STRESS (slippage multiplied):")
    for k, v in stress.items():
        w(f"   x{int(k):>2} slippage : net CAGR {v.cagr:>6.1%} | Sharpe {v.sharpe_ratio:>5.2f} | "
          f"MaxDD {v.max_drawdown:>6.1%}  (bm {ctx['bm_cagr']:.1%})")
    w("")
    w("[E] HONEST CAPACITY (impact-aware engine; impact term ACTIVE):")
    base_cagr = cap_rows[0]["cagr"]
    for r in cap_rows:
        decay = r["cagr"] - base_cagr
        w(f"   Rs {r['capital']/1e5:>4.0f}L : CAGR {r['cagr']:>6.1%} ({decay:>+5.1%} vs Rs1L) | "
          f"Sharpe {r['sharpe']:>5.2f} | impact Rs {r['impact']:>12,.0f} | costs Rs {r['costs']:>12,.0f}")
    w("")
    w("-" * 100)
    w("PRE-REGISTERED GATES:")
    gates = _gate(ctx)
    for name, passed, detail in gates:
        w(f"   [{'PASS' if passed else 'FAIL'}]  {name:<48} {detail}")
    all_pass = all(g[1] for g in gates)
    w("-" * 100)
    if all_pass:
        w("VERDICT: VALIDATED. The SmallCap-tail Mom+LowVol edge survives split-sample, cost")
        w("  stress, and the rolling-window test. The honest ceiling is ABOVE the 17-18% champion.")
        w("  -> Promote as the new research champion; Track 2 hunts above this.")
    else:
        fails = [g[0] for g in gates if not g[1]]
        w("VERDICT: NOT VALIDATED. Failed gate(s): " + "; ".join(fails))
        w("  -> The 21.8% is not robust under this gate; the tail is (partly) a mirage. Champion stands;")
        w("     the higher-CAGR question moves to Track 2's new styles.")
    w("=" * 100)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")

    # machine-readable
    rows = [{"test": "smallcap_net", "cagr": m.cagr, "sharpe": m.sharpe_ratio, "max_dd": m.max_drawdown,
             "alpha": m.alpha, "gross_cagr": gm.cagr},
            {"test": "top500_ref_net", "cagr": rm.cagr, "sharpe": rm.sharpe_ratio, "max_dd": rm.max_drawdown,
             "alpha": rm.alpha, "gross_cagr": np.nan}]
    if h1: rows.append({"test": "split_2012_2018", "cagr": h1.cagr, "sharpe": h1.sharpe_ratio,
                        "max_dd": h1.max_drawdown, "alpha": h1.alpha, "gross_cagr": np.nan})
    if h2: rows.append({"test": "split_2019_2026", "cagr": h2.cagr, "sharpe": h2.sharpe_ratio,
                        "max_dd": h2.max_drawdown, "alpha": h2.alpha, "gross_cagr": np.nan})
    for k, v in stress.items():
        rows.append({"test": f"stress_x{int(k)}", "cagr": v.cagr, "sharpe": v.sharpe_ratio,
                     "max_dd": v.max_drawdown, "alpha": v.alpha, "gross_cagr": np.nan})
    for r in cap_rows:
        rows.append({"test": f"capacity_Rs{r['capital']/1e5:.0f}L", "cagr": r["cagr"], "sharpe": r["sharpe"],
                     "max_dd": r["max_dd"], "alpha": np.nan, "gross_cagr": np.nan})
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


def _make_chart(ctx):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 12))
    gs = GridSpec(2, 2, figure=fig, hspace=0.32, wspace=0.22)
    fig.suptitle("Program #2 Exp 1 — Validate SmallCap 300-1000 Mom+LowVol (Rs 1L, net)",
                 fontsize=15, fontweight="bold", color="#fff", y=0.97)
    eq, refeq, beq = ctx["net"]["equity_curve"], ctx["refnet"]["equity_curve"], ctx["bench_eq"]

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    ax1.plot(eq.index, eq/eq.iloc[0]*100, color="#00ff88", lw=1.6, label="SmallCap 300-1000")
    ax1.plot(refeq.index, refeq/refeq.iloc[0]*100, color="#4ecdc4", lw=1.3, label="Liquid Top-500 (champion)")
    if not beq.empty:
        ax1.plot(beq.index, beq/beq.iloc[0]*100, color="#888", lw=1.1, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[1, 0]); ax2.set_title("Split-sample & stress: net CAGR", fontweight="bold")
    labels, vals, cols = ["2012-18", "2019-26"], [], ["#00ff88", "#ffd93d"]
    vals = [ctx["h1"].cagr*100 if ctx["h1"] else 0, ctx["h2"].cagr*100 if ctx["h2"] else 0]
    for k, v in ctx["stress"].items():
        labels.append(f"x{int(k)} slip"); vals.append(v.cagr*100); cols.append("#ff6b6b")
    ax2.bar(range(len(vals)), vals, color=cols)
    ax2.axhline(ctx["bm_cagr"]*100, color="#888", ls="--", lw=1, label=f"bm {ctx['bm_cagr']:.0%}")
    ax2.axhline(CHAMP_CAGR*100, color="#4ecdc4", ls=":", lw=1, label=f"champ {CHAMP_CAGR:.0%}")
    ax2.set_xticks(range(len(vals))); ax2.set_xticklabels(labels, fontsize=8); ax2.set_ylabel("Net CAGR %")
    ax2.legend(framealpha=.3, fontsize=7); ax2.grid(True, alpha=.2, axis="y")

    ax3 = fig.add_subplot(gs[1, 1]); ax3.set_title("Capacity: net CAGR vs book size (impact ON)", fontweight="bold")
    caps = [r["capital"]/1e5 for r in ctx["cap_rows"]]
    ax3.plot(caps, [r["cagr"]*100 for r in ctx["cap_rows"]], color="#00ff88", marker="o", lw=1.6)
    ax3.axhline(ctx["bm_cagr"]*100, color="#888", ls="--", lw=1, label=f"bm {ctx['bm_cagr']:.0%}")
    ax3.set_xscale("log"); ax3.set_xlabel("Book size (Rs lakh, log)"); ax3.set_ylabel("Net CAGR %")
    ax3.set_xticks(caps); ax3.set_xticklabels([f"{c:.0f}L" for c in caps])
    ax3.legend(framealpha=.3, fontsize=7); ax3.grid(True, alpha=.2)

    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
