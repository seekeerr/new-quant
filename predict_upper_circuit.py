"""
Out-of-sample validated scorer for "which stocks lock +10% UC tomorrow".

Model: additive log-odds (naive Bayes) over discretised features. Chosen over a
black-box fit deliberately - every point of the score is auditable, and with a
0.1% base rate a flexible learner would mostly memorise noise.

Protocol:
  TRAIN 2018-01-01 .. 2023-12-31   (fit bucket log-odds)
  TEST  2024-01-01 .. today        (never touched during fitting)

Reported on TEST only:
  * precision@K - of the K highest-scored names each day, what share actually
    locked UC the next day
  * lift vs the unconditional base rate
  * mean / excess (date-demeaned) next-day return of the top-K basket
  * fillability split - how many of the hits were buyable at all

Run:  py predict_upper_circuit.py            (validate + print today's list)
"""
import sys
import io
import os

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

EV = 'results/upper_circuit/events.parquet'
OUT = 'results/upper_circuit'
TRAIN_END = '2023-12-31'
TEST_START = '2024-01-01'
TOPK = 10

# feature -> (bin edges, labels). Deliberately coarse: coarse bins survive
# regime change, fine bins fit noise.
SPECS = {
    'uc_today':   ([-.1, .5, 1.1], ['no', 'yes']),
    'uc_20d':     ([-.1, .5, 1.5, 3.5, 99], ['0', '1', '2-3', '4+']),
    'vol_ratio':  ([0, 1, 2, 3, 5, 10, 1e9], ['<1', '1-2', '2-3', '3-5',
                                              '5-10', '>10']),
    'ret_1d':     ([-1, -.05, 0, .03, .06, .097, 1], ['<-5', '-5-0', '0-3',
                                                      '3-6', '6-9.7', 'UC']),
    'ret_20d':    ([-1, -.1, 0, .2, .5, 1e3], ['<-10', '-10-0', '0-20',
                                               '20-50', '>50']),
    'pct_52wh':   ([0, .5, .8, .95, .999, 1e3], ['<50', '50-80', '80-95',
                                                 '95-100', 'ATH']),
    'atr_ratio':  ([0, .7, 1, 1.5, 2.5, 1e3], ['<0.7', '0.7-1', '1-1.5',
                                               '1.5-2.5', '>2.5']),
    'price':      ([0, 20, 50, 200, 1000, 1e9], ['5-20', '20-50', '50-200',
                                                 '200-1k', '>1k']),
    'turn_med20': ([0, 2.5e6, 1e7, 5e7, 1e18], ['micro', 'small', 'mid',
                                                'liquid']),
}
PRIOR = 30.0   # Laplace-style shrink toward base rate (in pseudo-observations)


def discretise(ev):
    d = {}
    for col, (bins, labels) in SPECS.items():
        d[col] = pd.cut(ev[col], bins=bins, labels=labels, include_lowest=True)
    return pd.DataFrame(d, index=ev.index)


def fit(tr_d, tr_y):
    """Bucket log-odds, shrunk toward the global base rate."""
    base = tr_y.mean()
    b_lo = np.log(base / (1 - base))
    w = {}
    for col in SPECS:
        g = tr_y.groupby(tr_d[col], observed=True).agg(['sum', 'count'])
        g = g.astype(float)
        p = (g['sum'] + PRIOR * base) / (g['count'] + PRIOR)   # shrunk
        w[col] = (np.log(p / (1 - p)) - b_lo).to_dict()
    return w, b_lo


def score(d, w, b_lo):
    s = np.full(len(d), b_lo)
    for col, m in w.items():
        s = s + d[col].map(m).astype(float).fillna(0.0).values
    return s


def main():
    ev = pd.read_parquet(EV)
    ev['date'] = pd.to_datetime(ev['date'])

    # attach next-day return for economics
    C = pd.read_parquet('data/cache_bhav/adj_close.parquet').loc['2018-01-01':]
    f1 = C.pct_change().shift(-1).stack().rename('f1').reset_index()
    f1.columns = ['date', 'symbol', 'f1']
    ev = ev.merge(f1, on=['date', 'symbol'], how='left')
    ev['f1_ex'] = ev['f1'] - ev.groupby('date')['f1'].transform('mean')

    d = discretise(ev)
    tr = ev['date'] <= TRAIN_END
    te = ev['date'] >= TEST_START

    w, b_lo = fit(d[tr], ev.loc[tr, 'uc_next'])
    ev['score'] = score(d, w, b_lo)

    R = []
    R.append('=' * 78)
    R.append('  OUT-OF-SAMPLE VALIDATION  -  next-day +10% upper circuit')
    R.append(f'  train {ev.date[tr].min():%Y-%m-%d}..{TRAIN_END}  '
             f'({int(tr.sum()):,} obs, {int(ev.uc_next[tr].sum()):,} UC)')
    R.append(f'  test  {TEST_START}..{ev.date[te].max():%Y-%m-%d}  '
             f'({int(te.sum()):,} obs, {int(ev.uc_next[te].sum()):,} UC)')
    R.append('=' * 78)

    t = ev[te].copy()
    base = t['uc_next'].mean()
    R.append(f'\n  test base rate = {base*100:.3f}%\n')

    # --- precision@K, computed per day then pooled ---
    t['rk'] = t.groupby('date')['score'].rank(ascending=False, method='first')
    R.append(f'  {"basket":<16}{"n picks":>9}{"hit%":>9}{"lift":>8}'
             f'{"mean ret":>10}{"excess":>9}{"win%":>8}')
    R.append('  ' + '-' * 70)
    for k in (1, 3, 5, 10, 20, 50):
        s = t[t['rk'] <= k]
        R.append(f'  top-{k:<11}{len(s):>9,}{s.uc_next.mean()*100:>8.2f}%'
                 f'{s.uc_next.mean()/base:>8.1f}{s.f1.mean()*100:>9.2f}%'
                 f'{s.f1_ex.mean()*100:>8.2f}%{(s.f1 > 0).mean()*100:>7.1f}%')
    s = t[t['rk'] > 50]
    R.append(f'  {"rest":<16}{len(s):>9,}{s.uc_next.mean()*100:>8.2f}%'
             f'{s.uc_next.mean()/base:>8.1f}{s.f1.mean()*100:>9.2f}%'
             f'{s.f1_ex.mean()*100:>8.2f}%{(s.f1 > 0).mean()*100:>7.1f}%')

    # --- year-by-year stability of top-10 ---
    R.append('\n  TOP-10 BY YEAR (is the edge stable or one lucky year?)')
    R.append('  ' + '-' * 70)
    R.append(f'  {"year":<10}{"picks":>8}{"hit%":>9}{"mean ret":>11}'
             f'{"excess":>10}{"win%":>8}')
    s10 = t[t['rk'] <= TOPK]
    for y, g in s10.groupby(s10['date'].dt.year):
        R.append(f'  {y:<10}{len(g):>8,}{g.uc_next.mean()*100:>8.2f}%'
                 f'{g.f1.mean()*100:>10.2f}%{g.f1_ex.mean()*100:>9.2f}%'
                 f'{(g.f1 > 0).mean()*100:>7.1f}%')

    # --- what the top-10 actually looks like (the catch) ---
    R.append('\n  COMPOSITION OF THE TOP-10 BASKET')
    R.append('  ' + '-' * 70)
    R.append(f'    locked UC on the signal day : '
             f'{s10.uc_today.mean()*100:.1f}%  '
             f'(<- you must buy a stock that is limit-up)')
    R.append(f'    micro-cap (<Rs25L/day)      : '
             f'{(s10.turn_med20 < 2.5e6).mean()*100:.1f}%')
    R.append(f'    median 20d turnover          : Rs '
             f'{s10.turn_med20.median()/1e5:,.1f} lakh')
    R.append(f'    median price                 : Rs {s10.price.median():,.1f}')

    txt = '\n'.join(R)
    print(txt)
    with open(os.path.join(OUT, 'validation.txt'), 'w', encoding='utf-8') as fh:
        fh.write(txt)

    # --- today's candidates ---
    last = ev['date'].max()
    today = ev[ev['date'] == last].nlargest(40, 'score')
    today.to_parquet(os.path.join(OUT, 'candidates_raw.parquet'))
    print(f'\n  signal date = {last:%Y-%m-%d}  -> {len(today)} candidates saved')


if __name__ == '__main__':
    main()
