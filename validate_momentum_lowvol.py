"""
ROBUSTNESS VALIDATION of the Momentum + LowVol 50/50 strategy.

NOT an optimization. Nothing is tuned. We run the EXACT winning configuration once
and interrogate the single result five ways to see whether the +3.5% alpha / 0.46
Sharpe is broad-based or an artifact of a few stocks, years, or a regime.

FROZEN configuration (identical to results/momentum_lowvol/):
  - Survivorship-free universe (bhavcopy, top-500 liquidity, point-in-time)
  - Top 5 / quarterly / Buffer 20 / equal weight
  - Signal: 0.5*(12-1 momentum pctile) + 0.5*(low-vol pctile), 252-day realised vol
  - Net of the Indian cost model

TESTS:
  1. Split sample            : 2012-2018 vs 2019-2026 (CAGR/Sharpe/Alpha/MaxDD each).
  2. Rolling 5-year windows  : same 4 metrics for every monthly-stepped 5y window.
  3. Holdings breadth        : unique names held + top-20 most frequently held.
  4. Return concentration    : share of total P&L from the top-10 winning stocks.
  5. Universe segmentation   : P&L / holdings split across Large / Mid / Small cap,
                               where cap is proxied by point-in-time ADTV rank within
                               the 500-name universe (1-100 Large, 101-250 Mid, 251+
                               Small) — true free-float cap is not in free bhavcopy.

Benchmark: NIFTY 500 PRICE index (true TRI ~+1.3%/yr higher).
"""
import sys, io, warnings
from pathlib import Path
from collections import defaultdict

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
from data.benchmark import get_benchmark_equity_curve, get_benchmark_returns
from analytics.metrics import compute_metrics

from run_buffer_experiment import run_buffered_backtest
from run_momentum_lowvol import make_mom_lowvol_scorer, VOL_LOOKBACK
from run_survivorship_validation import TopNTurnoverUniverseBuilder

N_STOCKS, BUFFER, FREQ = 5, 20, "quarterly"
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
SPLITS = [("2012-2018", "2012-01-01", "2018-12-31"),
          ("2019-2026", "2019-01-01", "2026-12-31")]
ROLL_YEARS = 5


def load_equity_symbols():
    """Common-equity whitelist (ISIN 'INE'); excludes ETF/fund units (INF) and
    DVR/special (IN9). Built by build_equity_universe.py."""
    f = CACHE_BHAV / "symbols_equity.txt"
    return set(f.read_text().split()) if f.exists() else None


def m4(equity, returns, bench):
    """Compute the four validation metrics on a slice."""
    mm = compute_metrics(equity, returns, benchmark_returns=bench)
    return dict(cagr=mm.cagr, sharpe=mm.sharpe_ratio, alpha=mm.alpha,
                maxdd=mm.max_drawdown, beta=mm.beta)


# ─────────────────────────────────────────────────────────────────────
def main():
    cfg = SystemConfig()
    cap = cfg.portfolio.initial_capital
    start, end = cfg.backtest.start_date, cfg.backtest.end_date

    print("=" * 84)
    print("  ROBUSTNESS VALIDATION — Momentum + LowVol 50/50  (no tuning)")
    print("=" * 84)

    bench_ret = get_benchmark_returns(start, end)
    # bench_eq aligned to the strategy's realized span after the run (see below).

    print("\nLoading survivorship-free bhavcopy panels ...")
    ac = pd.read_parquet(CACHE_BHAV / "adj_close.parquet")
    ah = pd.read_parquet(CACHE_BHAV / "adj_high.parquet")
    al = pd.read_parquet(CACHE_BHAV / "adj_low.parquet")
    av = pd.read_parquet(CACHE_BHAV / "raw_volume.parquet")
    at = pd.read_parquet(CACHE_BHAV / "raw_turnover.parquet")
    print(f"  panel: {ac.shape[0]} dates x {ac.shape[1]} symbols")
    # ── UNIVERSE CLEANING: equity-only (drop ETF/gold/silver/liquid/index-fund units
    #    'INF' and DVR/special 'IN9'). Strategy/signals/params UNCHANGED. ──
    eq_syms = load_equity_symbols()
    if eq_syms is not None:
        keep = [c for c in ac.columns if c in eq_syms]
        dropped = ac.shape[1] - len(keep)
        ac, ah, al, av, at = (p[keep] for p in (ac, ah, al, av, at))
        print(f"  equity-only: kept {len(keep)} symbols, dropped {dropped} non-equity (ETF/fund) instruments")
    builder = TopNTurnoverUniverseBuilder(ac, ah, al, av, at, cfg.universe, max_size=500)
    scorer = make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)

    print("\nRunning the frozen Mom+LowVol 50/50 strategy (net of costs) ...")
    res = run_buffered_backtest(ac, ah, al, av, n_stocks=N_STOCKS, rebalance_freq=FREQ,
        buffer=BUFFER, initial_capital=cap, config=cfg, apply_costs=True,
        label="MomLowVol", universe_builder=builder, scorer=scorer)
    eq = res["equity_curve"]; rets = res["returns"]; trades = res["trades"]
    # Benchmark aligned to the strategy's realized span (warmup => starts ~2012-01).
    bstart, bend = str(eq.index[0].date()), str(eq.index[-1].date())
    bench_eq = get_benchmark_equity_curve(bstart, bend, cap)
    full = compute_metrics(eq, rets, benchmark_returns=bench_ret,
                           trades=trades, total_costs=res["total_costs"], initial_capital=cap)
    print(f"  FULL: CAGR {full.cagr:.2%} | MaxDD {full.max_drawdown:.2%} | "
          f"Sharpe {full.sharpe_ratio:.2f} | Alpha {full.alpha:+.2%}")

    L = []; w = L.append
    w("=" * 100)
    w("ROBUSTNESS VALIDATION — MOMENTUM + LOWVOL 50/50 (survivorship-free, no tuning)".center(100))
    w("=" * 100)
    w(f"Period {full.start_date}..{full.end_date} | Initial Rs {cap:,.0f} | "
      f"Final Rs {eq.iloc[-1]:,.0f}")
    w(f"FULL-SAMPLE: CAGR {full.cagr:.2%} | Sharpe {full.sharpe_ratio:.2f} | "
      f"Alpha {full.alpha:+.2%} | MaxDD {full.max_drawdown:.2%} | Beta {full.beta:.2f}")
    w("")

    # ── TEST 1: SPLIT SAMPLE ──
    w("-" * 100)
    w("TEST 1 — SPLIT SAMPLE")
    w("-" * 100)
    w(f"{'Sub-period':<14}{'CAGR':>10}{'Sharpe':>10}{'Alpha':>10}{'MaxDD':>10}{'Beta':>8}   {'days':>6}")
    split_rows = []
    for label, s, e in SPLITS:
        seq = eq.loc[s:e]; sret = rets.loc[s:e]; sben = bench_ret.loc[s:e]
        if len(seq) < 30:
            continue
        d = m4(seq, sret, sben)
        w(f"{label:<14}{d['cagr']:>9.2%}{d['sharpe']:>10.2f}{d['alpha']:>+9.2%}"
          f"{d['maxdd']:>9.2%}{d['beta']:>8.2f}   {len(seq):>6}")
        split_rows.append({"period": label, **d, "days": len(seq)})
    w("")
    if len(split_rows) == 2:
        a, b = split_rows
        w(f"  Both halves positive alpha? {'YES' if a['alpha'] > 0 and b['alpha'] > 0 else 'NO'}"
          f"   (alpha {a['alpha']:+.2%} / {b['alpha']:+.2%})")
        w(f"  Sharpe stable across halves? {a['sharpe']:.2f} vs {b['sharpe']:.2f}")
    w("")

    # ── TEST 2: ROLLING 5-YEAR WINDOWS ──
    w("-" * 100)
    w(f"TEST 2 — ROLLING {ROLL_YEARS}-YEAR WINDOWS (monthly step)")
    w("-" * 100)
    starts = pd.date_range(eq.index[0], eq.index[-1] - pd.DateOffset(years=ROLL_YEARS), freq="MS")
    roll_rows = []
    for s in starts:
        e = s + pd.DateOffset(years=ROLL_YEARS)
        seq = eq.loc[s:e]; sret = rets.loc[s:e]; sben = bench_ret.loc[s:e]
        if len(seq) < ROLL_YEARS * 252 * 0.8:
            continue
        d = m4(seq, sret, sben)
        roll_rows.append({"win_start": seq.index[0].date(), "win_end": seq.index[-1].date(), **d})
    rdf = pd.DataFrame(roll_rows)
    if not rdf.empty:
        w(f"  {len(rdf)} windows.  Each metric — min / median / max:")
        for k, lbl in [("cagr", "CAGR"), ("sharpe", "Sharpe"), ("alpha", "Alpha"), ("maxdd", "MaxDD")]:
            fmt = (lambda x: f"{x:+.2%}") if k in ("cagr", "alpha", "maxdd") else (lambda x: f"{x:.2f}")
            w(f"     {lbl:<8}: {fmt(rdf[k].min())} / {fmt(rdf[k].median())} / {fmt(rdf[k].max())}")
        w(f"  Windows with POSITIVE alpha : {(rdf['alpha'] > 0).mean():.0%}  "
          f"({int((rdf['alpha'] > 0).sum())}/{len(rdf)})")
        w(f"  Windows with POSITIVE CAGR  : {(rdf['cagr'] > 0).mean():.0%}")
        w(f"  Windows Sharpe > full(0.20*): {(rdf['sharpe'] > 0.20).mean():.0%}")
    w("")

    # ── Reconstruct holdings + cash flows from the trade log (no engine change) ──
    trades_sorted = sorted(trades, key=lambda t: t["date"])
    from utils.helpers import get_rebalance_dates
    rebal_dates = get_rebalance_dates(eq.index, FREQ)
    positions = defaultdict(int)
    buys_cash = defaultdict(float); sells_cash = defaultdict(float)
    snaps = {}                       # rebal date -> set of held symbols
    held_quarters = defaultdict(int) # symbol -> # quarters held
    i = 0
    for d in rebal_dates:
        while i < len(trades_sorted) and trades_sorted[i]["date"] <= d:
            t = trades_sorted[i]; sym = t["symbol"]
            if t["side"] == "BUY":
                positions[sym] += t["shares"]; buys_cash[sym] += t["value"] + t["cost"]
            else:
                positions[sym] -= t["shares"]; sells_cash[sym] += t["value"] - t["cost"]
            i += 1
        held = {s for s, q in positions.items() if q > 0}
        snaps[d] = held
        for s in held:
            held_quarters[s] += 1
    while i < len(trades_sorted):     # safety: any trades past last rebal date
        t = trades_sorted[i]; sym = t["symbol"]
        if t["side"] == "BUY":
            positions[sym] += t["shares"]; buys_cash[sym] += t["value"] + t["cost"]
        else:
            positions[sym] -= t["shares"]; sells_cash[sym] += t["value"] - t["cost"]
        i += 1

    # End-of-sample holdings valued at last known price (ffill).
    last_px = ac.ffill().iloc[-1]
    end_value = {s: positions[s] * last_px.get(s, np.nan) for s in positions if positions[s] > 0}
    end_value = {s: (v if pd.notna(v) else 0.0) for s, v in end_value.items()}

    all_syms = set(buys_cash) | set(sells_cash)
    pnl = {s: sells_cash.get(s, 0.0) - buys_cash.get(s, 0.0) + end_value.get(s, 0.0) for s in all_syms}
    pnl_s = pd.Series(pnl).sort_values(ascending=False)
    total_pnl = eq.iloc[-1] - cap

    # ── TEST 3: HOLDINGS BREADTH ──
    w("-" * 100)
    w("TEST 3 — HOLDINGS BREADTH")
    w("-" * 100)
    hq = pd.Series(held_quarters).sort_values(ascending=False)
    w(f"  Unique stocks ever held         : {len(hq)}")
    w(f"  Total quarterly rebalances      : {len(rebal_dates)}")
    w(f"  Avg distinct names held / quarter: {np.mean([len(s) for s in snaps.values()]):.2f}")
    w(f"  Median quarters a name is held  : {hq.median():.0f}  (max {hq.max()})")
    w("")
    w("  TOP 20 MOST FREQUENTLY HELD (quarters held | total P&L Rs | % of total P&L):")
    for rank, (sym, q) in enumerate(hq.head(20).items(), 1):
        p = pnl.get(sym, 0.0)
        w(f"     {rank:>2}. {sym:<16} {q:>3}q   {p:>14,.0f}   {p/total_pnl:>6.1%}")
    w("")

    # ── TEST 4: RETURN CONCENTRATION ──
    w("-" * 100)
    w("TEST 4 — RETURN CONCENTRATION")
    w("-" * 100)
    pos_pnl = pnl_s[pnl_s > 0].sum()
    neg_pnl = pnl_s[pnl_s < 0].sum()
    top10 = pnl_s.head(10)
    w(f"  Total net P&L (final - initial) : Rs {total_pnl:,.0f}")
    w(f"  Reconstructed sum of stock P&L  : Rs {pnl_s.sum():,.0f}  "
      f"(reconciliation gap {pnl_s.sum()-total_pnl:+,.0f}, costs/rounding)")
    w(f"  Gross winners P&L / gross losers: Rs {pos_pnl:,.0f} / Rs {neg_pnl:,.0f}")
    w(f"  Profitable names                : {(pnl_s>0).sum()}/{len(pnl_s)} ({(pnl_s>0).mean():.0%})")
    w("")
    w(f"  TOP 10 WINNERS contribute Rs {top10.sum():,.0f}")
    w(f"     = {top10.sum()/total_pnl:.0%} of TOTAL net P&L")
    w(f"     = {top10.sum()/pos_pnl:.0%} of all GROSS positive P&L")
    w("")
    w("  Top 10 winners (P&L Rs | % total | quarters held):")
    for rank, (sym, p) in enumerate(top10.items(), 1):
        w(f"     {rank:>2}. {sym:<16} {p:>14,.0f}   {p/total_pnl:>6.1%}   {held_quarters.get(sym,0):>3}q")
    w("  Bottom 5 losers:")
    for sym, p in pnl_s.tail(5).items():
        w(f"         {sym:<16} {p:>14,.0f}   {p/total_pnl:>6.1%}   {held_quarters.get(sym,0):>3}q")
    w("")

    # ── TEST 5: UNIVERSE SEGMENTATION (ADTV-rank cap proxy) ──
    w("-" * 100)
    w("TEST 5 — UNIVERSE SEGMENTATION  (cap proxied by point-in-time ADTV rank)")
    w("-" * 100)
    lookback = cfg.universe.turnover_lookback
    seg_quarter_counts = defaultdict(lambda: defaultdict(int))   # sym -> segment -> count
    seg_hold_quarters = defaultdict(int)                          # segment -> holding-quarters
    for d, held in snaps.items():
        if not held:
            continue
        uni = builder.build_universe(d).symbols
        cols = [s for s in uni if s in at.columns]
        adtv = at.loc[at.index <= d].tail(lookback)[cols].mean().sort_values(ascending=False)
        rank_of = {s: r for r, s in enumerate(adtv.index, 1)}
        for s in held:
            r = rank_of.get(s, len(adtv) + 1)
            seg = "Large" if r <= 100 else ("Mid" if r <= 250 else "Small")
            seg_quarter_counts[s][seg] += 1
            seg_hold_quarters[seg] += 1
    # Each stock's modal segment, then attribute its P&L.
    seg_pnl = defaultdict(float); seg_names = defaultdict(set)
    for s, segc in seg_quarter_counts.items():
        modal = max(segc, key=segc.get)
        seg_pnl[modal] += pnl.get(s, 0.0)
        seg_names[modal].add(s)
    total_hold_q = sum(seg_hold_quarters.values()) or 1
    w(f"  {'Segment':<8}{'HoldQtrs':>10}{'% Hold':>9}{'Uniq names':>12}{'P&L Rs':>16}{'% total P&L':>13}")
    for seg in ["Large", "Mid", "Small"]:
        hq_seg = seg_hold_quarters.get(seg, 0)
        w(f"  {seg:<8}{hq_seg:>10}{hq_seg/total_hold_q:>9.0%}{len(seg_names.get(seg,set())):>12}"
          f"{seg_pnl.get(seg,0.0):>16,.0f}{seg_pnl.get(seg,0.0)/total_pnl:>13.0%}")
    w("")
    w("  (Large = ADTV rank 1-100, Mid = 101-250, Small = 251-500 within the daily")
    w("   500-name universe. A turnover-based size proxy, not free-float market cap.)")
    w("")

    # ── VERDICT ──
    w("=" * 100)
    w("VALIDATION VERDICT".center(100, "-"))
    robust_split = len(split_rows) == 2 and all(r["alpha"] > 0 for r in split_rows)
    robust_roll = (not rdf.empty) and (rdf["alpha"] > 0).mean() >= 0.6
    top10_share = top10.sum() / total_pnl
    concentrated = top10_share > 0.80
    seg_shares = {s: seg_pnl.get(s, 0.0) / total_pnl for s in ["Large", "Mid", "Small"]}
    one_seg = max(seg_shares.values()) > 0.80
    w(f"  1. Split sample : both halves alpha>0 ? {'YES' if robust_split else 'NO'}")
    w(f"  2. Rolling 5y   : >=60% windows alpha>0 ? {'YES' if robust_roll else 'NO'} "
      f"({(rdf['alpha']>0).mean():.0%})" if not rdf.empty else "  2. Rolling 5y: n/a")
    w(f"  3/4. Concentration: top-10 names = {top10_share:.0%} of P&L "
      f"=> {'CONCENTRATED' if concentrated else 'broad-based'}")
    w(f"  5. Segments     : largest segment = {max(seg_shares, key=seg_shares.get)} "
      f"at {max(seg_shares.values()):.0%} of P&L => {'REGIME-DEPENDENT' if one_seg else 'spread across caps'}")
    verdict = "ROBUST" if (robust_split and robust_roll and not concentrated and not one_seg) else \
              "PARTIALLY ROBUST / see caveats"
    w("")
    w(f"  => OVERALL: {verdict}")
    w("=" * 100)

    txt = "\n".join(L)
    print("\n" + txt)

    rdir = RESULTS_DIR / "momentum_lowvol_validation"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "report.txt").write_text(txt, encoding="utf-8")
    pd.DataFrame(split_rows).to_csv(rdir / "split_sample.csv", index=False)
    if not rdf.empty:
        rdf.to_csv(rdir / "rolling_5y.csv", index=False)
    hq.rename("quarters_held").to_frame().join(
        pnl_s.rename("total_pnl")).to_csv(rdir / "holdings_breadth.csv")
    pnl_s.rename("total_pnl").to_frame().to_csv(rdir / "stock_pnl.csv")
    make_charts(eq, bench_eq, rdf, hq, pnl_s, total_pnl, seg_pnl, rdir / "report.png")
    print(f"\n  All outputs in: {rdir}/")


def make_charts(eq, bench_eq, rdf, hq, pnl_s, total_pnl, seg_pnl, save_path):
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(18, 22)); gs = GridSpec(4, 2, figure=fig, hspace=0.42, wspace=0.24)
    fig.suptitle("Momentum + LowVol 50/50 — Robustness Validation", fontsize=15,
                 fontweight="bold", y=0.995, color="#fff")
    G = "#00ff88"

    ax1 = fig.add_subplot(gs[0, :]); ax1.set_title("Equity vs Benchmark (base 100, log)", fontweight="bold")
    ax1.plot(eq.index, eq/eq.iloc[0]*100, color=G, lw=1.8, label="Mom+LowVol 50/50")
    if bench_eq is not None and not bench_eq.empty:
        ax1.plot(bench_eq.index, bench_eq/bench_eq.iloc[0]*100, color="#888", lw=1.3, ls="--", label="NIFTY 500 (price)")
    ax1.set_yscale("log"); ax1.legend(loc="upper left", framealpha=.3); ax1.grid(True, alpha=.2)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    if rdf is not None and not rdf.empty:
        x = pd.to_datetime(rdf["win_end"])
        ax2 = fig.add_subplot(gs[1, 0]); ax2.set_title("Rolling 5Y CAGR & Alpha", fontweight="bold")
        ax2.plot(x, rdf["cagr"]*100, color=G, lw=1.5, label="CAGR %")
        ax2.plot(x, rdf["alpha"]*100, color="#ffd93d", lw=1.5, label="Alpha %")
        ax2.axhline(0, color="white", lw=.5, alpha=.4); ax2.legend(framealpha=.3); ax2.grid(True, alpha=.2)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax3 = fig.add_subplot(gs[1, 1]); ax3.set_title("Rolling 5Y Sharpe & MaxDD", fontweight="bold")
        ax3.plot(x, rdf["sharpe"], color="#4ecdc4", lw=1.5, label="Sharpe")
        ax3.axhline(0.20, color="#ff6b6b", ls="--", lw=1, alpha=.6, label="full-sample 0.20")
        a3 = ax3.twinx(); a3.plot(x, rdf["maxdd"]*100, color="#ff6b6b", lw=1.2, label="MaxDD %")
        a3.set_ylabel("MaxDD %", color="#ff6b6b")
        ax3.legend(loc="upper left", framealpha=.3); ax3.grid(True, alpha=.2)
        ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    ax4 = fig.add_subplot(gs[2, :]); ax4.set_title("Top 20 Most Frequently Held (quarters)", fontweight="bold")
    top = hq.head(20)
    ax4.bar(range(len(top)), top.values, color=G)
    ax4.set_xticks(range(len(top))); ax4.set_xticklabels(top.index, rotation=60, ha="right", fontsize=8)
    ax4.set_ylabel("Quarters held"); ax4.grid(True, alpha=.2, axis="y")

    ax5 = fig.add_subplot(gs[3, 0]); ax5.set_title("Return Concentration (cumulative P&L share)", fontweight="bold")
    cum = pnl_s.cumsum() / total_pnl
    ax5.plot(range(1, len(cum)+1), cum.values*100, color=G, lw=1.6)
    ax5.axvline(10, color="#ffd93d", ls="--", lw=1, label="top 10")
    ax5.axhline(100, color="white", lw=.5, alpha=.3)
    ax5.set_xlabel("Stocks ranked by P&L"); ax5.set_ylabel("Cumulative % of total P&L")
    ax5.legend(framealpha=.3); ax5.grid(True, alpha=.2)

    ax6 = fig.add_subplot(gs[3, 1]); ax6.set_title("P&L by Cap Segment (ADTV proxy)", fontweight="bold")
    segs = ["Large", "Mid", "Small"]; vals = [seg_pnl.get(s, 0.0)/total_pnl*100 for s in segs]
    b = ax6.bar(segs, vals, color=["#4ecdc4", "#ffd93d", "#ff6b6b"])
    for bb, vv in zip(b, vals):
        ax6.text(bb.get_x()+bb.get_width()/2, bb.get_height(), f"{vv:.0f}%", ha="center", va="bottom",
                 color="#fff", fontweight="bold")
    ax6.axhline(0, color="white", lw=.5, alpha=.4); ax6.set_ylabel("% of total P&L"); ax6.grid(True, alpha=.2, axis="y")

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor()); plt.close(fig)
    print(f"  Chart saved: {save_path}")


if __name__ == "__main__":
    main()
