"""
ADAPTIVE / CONDITIONAL LOGIC research track.

Family brief: everything else in the campaign ranks stocks or allocates capital.
This track decides WHEN to be in, WHEN to exit, and WHICH stocks to veto.

Baseline = frozen champion: Mom+LowVol 50/50, Top-10, monthly, Buffer-20,
equal weight, whole-share, NET of costs, Rs 10,00,000, liquid rank band 0-500.
DISCOVERY (2013-01..2021-12 after the 1-yr warm-up): CAGR 24.30%, Sharpe 1.12,
MaxDD -31.4%, rolling-3y-min 5.5%.  Benchmark 13.63%.

SPLIT DISCIPLINE: every search run is split='discovery'. Holdout is touched once,
at the end, by the finalists only (stage `holdout`).

Everything the rules look at is backward-looking by construction (rolling windows
with no shift(-n) anywhere, indexed strictly at `date`), so no look-ahead.

Usage:
    py run_adaptive_rules.py baseline|vetoes|timing|exits|entry|stacks|holdout|all
"""
import sys
import io
import os
import time
import json
import argparse
import warnings
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.ERROR)
for _n in list(logging.root.manager.loggerDict):
    logging.getLogger(_n).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from config import SystemConfig
from costs.cost_model import CostModel
from utils.helpers import get_rebalance_dates
from analytics.metrics import compute_metrics
from data.benchmark import get_benchmark_returns

from research_harness import (load_panels, rolling_3y_min, champion_scorer,
                              deflated_sharpe, SPLITS, CAP)
from run_smallcap_universe import RankBandUniverseBuilder
from run_buffer_experiment import select_with_buffer

RDIR = PROJECT_ROOT / "results" / "adaptive_rules"
RDIR.mkdir(parents=True, exist_ok=True)

N_STOCKS, BUFFER, FREQ, BAND = 10, 20, "monthly", (0, 500)
CHAMP = {"cagr": 0.2430, "sharpe": 1.117, "maxdd": -0.3145, "roll3y": 0.0549}

# ════════════════════════════════════════════════════════════════════════
#  PANELS + DERIVED (computed ONCE over full history; all backward-looking)
# ════════════════════════════════════════════════════════════════════════
_P = {}


def panels():
    if "close" not in _P:
        c, h, l, v, t = load_panels()
        _P.update(close=c, high=h, low=l, vol=v, turn=t)
    return _P["close"], _P["high"], _P["low"], _P["vol"], _P["turn"]


def derived():
    """Per-stock veto metrics. rolling(...) is strictly backward-looking."""
    if "ext" in _P:
        return _P
    c, h, l, v, t = panels()
    ret = c.pct_change()
    f32 = lambda d: d.astype("float32")
    _P["volspike"] = f32(ret.rolling(21).std() / ret.rolling(252).std())
    _P["volcollapse"] = f32(v.rolling(21).mean() / v.rolling(252).mean())
    _P["ext"] = f32(c / c.rolling(200).mean() - 1.0)
    _P["maxret21"] = f32(ret.rolling(21).max())
    _P["volcv"] = f32(v.rolling(60).std() / v.rolling(60).mean())
    _P["ret21"] = f32(c.pct_change(21))
    return _P


def market_series():
    """
    Daily, backward-looking market-state series used by the timing rules.
      mkt        : NIFTY-500 TRI level (real published index, PIT)
      above200   : TRI > its own 200d SMA
      breadth    : fraction of live stocks above their own 200d MA
      disp       : cross-sectional std of trailing 21d stock returns
      volratio   : TRI 21d realised vol / TRI 252d realised vol (turbulence)
    """
    if "mkt" in _P:
        return _P
    c, _h, _l, _v, _t = panels()
    br = get_benchmark_returns(SPLITS["full"][0], SPLITS["full"][1])
    mkt = (1 + br.fillna(0)).cumprod()
    mkt = mkt.reindex(c.index).ffill()
    _P["mkt"] = mkt
    _P["mkt_ma200"] = mkt.rolling(200).mean()
    _P["mkt_ma50"] = mkt.rolling(50).mean()
    mr = mkt.pct_change()
    _P["volratio"] = (mr.rolling(21).std() / mr.rolling(252).std())
    d = derived()
    ma200 = c.rolling(200).mean()
    above = (c > ma200) & c.notna() & ma200.notna()
    live = (c.notna() & ma200.notna()).sum(axis=1)
    _P["breadth"] = (above.sum(axis=1) / live.replace(0, np.nan))
    _P["disp"] = d["ret21"].std(axis=1).astype(float)
    # percentile rank of dispersion vs its own trailing 3y history (PIT)
    _P["disp_pct"] = _P["disp"].rolling(756, min_periods=252).apply(
        lambda w: (w[-1] > w[:-1]).mean(), raw=True)
    return _P


# ════════════════════════════════════════════════════════════════════════
#  UNIVERSE CACHE  (built once per split; reused by every config)
# ════════════════════════════════════════════════════════════════════════
_UCACHE = {}


def split_panels(split):
    s, e = SPLITS[split]
    c, h, l, v, t = panels()
    return [p.loc[s:e] for p in (c, h, l, v, t)]


def universe_cache(split, cfg):
    key = (split, BAND, FREQ)
    if key in _UCACHE:
        return _UCACHE[key]
    c, h, l, v, t = split_panels(split)
    start = max(pd.Timestamp(cfg.backtest.start_date),
                c.index.min() + pd.Timedelta(days=365))
    end = min(pd.Timestamp(cfg.backtest.end_date), c.index.max())
    all_dates = c.index[(c.index >= start) & (c.index <= end)]
    rebal = list(get_rebalance_dates(all_dates, FREQ))
    ub = RankBandUniverseBuilder(c, h, l, v, t, cfg.universe, BAND[0], BAND[1])
    lookback = cfg.universe.turnover_lookback
    snaps, adtvs = {}, {}
    t0 = time.time()
    for i, d in enumerate(rebal):
        snaps[d] = ub.build_universe(d)
        adtvs[d] = t.loc[:d].tail(lookback).mean()
        if (i + 1) % 20 == 0:
            print(f"    universe {i+1}/{len(rebal)}  ({time.time()-t0:.0f}s)",
                  flush=True)
    out = dict(all_dates=all_dates, rebal=rebal, snaps=snaps, adtvs=adtvs)
    _UCACHE[key] = out
    print(f"  universe cache[{split}] {len(rebal)} rebalances in "
          f"{time.time()-t0:.0f}s", flush=True)
    return out


# ════════════════════════════════════════════════════════════════════════
#  ENGINE  (mirror of run_impact_aware_backtest + adaptive hooks)
# ════════════════════════════════════════════════════════════════════════
def run_adaptive(split, scorer, *, buffer=BUFFER, n_stocks=N_STOCKS,
                 capital=CAP, cfg=None, exposure_fn=None, veto_fn=None,
                 trailing_stop=None, hard_stop=None, profit_take=None,
                 max_hold_days=None, entry_delay=0, pullback=None, label=""):
    """
    hooks (all default-off => exact champion reproduction):
      exposure_fn(date) -> float in [0,1]; scales capital-at-risk, rest to cash
      veto_fn(date, syms) -> iterable of symbols to drop from the candidate list
      trailing_stop  : sell a name after it falls this fraction from its running
                       peak close since entry (daily check)
      hard_stop      : sell after it falls this fraction below its entry price
      profit_take    : sell after it rises this fraction above its entry price
      max_hold_days  : a holding older than this many calendar days may not be
                       retained by the buffer (forced re-evaluation at rebalance)
      entry_delay    : buy NEW names d trading days after the rebalance
      pullback       : (window, drop) - buy a NEW name on the first day within
                       `window` days whose close is <= (1-drop) x rebalance close,
                       else at the end of the window
    """
    cfg = cfg or SystemConfig()
    c, h, l, v, t = split_panels(split)
    uc = universe_cache(split, cfg)
    all_dates, rebal_set = uc["all_dates"], set(uc["rebal"])
    snaps, adtvs = uc["snaps"], uc["adtvs"]

    valuation = c.ffill()
    val = valuation.values
    raw = c.values
    col = {s: i for i, s in enumerate(c.columns)}
    pos = {d: i for i, d in enumerate(c.index)}

    cost_model = CostModel(cfg.costs)
    cash = float(capital)
    holdings = {}                 # sym -> qty
    meta = {}                     # sym -> dict(entry_px, peak, entry_date)
    tiers_last = {}
    adtv_last = {}
    pending = []                  # queued buys: dict(sym, qty_value, ref_px, deadline_i)
    eq_rows, trades = [], []
    total_costs = 0.0
    exposure_log = {}

    def sell(sym, qty, px, date, reason):
        nonlocal cash, total_costs
        tc = cost_model.calculate_trade_cost(
            sym, "SELL", qty, px, liquidity_tier=tiers_last.get(sym, 2),
            avg_daily_value=float(adtv_last.get(sym, 0) or 0))
        cash += qty * px - tc.total_cost
        total_costs += tc.total_cost
        trades.append({"date": date, "symbol": sym, "side": "SELL",
                       "shares": qty, "price": px, "value": qty * px,
                       "cost": tc.total_cost, "reason": reason})

    def buy(sym, qty, px, date, adtv):
        nonlocal cash, total_costs
        tc = cost_model.calculate_trade_cost(
            sym, "BUY", qty, px, liquidity_tier=tiers_last.get(sym, 2),
            avg_daily_value=adtv)
        tot = qty * px + tc.total_cost
        if tot > cash:
            aff = int((cash - tc.total_cost) / px) if px > 0 else 0
            if aff <= 0:
                return 0
            qty = aff
            tc = cost_model.calculate_trade_cost(
                sym, "BUY", qty, px, liquidity_tier=tiers_last.get(sym, 2),
                avg_daily_value=adtv)
            tot = qty * px + tc.total_cost
        cash -= tot
        total_costs += tc.total_cost
        holdings[sym] = holdings.get(sym, 0) + qty
        trades.append({"date": date, "symbol": sym, "side": "BUY",
                       "shares": qty, "price": px, "value": qty * px,
                       "cost": tc.total_cost, "reason": "entry"})
        return qty

    daily_exits = (trailing_stop is not None or hard_stop is not None
                   or profit_take is not None)

    for i, date in enumerate(all_dates):
        p = pos[date]
        vrow, crow = val[p], raw[p]

        hv = 0.0
        for s, q in holdings.items():
            x = vrow[col[s]]
            if x == x:
                hv += q * x
        pv = cash + hv
        eq_rows.append((date, pv))

        # ── daily exit checks (use today's traded close only) ──
        if daily_exits and holdings:
            for s in list(holdings.keys()):
                px = crow[col[s]]
                if not (px == px and px > 0):
                    continue
                md = meta.get(s)
                if md is None:
                    continue
                if px > md["peak"]:
                    md["peak"] = px
                why = None
                if trailing_stop and px <= md["peak"] * (1 - trailing_stop):
                    why = "trail"
                elif hard_stop and px <= md["entry_px"] * (1 - hard_stop):
                    why = "stop"
                elif profit_take and px >= md["entry_px"] * (1 + profit_take):
                    why = "profit"
                if why:
                    sell(s, holdings[s], float(px), date, why)
                    del holdings[s]
                    meta.pop(s, None)

        # ── queued (delayed / pullback) entries ──
        if pending:
            still = []
            for job in pending:
                if i < job["first_i"]:
                    still.append(job)
                    continue
                px = crow[col[job["sym"]]]
                ok_price = px == px and px > 0
                triggered = i >= job["deadline_i"]
                if ok_price and job["trigger_px"] is not None:
                    triggered = triggered or px <= job["trigger_px"]
                if not triggered:
                    still.append(job)
                    continue
                if ok_price:
                    q = int(job["budget"] / px)
                    if q > 0:
                        got = buy(job["sym"], q, float(px), date, job["adtv"])
                        if got:
                            meta[job["sym"]] = {"entry_px": float(px),
                                                "peak": float(px),
                                                "entry_date": date}
            pending = still

        if date not in rebal_set:
            continue

        snap = snaps.get(date)
        if snap is None or not snap.symbols:
            continue
        tiers_last.update(snap.liquidity_tiers)
        adtv = adtvs[date]
        adtv_last = {s: float(adtv.get(s, 0) or 0) for s in snap.symbols}

        cand = snap.symbols
        if veto_fn is not None:
            bad = set(veto_fn(date, cand))
            cand = [s for s in cand if s not in bad]
            if len(cand) < n_stocks:
                cand = snap.symbols          # never starve the book
        scores = scorer(c, date, cand)
        if scores.empty or len(scores) < n_stocks:
            continue

        hold_for_buffer = dict(holdings)
        if max_hold_days:
            # a position older than max_hold_days is force-sold and barred from
            # re-entry at this rebalance (a genuine time stop, not a re-rank)
            stale = {s for s in holdings
                     if s in meta and (date - meta[s]["entry_date"]).days >= max_hold_days}
            if stale:
                hold_for_buffer = {s: q for s, q in holdings.items() if s not in stale}
                scores = scores[~scores.index.isin(stale)]
                if len(scores) < n_stocks:
                    continue
        selected = select_with_buffer(scores, hold_for_buffer, n_stocks, buffer)

        expo = 1.0 if exposure_fn is None else float(exposure_fn(date))
        expo = min(max(expo, 0.0), 1.0)
        exposure_log[date] = expo
        per_stock = pv * expo / n_stocks

        target = {}
        for s in selected:
            px = crow[col[s]]
            if not (px == px and px > 0):
                continue
            q = int(per_stock / px)
            if q > 0:
                target[s] = q

        # sells first
        for s, q in list(holdings.items()):
            tq = target.get(s, 0)
            sq = q - tq
            if sq <= 0:
                continue
            px = crow[col[s]]
            if not (px == px and px > 0):
                px = vrow[col[s]]
            if not (px == px and px > 0):
                del holdings[s]
                meta.pop(s, None)
                continue
            sell(s, sq, float(px), date, "rebal")
            holdings[s] = q - sq
            if holdings[s] <= 0:
                del holdings[s]
                meta.pop(s, None)
        # cancel stale queued buys for names no longer wanted
        if pending:
            pending = [j for j in pending if j["sym"] in target]

        # buys
        for s, tq in target.items():
            bq = tq - holdings.get(s, 0)
            if bq <= 0:
                continue
            px = crow[col[s]]
            if not (px == px and px > 0):
                continue
            is_new = s not in holdings
            if is_new and (entry_delay or pullback):
                win = pullback[0] if pullback else entry_delay
                trig = float(px) * (1 - pullback[1]) if pullback else None
                first = i + (1 if pullback else entry_delay)
                pending.append({"sym": s, "budget": bq * float(px),
                                "trigger_px": trig, "first_i": first,
                                "deadline_i": min(i + win, len(all_dates) - 1),
                                "adtv": float(adtv.get(s, 0) or 0)})
                continue
            got = buy(s, bq, float(px), date, float(adtv.get(s, 0) or 0))
            if got and is_new:
                meta[s] = {"entry_px": float(px), "peak": float(px),
                           "entry_date": date}

    eq = pd.Series(dict(eq_rows)).sort_index()
    eq.index = pd.DatetimeIndex(eq.index)
    rets = eq.pct_change().fillna(0)
    s, e = SPLITS[split]
    br = get_benchmark_returns(s, e)
    m = compute_metrics(eq, rets, benchmark_returns=br, trades=trades,
                        total_costs=total_costs, initial_capital=capital)
    return {
        "label": label, "split": split, "cagr": m.cagr,
        "sharpe": m.sharpe_ratio, "maxdd": m.max_drawdown,
        "calmar": m.cagr / abs(m.max_drawdown) if m.max_drawdown else np.nan,
        "roll3y": rolling_3y_min(rets), "n_trades": len(trades),
        "costs": total_costs, "final": float(eq.iloc[-1]),
        "equity": eq, "returns": rets, "exposure": pd.Series(exposure_log),
        "trades": trades,
    }


# ════════════════════════════════════════════════════════════════════════
#  VETOES
# ════════════════════════════════════════════════════════════════════════
def _asof(df, date, syms):
    cols = [s for s in syms if s in df.columns]
    return df.loc[date, cols].astype(float)


def make_veto(metric, thresh, mode="gt", pctile=None):
    """mode 'gt': drop metric > thresh. 'lt': drop metric < thresh.
       pctile: instead drop the worst `pctile` fraction of the candidate set."""
    d = derived()
    df = d[metric]

    def veto_fn(date, syms):
        x = _asof(df, date, syms).dropna()
        if x.empty:
            return []
        if pctile is not None:
            k = x.quantile(1 - pctile) if mode == "gt" else x.quantile(pctile)
            return x[x > k].index if mode == "gt" else x[x < k].index
        return x[x > thresh].index if mode == "gt" else x[x < thresh].index
    return veto_fn


def stack_vetoes(*fns):
    def veto_fn(date, syms):
        out = set()
        for f in fns:
            out |= set(f(date, syms))
        return out
    return veto_fn


# ════════════════════════════════════════════════════════════════════════
#  TIMING RULES  (exposure_fn: date -> [0,1])
# ════════════════════════════════════════════════════════════════════════
def expo_ma200(low_expo=0.0):
    ms = market_series()
    mkt, ma = ms["mkt"], ms["mkt_ma200"]

    def f(date):
        if date not in mkt.index or not np.isfinite(ma.get(date, np.nan)):
            return 1.0
        return 1.0 if mkt[date] > ma[date] else low_expo
    return f


def expo_regime():
    """RegimeFilter-style 3-state on the TRI proxy (BULL/NEUTRAL/BEAR)."""
    ms = market_series()
    mkt, ma200, ma50 = ms["mkt"], ms["mkt_ma200"], ms["mkt_ma50"]
    alloc = {"BULL": 1.0, "NEUTRAL": 0.7, "BEAR": 0.3}

    def f(date):
        if not np.isfinite(ma200.get(date, np.nan)):
            return 1.0
        above = mkt[date] > ma200[date]
        fast = ma50[date] > ma200[date]
        r = "BULL" if (above and fast) else ("NEUTRAL" if above else "BEAR")
        return alloc[r]
    return f


def expo_breadth(lo=0.30, hi=0.50, floor=0.0):
    b = market_series()["breadth"]

    def f(date):
        x = b.get(date, np.nan)
        if not np.isfinite(x):
            return 1.0
        if x >= hi:
            return 1.0
        if x <= lo:
            return floor
        return floor + (1 - floor) * (x - lo) / (hi - lo)
    return f


def expo_disp(cut=0.25, low_expo=0.5, invert=False):
    dp = market_series()["disp_pct"]

    def f(date):
        x = dp.get(date, np.nan)
        if not np.isfinite(x):
            return 1.0
        risk_off = (x > 1 - cut) if invert else (x < cut)
        return low_expo if risk_off else 1.0
    return f


def expo_turbulence(thr=1.5, low_expo=0.5):
    vr = market_series()["volratio"]

    def f(date):
        x = vr.get(date, np.nan)
        if not np.isfinite(x):
            return 1.0
        return low_expo if x > thr else 1.0
    return f


def episodes(expo_series):
    """(#distinct risk-off episodes, #rebalances risk-off, mean exposure)."""
    e = expo_series.sort_index()
    off = (e < 0.999).astype(int)
    starts = int(((off == 1) & (off.shift(1).fillna(0) == 0)).sum())
    return starts, int(off.sum()), float(e.mean())


# ════════════════════════════════════════════════════════════════════════
#  DRIVER
# ════════════════════════════════════════════════════════════════════════
ROWS_CSV = RDIR / "results.csv"


def record(rows, res, note=""):
    r = {k: res[k] for k in ("label", "split", "cagr", "sharpe", "maxdd",
                             "calmar", "roll3y", "n_trades", "final")}
    r["vs_champ"] = res["cagr"] - CHAMP["cagr"] if res["split"] == "discovery" else np.nan
    r["note"] = note
    rows.append(r)
    print(f"  {res['label']:<34} CAGR {res['cagr']*100:6.2f}%  "
          f"Sh {res['sharpe']:.2f}  DD {res['maxdd']*100:6.1f}%  "
          f"r3y {(res['roll3y'] or np.nan)*100:5.1f}%  "
          f"d {r['vs_champ']*100 if r['vs_champ'] == r['vs_champ'] else 0:+5.2f}  {note}",
          flush=True)
    return r


def flush(rows, name):
    if not rows:
        return
    df = pd.DataFrame(rows)
    path = RDIR / f"{name}.csv"
    df.to_csv(path, index=False)
    hdr = not ROWS_CSV.exists()
    df.to_csv(ROWS_CSV, mode="a", header=hdr, index=False)
    print(f"  -> {path}")


VETO_GRID = [
    ("volspike>2.0",      make_veto("volspike", 2.0)),
    ("volspike>1.5",      make_veto("volspike", 1.5)),
    ("volspike top10%",   make_veto("volspike", None, pctile=0.10)),
    ("volcollapse<0.5",   make_veto("volcollapse", 0.5, mode="lt")),
    ("volcollapse<0.7",   make_veto("volcollapse", 0.7, mode="lt")),
    ("volcollapse bot10%", make_veto("volcollapse", None, mode="lt", pctile=0.10)),
    ("extended>50%MA200", make_veto("ext", 0.50)),
    ("extended>100%MA200", make_veto("ext", 1.00)),
    ("extended top10%",   make_veto("ext", None, pctile=0.10)),
    ("extended top20%",   make_veto("ext", None, pctile=0.20)),
    ("lottery max1d>15%", make_veto("maxret21", 0.15)),
    ("lottery max1d>20%", make_veto("maxret21", 0.20)),
    ("lottery top10%",    make_veto("maxret21", None, pctile=0.10)),
    ("volCV>1.5",         make_veto("volcv", 1.5)),
    ("volCV>1.0",         make_veto("volcv", 1.0)),
    ("volCV top10%",      make_veto("volcv", None, pctile=0.10)),
]

TIMING_GRID = [
    ("MA200 on/off",        expo_ma200(0.0)),
    ("MA200 1.0/0.5",       expo_ma200(0.5)),
    ("MA200 1.0/0.7",       expo_ma200(0.7)),
    ("Regime 3-state",      expo_regime()),
    ("Breadth 30/50 ->0",   expo_breadth(0.30, 0.50, 0.0)),
    ("Breadth 30/50 ->0.5", expo_breadth(0.30, 0.50, 0.5)),
    ("Breadth 40/60 ->0",   expo_breadth(0.40, 0.60, 0.0)),
    ("Disp low->0.5",       expo_disp(0.25, 0.5, invert=False)),
    ("Disp high->0.5",      expo_disp(0.25, 0.5, invert=True)),
    ("Turbulence>1.5->0.5", expo_turbulence(1.5, 0.5)),
    ("Turbulence>1.3->0.5", expo_turbulence(1.3, 0.5)),
    ("Turbulence>1.5->0",   expo_turbulence(1.5, 0.0)),
]

EXIT_GRID = [
    ("buffer=10 (plain topN)", dict(buffer=10)),
    ("buffer=15",              dict(buffer=15)),
    ("buffer=30",              dict(buffer=30)),
    ("buffer=50",              dict(buffer=50)),
    ("buffer=100",             dict(buffer=100)),
    ("buffer=250",             dict(buffer=250)),
    ("maxhold 3m",             dict(max_hold_days=92)),
    ("maxhold 6m",             dict(max_hold_days=183)),
    ("maxhold 12m",            dict(max_hold_days=365)),
    ("trail stop 15%",         dict(trailing_stop=0.15)),
    ("trail stop 25%",         dict(trailing_stop=0.25)),
    ("trail stop 35%",         dict(trailing_stop=0.35)),
    ("hard stop 20%",          dict(hard_stop=0.20)),
    ("hard stop 30%",          dict(hard_stop=0.30)),
    ("profit take +50%",       dict(profit_take=0.50)),
    ("profit take +100%",      dict(profit_take=1.00)),
]

ENTRY_GRID = [
    ("entry delay 3d",         dict(entry_delay=3)),
    ("entry delay 5d",         dict(entry_delay=5)),
    ("entry delay 10d",        dict(entry_delay=10)),
    ("pullback -2% w10",       dict(pullback=(10, 0.02))),
    ("pullback -5% w10",       dict(pullback=(10, 0.05))),
]


def stage_baseline(rows):
    sc = champion_scorer()
    r = run_adaptive("discovery", sc, label="champion (engine check)")
    record(rows, r)
    return r


def stage_vetoes(rows):
    sc = champion_scorer()
    for name, fn in VETO_GRID:
        r = run_adaptive("discovery", sc, veto_fn=fn, label=f"veto {name}")
        record(rows, r)


def stage_timing(rows):
    sc = champion_scorer()
    for name, fn in TIMING_GRID:
        r = run_adaptive("discovery", sc, exposure_fn=fn, label=f"time {name}")
        ep = episodes(r["exposure"])
        record(rows, r, note=f"episodes={ep[0]} months_off={ep[1]} mean_expo={ep[2]:.2f}")


def stage_exits(rows):
    sc = champion_scorer()
    for name, kw in EXIT_GRID:
        r = run_adaptive("discovery", sc, label=f"exit {name}", **kw)
        record(rows, r)


def stage_entry(rows):
    sc = champion_scorer()
    for name, kw in ENTRY_GRID:
        r = run_adaptive("discovery", sc, label=f"entry {name}", **kw)
        record(rows, r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", nargs="?", default="all")
    a = ap.parse_args()
    stages = {"baseline": stage_baseline, "vetoes": stage_vetoes,
              "timing": stage_timing, "exits": stage_exits,
              "entry": stage_entry}
    print("=" * 96)
    print(f"  ADAPTIVE / CONDITIONAL LOGIC  —  stage: {a.stage}".center(96))
    print("=" * 96)
    panels()
    if a.stage in ("vetoes", "all"):
        derived()
    if a.stage in ("timing", "all"):
        market_series()
    rows = []
    todo = list(stages) if a.stage == "all" else [a.stage]
    for st in todo:
        print(f"\n── {st} " + "─" * 70)
        stages[st](rows)
        flush(rows, st)
        rows = []


if __name__ == "__main__":
    main()
