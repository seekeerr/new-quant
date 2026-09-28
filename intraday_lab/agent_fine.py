"""
Sub-hourly signal battery (5m / 15m / 30m).

The hourly campaign measured a ceiling of 22.1 bp gross against a 21 bp cost
floor across 14,667 configs, and named exactly one thing that could change the
answer: finer resolution. This tests that.

Every config: signal known at bar t -> buy open[t+1] -> sell open[t+1+h],
same day only. Cost 21 bp per round trip, charged per trade.

Read `gross_bp` first. If the best gross across the whole battery does not
clear 21 by a wide margin, nothing else in the table matters - and the margin
has to be wide because N configs of searching inflates the best one.
"""
import sys, io, os, argparse, time
if __name__ == '__main__':   # only when run directly - importing must not touch stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
from intraday_lab import harness_fine as H


def signals(d):
    """{name: DataFrame} - every one uses bars <= t only."""
    C, O, Hi, Lo, V = d['open'], d['open'], d['high'], d['low'], d['volume']
    C = d['close']
    npd = H.bars_per_day(d)
    date = d['date']
    sig = {}

    # --- short-horizon reversal / momentum over the last k bars
    for k in (1, 2, 3, 4, 6, 8, 12, npd):
        r = C / C.shift(k) - 1
        r = r.where(H.bcast(date.shift(k) == date, r))   # same-day only
        sig[f'rev{k}'] = -r
        sig[f'mom{k}'] = r

    # --- distance from today's running VWAP
    rv = (C * V).where(V > 0)
    cum_rv = rv.groupby(date.values).cumsum()
    cum_v = V.groupby(date.values).cumsum().replace(0, np.nan)
    vwap = cum_rv / cum_v
    sig['rev_vwap'] = -(C / vwap - 1)

    # --- where price sits in today's range so far
    hi = Hi.groupby(date.values).cummax()
    lo = Lo.groupby(date.values).cummin()
    rng = (hi - lo).replace(0, np.nan)
    sig['rev_range'] = -((C - lo) / rng)

    # --- overnight gap, faded
    day_open = O.groupby(date.values).transform('first')
    prev_close = C.groupby(date.values).transform('last').groupby(
        date.values).transform('first').shift(npd)
    sig['gap_fade'] = -(day_open / prev_close - 1)

    # --- volume-weighted reversal: a move on heavy volume reverts harder?
    vmed = V.shift(1).rolling(npd * 5, min_periods=npd).median().replace(0, np.nan)
    vr = (V / vmed).clip(0, 20)
    r1 = (C / C.shift(1) - 1)
    r1 = r1.where(H.bcast(date.shift(1) == date, r1))
    sig['rev1_x_vol'] = -r1 * vr
    sig['rev1_hi_vol'] = (-r1).where(vr > 1.5)

    # --- the one stable structure the hourly campaign found: short high vol
    rb = C.pct_change()
    rb = rb.where(H.bcast(date.shift(1) == date, rb))
    sig['lowvol'] = -rb.shift(1).rolling(npd * 3, min_periods=npd).std()

    return sig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', default='15m')
    ap.add_argument('--cost', type=float, default=21.0)
    a = ap.parse_args()

    d = H.load(a.interval)
    npd = H.bars_per_day(d)
    print(f'{a.interval}: {d["close"].shape[1]} symbols, {d["date"].nunique()} days, '
          f'{npd} bars/day, cost {a.cost} bp/round trip')

    sig = signals(d)
    el_base = H.eligible(d)
    liq = H.liquidity(d)
    liq_rank = liq.where(el_base).rank(axis=1, ascending=False, method='first')
    tiers = {'all': el_base, 'top100': el_base & (liq_rank <= 100)}

    horizons = [h for h in (1, 2, 4, 8) if h < npd]
    fwds = {h: H.forward(d, h) for h in horizons}

    rows, t0 = [], time.time()
    for h in horizons:
        fwd = fwds[h]
        for tname, el in tiers.items():
            for sname, s in sig.items():
                for topn in (5, 10, 20):
                    for long in (True, False):
                        r = H.evaluate(s, d, fwd, topn=topn, long=long,
                                       cost_bp=a.cost, el=el,
                                       label=f'{sname}|h{h}|{tname}')
                        if r:
                            r['h'] = h
                            r['tier'] = tname
                            r['signal'] = sname
                            r['trades_day'] = round(npd / h, 1)
                            rows.append(r)
    print(f'{len(rows)} configs in {time.time()-t0:.0f}s')

    t = H.report(rows, f'{a.interval} battery - by GROSS edge vs {a.cost} bp cost',
                 top=25, sort='gross_bp')
    p = os.path.join(H.OUT, f'fine_{a.interval}_battery.csv')
    t.to_csv(p, index=False)

    best = t.iloc[0]
    print(f'\n  best gross anywhere : {best.gross_bp:.1f} bp  ({best.label} '
          f'{best.side} top{int(best.topn)})')
    print(f'  cost floor          : {a.cost:.1f} bp')
    print(f'  ratio               : {best.gross_bp/a.cost:.2f}x')
    n = len(rows)
    print(f'  noise bar for N={n}: expected max |t| = {np.sqrt(2*np.log(n)):.2f}; '
          f'best |t| found = {t.tstat.abs().max():.2f}')
    surv = t[(t.net_bp > 0) & (t.consistent)]
    print(f'  net-positive AND both halves agreeing: {len(surv)}')
    if len(surv):
        print(surv.head(10).to_string(index=False))
    print(f'\n  -> {p}')


if __name__ == '__main__':
    main()
