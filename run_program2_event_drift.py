"""
RESEARCH PROGRAM #2 — TRACK 2, EXPERIMENT 2E: EVENT-DRIVEN POST-EVENT DRIFT (PEAD proxy).

PRE-REGISTERED (RESEARCH_PROGRAM_2_TRACK2_DESIGN.md). The first GENUINELY INDEPENDENT
return family tested beyond momentum / low-vol / reversal. Post-earnings-announcement drift
(PEAD) is among the most robust anomalies worldwide: after a large positive surprise a stock
keeps drifting up for weeks. We have no earnings dates, so the surprise is proxied by a
PRICE GAP + VOLUME SURGE (a big one-day jump on heavy volume = the market repricing on news).

THIS NEEDS A NEW ENGINE. The frozen engine is a fixed-N, scheduled-rebalance, cross-sectional
RANK machine. Event-driven trading is different: entries fire on ARBITRARY days when an event
triggers, exits happen on a TIME rule (hold the drift window), and the number of open
positions varies. So this file adds `run_event_drift_backtest` — a long-only event-execution
engine — built fresh (the frozen rank engine cannot express this). It is documented as a NEW
engine, not a modification of the frozen shell.

NO LOOK-AHEAD: an event is measured at the close of day t (1-day return t-1->t and volume at
t vs its trailing average). We ENTER at the close of day t+1 (you see the surge after the
close, act next session). Exit at the close of t+1+HOLD_DAYS. Held names that stop trading
exit at their last valid (ffilled) mark.

PRE-REGISTERED PARAMETERS (ONE config, no grid — grids on a fresh anomaly invite overfitting):
  gap threshold   = +8% one-day return          (a decisive surprise, not noise)
  volume surge    = 3x trailing 50-day avg vol   (confirms it is news, not drift)
  hold window     = 40 trading days (~2 months)  (the classic PEAD drift horizon)
  max positions   = 10 (equal-weight slots)      (matches the Top-10 shell)
  when > 10 events fire, rank by strength = 1-day return x volume ratio.
UNIVERSES: Liquid Top-500 (realistic fills) and All-Equity-filtered (where gaps are common).
Judged on the SAME six gates; x5/x10 slippage stress + impact capacity run only on cells that
clear the headline gates.

PRE-REGISTERED PRIOR: strong economic basis, but (a) the gap+volume proxy is noisier than a
true earnings surprise and (b) event churn costs. Honest expectation: a real but modest edge;
uncertain whether it clears the champion's Sharpe 0.69 net.

Run:  py run_program2_event_drift.py
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
from data.benchmark import get_benchmark_returns, get_benchmark_equity_curve
from analytics.metrics import compute_metrics
from costs.cost_model import CostModel

from run_buffer_experiment import drawdown_analytics, rolling_3y_cagr
from run_smallcap_universe import RankBandUniverseBuilder
from run_momentum_lowvol import load_equity_symbols
from run_program2_smallcap_validation import (
    stressed_config, subperiod, CHAMP_CAGR, CHAMP_SHARPE, CHAMP_DD, DD_TOL,
    SPLIT_DATE, CAP_LADDER, STRESS_MULTS,
)

CAP_BASE = 100_000.0
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
RDIR = RESULTS_DIR / "program2_event_drift"

# Pre-registered event parameters (single config).
GAP_THRESH = 0.08      # +8% one-day return
VOL_MULT = 3.0         # 3x trailing 50-day avg volume
VOL_WIN = 50
HOLD_DAYS = 40         # trading-day drift window
MAX_POS = 10

# Cells: (label, min_rank, max_rank)
CELLS = [("Top-500", 0, 500), ("All-filtered", 0, 10**9)]


def run_event_drift_backtest(close, volume, turnover, *, universe_builder, config,
                             initial_capital, apply_costs=True, impact=False, label="",
                             gap_thresh=GAP_THRESH, vol_mult=VOL_MULT, hold_days=HOLD_DAYS,
                             max_pos=MAX_POS, event_signal=None, strength_signal=None):
    """Long-only event-execution engine. Enter on an event (detected at close t-1) at close t;
    exit at close t+hold_days. Equal-weight up to max_pos slots. NET of costs.

    Default event = gap+volume (PEAD proxy). A caller may inject `event_signal` (bool DataFrame)
    and `strength_signal` (float DataFrame, higher=better) to reuse this engine for ANY
    event-driven style (e.g. the volatility-expansion family) without changing its mechanics."""
    cfg = config
    start = max(pd.Timestamp(cfg.backtest.start_date), close.index.min() + pd.Timedelta(days=365))
    end = min(pd.Timestamp(cfg.backtest.end_date), close.index.max())
    dates = close.index[(close.index >= start) & (close.index <= end)]
    if len(dates) < hold_days + 5:
        return {"equity_curve": pd.Series(dtype=float), "returns": pd.Series(dtype=float)}
    valuation = close.ffill()
    cost_model = CostModel(cfg.costs)
    lookback = cfg.universe.turnover_lookback

    # Event signals: injected (any event style) or the default gap+volume PEAD proxy.
    if event_signal is not None and strength_signal is not None:
        is_event = event_signal
        strength = strength_signal
    else:
        ret1 = close.pct_change()
        vol_avg = volume.rolling(VOL_WIN).mean()
        vol_ratio = volume / vol_avg.replace(0, np.nan)
        is_event = (ret1 >= gap_thresh) & (vol_ratio >= vol_mult)
        strength = ret1 * vol_ratio                        # ranking score when events compete

    date_list = list(dates)
    idx_of = {d: i for i, d in enumerate(date_list)}
    cash = initial_capital
    positions = {}          # sym -> dict(shares, exit_i, tier)
    equity_values, trades = [], []
    total_costs = total_impact = 0.0

    def adtv_at(date):
        m = turnover.index <= date
        return turnover.loc[m].tail(lookback).mean()

    def trade_cost(sym, side, shares, price, tier, adv):
        if not apply_costs:
            return 0.0, 0.0
        tc = cost_model.calculate_trade_cost(sym, side, shares, price, liquidity_tier=tier,
                                             avg_daily_value=(adv if impact else 0.0))
        return tc.total_cost, tc.impact_cost

    for i, date in enumerate(tqdm(date_list, desc=f"[event] {label}", unit="day")):
        today_close = close.loc[date]
        today_val = valuation.loc[date]

        # 1. mark to market
        hv = sum(q["shares"] * today_val.get(s, 0) for s, q in positions.items()
                 if not np.isnan(today_val.get(s, np.nan)))
        pv = cash + hv
        equity_values.append({"date": date, "portfolio_value": pv})

        # 2. exits scheduled for today
        adtv = None
        for s, pos in list(positions.items()):
            if pos["exit_i"] > i:
                continue
            price = today_close.get(s, np.nan)
            if not (price > 0):
                price = today_val.get(s, np.nan)
            if not (price > 0):
                del positions[s]; continue
            if adtv is None:
                adtv = adtv_at(date)
            c, imp = trade_cost(s, "SELL", pos["shares"], price, pos["tier"], float(adtv.get(s, 0) or 0))
            cash += pos["shares"] * price - c
            total_costs += c; total_impact += imp
            trades.append({"date": date, "symbol": s, "side": "SELL", "shares": pos["shares"],
                           "price": price, "value": pos["shares"] * price, "cost": c})
            del positions[s]

        # 3. entries: events detected on the PREVIOUS day (i-1), executed at today's close
        if i == 0:
            continue
        prev = date_list[i - 1]
        free = max_pos - len(positions)
        if free <= 0 or prev not in is_event.index:
            continue
        row = is_event.loc[prev]
        fired = row.index[row.fillna(False)].tolist()
        if not fired:
            continue
        uni = set(universe_builder.build_universe(prev).symbols)
        cand = [s for s in fired if s in uni and s not in positions]
        if not cand:
            continue
        stro = strength.loc[prev, cand].dropna().sort_values(ascending=False)
        picks = list(stro.index[:free])
        if not picks:
            continue
        if adtv is None:
            adtv = adtv_at(date)
        tiers = universe_builder.build_universe(prev).liquidity_tiers
        slot_capital = pv / max_pos
        for s in picks:
            price = today_close.get(s, np.nan)
            if not (price > 0):
                continue
            shares = int(slot_capital / price)
            if shares <= 0:
                continue
            tier = tiers.get(s, 2)
            adv = float(adtv.get(s, 0) or 0)
            c, imp = trade_cost(s, "BUY", shares, price, tier, adv)
            total_cost = shares * price + c
            if total_cost > cash:
                aff = int((cash - c) / price) if price > 0 else 0
                if aff <= 0:
                    continue
                shares = aff
                c, imp = trade_cost(s, "BUY", shares, price, tier, adv)
                total_cost = shares * price + c
            cash -= total_cost
            total_costs += c; total_impact += imp
            positions[s] = {"shares": shares, "exit_i": i + hold_days, "tier": tier}
            trades.append({"date": date, "symbol": s, "side": "BUY", "shares": shares,
                           "price": price, "value": shares * price, "cost": c})

    eq = pd.DataFrame(equity_values).set_index("date")["portfolio_value"]
    return {"equity_curve": eq, "returns": eq.pct_change().fillna(0), "trades": trades,
            "total_costs": total_costs, "total_impact": total_impact,
            "total_trades": len(trades), "avg_turnover": np.nan}


def _metrics(res, bench_ret, cap):
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
    print("  PROGRAM #2 EXP 2E — EVENT-DRIVEN POST-EVENT DRIFT (PEAD proxy) — NET".center(100))
    print(f"  gap>=+{GAP_THRESH:.0%} & vol>={VOL_MULT:.0f}x, hold {HOLD_DAYS}d, max {MAX_POS} pos".center(100))
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

    def builder(lo, hi):
        return RankBandUniverseBuilder(ac, ah, al, av, at, cfg.universe, lo, hi)

    cells = {}
    for label, lo, hi in CELLS:
        print(f"\n[{label}] event-drift net ...")
        res = run_event_drift_backtest(ac, av, at, universe_builder=builder(lo, hi), config=cfg,
                                       initial_capital=CAP_BASE, apply_costs=True, label=label)
        if res["equity_curve"].empty:
            print(f"    (no equity curve for {label})"); continue
        m, roll, h1, h2 = _metrics(res, bench_ret, CAP_BASE)
        cells[label] = {"lo": lo, "hi": hi, "res": res, "m": m, "roll": roll, "h1": h1, "h2": h2}
        print(f"    CAGR {m.cagr:.2%} | Sharpe {m.sharpe_ratio:.2f} | MaxDD {m.max_drawdown:.2%} | "
              f"trades {res['total_trades']} | costs Rs {res['total_costs']:,.0f}")

    if not cells:
        print("No cells produced results."); return
    eq0 = cells[list(cells)[0]]["res"]["equity_curve"]
    bstart, bend = str(eq0.index[0].date()), str(eq0.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, CAP_BASE)
    bm_cagr = compute_metrics(bench_eq, initial_capital=CAP_BASE).cagr if not bench_eq.empty else np.nan

    for label, c in cells.items():
        m = c["m"]
        headline_ok = (m.cagr > CHAMP_CAGR and m.sharpe_ratio >= CHAMP_SHARPE
                       and m.max_drawdown >= CHAMP_DD - DD_TOL)
        c["headline_ok"] = headline_ok; c["stress"] = None; c["capacity"] = None
        if headline_ok:
            print(f"\n  [{label}] clears headline gates -> x5/x10 stress + impact capacity ...")
            stress = {}
            for mult in STRESS_MULTS:
                sr = run_event_drift_backtest(ac, av, at, universe_builder=builder(c["lo"], c["hi"]),
                    config=stressed_config(cfg, mult), initial_capital=CAP_BASE, apply_costs=True,
                    label=f"{label} x{mult:.0f}")
                stress[mult] = compute_metrics(sr["equity_curve"], sr["returns"], benchmark_returns=bench_ret,
                    trades=sr["trades"], total_costs=sr["total_costs"], initial_capital=CAP_BASE)
            c["stress"] = stress
            cap_rows = []
            for capital in CAP_LADDER:
                res = run_event_drift_backtest(ac, av, at, universe_builder=builder(c["lo"], c["hi"]),
                    config=cfg, initial_capital=capital, apply_costs=True, impact=True,
                    label=f"{label} Rs{capital/1e5:.0f}L")
                cm = compute_metrics(res["equity_curve"], res["returns"], benchmark_returns=bench_ret,
                    trades=res["trades"], total_costs=res["total_costs"], initial_capital=capital)
                cap_rows.append({"capital": capital, "cagr": cm.cagr, "sharpe": cm.sharpe_ratio,
                                 "impact": res.get("total_impact", 0.0)})
            c["capacity"] = cap_rows

    RDIR.mkdir(parents=True, exist_ok=True)
    _report(cells, bm_cagr, bstart, bend, bench_eq)
    _chart(cells, bench_eq, bm_cagr)
    print(f"\n  Saved to {RDIR}/   (total {time.time()-t0:.0f}s)")


def _report(cells, bm_cagr, bstart, bend, bench_eq):
    L = []; w = L.append
    labels = list(cells)
    w("=" * 100)
    w("  PROGRAM #2 EXP 2E — EVENT-DRIVEN POST-EVENT DRIFT (PEAD proxy, NET)".center(100))
    w("=" * 100)
    w(f"Period {bstart}..{bend}   NIFTY500(px) {bm_cagr:.2%}   Champion 17.4%/Sharpe0.69")
    w(f"Event: 1-day ret>=+{GAP_THRESH:.0%} AND volume>={VOL_MULT:.0f}x {VOL_WIN}d-avg; "
      f"enter t+1 close; hold {HOLD_DAYS}d; max {MAX_POS} EW slots.")
    w("")
    hdr = (f"{'Universe':<15}{'CAGR':>9}{'Sharpe':>8}{'MaxDD':>9}{'Alpha':>9}{'Trades':>8}"
           f"{'roll3yMin':>11}{'H1 a':>8}{'H2 a':>8}")
    w(hdr); w("-" * 100)
    for label in labels:
        c = cells[label]; m = c["m"]
        rmin = c["roll"].min() if not c["roll"].empty else np.nan
        h1a = c["h1"].alpha if c["h1"] else np.nan
        h2a = c["h2"].alpha if c["h2"] else np.nan
        w(f"{label:<15}{m.cagr:>8.1%}{m.sharpe_ratio:>8.2f}{m.max_drawdown:>9.1%}{m.alpha:>+9.1%}"
          f"{c['res']['total_trades']:>8d}{rmin:>10.1%}{h1a:>+8.1%}{h2a:>+8.1%}")
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
    any_pass = any(all(p for _, p in _gates(cells[l]["m"], cells[l]["roll"], cells[l]["h1"],
                       cells[l]["h2"], cells[l]["stress"], bm_cagr)) for l in labels)
    w("-" * 100)
    if any_pass:
        w("VERDICT: event-driven post-event drift CLEARS all gates -> a genuinely INDEPENDENT")
        w("  family (family #4) beats the champion. Promote for deeper validation + ensemble study.")
    else:
        best = max(labels, key=lambda l: cells[l]["m"].sharpe_ratio)
        bm = cells[best]["m"]
        w(f"VERDICT: NO event-drift cell clears all gates. Best = {best} "
          f"(CAGR {bm.cagr:.1%}, Sharpe {bm.sharpe_ratio:.2f}, alpha {bm.alpha:+.1%}).")
        w("  The gap+volume PEAD proxy does not beat the champion net of costs as a standalone.")
        w("  (Records whether an independent event family has ANY standalone edge for later ensemble.)")
    w("=" * 100)
    txt = "\n".join(L)
    print("\n" + txt)
    (RDIR / "report.txt").write_text(txt, encoding="utf-8")

    rows = []
    for label in labels:
        c = cells[label]; m = c["m"]
        rows.append({"universe": label, "cagr": m.cagr, "sharpe": m.sharpe_ratio,
                     "max_dd": m.max_drawdown, "alpha": m.alpha, "trades": c["res"]["total_trades"],
                     "roll3y_min": c["roll"].min() if not c["roll"].empty else np.nan,
                     "h1_alpha": c["h1"].alpha if c["h1"] else np.nan,
                     "h2_alpha": c["h2"].alpha if c["h2"] else np.nan,
                     "headline_ok": c["headline_ok"]})
    pd.DataFrame(rows).to_csv(RDIR / "comparison.csv", index=False)


def _chart(cells, bench_eq, bm_cagr):
    plt.style.use("dark_background")
    labels = list(cells)
    fig = plt.figure(figsize=(18, 9))
    gs = GridSpec(1, 2, figure=fig, wspace=0.22)
    fig.suptitle("Program #2 Exp 2E — Event-Driven Post-Event Drift (PEAD proxy, net)",
                 fontsize=15, fontweight="bold", color="#fff", y=0.98)
    palette = ["#00ff88", "#ffd93d", "#ff6b6b"]

    ax1 = fig.add_subplot(gs[0, 0]); ax1.set_title("Equity Curve (base 100, log)", fontweight="bold")
    for i, label in enumerate(labels):
        eq = cells[label]["res"]["equity_curve"]
        ax1.plot(eq.index, eq/eq.iloc[0]*100, color=palette[i % len(palette)], lw=1.4, label=label)
    if not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.0, ls="--", label="NIFTY500(px)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax2 = fig.add_subplot(gs[0, 1]); ax2.set_title("CAGR & Sharpe vs champion", fontweight="bold")
    x = np.arange(len(labels))
    ax2.bar(x-0.2, [cells[l]["m"].cagr*100 for l in labels], 0.4, color="#00ff88", label="CAGR %")
    ax2.axhline(CHAMP_CAGR*100, color="#fff", ls=":", lw=1, label=f"champ CAGR {CHAMP_CAGR:.0%}")
    ax2.axhline(bm_cagr*100, color="#888", ls="--", lw=1, label=f"bm {bm_cagr:.0%}")
    a2 = ax2.twinx()
    a2.plot(x, [cells[l]["m"].sharpe_ratio for l in labels], color="#ff6b6b", marker="o", lw=1.6, label="Sharpe")
    a2.axhline(CHAMP_SHARPE, color="#ff6b6b", ls=":", lw=0.8)
    a2.set_ylabel("Sharpe", color="#ff6b6b")
    ax2.set_xticks(x); ax2.set_xticklabels(labels); ax2.set_ylabel("CAGR %")
    ax2.legend(framealpha=.3, fontsize=7, loc="upper left"); ax2.grid(True, alpha=.2, axis="y")

    fig.savefig(RDIR / "report.png", dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
