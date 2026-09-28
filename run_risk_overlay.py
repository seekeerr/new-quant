"""
RESEARCH: PORTFOLIO CONSTRUCTION, POSITION SIZING AND RISK OVERLAYS.

Goal: take the frozen champion ALPHA (Mom+LowVol 50/50, `champion_scorer()`) as given
and try to PACKAGE it better.  No new signal is invented anywhere in this file.

Split discipline (research_harness.py):
    DISCOVERY 2012-01-01..2021-12-31   <- all searching happens here
    HOLDOUT   2022-01-01..2026-05-30   <- touched once, by the finalists only

Baseline (champion, monthly / Top-10 / buffer 20 / rank-band 0-500 / Rs 10L):
    DISCOVERY CAGR 24.30%  Sharpe 1.12  MaxDD -31.4%  roll-3y-min 5.5%

What is swept (each needs a fresh ~50s backtest):
    A  concentration      n_stocks 3..30
    B  buffer x frequency monthly/quarterly x buffer 0..40
    C  universe geometry  rank_band frontier
    D  interactions       best band x n x (freq,buffer)
    E  position sizing    equal / inverse-vol / capped inverse-vol / rank-conviction
                          (custom engine, real costs on the weight differences)
    F  capital ladder     Rs 1L .. Rs 10cr on the best config
    G  in-engine overlays vol-target and drawdown-throttle applied AT REBALANCE with
                          real transaction costs on the exposure change

What is nearly free (applied to a stored daily return series):
    post-hoc overlays  - vol targeting, drawdown throttle, regime (NIFTY500 200DMA).
    These IGNORE the transaction cost of changing exposure, so anything promising is
    re-run through stage G inside the engine before it is believed.

Usage:  py run_risk_overlay.py <stage>      stage in a,b,c,d,e,f,g,overlay,holdout,report
"""
import sys
import io
import os
import json
import time
import hashlib
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
os.environ.setdefault("TQDM_DISABLE", "1")

import numpy as np
import pandas as pd

RDIR = PROJECT_ROOT / "results" / "risk_overlay"
CURVES = RDIR / "curves"
RDIR.mkdir(parents=True, exist_ok=True)
CURVES.mkdir(parents=True, exist_ok=True)
ROWS_CSV = RDIR / "all_runs.csv"

CAP = 1_000_000.0
N_WORKERS = 5


# ──────────────────────────────────────────────────────────────────────────
#  Custom engine: run_impact_aware_backtest + (weight_fn, exposure_fn)
#  Identical mechanics otherwise; equal weight + exposure 1.0 reproduces it.
# ──────────────────────────────────────────────────────────────────────────
def run_sized_backtest(close, high, low, volume, turnover, *, n_stocks, rebalance_freq,
                       buffer, initial_capital, config, scorer, universe_builder,
                       weight_scheme="equal", vol_lookback=60, weight_cap=None,
                       target_vol=None, dd_throttle=None, exposure_vol_window=60,
                       label=""):
    """
    weight_scheme : 'equal' | 'invvol' | 'rank'
    weight_cap    : max weight per name as a multiple of 1/n (None = uncapped)
    target_vol    : annualised vol target; exposure = min(1, tv / trailing port vol)
                    computed from the strategy's OWN equity curve up to t-1 ONLY.
    dd_throttle   : (threshold, exposure) e.g. (0.15, 0.5) -> when the equity curve is
                    >15% below its running peak (as of t-1), deploy only 50%.
    Un-invested capital sits in cash at 0% (conservative).
    """
    from tqdm import tqdm
    from costs.cost_model import CostModel
    from utils.helpers import get_rebalance_dates

    cfg = config
    start = pd.Timestamp(cfg.backtest.start_date)
    end = pd.Timestamp(cfg.backtest.end_date)
    start = max(start, close.index.min() + pd.Timedelta(days=365))
    end = min(end, close.index.max())
    all_dates = close.index[(close.index >= start) & (close.index <= end)]
    if all_dates.empty:
        return {"equity_curve": pd.Series(dtype=float), "returns": pd.Series(dtype=float)}

    from run_buffer_experiment import select_with_buffer
    rebal_set = set(get_rebalance_dates(all_dates, rebalance_freq))
    valuation = close.ffill()
    cost_model = CostModel(cfg.costs)
    lookback = cfg.universe.turnover_lookback
    daily_ret_panel = close.pct_change()

    cash = initial_capital
    holdings = {}
    equity_values, trades_history = [], []
    total_costs = total_rebalances = 0.0
    total_turnover = 0.0
    exposures = []

    def adtv_at(date):
        m = turnover.index <= date
        return turnover.loc[m].tail(lookback).mean()

    for date in tqdm(all_dates, desc=f"[sized] {label}", unit="day", disable=True):
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

        # ---- exposure (uses ONLY equity history strictly before today) ----
        exposure = 1.0
        hist = pd.Series([e["portfolio_value"] for e in equity_values[:-1]],
                         index=[e["date"] for e in equity_values[:-1]])
        if target_vol is not None and len(hist) > exposure_vol_window + 5:
            rv = hist.pct_change().tail(exposure_vol_window).std() * np.sqrt(252)
            if rv and rv > 0:
                exposure = min(1.0, float(target_vol) / float(rv))
        if dd_throttle is not None and len(hist) > 20:
            thr, ex_dd = dd_throttle
            dd = hist.iloc[-1] / hist.cummax().iloc[-1] - 1.0
            if dd < -abs(thr):
                exposure = min(exposure, ex_dd)
        exposures.append({"date": date, "exposure": exposure})

        # ---- weights ----
        w = pd.Series(1.0 / len(selected), index=selected)
        if weight_scheme == "invvol":
            r = daily_ret_panel.loc[daily_ret_panel.index <= date].tail(vol_lookback)
            sd = r[[s for s in selected if s in r.columns]].std()
            sd = sd.replace(0, np.nan).reindex(selected)
            iv = 1.0 / sd
            iv = iv.fillna(iv.median() if iv.notna().any() else 1.0)
            w = iv / iv.sum()
        elif weight_scheme == "rank":
            k = np.arange(1, len(selected) + 1, dtype=float)   # 1 = best
            raw = 1.0 / k
            w = pd.Series(raw / raw.sum(), index=selected)
        if weight_cap is not None:
            cap = weight_cap / len(selected)
            for _ in range(20):
                if (w > cap + 1e-12).sum() == 0:
                    break
                over = w > cap
                excess = float((w[over] - cap).sum())
                w[over] = cap
                room = ~over
                if room.sum() == 0:
                    break
                w[room] = w[room] + excess * (w[room] / w[room].sum())
            w = w / w.sum()

        deploy = pv * exposure
        adtv = adtv_at(date)
        target_shares = {}
        for s in selected:
            p = today_close.get(s, np.nan)
            if np.isnan(p) or p <= 0:
                continue
            sh = int(deploy * float(w.get(s, 0.0)) / p)
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
                del holdings[s]
                continue
            sv = sq * p
            tier = universe.liquidity_tiers.get(s, 2)
            tc = cost_model.calculate_trade_cost(s, "SELL", sq, p, liquidity_tier=tier,
                                                 avg_daily_value=float(adtv.get(s, 0) or 0))
            cash += sv - tc.total_cost
            total_costs += tc.total_cost
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
            tc = cost_model.calculate_trade_cost(s, "BUY", bq, p, liquidity_tier=tier,
                                                 avg_daily_value=adv)
            bv = bq * p
            total = bv + tc.total_cost
            if total > cash:
                aff = int((cash - tc.total_cost) / p) if p > 0 else 0
                if aff <= 0:
                    continue
                bq = aff
                bv = bq * p
                tc = cost_model.calculate_trade_cost(s, "BUY", bq, p, liquidity_tier=tier,
                                                     avg_daily_value=adv)
                total = bv + tc.total_cost
            cash -= total
            total_costs += tc.total_cost
            buys_value += bv
            holdings[s] = holdings.get(s, 0) + bq
            trades_history.append({"date": date, "symbol": s, "side": "BUY", "shares": bq,
                                   "price": p, "value": bv, "cost": tc.total_cost})
        if pv > 0:
            total_turnover += max(sells_value, buys_value) / pv

    eq = pd.DataFrame(equity_values).set_index("date")["portfolio_value"]
    return {"equity_curve": eq, "returns": eq.pct_change().fillna(0),
            "trades": trades_history, "total_costs": total_costs,
            "total_rebalances": total_rebalances,
            "avg_exposure": float(np.mean([e["exposure"] for e in exposures])) if exposures else 1.0,
            "avg_turnover": total_turnover / total_rebalances if total_rebalances else 0}


# ──────────────────────────────────────────────────────────────────────────
#  Job plumbing (multiprocess, disk-cached)
# ──────────────────────────────────────────────────────────────────────────
_PANELS = None


def _panels():
    global _PANELS
    if _PANELS is None:
        from research_harness import load_panels
        _PANELS = load_panels()
    return _PANELS


def job_key(job):
    j = {k: v for k, v in sorted(job.items()) if k != "label"}
    return hashlib.md5(json.dumps(j, default=str).encode()).hexdigest()[:12]


def run_job(job):
    """Run one backtest (or return the cached result)."""
    key = job_key(job)
    meta_p = CURVES / f"{key}.json"
    ret_p = CURVES / f"{key}.parquet"
    if meta_p.exists() and ret_p.exists():
        meta = json.loads(meta_p.read_text())
        meta["cached"] = True
        return meta
    t0 = time.time()
    import run_program2_smallcap_validation as _p2
    _p2.tqdm = lambda x, **k: x            # silence per-day progress bars in workers
    from config import SystemConfig
    from research_harness import (champion_scorer, SPLITS, rolling_3y_min)
    from run_smallcap_universe import RankBandUniverseBuilder
    from run_program2_smallcap_validation import run_impact_aware_backtest
    from analytics.metrics import compute_metrics
    from data.benchmark import get_benchmark_returns

    close, high, low, vol, turn = _panels()
    s, e = SPLITS[job["split"]]
    c, h, l, v, t = [p.loc[s:e] for p in (close, high, low, vol, turn)]
    cfg = SystemConfig()
    band = job.get("rank_band", (0, 500))
    ub = RankBandUniverseBuilder(c, h, l, v, t, cfg.universe, band[0], band[1])
    scorer = champion_scorer()
    common = dict(n_stocks=job["n_stocks"], rebalance_freq=job["rebalance"],
                  buffer=job["buffer"], initial_capital=job.get("capital", CAP),
                  config=cfg, scorer=scorer, universe_builder=ub,
                  label=job.get("label", key))
    if job.get("engine", "base") == "base":
        res = run_impact_aware_backtest(c, h, l, v, t, **common)
    else:
        res = run_sized_backtest(
            c, h, l, v, t,
            weight_scheme=job.get("weight_scheme", "equal"),
            weight_cap=job.get("weight_cap"),
            target_vol=job.get("target_vol"),
            dd_throttle=tuple(job["dd_throttle"]) if job.get("dd_throttle") else None,
            **common)
    br = get_benchmark_returns(s, e)
    m = compute_metrics(res["equity_curve"], res["returns"], benchmark_returns=br,
                        trades=res["trades"], total_costs=res["total_costs"],
                        initial_capital=job.get("capital", CAP))
    rr = res["returns"]
    meta = {
        "key": key, "label": job.get("label", key), "split": job["split"],
        "n_stocks": job["n_stocks"], "rebalance": job["rebalance"],
        "buffer": job["buffer"], "rank_band": str(job.get("rank_band", (0, 500))),
        "capital": job.get("capital", CAP), "engine": job.get("engine", "base"),
        "weight_scheme": job.get("weight_scheme", "equal"),
        "weight_cap": job.get("weight_cap"), "target_vol": job.get("target_vol"),
        "dd_throttle": str(job.get("dd_throttle")),
        "cagr": float(m.cagr), "sharpe": float(m.sharpe_ratio),
        "maxdd": float(m.max_drawdown),
        "calmar": float(m.cagr / abs(m.max_drawdown)) if m.max_drawdown else np.nan,
        "vol": float(rr.std() * np.sqrt(252)),
        "roll3y_min": float(rolling_3y_min(rr)),
        "n_trades": len(res["trades"]),
        "costs": float(res["total_costs"]),
        "avg_turnover": float(res.get("avg_turnover", np.nan)),
        "avg_exposure": float(res.get("avg_exposure", 1.0)),
        "final": float(res["equity_curve"].iloc[-1]),
        "secs": round(time.time() - t0, 1), "cached": False,
    }
    rr.to_frame("ret").to_parquet(ret_p)
    meta_p.write_text(json.dumps(meta, default=str))
    return meta


def load_returns(key):
    return pd.read_parquet(CURVES / f"{key}.parquet")["ret"]


def run_jobs(jobs, stage):
    from concurrent.futures import ProcessPoolExecutor
    todo = [j for j in jobs if not (CURVES / f"{job_key(j)}.json").exists()]
    done = [run_job(j) for j in jobs if (CURVES / f"{job_key(j)}.json").exists()]
    print(f"[{stage}] {len(jobs)} jobs, {len(done)} cached, {len(todo)} to run")
    rows = list(done)
    if todo:
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=min(N_WORKERS, len(todo))) as ex:
            for i, meta in enumerate(ex.map(run_job, todo), 1):
                rows.append(meta)
                print(f"   [{i}/{len(todo)}] {meta['label']:<34} "
                      f"CAGR {meta['cagr']*100:6.2f}%  Sh {meta['sharpe']:.2f}  "
                      f"DD {meta['maxdd']*100:6.1f}%  r3y {meta['roll3y_min']*100:5.1f}%",
                      flush=True)
        print(f"[{stage}] wall {time.time()-t0:.0f}s")
    df = pd.DataFrame(rows)
    df["stage"] = stage
    if ROWS_CSV.exists():
        old = pd.read_csv(ROWS_CSV)
        df = pd.concat([old[~old["key"].isin(df["key"])], df], ignore_index=True)
    df.to_csv(ROWS_CSV, index=False)
    return pd.DataFrame(rows)


def show(rows, sort="cagr"):
    d = pd.DataFrame(rows).sort_values(sort, ascending=False)
    cols = ["label", "cagr", "sharpe", "maxdd", "calmar", "roll3y_min",
            "avg_turnover", "n_trades", "avg_exposure"]
    d = d[[c for c in cols if c in d.columns]].copy()
    for c in ("cagr", "maxdd", "roll3y_min"):
        if c in d:
            d[c] = (d[c] * 100).round(2)
    for c in ("sharpe", "calmar", "avg_turnover", "avg_exposure"):
        if c in d:
            d[c] = d[c].round(3)
    print(d.to_string(index=False))
    return d


# ──────────────────────────────────────────────────────────────────────────
#  Post-hoc overlays on a stored daily return series  (nearly free)
# ──────────────────────────────────────────────────────────────────────────
def _ann(r):
    n = len(r)
    if n < 2:
        return np.nan
    return float((1 + r).prod() ** (252 / n) - 1)


def _mdd(r):
    eq = (1 + r).cumprod()
    return float((eq / eq.cummax() - 1).min())


def _sharpe(r):
    sd = r.std()
    return float(r.mean() / sd * np.sqrt(252)) if sd else np.nan


def stats(r, label, cash_yield=0.0, exposure=None):
    from research_harness import rolling_3y_min
    return {"label": label, "cagr": _ann(r), "sharpe": _sharpe(r), "maxdd": _mdd(r),
            "calmar": _ann(r) / abs(_mdd(r)) if _mdd(r) else np.nan,
            "vol": float(r.std() * np.sqrt(252)),
            "roll3y_min": float(rolling_3y_min(r)),
            "avg_exposure": float(np.mean(exposure)) if exposure is not None else 1.0,
            "cash_yield": cash_yield}


def _monthly_step(series):
    """Hold a daily value constant within a calendar month, using the value as of the
    LAST day of the PREVIOUS month (so it is known before the month starts)."""
    monthly = series.resample("M").last()
    return monthly.reindex(series.index, method="ffill")


def overlay_voltarget(r, target, window=60, monthly=True, cash_yield=0.0):
    rv = r.rolling(window).std().shift(1) * np.sqrt(252)      # shift(1): uses <= t-1
    ex = (target / rv).clip(upper=1.0)
    ex = _monthly_step(ex) if monthly else ex
    ex = ex.fillna(1.0).clip(0.0, 1.0)
    cash_r = (1 + cash_yield) ** (1 / 252) - 1
    return ex * r + (1 - ex) * cash_r, ex


def overlay_ddthrottle(r, thr, ex_dd, monthly=True, cash_yield=0.0):
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).shift(1)
    ex = pd.Series(np.where(dd < -abs(thr), ex_dd, 1.0), index=r.index)
    ex = _monthly_step(ex) if monthly else ex
    ex = ex.fillna(1.0)
    cash_r = (1 + cash_yield) ** (1 / 252) - 1
    return ex * r + (1 - ex) * cash_r, ex


def market_proxy(split):
    """NIFTY 500 TRI level over the split window - the PIT regime proxy."""
    from research_harness import SPLITS
    from data.benchmark import get_benchmark_returns
    s, e = SPLITS[split]
    br = get_benchmark_returns(s, e)
    return (1 + br.fillna(0)).cumprod()


def overlay_regime(r, split, sma=200, ex_bear=0.0, cash_yield=0.0, monthly=True):
    full = market_proxy(split)
    above_full = (full > full.rolling(sma).mean()).shift(1)   # shift(1): PIT
    above = above_full.reindex(r.index, method="ffill")
    ex = pd.Series(np.where(above.fillna(True), 1.0, ex_bear), index=r.index)
    ex = _monthly_step(ex) if monthly else ex
    ex = ex.fillna(1.0)
    cash_r = (1 + cash_yield) ** (1 / 252) - 1
    return ex * r + (1 - ex) * cash_r, ex


# ──────────────────────────────────────────────────────────────────────────
#  Stages
# ──────────────────────────────────────────────────────────────────────────
BASE = dict(split="discovery", n_stocks=10, rebalance="monthly", buffer=20,
            rank_band=(0, 500), capital=CAP)


def J(label, **kw):
    j = dict(BASE)
    j.update(kw)
    j["label"] = label
    return j


def stage_a():
    jobs = [J(f"n={n}", n_stocks=n) for n in (3, 5, 8, 10, 15, 20, 25, 30)]
    return run_jobs(jobs, "A_concentration")


def stage_b():
    jobs = [J(f"monthly/buf{b}", buffer=b) for b in (0, 10, 15, 20, 30, 40)]
    jobs += [J(f"quarterly/buf{b}", rebalance="quarterly", buffer=b)
             for b in (0, 10, 20, 30, 40)]
    return run_jobs(jobs, "B_buffer_freq")


def stage_c():
    bands = [(0, 100), (0, 250), (0, 500), (100, 500), (250, 750), (0, 750),
             (300, 1000), (500, 1500)]
    jobs = [J(f"band{b[0]}-{b[1]}", rank_band=b) for b in bands]
    return run_jobs(jobs, "C_rankband")


def stage_d(band=(250, 750), freq="monthly", buf=20):
    tag = f"{band[0]}-{band[1]}"
    jobs = [J(f"{tag}/n={n}", rank_band=band, n_stocks=n, rebalance=freq, buffer=buf)
            for n in (5, 8, 10, 15, 20, 25)]
    jobs += [J(f"{tag}/n=15/buf{b}", rank_band=band, n_stocks=15, buffer=b)
             for b in (0, 10, 30, 40)]
    jobs += [J(f"{tag}/n=15/qtr/buf{b}", rank_band=band, n_stocks=15,
               rebalance="quarterly", buffer=b) for b in (10, 20, 30)]
    return run_jobs(jobs, "D_interaction")


def stage_e(**best):
    b = dict(BASE)
    b.update(best)
    jobs = [
        J("EW (engine check)", engine="sized", weight_scheme="equal", **best),
        J("InvVol 60d", engine="sized", weight_scheme="invvol", **best),
        J("InvVol capped 1.5x", engine="sized", weight_scheme="invvol",
          weight_cap=1.5, **best),
        J("Rank-conviction 1/k", engine="sized", weight_scheme="rank",
          weight_cap=2.0, **best),
    ]
    return run_jobs(jobs, "E_sizing")


def stage_f(**best):
    jobs = [J(f"cap={c:.0e}", capital=c, **best)
            for c in (1e5, 1e6, 1e7, 1e8)]
    return run_jobs(jobs, "F_capital")


def stage_g(**best):
    jobs = [
        J("in-engine volTGT 15%", engine="sized", target_vol=0.15, **best),
        J("in-engine volTGT 18%", engine="sized", target_vol=0.18, **best),
        J("in-engine DD -15%/0.5", engine="sized", dd_throttle=(0.15, 0.5), **best),
    ]
    return run_jobs(jobs, "G_engine_overlays")


def stage_overlay(**best):
    """Post-hoc overlays on the stored daily return series of `best` (free).
    Exposure at day t always uses data up to t-1 and only steps at month ends."""
    j = dict(BASE); j.update(best); j["label"] = "base"
    meta = run_job(j)
    r = load_returns(meta["key"])
    rows = [stats(r, "RAW (no overlay)")]
    for cy in (0.0, 0.06):
        tag = "" if cy == 0 else " +6% cash"
        for tv in (0.10, 0.12, 0.15, 0.18, 0.22):
            rr, ex = overlay_voltarget(r, tv, monthly=True, cash_yield=cy)
            rows.append(stats(rr, f"volTGT {tv*100:.0f}%{tag}", cy, ex))
        for thr, exd in ((0.10, 0.5), (0.15, 0.5), (0.20, 0.5), (0.15, 0.0),
                         (0.20, 0.0), (0.25, 0.5)):
            rr, ex = overlay_ddthrottle(r, thr, exd, monthly=True, cash_yield=cy)
            rows.append(stats(rr, f"DD -{thr*100:.0f}% -> {exd:.0%}{tag}", cy, ex))
        for sma_ in (100, 200):
            for exb in (0.0, 0.5):
                rr, ex = overlay_regime(r, j["split"], sma_, exb, cash_yield=cy)
                rows.append(stats(rr, f"regime {sma_}dma -> {exb:.0%}{tag}", cy, ex))
    # daily-stepped variants of the two best families (upper bound, ignores costs)
    for tv in (0.12, 0.15):
        rr, ex = overlay_voltarget(r, tv, monthly=False)
        rows.append(stats(rr, f"volTGT {tv*100:.0f}% DAILY-step", 0.0, ex))
    d = pd.DataFrame(rows)
    d.to_csv(RDIR / f"overlays_{j['split']}.csv", index=False)
    return rows


def stage_holdout(configs):
    jobs = []
    for c in configs:
        c = dict(c)
        lab = c.pop("label", "finalist")
        j = dict(BASE); j.update(c); j["split"] = "holdout"; j["label"] = lab
        jobs.append(j)
    return run_jobs(jobs, "H_holdout")


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "a"
    extra = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    if "rank_band" in extra:
        extra["rank_band"] = tuple(extra["rank_band"])
    fn = {"a": stage_a, "b": stage_b, "c": stage_c}.get(stage)
    if fn:
        show(fn())
        return
    if stage == "d":
        show(stage_d(**extra))
    elif stage == "e":
        show(stage_e(**extra))
    elif stage == "f":
        show(stage_f(**extra), sort="capital" if False else "cagr")
    elif stage == "g":
        show(stage_g(**extra))
    elif stage == "overlay":
        show(stage_overlay(**extra))
    elif stage == "holdout":
        show(stage_holdout(json.loads(sys.argv[2])))
    elif stage == "custom":
        jobs = json.loads(sys.argv[2])
        for j in jobs:
            j.setdefault("split", "discovery")
            if "rank_band" in j:
                j["rank_band"] = tuple(j["rank_band"])
            for k, v in BASE.items():
                j.setdefault(k, v)
        show(run_jobs(jobs, sys.argv[3] if len(sys.argv) > 3 else "custom"))
    else:
        raise SystemExit(f"unknown stage {stage}")


if __name__ == "__main__":
    main()
