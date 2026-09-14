"""
Study: what happens in the NEXT 5 trading days to stocks that just rose ~10-12%
over the PREVIOUS 5 trading days?

Data: survivorship-free NSE bhavcopy spine (data/cache_bhav/), equity-only universe
(ISIN 'INE', ETFs/funds excluded). Period: last ~4 years.

Design notes (why the numbers are trustworthy):
  * Universe includes delisted names -> no survivorship bias.
  * Forward return is measured from close[t] to close[t+5] (you see the spike at t's
    close and buy at t's close). No look-ahead in the signal.
  * A raw forward return is meaningless on its own in a bull market, so every bucket is
    also reported DATE-DEMEANED: excess over the cross-sectional mean forward return of
    all eligible stocks on the same date. That removes market direction entirely.
  * Overlapping signals (a stock can trigger on 5 consecutive days) inflate the sample,
    so a non-overlapping variant (>=7 calendar days between signals per stock) is shown.
"""
import sys
import io
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd

CACHE = 'data/cache_bhav'
OUT = 'results/spike_followthrough'
START = '2022-01-01'          # ~4.4 years of signals
MIN_PRICE = 10.0              # rupees, drop penny-stock noise
LIQ_TIERS = {                 # median 20d turnover, rupees
    'all (>=Rs1cr)': 1e7,
    'liquid (>=Rs5cr)': 5e7,
    'very liquid (>=Rs25cr)': 2.5e8,
}
PRIMARY_TIER = 'liquid (>=Rs5cr)'
FWD = [1, 3, 5, 10, 20]
LOOKBACK = 5

BUCKETS = [
    ('down (<0%)', -np.inf, 0.0),
    ('flat 0-5%', 0.0, 5.0),
    ('up 5-10%', 5.0, 10.0),
    ('up 10-12%', 10.0, 12.0),   # <-- the question
    ('up 12-15%', 12.0, 15.0),
    ('up 15-20%', 15.0, 20.0),
    ('up 20-30%', 20.0, 30.0),
    ('up 30%+', 30.0, np.inf),
]

os.makedirs(OUT, exist_ok=True)


def load():
    close = pd.read_parquet(CACHE + '/adj_close.parquet')
    turn = pd.read_parquet(CACHE + '/raw_turnover.parquet')
    eq = [l.strip() for l in open(CACHE + '/symbols_equity.txt') if l.strip()]
    eq = [s for s in eq if s in close.columns]
    close = close[eq].astype('float32')
    turn = turn.reindex(columns=eq).astype('float32')
    return close, turn


def build_events(close, turn):
    """Tidy DataFrame of every eligible stock-day with past/forward returns."""
    c = close.astype('float64')

    traded = c.notna()
    hist_ok = traded.rolling(LOOKBACK + 1).sum() == (LOOKBACK + 1)
    fut_ok = traded[::-1].rolling(LOOKBACK).sum()[::-1].shift(-1) == LOOKBACK

    past = c / c.shift(LOOKBACK) - 1.0
    liq20 = turn.astype('float64').rolling(20).median()
    fwd = {h: c.shift(-h) / c - 1.0 for h in FWD}

    # trend context (all strictly backward-looking)
    daily = c / c.shift(1) - 1.0
    sma200 = c.rolling(200, min_periods=200).mean()
    vs200 = c / sma200 - 1.0                       # >0 => above 200-DMA
    mom12_1 = c.shift(21) / c.shift(252) - 1.0     # classic 12-1 momentum
    max1d = daily.rolling(LOOKBACK).max()          # biggest single day inside the spike

    base = hist_ok & fut_ok & (c >= MIN_PRICE) & past.notna() & fwd[5].notna()
    base = base.loc[START:]

    idx = np.where(base.values)
    dates = base.index.values[idx[0]]
    syms = np.array(base.columns)[idx[1]]

    def pick(df):
        return df.loc[base.index].values[idx]

    ev = pd.DataFrame({
        'date': dates,
        'symbol': syms,
        'past5': pick(past) * 100.0,
        'liq20': pick(liq20),
        'close': pick(c),
        'vs200': pick(vs200) * 100.0,
        'mom12_1': pick(mom12_1) * 100.0,
        'max1d': pick(max1d) * 100.0,
    })
    for h in FWD:
        ev['fwd' + str(h)] = pick(fwd[h]) * 100.0
    return ev.dropna(subset=['past5', 'liq20'])


def add_demeaned(ev, tier_min):
    """Excess over the same-day cross-sectional mean of the SAME eligible tier."""
    sub = ev[ev.liq20 >= tier_min].copy()
    for h in FWD:
        col = 'fwd' + str(h)
        sub['ex' + str(h)] = sub[col] - sub.groupby('date')[col].transform('mean')
    return sub


def describe(g, col):
    v = g[col].dropna().values
    if len(v) == 0:
        return dict(n=0)
    return dict(
        n=len(v),
        mean=v.mean(),
        median=float(np.median(v)),
        win=float((v > 0).mean() * 100),
        std=v.std(ddof=1),
        p10=float(np.percentile(v, 10)),
        p25=float(np.percentile(v, 25)),
        p75=float(np.percentile(v, 75)),
        p90=float(np.percentile(v, 90)),
    )


def table(sub, col):
    rows = []
    for name, lo, hi in BUCKETS:
        g = sub[(sub.past5 >= lo) & (sub.past5 < hi)]
        d = describe(g, col)
        d['bucket'] = name
        rows.append(d)
    d = describe(sub, col)
    d['bucket'] = 'ALL (baseline)'
    rows.append(d)
    return pd.DataFrame(rows).set_index('bucket')


def nonoverlap(sub, lo, hi):
    """Keep only signals >= 7 calendar days apart per symbol."""
    g = sub[(sub.past5 >= lo) & (sub.past5 < hi)].sort_values(['symbol', 'date'])
    keep, last = [], {}
    for sym, dt in zip(g.symbol.values, g.date.values):
        prev = last.get(sym)
        ok = prev is None or (dt - prev) / np.timedelta64(1, 'D') >= 7
        keep.append(ok)
        if ok:
            last[sym] = dt
    return g[np.array(keep)]


def fmt(df):
    cols = ['n', 'mean', 'median', 'win', 'std', 'p10', 'p25', 'p75', 'p90']
    d = df[cols].copy()
    d['n'] = d['n'].astype(int)
    return d.round(2).to_string()


def make_chart(t_ex, g, yr, ct):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle('5-day spike -> next 5 days (NSE, survivorship-free, 2022-2026, >=Rs5cr ADV)',
                 fontsize=14, weight='bold')

    d = t_ex.drop(index='ALL (baseline)')
    x = np.arange(len(d))
    a = ax[0, 0]
    a.bar(x - 0.2, d['mean'], 0.4, label='mean excess', color='#4c78a8')
    a.bar(x + 0.2, d['median'], 0.4, label='median excess', color='#f58518')
    a.set_xticks(x)
    a.set_xticklabels(d.index, rotation=30, ha='right', fontsize=8)
    a.axhline(0, color='k', lw=0.8)
    a.set_ylabel('excess fwd-5d return (%)')
    a.set_title('A. Follow-through by size of the prior 5-day move')
    a.legend(fontsize=8)
    a.grid(alpha=0.3, axis='y')
    for i, b in enumerate(d.index):
        if b == 'up 10-12%':
            a.axvspan(i - 0.5, i + 0.5, color='red', alpha=0.10)

    a = ax[0, 1]
    a.bar(x, d['win'], color='#54a24b')
    a.axhline(45.0, color='r', ls='--', lw=1, label='baseline 45.0%')
    a.set_xticks(x)
    a.set_xticklabels(d.index, rotation=30, ha='right', fontsize=8)
    a.set_ylim(35, 50)
    a.set_ylabel('% of events beating the cross-section')
    a.set_title('B. Win rate vs the average stock that day')
    a.legend(fontsize=8)
    a.grid(alpha=0.3, axis='y')

    a = ax[1, 0]
    raw = g['ex5'].dropna()
    v = raw.clip(-25, 25)
    a.hist(v, bins=120, color='#4c78a8', alpha=0.85)
    a.axvline(0, color='k', lw=0.8)
    a.axvline(raw.mean(), color='r', ls='--', lw=1.2, label='mean %.2f%%' % raw.mean())
    a.axvline(raw.median(), color='orange', ls='--', lw=1.2, label='median %.2f%%' % raw.median())
    a.set_xlabel('excess fwd-5d return (%, clipped at +/-25 for display)')
    a.set_title('C. Distribution for the 10-12% bucket (n={:,})'.format(len(raw)))
    a.legend(fontsize=8)
    a.grid(alpha=0.3)

    a = ax[1, 1]
    y = np.arange(len(ct))
    a.barh(y, ct['mean'], color=['#54a24b' if m > 0 else '#e45756' for m in ct['mean']])
    a.set_yticks(y)
    a.set_yticklabels(ct.index, fontsize=8)
    a.invert_yaxis()
    a.axvline(0, color='k', lw=0.8)
    a.set_xlabel('mean excess fwd-5d return (%)')
    a.set_title('D. Does trend context rescue the 10-12% signal?')
    a.grid(alpha=0.3, axis='x')

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUT + '/report.png', dpi=120)
    plt.close(fig)


def main():
    print('Loading survivorship-free bhavcopy panels...')
    close, turn = load()
    print('  equities: %d,  sessions: %d' % (close.shape[1], close.shape[0]))

    ev = build_events(close, turn)
    print('  eligible stock-days from %s: %d' % (START, len(ev)))

    lines = []

    def P(*a):
        s = ' '.join(str(x) for x in a)
        print(s)
        lines.append(s)

    P('=' * 100)
    P('5-DAY SPIKE FOLLOW-THROUGH STUDY  (NSE, survivorship-free, equity-only)')
    P('=' * 100)
    P('Signal window : %s -> %s' % (pd.Timestamp(ev.date.min()).date(),
                                    pd.Timestamp(ev.date.max()).date()))
    P('Universe      : %d equities (ISIN INE only, ETFs/funds removed)' % close.shape[1])
    P('Filters       : traded all of t-5..t+5, close >= Rs%.0f, liquidity tier below' % MIN_PRICE)
    P('Signal        : return from close[t-5] to close[t]')
    P('Forward       : return from close[t] to close[t+h], h in %s' % FWD)
    P('')

    sub = add_demeaned(ev, LIQ_TIERS[PRIMARY_TIER])
    P('PRIMARY TIER: %s   ->  %d stock-days' % (PRIMARY_TIER, len(sub)))
    P('')
    P('-' * 100)
    P('A. RAW forward 5-day return by 5-day prior-move bucket  (%)')
    P('-' * 100)
    t_raw = table(sub, 'fwd5')
    P(fmt(t_raw))
    P('')
    P('-' * 100)
    P('B. EXCESS forward 5-day return (minus same-day cross-sectional mean)  (%)')
    P('   -> the honest number: removes market direction entirely')
    P('-' * 100)
    t_ex = table(sub, 'ex5')
    P(fmt(t_ex))
    P('')

    P('-' * 100)
    P('C. The 10-12% bucket across horizons')
    P('-' * 100)
    g = sub[(sub.past5 >= 10) & (sub.past5 < 12)]
    rows = []
    for h in FWD:
        r = describe(g, 'fwd' + str(h))
        e = describe(g, 'ex' + str(h))
        rows.append(dict(horizon=str(h) + 'd', n=r['n'], raw_mean=r['mean'],
                         raw_median=r['median'], raw_win=r['win'],
                         excess_mean=e['mean'], excess_median=e['median'],
                         excess_win=e['win']))
    hz = pd.DataFrame(rows).set_index('horizon').round(2)
    P(hz.to_string())
    P('')

    P('-' * 100)
    P('D. 10-12% bucket, NON-OVERLAPPING signals only (>=7 calendar days apart per stock)')
    P('-' * 100)
    no = nonoverlap(sub, 10, 12)
    r = describe(no, 'fwd5')
    e = describe(no, 'ex5')
    P('  n=%d   raw fwd5: mean %.2f%%  median %.2f%%  win %.1f%%'
      % (r['n'], r['mean'], r['median'], r['win']))
    P('            excess fwd5: mean %.2f%%  median %.2f%%  win %.1f%%'
      % (e['mean'], e['median'], e['win']))
    dm = no.groupby('date')['ex5'].mean()
    tstat = dm.mean() / (dm.std(ddof=1) / np.sqrt(len(dm))) if len(dm) > 2 else float('nan')
    P('  per-date mean excess: %.3f%%  over %d dates  ->  t-stat %.2f'
      % (dm.mean(), len(dm), tstat))
    P('')

    P('-' * 100)
    P('E. 10-12% bucket year by year (excess fwd5 %)')
    P('-' * 100)
    g2 = g.copy()
    g2['year'] = pd.to_datetime(g2.date).dt.year
    yr = g2.groupby('year').agg(n=('ex5', 'size'), raw_mean=('fwd5', 'mean'),
                                excess_mean=('ex5', 'mean'),
                                excess_median=('ex5', 'median'),
                                win=('ex5', lambda v: (v > 0).mean() * 100)).round(2)
    P(yr.to_string())
    P('')

    P('-' * 100)
    P('F. 10-12% bucket by liquidity tier (excess fwd5 %)')
    P('-' * 100)
    rows = []
    for name, thr in LIQ_TIERS.items():
        s2 = add_demeaned(ev, thr)
        g3 = s2[(s2.past5 >= 10) & (s2.past5 < 12)]
        d = describe(g3, 'ex5')
        d['tier'] = name
        rows.append(d)
    lt = pd.DataFrame(rows).set_index('tier')
    P(fmt(lt))
    P('')

    P('-' * 100)
    P('G. Does CONTEXT rescue it? 10-12% bucket split by trend / spike shape (excess fwd5 %)')
    P('-' * 100)
    cuts = [
        ('above 200-DMA', g[g.vs200 > 0]),
        ('below 200-DMA', g[g.vs200 <= 0]),
        ('12-1 momentum > 0', g[g.mom12_1 > 0]),
        ('12-1 momentum <= 0', g[g.mom12_1 <= 0]),
        ('above 200DMA AND mom>0', g[(g.vs200 > 0) & (g.mom12_1 > 0)]),
        ('smooth spike (max 1d < 5%)', g[g.max1d < 5]),
        ('gappy spike (max 1d >= 8%)', g[g.max1d >= 8]),
    ]
    rows = []
    for name, gc in cuts:
        d = describe(gc, 'ex5')
        d['cut'] = name
        rows.append(d)
    ct = pd.DataFrame(rows).set_index('cut')
    P(fmt(ct))
    P('')

    P('-' * 100)
    P('H. Cost reality check')
    P('-' * 100)
    try:
        from costs.cost_model import CostModel
        cm = CostModel()
        for val in (50000, 100000):
            pct = cm.estimate_round_trip_cost_pct(val) * 100
            P('  round-trip cost on a Rs%d position: %.2f%%' % (val, pct))
    except Exception as exc:
        P('  (cost model unavailable: %s)' % exc)
    P('')

    t_raw.to_csv(OUT + '/buckets_raw_fwd5.csv')
    t_ex.to_csv(OUT + '/buckets_excess_fwd5.csv')
    hz.to_csv(OUT + '/horizons_10_12.csv')
    yr.to_csv(OUT + '/by_year_10_12.csv')
    lt.to_csv(OUT + '/by_liquidity_10_12.csv')
    ct.to_csv(OUT + '/by_context_10_12.csv')
    g.to_csv(OUT + '/events_10_12.csv', index=False)
    make_chart(t_ex, g, yr, ct)
    with open(OUT + '/report.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('\nSaved -> ' + OUT + '/')
    return sub, g


if __name__ == '__main__':
    main()
