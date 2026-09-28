"""
INTRADAY / OVERNIGHT MICROSTRUCTURE research program.

Family recorded as NEVER TESTED in RESEARCH_PROGRAM_2_FINDINGS.md (~line 107).

Question: does decomposing the daily bar into its OVERNIGHT (close[t-1] -> open[t])
and INTRADAY (open[t] -> close[t]) components produce a long-only cross-sectional
signal that beats the frozen champion (Mom+LowVol Top-10 monthly, discovery CAGR
24.30% / Sharpe 1.12 / MaxDD -31.4%)?

DATA HYGIENE (this is where fake alpha gets invented, so read this):
  * close / high / low panels are CORPORATE-ACTION ADJUSTED.
  * open panel is RAW (rebuilt full-history 2011-2026 by build_open_panel.py logic
    extended to all bhavcopy files - the shipped one started at 2017 and would have
    silently blanked half of DISCOVERY).
  * Mixing raw open[t] with adjusted close[t-1] across a split/bonus date invents a
    -50% "overnight return". So we NEVER do that. Instead:
        intraday[t]  = raw_close[t] / raw_open[t] - 1          (same day -> the
                       adjustment factor cancels exactly; this is safe)
        total[t]     = adj_close[t] / adj_close[t-1] - 1       (properly adjusted)
        overnight[t] = (1 + total[t]) / (1 + intraday[t]) - 1  (derived, clean)
    so that (1+overnight)(1+intraday) = (1+total) identically.
  * Residual |overnight| > 25% moves are still dropped as suspected artifacts.

NO LOOK-AHEAD: every scorer only ever touches panel rows with index <= `date`, and
all signal panels are sliced to the active split before any scorer is built, so a
DISCOVERY run physically cannot see HOLDOUT bars (same discipline the harness
applies to the price panels).

SPLIT DISCIPLINE: search on discovery only. Holdout is run once, by the finalists.

Usage:
    py run_micro_alpha.py --stage sweep1 --shard 0 --nshards 6
    py run_micro_alpha.py --stage final --split holdout
"""
import sys, io, os, json, time, argparse, warnings, logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
logging.basicConfig(level=logging.ERROR)
for _n in list(logging.root.manager.loggerDict):
    logging.getLogger(_n).setLevel(logging.ERROR)
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd

from research_harness import (load_panels, evaluate, champion_scorer,
                              rolling_3y_min, SPLITS, CACHE)
from run_pure_momentum import compute_12_1_momentum
from run_momentum_lowvol import compute_realized_vol, VOL_LOOKBACK

OUT = ROOT / 'results' / 'micro_alpha'
OUT.mkdir(parents=True, exist_ok=True)

MAX_ON = 0.25          # drop |overnight| beyond this as a corp-action artifact
MIN_FRAC = 0.6         # require this fraction of the lookback window populated


# ───────────────────────────── signal panels ─────────────────────────────
def build_micro_panels():
    """Return dict of full-history microstructure panels (columns = close's columns)."""
    rd = lambda n: pd.read_parquet(os.path.join(CACHE, n))
    ropen, rclose = rd('raw_open.parquet'), rd('raw_close.parquet')
    rhigh, rlow = rd('raw_high.parquet'), rd('raw_low.parquet')
    aclose = rd('adj_close.parquet')

    ropen = ropen.reindex(index=aclose.index, columns=aclose.columns)
    rclose = rclose.reindex(index=aclose.index, columns=aclose.columns)
    rhigh = rhigh.reindex(index=aclose.index, columns=aclose.columns)
    rlow = rlow.reindex(index=aclose.index, columns=aclose.columns)

    o = ropen.where(ropen > 0)
    c = rclose.where(rclose > 0)
    intraday = c / o - 1.0
    total = aclose.pct_change()
    overnight = (1.0 + total) / (1.0 + intraday) - 1.0

    bad = overnight.abs() > MAX_ON
    overnight = overnight.mask(bad)
    intraday = intraday.mask(bad | (intraday.abs() > MAX_ON))

    rng = (rhigh - rlow)
    cpr = ((rclose - rlow) / rng.where(rng > 0)).clip(0, 1)

    return {
        'on':   np.log1p(overnight),                  # log overnight return
        'id':   np.log1p(intraday),                   # log intraday return
        'tot':  np.log1p(total.mask(bad)),            # log total return
        'cpr':  cpr,                                  # close position in day range
        'onp':  (overnight > 0).astype(float).mask(overnight.isna()),
        'idp':  (intraday > 0).astype(float).mask(intraday.isna()),
        'gapu': (overnight > 0.01).astype(float).mask(overnight.isna()),
        'gapd': (overnight < -0.01).astype(float).mask(overnight.isna()),
        'onr':  overnight,                            # simple overnight return
        'idr':  intraday,
    }


def slice_panels(panels, split):
    s, e = SPLITS[split]
    return {k: v.loc[s:e] for k, v in panels.items()}


# ───────────────────────────── signal computation ─────────────────────────
def _win(panel, date, cols, lookback, skip):
    """Rows strictly <= date, drop last `skip` rows, keep last `lookback`."""
    sub = panel.loc[panel.index <= date, cols]
    if skip:
        sub = sub.iloc[:-skip] if len(sub) > skip else sub.iloc[0:0]
    return sub.tail(lookback)


def _clean(s, w, need):
    return s.where(w >= need).replace([np.inf, -np.inf], np.nan).dropna()


def compute_signal(P, kind, close_panel, date, cols, lookback, skip):
    """One microstructure signal, higher = 'more of it'. No data after `date`."""
    need = max(10, int(MIN_FRAC * lookback))

    if kind in ('on', 'id', 'tot'):
        w = _win(P[kind], date, cols, lookback, skip)
        return _clean(w.sum(min_count=1), w.notna().sum(), need)

    if kind == 'diff':                      # overnight minus intraday momentum
        a = _win(P['on'], date, cols, lookback, skip)
        b = _win(P['id'], date, cols, lookback, skip)
        return _clean(a.sum(min_count=1) - b.sum(min_count=1), a.notna().sum(), need)

    if kind in ('cpr', 'onp', 'idp', 'gapu', 'gapd'):
        w = _win(P[kind], date, cols, lookback, skip)
        return _clean(w.mean(), w.notna().sum(), need)

    if kind in ('onvol', 'idvol'):          # HIGHER = more volatile
        w = _win(P['onr' if kind == 'onvol' else 'idr'], date, cols, lookback, skip)
        return _clean(w.std(), w.notna().sum(), need)

    if kind in ('onir', 'idir'):            # information ratio of the component
        w = _win(P['onr' if kind == 'onir' else 'idr'], date, cols, lookback, skip)
        sd = w.std()
        return _clean(w.mean() / sd.where(sd > 0), w.notna().sum(), need)

    if kind == 'gaphold':                   # avg intraday return on up-gap days
        g = _win(P['gapu'], date, cols, lookback, skip)
        i = _win(P['idr'], date, cols, lookback, skip)
        m = i.where(g > 0)
        return _clean(m.mean(), m.notna().sum(), max(5, int(0.05 * lookback)))

    if kind == 'gapfade':                   # avg intraday return on down-gap days
        g = _win(P['gapd'], date, cols, lookback, skip)
        i = _win(P['idr'], date, cols, lookback, skip)
        m = i.where(g > 0)
        return _clean(m.mean(), m.notna().sum(), max(5, int(0.05 * lookback)))

    if kind == 'mom':                       # champion's 12-1 price momentum
        return compute_12_1_momentum(close_panel, date, cols)

    if kind == 'lowvol':                    # HIGHER = more volatile (sign flips it)
        return compute_realized_vol(close_panel, date, cols, lookback or VOL_LOOKBACK)

    raise ValueError(f'unknown signal {kind}')


def make_scorer(comps, panels):
    """
    comps: list of (kind, lookback, skip, sign, weight).
    Blend of cross-sectional percentile ranks over the common intersection.
    """
    def scorer(close_panel, date, universe):
        cols = [s for s in universe if s in close_panel.columns]
        if len(cols) < 5:
            return pd.Series(dtype=float)
        parts = []
        for kind, lb, sk, sign, wt in comps:
            s = compute_signal(panels, kind, close_panel, date, cols, lb, sk)
            if len(s) < 5:
                return pd.Series(dtype=float)
            parts.append((s, sign, wt))
        common = parts[0][0].index
        for s, _, _ in parts[1:]:
            common = common.intersection(s.index)
        if len(common) < 5:
            return pd.Series(dtype=float)
        blend = None
        for s, sign, wt in parts:
            pct = (sign * s[common]).rank(pct=True)
            blend = wt * pct if blend is None else blend + wt * pct
        return blend.sort_values(ascending=False)
    return scorer


# ───────────────────────────── config generation ──────────────────────────
def cfg(name, comps, n=10, rebal='monthly'):
    return {'name': name, 'comps': comps, 'n': n, 'rebal': rebal}


def sweep1():
    """Broad single-signal sweep: which microstructure primitive has ANY edge?"""
    out = []
    LB = [21, 63, 126, 252]
    for lb in LB:
        for kind, sign, tag in [
            ('on',  +1, 'ONmom'), ('on',  -1, 'ONrev'),
            ('id',  +1, 'IDmom'), ('id',  -1, 'IDrev'),
            ('diff', +1, 'DIFF'), ('diff', -1, 'DIFFneg'),
            ('cpr', +1, 'CPR'),   ('cpr', -1, 'CPRlow'),
            ('onp', +1, 'ONhit'), ('idp', +1, 'IDhit'),
            ('gapu', +1, 'GAPUPfreq'),
            ('onir', +1, 'ONir'), ('idir', -1, 'IDirNeg'),
            ('onvol', -1, 'ONlowvol'),
        ]:
            out.append(cfg(f'{tag}_{lb}', [(kind, lb, 0, sign, 1.0)]))
    # skip-a-month variants of the two decomposed momenta (Jegadeesh-Titman shape)
    for lb in [126, 252]:
        out.append(cfg(f'ONmom_{lb}s21', [('on', lb, 21, +1, 1.0)]))
        out.append(cfg(f'IDmom_{lb}s21', [('id', lb, 21, +1, 1.0)]))
        out.append(cfg(f'IDrev_{lb}s21', [('id', lb, 21, -1, 1.0)]))
        out.append(cfg(f'DIFF_{lb}s21',  [('diff', lb, 21, +1, 1.0)]))
    # gap-and-hold / gap-and-fade behaviour
    for lb in [126, 252]:
        out.append(cfg(f'GAPHOLD_{lb}',  [('gaphold', lb, 0, +1, 1.0)]))
        out.append(cfg(f'GAPFADE_{lb}',  [('gapfade', lb, 0, +1, 1.0)]))
    return out


def sweep2(winners):
    """Refine: n_stocks / rebalance grid around whatever sweep1 liked."""
    out = []
    for w in winners:
        for n in (5, 10, 15, 20):
            for rb in ('monthly', 'quarterly'):
                if n == 10 and rb == 'monthly':
                    continue            # already measured in sweep1
                out.append(cfg(f"{w['name']}_n{n}_{rb}", w['comps'], n=n, rebal=rb))
    return out


def sweep3(winners):
    """Blend the best microstructure signal with the champion's Mom+LowVol core."""
    out = []
    core = [('mom', 0, 0, +1, 1.0), ('lowvol', VOL_LOOKBACK, 0, -1, 1.0)]
    for w in winners:
        mc = w['comps']
        for wm in (0.25, 0.5, 0.75):
            # micro blended onto the 50/50 champion core
            comps = [(k, lb, sk, sg, wt * wm) for (k, lb, sk, sg, wt) in mc] + \
                    [(k, lb, sk, sg, (1 - wm) * 0.5) for (k, lb, sk, sg, _) in core]
            out.append(cfg(f"{w['name']}+CHAMP_w{wm}", comps, n=w['n'], rebal=w['rebal']))
            # micro blended onto pure 12-1 momentum
            comps2 = [(k, lb, sk, sg, wt * wm) for (k, lb, sk, sg, wt) in mc] + \
                     [('mom', 0, 0, +1, 1 - wm)]
            out.append(cfg(f"{w['name']}+MOM_w{wm}", comps2, n=w['n'], rebal=w['rebal']))
    return out


STAGES = {'sweep1': sweep1}


# ───────────────────────────── runner ─────────────────────────────────────
def run_configs(configs, split, tag, save_equity=False):
    close, high, low, vol, turn = load_panels()
    panels = slice_panels(build_micro_panels(), split)
    # keep only equity columns present in close
    panels = {k: v.reindex(columns=close.columns) for k, v in panels.items()}

    path = OUT / f'{tag}.jsonl'
    done = set()
    if path.exists():
        for ln in path.read_text(encoding='utf-8').splitlines():
            try:
                done.add(json.loads(ln)['label'])
            except Exception:
                pass

    for i, c in enumerate(configs):
        if c['name'] in done:
            continue
        t0 = time.time()
        try:
            sc = make_scorer(c['comps'], panels)
            m = evaluate(sc, close, high, low, vol, turn, split=split,
                         n_stocks=c['n'], rebalance=c['rebal'], label=c['name'])
            row = {k: m[k] for k in ('label', 'split', 'cagr', 'sharpe', 'maxdd',
                                     'calmar', 'n_trades', 'final')}
            row['roll3y_min'] = rolling_3y_min(m['returns'])
            row['n'] = c['n']; row['rebal'] = c['rebal']
            row['comps'] = c['comps']
            row['secs'] = round(time.time() - t0, 1)
            if save_equity:
                m['equity'].to_csv(OUT / f"eq_{c['name']}_{split}.csv")
                m['returns'].to_csv(OUT / f"ret_{c['name']}_{split}.csv")
        except Exception as ex:
            row = {'label': c['name'], 'split': split, 'error': repr(ex)[:300]}
        with path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row) + '\n')
        print(f"[{i+1}/{len(configs)}] {c['name']:<28} "
              f"CAGR {row.get('cagr', float('nan')) if 'cagr' in row else 'ERR'} "
              f"({row.get('secs', '-')}s)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', default='sweep1')
    ap.add_argument('--split', default='discovery')
    ap.add_argument('--shard', type=int, default=0)
    ap.add_argument('--nshards', type=int, default=1)
    ap.add_argument('--configs', default=None, help='json file of configs')
    ap.add_argument('--tag', default=None)
    ap.add_argument('--save-equity', action='store_true')
    a = ap.parse_args()

    if a.configs:
        configs = json.loads(Path(a.configs).read_text(encoding='utf-8'))
        configs = [{**c, 'comps': [tuple(x) for x in c['comps']]} for c in configs]
    else:
        configs = STAGES[a.stage]()
    configs = configs[a.shard::a.nshards]
    tag = a.tag or f'{a.stage}_{a.split}_s{a.shard}'
    print(f'{len(configs)} configs -> {tag}', flush=True)
    run_configs(configs, a.split, tag, save_equity=a.save_equity)
    print('DONE', tag, flush=True)


if __name__ == '__main__':
    main()
