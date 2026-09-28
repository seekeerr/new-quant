"""
MULTI-SLEEVE ENSEMBLE / ALLOCATION SEARCH.

Family assignment: "ensembles and allocation BETWEEN strategies". Program #2 tried a
handful of hand-picked pairs (A+B, A+C, B+C, A+B+C). This does the search properly.

METHOD
  1. Run N distinct sleeves ONCE each on DISCOVERY (2012-2021, effectively 2013-01-01
     onward after the engine's 365d warmup), net of each sleeve's own trading costs.
     Cache the daily net return series.
  2. Blend at the RETURN level -> thousands of allocations are almost free.
  3. Search: exhaustive fixed-weight 2/3/4-way grids (step 0.1), 1/N, inverse-vol,
     min-variance, and strategy-momentum (trailing 12m Sharpe). All adaptive schemes
     are strictly point-in-time (weights from data up to t-1, applied from t).
  4. HONESTY LAYER: the return-level blend assumes costless inter-sleeve rebalancing
     and ignores holding overlap. Both are measured and charged.
  5. Only the finalists touch HOLDOUT.

Stages:  py run_ensemble_search.py sleeves | search | holdout
"""
import sys
import io
import os
import time
import json
import pickle
import argparse
import itertools
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import logging
logging.basicConfig(level=logging.ERROR)
for _n in list(logging.root.manager.loggerDict):
    logging.getLogger(_n).setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from research_harness import (load_panels, evaluate, rolling_3y_min,
                              deflated_sharpe, SPLITS, CAP)
from run_momentum_lowvol import (make_mom_lowvol_scorer, make_lowvol_scorer,
                                 compute_realized_vol, VOL_LOOKBACK)
from run_pure_momentum import compute_12_1_momentum
from run_program2_breakout import make_breakout_scorer

RF = 0.065
BENCH_CAGR = 0.1363
RDIR = PROJECT_ROOT / "results" / "ensemble_search"
RDIR.mkdir(parents=True, exist_ok=True)

# Champion reference on DISCOVERY (reproduced exactly by this harness):
CHAMP = dict(cagr=0.2430, sharpe=1.117, maxdd=-0.3145, roll3y=0.0549)

# Round-trip cost of moving Rs.1 of capital from one sleeve to another, using the
# repo's own Indian delivery cost stack: sell side (STT 0.10% + exch 0.0035% + slip
# ~0.05-0.10%) + buy side (stamp 0.015% + exch + slip). ~0.35% round trip central.
RT_COST = {"low": 0.0020, "central": 0.0035, "high": 0.0060}


# ──────────────────────────────────────────────────────────────────────
# SLEEVE DEFINITIONS
# ──────────────────────────────────────────────────────────────────────
def make_momentum_scorer(lookback=252, skip=21):
    def scorer(close_panel, date, universe):
        m = compute_12_1_momentum(close_panel, date, universe,
                                  lookback=lookback, skip=skip)
        return m.sort_values(ascending=False) if not m.empty else pd.Series(dtype=float)
    return scorer


def sleeve_specs(vol_panel):
    """15 sleeves. Each is one backtest; its net daily returns are then reused."""
    mlv = make_mom_lowvol_scorer(0.5, VOL_LOOKBACK)
    return {
        # --- the reference ---
        "A_champ":   dict(scorer=mlv, n=10, freq="monthly",   band=(0, 500),
                          desc="Mom+LowVol Top-10 monthly Liq500 (CHAMPION)"),
        # --- champion shell variations (frequency / concentration) ---
        "A_qtr":     dict(scorer=mlv, n=10, freq="quarterly", band=(0, 500),
                          desc="Mom+LowVol Top-10 quarterly Liq500"),
        "A_conc5":   dict(scorer=mlv, n=5,  freq="monthly",   band=(0, 500),
                          desc="Mom+LowVol Top-5 monthly Liq500 (concentrated)"),
        "A_div25":   dict(scorer=mlv, n=25, freq="monthly",   band=(0, 500),
                          desc="Mom+LowVol Top-25 monthly Liq500 (diversified)"),
        # --- pure factor legs ---
        "MOM10":     dict(scorer=make_momentum_scorer(), n=10, freq="monthly", band=(0, 500),
                          desc="Pure 12-1 momentum Top-10 monthly Liq500"),
        "MOM25":     dict(scorer=make_momentum_scorer(), n=25, freq="monthly", band=(0, 500),
                          desc="Pure 12-1 momentum Top-25 monthly Liq500"),
        "MOM6_1":    dict(scorer=make_momentum_scorer(126, 21), n=10, freq="monthly", band=(0, 500),
                          desc="6-1 momentum Top-10 monthly Liq500"),
        "LOWVOL":    dict(scorer=make_lowvol_scorer(VOL_LOOKBACK), n=10, freq="monthly", band=(0, 500),
                          desc="Low-vol only Top-10 monthly Liq500"),
        # --- breakout / 52-week high family ---
        "BO_M":      dict(scorer=make_breakout_scorer(vol_panel, True), n=10, freq="monthly", band=(0, 500),
                          desc="Breakout (vol-confirmed) Top-10 monthly Liq500"),
        "BO_Q":      dict(scorer=make_breakout_scorer(vol_panel, True), n=10, freq="quarterly", band=(0, 500),
                          desc="Breakout (vol-confirmed) Top-10 quarterly Liq500"),
        "BO_NV":     dict(scorer=make_breakout_scorer(vol_panel, False), n=10, freq="monthly", band=(0, 500),
                          desc="52wk-high proximity (no vol filter) Top-10 monthly Liq500"),
        # --- universe tilts ---
        "SMALL_Q":   dict(scorer=mlv, n=10, freq="quarterly", band=(300, 1000),
                          desc="Mom+LowVol Top-10 quarterly SmallTail 300-1000"),
        "SMALL_M":   dict(scorer=mlv, n=10, freq="monthly",   band=(250, 750),
                          desc="Mom+LowVol Top-10 monthly SmallTail 250-750"),
        "LARGE":     dict(scorer=mlv, n=10, freq="monthly",   band=(0, 100),
                          desc="Mom+LowVol Top-10 monthly Large-liquid 0-100"),
        "MID":       dict(scorer=mlv, n=10, freq="monthly",   band=(100, 500),
                          desc="Mom+LowVol Top-10 monthly Mid 100-500"),
    }


# ──────────────────────────────────────────────────────────────────────
# STAGE 1 - run the sleeves
# ──────────────────────────────────────────────────────────────────────
def evaluate_keep_trades(scorer, close, high, low, vol, turn, *, split, n_stocks,
                         rebalance, buffer, rank_band, label):
    """Same engine/slicing as research_harness.evaluate, but keeps the trade log
    (needed for the holding-overlap honesty check)."""
    from config import SystemConfig
    from run_program2_smallcap_validation import run_impact_aware_backtest
    from run_smallcap_universe import RankBandUniverseBuilder
    from analytics.metrics import compute_metrics
    from data.benchmark import get_benchmark_returns
    s, e = SPLITS[split]
    c, h, l, v, t = [p.loc[s:e] for p in (close, high, low, vol, turn)]
    cfg = SystemConfig()
    ub = RankBandUniverseBuilder(c, h, l, v, t, cfg.universe, rank_band[0], rank_band[1])
    res = run_impact_aware_backtest(c, h, l, v, t, n_stocks=n_stocks,
                                    rebalance_freq=rebalance, buffer=buffer,
                                    initial_capital=CAP, config=cfg, scorer=scorer,
                                    universe_builder=ub, label=label)
    m = compute_metrics(res["equity_curve"], res["returns"],
                        benchmark_returns=get_benchmark_returns(s, e),
                        trades=res["trades"], total_costs=res["total_costs"],
                        initial_capital=CAP)
    return {"returns": res["returns"], "trades": res["trades"],
            "cagr": m.cagr, "sharpe": m.sharpe_ratio, "maxdd": m.max_drawdown,
            "costs": res["total_costs"], "avg_turnover": res.get("avg_turnover")}


def run_sleeves(split):
    close, high, low, vol, turn = load_panels()
    specs = sleeve_specs(vol)
    out = {}
    for i, (k, s) in enumerate(specs.items(), 1):
        t0 = time.time()
        print(f"  [{i:2d}/{len(specs)}] {k:<9} {s['desc']}", flush=True)
        m = evaluate_keep_trades(s["scorer"], close, high, low, vol, turn, split=split,
                                 n_stocks=s["n"], rebalance=s["freq"], buffer=20,
                                 rank_band=s["band"], label=k)
        out[k] = {"returns": m["returns"], "cagr": m["cagr"], "sharpe": m["sharpe"],
                  "maxdd": m["maxdd"], "roll3y": rolling_3y_min(m["returns"]),
                  "trades": m.get("trades"), "desc": s["desc"],
                  "avg_turnover": m.get("avg_turnover"),
                  "n": s["n"], "freq": s["freq"], "band": s["band"]}
        print(f"          CAGR {m['cagr']*100:6.2f}%  Sharpe {m['sharpe']:5.2f}  "
              f"DD {m['maxdd']*100:6.1f}%  ({time.time()-t0:.0f}s)", flush=True)
    return out


def sleeve_cache(split):
    return RDIR / f"sleeves_{split}.pkl"


def load_or_run(split, force=False):
    f = sleeve_cache(split)
    if f.exists() and not force:
        with open(f, "rb") as fh:
            return pickle.load(fh)
    print(f"\nRunning sleeves on split={split} ...")
    d = run_sleeves(split)
    with open(f, "wb") as fh:
        pickle.dump(d, fh)
    return d


# ──────────────────────────────────────────────────────────────────────
# VECTORISED BLEND METRICS  (matches analytics.metrics definitions)
# ──────────────────────────────────────────────────────────────────────
def metrics_matrix(R, n_years):
    """R: (k, T) daily returns. Returns cagr, sharpe, maxdd, roll3y_min arrays."""
    eq = np.cumprod(1.0 + R, axis=1)
    final = eq[:, -1]
    cagr = np.power(np.maximum(final, 1e-12), 1.0 / n_years) - 1.0
    vol = R.std(axis=1, ddof=1) * np.sqrt(252.0)
    sharpe = np.where(vol > 0, (cagr - RF) / np.maximum(vol, 1e-12), 0.0)
    cm = np.maximum.accumulate(eq, axis=1)
    maxdd = ((eq - cm) / cm).min(axis=1)
    if eq.shape[1] > 756:
        r3 = np.power(eq[:, 756:] / eq[:, :-756], 1.0 / 3.0) - 1.0
        roll3 = r3.min(axis=1)
    else:
        roll3 = np.full(R.shape[0], np.nan)
    return cagr, sharpe, maxdd, roll3


def metrics_one(r, n_years=None):
    r = np.asarray(r, dtype=float)
    if n_years is None:
        n_years = len(r) / 252.0
    c, s, d, r3 = metrics_matrix(r.reshape(1, -1), n_years)
    return dict(cagr=float(c[0]), sharpe=float(s[0]), maxdd=float(d[0]),
                roll3y=float(r3[0]))


def weight_compositions(k, step=10):
    """All non-negative integer weights over k sleeves summing to `step`, each >0."""
    if k == 1:
        return [(step,)]
    out = []
    for c in itertools.combinations(range(1, step), k - 1):
        prev, w = 0, []
        for x in c:
            w.append(x - prev)
            prev = x
        w.append(step - prev)
        out.append(tuple(w))
    return out


# ──────────────────────────────────────────────────────────────────────
# ADAPTIVE (POINT-IN-TIME) ALLOCATION SCHEMES
# ──────────────────────────────────────────────────────────────────────
def pit_weights(S, dates, scheme, lookback, min_hist, rebal_freq="M"):
    """
    S: (T, k) sleeve daily returns. Returns (T, k) weight matrix applied to day t,
    built ONLY from data strictly before t. Weights are refreshed at month ends.
    """
    T, k = S.shape
    W = np.full((T, k), np.nan)
    df = pd.DataFrame(S, index=dates)
    # month-end decision points
    marks = pd.Series(1, index=dates).resample(rebal_freq).last().index
    dec_idx = []
    for mk in marks:
        loc = dates.searchsorted(mk, side="right") - 1
        if 0 <= loc < T:
            dec_idx.append(loc)
    dec_idx = sorted(set(dec_idx))
    cur = np.full(k, 1.0 / k)
    ptr = 0
    for t in range(T):
        while ptr < len(dec_idx) and dec_idx[ptr] < t:
            i = dec_idx[ptr]
            hist = S[max(0, i + 1 - lookback):i + 1]        # strictly <= day i
            if len(hist) >= min_hist:
                cur = _solve_weights(hist, scheme, k)
            ptr += 1
        W[t] = cur
    return W


def _solve_weights(hist, scheme, k):
    if scheme == "invvol":
        v = hist.std(axis=0, ddof=1)
        v = np.where(v > 1e-9, v, np.nan)
        w = 1.0 / v
        if np.all(np.isnan(w)):
            return np.full(k, 1.0 / k)
        w = np.nan_to_num(w, nan=0.0)
        return w / w.sum()
    if scheme == "minvar":
        C = np.cov(hist.T)
        C = C + np.eye(k) * 1e-8
        from scipy.optimize import minimize
        w0 = np.full(k, 1.0 / k)
        res = minimize(lambda w: w @ C @ w, w0, method="SLSQP",
                       bounds=[(0.0, 1.0)] * k,
                       constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
                       options={"maxiter": 200, "ftol": 1e-12})
        w = np.clip(res.x, 0, None)
        return w / w.sum() if w.sum() > 0 else np.full(k, 1.0 / k)
    if scheme in ("sharpemom", "retmom"):
        if scheme == "sharpemom":
            mu = hist.mean(axis=0) * 252.0
            sd = hist.std(axis=0, ddof=1) * np.sqrt(252.0)
            score = np.where(sd > 1e-9, (mu - RF) / np.maximum(sd, 1e-9), -9.0)
        else:
            score = np.prod(1.0 + hist, axis=0) - 1.0
        # long-only: top-half equal weight (robust, no negative weights)
        m = max(1, k // 3)
        idx = np.argsort(-score)[:m]
        w = np.zeros(k)
        w[idx] = 1.0 / m
        return w
    raise ValueError(scheme)


# ──────────────────────────────────────────────────────────────────────
# OVERLAP + INTER-SLEEVE REBALANCING COST
# ──────────────────────────────────────────────────────────────────────
def holdings_timeline(trades, dates):
    """Reconstruct set of held symbols after each rebalance from the trade log."""
    if not trades:
        return {}
    h = {}
    snaps = {}
    for tr in sorted(trades, key=lambda x: x["date"]):
        s, side, sh = tr["symbol"], tr["side"], tr["shares"]
        h[s] = h.get(s, 0) + (sh if side == "BUY" else -sh)
        if h[s] <= 0:
            h.pop(s, None)
        snaps[tr["date"]] = set(h.keys())
    return snaps


def overlap_matrix(sleeves, keys):
    """Average fraction of one sleeve's names also held by the other, month-ends."""
    idx = pd.DatetimeIndex(sorted(set().union(
        *[set(holdings_timeline(sleeves[k]["trades"], None).keys()) for k in keys])))
    series = {}
    for k in keys:
        snaps = holdings_timeline(sleeves[k]["trades"], None)
        sd = pd.Series({pd.Timestamp(d): v for d, v in snaps.items()}).sort_index()
        series[k] = sd.reindex(idx, method="ffill")
    M = pd.DataFrame(np.nan, index=keys, columns=keys, dtype=float)
    for a in keys:
        for b in keys:
            vals = []
            for d in idx:
                sa, sb = series[a].get(d), series[b].get(d)
                if isinstance(sa, set) and isinstance(sb, set) and sa and sb:
                    vals.append(len(sa & sb) / len(sa))
            M.loc[a, b] = np.mean(vals) if vals else np.nan
    return M


def rebal_cost_drag(S, w, rt_cost, dates, freq="M"):
    """
    Cost of holding a FIXED-weight sleeve blend: weights drift with relative
    performance, and are snapped back at each month end. Turnover at each snap =
    0.5 * sum|w_drifted - w_target| ; charged at `rt_cost` round trip.
    Returns (annual drag, avg annual two-way turnover between sleeves).
    """
    T = S.shape[0]
    marks = pd.Series(1, index=dates).resample(freq).last().index
    dec = sorted({min(T - 1, max(0, dates.searchsorted(m, side="right") - 1))
                  for m in marks})
    cur = np.array(w, dtype=float)
    tot_to = 0.0
    prev = 0
    for i in dec:
        if i <= prev:
            continue
        grow = np.prod(1.0 + S[prev + 1:i + 1], axis=0)
        drifted = cur * grow
        drifted = drifted / drifted.sum() if drifted.sum() > 0 else cur
        tot_to += 0.5 * np.abs(drifted - np.array(w)).sum()
        cur = np.array(w, dtype=float)
        prev = i
    years = T / 252.0
    ann_to = tot_to / years
    return ann_to * rt_cost, ann_to


def dynamic_rebal_turnover(W, S, dates):
    """Annual two-way turnover of an adaptive (time-varying-weight) scheme."""
    T = W.shape[0]
    changes = np.abs(np.diff(W, axis=0)).sum(axis=1) * 0.5
    return changes.sum() / (T / 252.0)


# ──────────────────────────────────────────────────────────────────────
# MAIN SEARCH
# ──────────────────────────────────────────────────────────────────────
def run_search():
    sleeves = load_or_run("discovery")
    keys = list(sleeves.keys())

    # align
    idx = None
    for k in keys:
        i = sleeves[k]["returns"].index
        idx = i if idx is None else idx.intersection(i)
    idx = pd.DatetimeIndex(sorted(idx))
    S = np.column_stack([sleeves[k]["returns"].reindex(idx).fillna(0).values for k in keys])
    T, K = S.shape
    n_years = (idx[-1] - idx[0]).days / 365.25
    print(f"\nAligned: {T} days x {K} sleeves  ({idx[0].date()} .. {idx[-1].date()}, "
          f"{n_years:.2f}y)")

    # ---- sleeve table ----
    rows = []
    for j, k in enumerate(keys):
        m = metrics_one(S[:, j], n_years)
        rows.append(dict(sleeve=k, desc=sleeves[k]["desc"], **m))
    sl = pd.DataFrame(rows).sort_values("cagr", ascending=False)
    print("\n" + "=" * 104)
    print("SLEEVE TABLE - DISCOVERY (net of each sleeve's own costs)".center(104))
    print("=" * 104)
    print(f"{'sleeve':<10}{'CAGR':>8}{'Sharpe':>8}{'MaxDD':>9}{'roll3y':>9}  description")
    for _, r in sl.iterrows():
        print(f"{r['sleeve']:<10}{r['cagr']*100:7.2f}%{r['sharpe']:8.2f}"
              f"{r['maxdd']*100:8.1f}%{r['roll3y']*100:8.1f}%  {r['desc']}")
    sl.to_csv(RDIR / "sleeve_table_discovery.csv", index=False)

    # ---- correlation ----
    C = pd.DataFrame(np.corrcoef(S.T), index=keys, columns=keys)
    C.to_csv(RDIR / "sleeve_correlation.csv")
    print("\n" + "=" * 104)
    print("SLEEVE DAILY-RETURN CORRELATION (DISCOVERY)".center(104))
    print("=" * 104)
    print("        " + "".join(f"{k[:7]:>8}" for k in keys))
    for a in keys:
        print(f"{a[:7]:<8}" + "".join(f"{C.loc[a,b]:8.2f}" for b in keys))
    off = C.values[np.triu_indices(K, 1)]
    print(f"\n  mean off-diagonal corr {off.mean():.3f}   min {off.min():.3f}   "
          f"max {off.max():.3f}")

    # ---- exhaustive fixed-weight grids ----
    results = []
    n_combos = 0
    t0 = time.time()
    for order in (2, 3, 4):
        comps = weight_compositions(order, 10)
        combos = list(itertools.combinations(range(K), order))
        print(f"\n  {order}-way: {len(combos):,} subsets x {len(comps)} weight "
              f"splits = {len(combos)*len(comps):,} allocations")
        Wl, Ll = [], []
        for cb in combos:
            for cp in comps:
                w = np.zeros(K)
                for p, q in zip(cb, cp):
                    w[p] = q / 10.0
                Wl.append(w)
                Ll.append((order, cb, cp))
        Wm = np.array(Wl)
        n_combos += len(Wm)
        CH = 4000
        for s in range(0, len(Wm), CH):
            blk = Wm[s:s + CH]
            R = blk @ S.T
            c, sh, dd, r3 = metrics_matrix(R, n_years)
            for i in range(len(blk)):
                o, cb, cp = Ll[s + i]
                results.append((o, "+".join(f"{keys[p]}:{q/10:.1f}"
                                            for p, q in zip(cb, cp)),
                                c[i], sh[i], dd[i], r3[i], tuple(blk[i])))
    print(f"  grid evaluated in {time.time()-t0:.0f}s")

    res = pd.DataFrame(results, columns=["order", "alloc", "cagr", "sharpe",
                                         "maxdd", "roll3y", "w"])

    # ---- named schemes ----
    named = []

    def add_named(name, r, w_series=None, turn=None):
        m = metrics_one(r, n_years)
        m["alloc"] = name
        m["ann_sleeve_turnover"] = turn
        named.append(m)

    eqw = np.full(K, 1.0 / K)
    add_named("1/N all 15 sleeves", S @ eqw,
              turn=rebal_cost_drag(S, eqw, 1.0, idx)[1])
    # 1/N over a de-duplicated "one per family" set
    fam = ["A_champ", "MOM10", "LOWVOL", "BO_M", "SMALL_Q", "LARGE"]
    fi = [keys.index(k) for k in fam]
    wf = np.zeros(K); wf[fi] = 1.0 / len(fi)
    add_named("1/N 6 distinct families", S @ wf,
              turn=rebal_cost_drag(S, wf, 1.0, idx)[1])
    # the Program-2 hand-picked blends, for continuity
    for nm, ws in [("A+C 50/50 (prog2)", {"A_champ": .5, "BO_M": .5}),
                   ("A+B 50/50 (prog2)", {"A_champ": .5, "SMALL_Q": .5}),
                   ("B+C 50/50 (prog2)", {"SMALL_Q": .5, "BO_M": .5}),
                   ("A+B+C 1/3 (prog2)", {"A_champ": 1/3, "SMALL_Q": 1/3, "BO_M": 1/3})]:
        w = np.zeros(K)
        for k, v in ws.items():
            w[keys.index(k)] = v
        add_named(nm, S @ w, turn=rebal_cost_drag(S, w, 1.0, idx)[1])

    for scheme, lb, mh, tag in [("invvol", 60, 60, "inverse-vol 60d"),
                                ("invvol", 252, 252, "inverse-vol 252d"),
                                ("minvar", 252, 252, "min-variance 252d roll"),
                                ("minvar", 10**6, 252, "min-variance expanding"),
                                ("sharpemom", 252, 252, "top-5 by trailing 12m Sharpe"),
                                ("retmom", 252, 252, "top-5 by trailing 12m return")]:
        W = pit_weights(S, idx, scheme, lb, mh)
        r = (W * S).sum(axis=1)
        add_named(f"PIT {tag} (all 15)", r, turn=dynamic_rebal_turnover(W, S, idx))

    nm = pd.DataFrame(named)
    nm.to_csv(RDIR / "named_schemes_discovery.csv", index=False)

    # ---- report best ----
    print("\n" + "=" * 104)
    print(f"EXHAUSTIVE FIXED-WEIGHT GRID - {n_combos:,} allocations".center(104))
    print("=" * 104)
    for metric, lab in (("cagr", "CAGR"), ("sharpe", "Sharpe"), ("roll3y", "roll-3y-min")):
        print(f"\n  TOP 8 BY {lab}")
        top = res.sort_values(metric, ascending=False).head(8)
        for _, r in top.iterrows():
            print(f"    {r['alloc']:<52} CAGR {r['cagr']*100:6.2f}%  "
                  f"Sh {r['sharpe']:5.2f}  DD {r['maxdd']*100:6.1f}%  "
                  f"r3y {r['roll3y']*100:6.1f}%")
    # best that also beats champion on all 4 dimensions
    dom = res[(res.cagr > CHAMP["cagr"]) & (res.sharpe > CHAMP["sharpe"]) &
              (res.maxdd > CHAMP["maxdd"]) & (res.roll3y > CHAMP["roll3y"])]
    print(f"\n  allocations dominating the champion on ALL FOUR metrics: {len(dom):,}"
          f"  ({100*len(dom)/max(1,len(res)):.2f}% of grid)")
    if len(dom):
        for _, r in dom.sort_values("cagr", ascending=False).head(10).iterrows():
            print(f"    {r['alloc']:<52} CAGR {r['cagr']*100:6.2f}%  "
                  f"Sh {r['sharpe']:5.2f}  DD {r['maxdd']*100:6.1f}%  "
                  f"r3y {r['roll3y']*100:6.1f}%")

    print("\n" + "=" * 104)
    print("NAMED / ADAPTIVE ALLOCATION SCHEMES".center(104))
    print("=" * 104)
    print(f"{'scheme':<38}{'CAGR':>8}{'Sharpe':>8}{'MaxDD':>9}{'roll3y':>9}{'slv-turn':>10}")
    for _, r in nm.sort_values("cagr", ascending=False).iterrows():
        tt = f"{r['ann_sleeve_turnover']*100:8.0f}%" if pd.notna(r['ann_sleeve_turnover']) else "       -"
        print(f"{r['alloc']:<38}{r['cagr']*100:7.2f}%{r['sharpe']:8.2f}"
              f"{r['maxdd']*100:8.1f}%{r['roll3y']*100:8.1f}%{tt:>10}")

    # ---- honesty layer: inter-sleeve rebalancing cost on the top allocations ----
    print("\n" + "=" * 104)
    print("HONESTY LAYER 1 - INTER-SLEEVE REBALANCING COST".center(104))
    print("=" * 104)
    cand = pd.concat([res.sort_values("cagr", ascending=False).head(5),
                      res.sort_values("sharpe", ascending=False).head(5),
                      res.sort_values("roll3y", ascending=False).head(3)]
                     ).drop_duplicates("alloc")
    print(f"{'allocation':<52}{'gross':>8}{'turn/yr':>9}{'-0.20%':>9}{'-0.35%':>9}{'-0.60%':>9}")
    adj_rows = []
    for _, r in cand.iterrows():
        w = np.array(r["w"])
        _, to = rebal_cost_drag(S, w, 1.0, idx)
        line = f"{r['alloc']:<52}{r['cagr']*100:7.2f}%{to*100:8.0f}%"
        adj = {}
        for tag, c in RT_COST.items():
            adj[tag] = r["cagr"] - to * c
            line += f"{adj[tag]*100:8.2f}%"
        print(line)
        adj_rows.append(dict(alloc=r["alloc"], cagr=r["cagr"], turnover=to, **adj,
                             sharpe=r["sharpe"], maxdd=r["maxdd"], roll3y=r["roll3y"],
                             w=list(w)))
    pd.DataFrame(adj_rows).to_csv(RDIR / "cost_adjusted_candidates.csv", index=False)

    # ---- honesty layer 2: holding overlap ----
    print("\n" + "=" * 104)
    print("HONESTY LAYER 2 - HOLDING OVERLAP BETWEEN SLEEVES".center(104))
    print("=" * 104)
    ov = overlap_matrix(sleeves, keys)
    ov.to_csv(RDIR / "sleeve_overlap.csv")
    print("        " + "".join(f"{k[:7]:>8}" for k in keys))
    for a in keys:
        print(f"{a[:7]:<8}" + "".join(
            f"{ov.loc[a,b]*100:7.0f}%" if pd.notna(ov.loc[a, b]) else "       -"
            for b in keys))

    with open(RDIR / "search_meta.json", "w") as fh:
        json.dump({"n_grid_allocations": int(n_combos),
                   "n_named_schemes": int(len(nm)),
                   "n_sleeve_backtests": int(K),
                   "total_evaluations": int(n_combos + len(nm) + K),
                   "n_days": int(T), "n_years": float(n_years),
                   "mean_corr": float(off.mean())}, fh, indent=2)
    res.drop(columns=["w"]).to_parquet(RDIR / "grid_results_discovery.parquet")

    e_max, _ = deflated_sharpe(res.sharpe.max(), n_combos + len(nm), T)
    print(f"\n  DEFLATED-SHARPE NULL: with {n_combos+len(nm):,} trials over {T} days, "
          f"expected max Sharpe of a ZERO-EDGE search = {e_max:.2f}")
    print(f"  best grid Sharpe {res.sharpe.max():.2f}  ->  "
          f"{'CLEARS' if res.sharpe.max() > e_max else 'DOES NOT CLEAR'} the null")
    return res, nm, sl, C, ov, n_combos


# ──────────────────────────────────────────────────────────────────────
# HOLDOUT - finalists only
# ──────────────────────────────────────────────────────────────────────
FINALISTS_FILE = RDIR / "finalists.json"


def run_holdout():
    with open(FINALISTS_FILE) as fh:
        fin = json.load(fh)
    need = sorted({k for f in fin for k in f["weights"]})
    print(f"Finalists need sleeves: {need}")
    sleeves = load_or_run("holdout")
    idx = None
    for k in need:
        i = sleeves[k]["returns"].index
        idx = i if idx is None else idx.intersection(i)
    idx = pd.DatetimeIndex(sorted(idx))
    n_years = (idx[-1] - idx[0]).days / 365.25
    print(f"\nHOLDOUT {idx[0].date()} .. {idx[-1].date()}  ({n_years:.2f}y, {len(idx)} days)")
    print("\n" + "=" * 104)
    print(f"{'allocation':<46}{'CAGR':>8}{'Sharpe':>8}{'MaxDD':>9}{'turn/yr':>9}{'net@0.35%':>11}")
    out = []
    for f in fin:
        w = np.zeros(len(need))
        for k, v in f["weights"].items():
            w[need.index(k)] = v
        S = np.column_stack([sleeves[k]["returns"].reindex(idx).fillna(0).values
                             for k in need])
        r = S @ w
        m = metrics_one(r, n_years)
        _, to = rebal_cost_drag(S, w, 1.0, idx)
        net = m["cagr"] - to * RT_COST["central"]
        print(f"{f['name']:<46}{m['cagr']*100:7.2f}%{m['sharpe']:8.2f}"
              f"{m['maxdd']*100:8.1f}%{to*100:8.0f}%{net*100:10.2f}%")
        out.append(dict(name=f["name"], **m, turnover=to, net_cagr=net))
    pd.DataFrame(out).to_csv(RDIR / "holdout_finalists.csv", index=False)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["sleeves", "search", "holdout"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.stage == "sleeves":
        load_or_run("discovery", force=a.force)
    elif a.stage == "search":
        run_search()
    else:
        run_holdout()
