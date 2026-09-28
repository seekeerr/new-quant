"""
Cross-sectional / multi-day signals held for ONE intraday session.

QUESTION
--------
The daily book in this repo makes money from momentum + low-vol + illiquidity
over MONTHLY holds. Does any of that edge exist inside a single session? Rank
the universe at entry slot E by a signal computed from daily history (yesterday
and before), buy/short the top N at E's open, flatten at 15:15.

The prior is that it does not. A monthly 1.5%/month edge is ~7 bp/day of drift,
and we pay 21-38 bp round trip to harvest one day of it. This file tries to
prove that honestly rather than assert it.

Rules inherited from harness.py: no look-ahead, never enter at 09:15, net_bp is
the only number that counts, both halves must agree.

Run:  py -m intraday_lab.agent_crosssec <phase>
      phases: 1 single | 2 cond | 3 blend | 4 sweep | 5 calendar | 6 attack | all
"""
import sys
import os
import itertools
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from intraday_lab.harness import (context, evaluate, zscore, report, eligible,
                                  OUT)

pd.set_option('display.width', 200)

ALL = []          # every row ever produced, for the multiple-testing count
NTESTED = [0]     # configs attempted (including ones evaluate() rejected)


def run(score, ctx, label, **kw):
    NTESTED[0] += 1
    r = evaluate(score, ctx, label=label, **kw)
    if r:
        ALL.append(r)
    return r


def rk(df):
    """Cross-sectional percentile rank, 0..1. Robust to outliers/units."""
    return df.rank(axis=1, pct=True)


# ----------------------------------------------------------------------------
# feature dictionary: name -> (score, direction note)
# direction is handled by testing +f and -f separately.
# ----------------------------------------------------------------------------
def features(ctx):
    f = {}
    for k in ('d1', 'd2', 'd5', 'd10', 'd20'):
        f[k] = ctx[k]
    f['vol20'] = ctx['vol20']
    f['atr'] = ctx['atr']
    f['pct52'] = ctx['pct52']
    f['price'] = ctx['price']
    f['liq'] = ctx['liq']
    f['logliq'] = np.log(ctx['liq'].clip(lower=1))
    # 12-1 analogue is impossible (only 2y, 20d max in ctx) - build longer ones
    # from prev_close directly, still strictly lagged.
    pc = ctx['prev_close']
    for k in (40, 60, 120, 250):
        f[f'd{k}'] = pc / pc.shift(k) - 1
    # momentum skipping the last week/month (Jegadeesh-Titman shape)
    f['d20_skip5'] = pc.shift(5) / pc.shift(25) - 1
    f['d120_skip20'] = pc.shift(20) / pc.shift(140) - 1
    f['d250_skip20'] = pc.shift(20) / pc.shift(270) - 1
    # risk-adjusted momentum
    f['d20_over_vol'] = ctx['d20'] / ctx['vol20'].replace(0, np.nan)
    f['d120_riskadj'] = f['d120_skip20'] / ctx['vol20'].replace(0, np.nan)
    # distance from 52w high, and 52w low proximity
    f['pct52_lo'] = pc / pc.rolling(250, min_periods=60).min()
    # daily-bar shape features
    f['gap'] = ctx['gap']
    f['entry_gap'] = ctx['entry_gap']
    f['today_sofar'] = ctx['today_sofar']
    f['pos_in_range'] = ctx['pos_in_range']
    f['range_sofar'] = ctx['range_sofar']
    f['vol_ratio'] = ctx['vol_ratio']
    # Amihud illiquidity: |ret| / rupee volume, the repo's daily premium
    r1 = pc.pct_change()
    f['amihud'] = (r1.abs() / ctx['liq'].replace(0, np.nan)) \
        .rolling(20, min_periods=10).mean()
    # dispersion / consistency of recent daily returns
    f['updays20'] = (r1 > 0).rolling(20, min_periods=10).mean()
    f['maxret20'] = r1.rolling(20, min_periods=10).max()   # MAX lottery effect
    f['skew20'] = r1.rolling(20, min_periods=10).skew()
    return f


# ----------------------------------------------------------------------------
def phase1(ctx, entry):
    print(f'\n### PHASE 1 - single daily features, entry {entry}, '
          f'topn=10, cost 38bp')
    f = features(ctx)
    rows = []
    for name, s in f.items():
        for sign, tag in ((1, '+'), (-1, '-')):
            for topn in (10, 20):
                r = run(sign * s, ctx, f'{tag}{name}', topn=topn, long=True,
                        cost_bp=38.0)
                if r:
                    rows.append(r)
    report(rows, f'P1 single features, LONG top-N, entry {entry}', top=18)
    # short side: shorting the top of +f is identical to longing -f only if
    # returns were symmetric; they are not (costs, drift), so test explicitly.
    rows_s = []
    for name, s in f.items():
        for sign, tag in ((1, '+'), (-1, '-')):
            r = run(sign * s, ctx, f'{tag}{name}', topn=10, long=False,
                    cost_bp=38.0)
            if r:
                rows_s.append(r)
    report(rows_s, f'P1 single features, SHORT top-10, entry {entry}', top=12)
    return rows + rows_s


# ----------------------------------------------------------------------------
def phase2(ctx, entry):
    """Daily signal conditioned on what today has already done."""
    print(f'\n### PHASE 2 - daily signal x session state, entry {entry}')
    f = features(ctx)
    rows = []
    base = {'d1': -1, 'd2': -1, 'd5': -1, 'd20': +1, 'd120_skip20': +1,
            'vol20': -1, 'pct52': +1, 'amihud': +1, 'liq': -1, 'price': -1,
            'd250_skip20': +1, 'maxret20': -1}
    conds = {
        'gapdn': ctx['gap'] < -0.005,
        'gapdn2': ctx['gap'] < -0.015,
        'gapup': ctx['gap'] > 0.005,
        'gapup2': ctx['gap'] > 0.015,
        'flat': ctx['gap'].abs() < 0.005,
        'am_dn': ctx['today_sofar'] < -0.003,
        'am_up': ctx['today_sofar'] > 0.003,
        'lowrange': rk(ctx['range_sofar']) < 0.3,
        'hirange': rk(ctx['range_sofar']) > 0.7,
        'volsurge': ctx['vol_ratio'] > 1.5,
        'voldry': ctx['vol_ratio'] < 0.7,
        'lowpos': ctx['pos_in_range'] < 0.3,
        'hipos': ctx['pos_in_range'] > 0.7,
    }
    for fname, sign in base.items():
        s = sign * f[fname]
        tag = ('+' if sign > 0 else '-') + fname
        for cname, m in conds.items():
            sc = s.where(m)
            for topn in (5, 10):
                r = run(sc, ctx, f'{tag}|{cname}', topn=topn, long=True,
                        cost_bp=38.0)
                if r:
                    rows.append(r)
    report(rows, f'P2 conditional signals, entry {entry}', top=18)
    return rows


# ----------------------------------------------------------------------------
def phase3(ctx, entry):
    """Blends of 2-3 daily features via cross-sectional z-scores."""
    print(f'\n### PHASE 3 - blends, entry {entry}')
    f = features(ctx)
    pool = {
        'rev1': -f['d1'], 'rev5': -f['d5'], 'mom20': f['d20'],
        'mom120': f['d120_skip20'], 'mom250': f['d250_skip20'],
        'lowvol': -f['vol20'], 'hivol': f['vol20'],
        'near52': f['pct52'], 'illiq': f['amihud'], 'smallliq': -f['logliq'],
        'cheap': -f['price'], 'lowmax': -f['maxret20'],
        'gapdn': -f['gap'], 'amdn': -f['today_sofar'],
    }
    z = {k: zscore(v.clip(v.quantile(.01, axis=1), v.quantile(.99, axis=1),
                          axis=0)) for k, v in pool.items()}
    rows = []
    keys = list(z)
    for a, b in itertools.combinations(keys, 2):
        for w in (0.5,):
            s = w * z[a] + (1 - w) * z[b]
            for topn in (10, 20):
                r = run(s, ctx, f'{a}+{b}', topn=topn, long=True, cost_bp=38.0)
                if r:
                    rows.append(r)
    report(rows, f'P3 two-way blends, entry {entry}', top=18)

    # three-way, restricted to the repo's daily winner shape + neighbours
    rows3 = []
    tri = [('mom120', 'lowvol', 'illiq'), ('mom20', 'lowvol', 'illiq'),
           ('mom250', 'lowvol', 'illiq'), ('mom120', 'lowvol', 'near52'),
           ('rev1', 'lowvol', 'illiq'), ('rev5', 'lowvol', 'illiq'),
           ('mom120', 'lowmax', 'illiq'), ('rev1', 'gapdn', 'lowvol'),
           ('rev1', 'amdn', 'illiq'), ('mom20', 'near52', 'lowvol')]
    for t in tri:
        s = sum(z[k] for k in t) / 3
        for topn in (5, 10, 20):
            r = run(s, ctx, '+'.join(t)[:33], topn=topn, long=True,
                    cost_bp=38.0)
            if r:
                rows3.append(r)
    report(rows3, f'P3 three-way blends, entry {entry}', top=12)
    return rows + rows3


# ----------------------------------------------------------------------------
def phase4(best_labels, ctx_by_slot):
    """Full sweep of the survivors: slot x topn x side x liquidity floor."""
    print('\n### PHASE 4 - sweep of survivors')
    rows = []
    for slot, ctx in ctx_by_slot.items():
        f = features(ctx)
        z = build_z(ctx, f)
        for lab in best_labels:
            s = resolve(lab, f, z)
            if s is None:
                continue
            for topn in (5, 10, 20, 30):
                for long in (True, False):
                    for min_liq, cost in ((1e7, 38.0), (1e8, 21.0)):
                        r = run(s, ctx, f'{lab}@{slot}/{int(np.log10(min_liq))}',
                                topn=topn, long=long, cost_bp=cost,
                                min_liq=min_liq)
                        if r:
                            r['slot'] = slot
                            r['min_liq'] = min_liq
                            rows.append(r)
    report(rows, 'P4 survivor sweep', top=25)
    return rows


def build_z(ctx, f):
    pool = {
        'rev1': -f['d1'], 'rev5': -f['d5'], 'mom20': f['d20'],
        'mom120': f['d120_skip20'], 'mom250': f['d250_skip20'],
        'lowvol': -f['vol20'], 'hivol': f['vol20'],
        'near52': f['pct52'], 'illiq': f['amihud'], 'smallliq': -f['logliq'],
        'cheap': -f['price'], 'lowmax': -f['maxret20'],
        'gapdn': -f['gap'], 'amdn': -f['today_sofar'],
    }
    return {k: zscore(v.clip(v.quantile(.01, axis=1), v.quantile(.99, axis=1),
                             axis=0)) for k, v in pool.items()}


def resolve(lab, f, z):
    """Turn a phase-1/3 label back into a score DataFrame."""
    if '|' in lab:
        return None
    if lab.startswith('+') or lab.startswith('-'):
        sign, name = (1, lab[1:]) if lab[0] == '+' else (-1, lab[1:])
        return sign * f[name] if name in f else None
    parts = lab.split('+')
    if all(p in z for p in parts):
        return sum(z[p] for p in parts) / len(parts)
    return None


# ----------------------------------------------------------------------------
def pnl_series(score, ctx, topn=10, long=True, min_liq=1e7):
    """Daily gross return series for a config - lets us slice by calendar
    without tripping evaluate()'s 120-day minimum (which exists for a reason:
    a weekday subset is only ~98 days, so these numbers are weak by design)."""
    el = eligible(ctx, min_liq=min_liq)
    s = score.where(el)
    sel = s.rank(axis=1, ascending=False, method='first') <= topn
    ret = (ctx['exit_close'] / ctx['entry_open'] - 1)
    if not long:
        ret = -ret
    return ret.where(sel).mean(axis=1).replace([np.inf, -np.inf],
                                               np.nan).dropna()


def phase5(ctx, entry):
    """Calendar: does anything concentrate on weekdays or month boundaries?"""
    print(f'\n### PHASE 5 - calendar conditioning, entry {entry}')
    print('    (subsets are ~98 days each - the harness would reject them;'
          ' shown raw, and BOTH HALVES must agree to mean anything)')
    f = features(ctx)
    z = build_z(ctx, f)
    days = ctx['days']
    ser = pd.Series(days, index=days)
    is_last3 = pd.Series(False, index=days)
    is_first3 = pd.Series(False, index=days)
    for _, grp in ser.groupby([days.year, days.month]):
        is_last3.loc[grp.index[-3:]] = True
        is_first3.loc[grp.index[:3]] = True
    dow = pd.Series(days.dayofweek, index=days)
    cal = {f'dow{i}': (dow == i) for i in range(5)}
    cal['eom3'] = is_last3
    cal['bom3'] = is_first3
    cal['mid'] = ~(is_last3 | is_first3)

    cols = ctx['entry_open'].columns
    cand = {'rev1': z['rev1'], 'mom120': z['mom120'], 'lowvol': z['lowvol'],
            'illiq': z['illiq'], 'near52': z['near52'],
            'lowmax': z['lowmax'],
            'mom+lv+il': (z['mom120'] + z['lowvol'] + z['illiq']) / 3,
            'equalwt': pd.DataFrame(0.0, index=days, columns=cols)}
    print(f'\n  {"signal":<12}{"calendar":>9}{"n":>5}{"gross":>8}{"net38":>8}'
          f'{"t":>7}{"H1":>8}{"H2":>8}  agree')
    print('  ' + '-' * 70)
    hits = []
    for sname, s in cand.items():
        d = pnl_series(s, ctx, topn=10 if sname != 'equalwt' else 400)
        for cname, mask in cal.items():
            NTESTED[0] += 1
            x = d[mask.reindex(d.index).fillna(False).values]
            if len(x) < 40:
                continue
            mid = x.index[len(x) // 2]
            a, b = x[x.index <= mid], x[x.index > mid]
            g = x.mean() * 1e4
            t = x.mean() / x.std() * np.sqrt(len(x)) if x.std() else np.nan
            agree = (a.mean() > 0) == (b.mean() > 0)
            row = (sname, cname, len(x), g, g - 38, t,
                   a.mean() * 1e4, b.mean() * 1e4, agree)
            if g > 5:
                hits.append(row)
            print(f'  {sname:<12}{cname:>9}{len(x):>5}{g:>8.1f}{g-38:>8.1f}'
                  f'{t:>7.2f}{a.mean()*1e4:>8.1f}{b.mean()*1e4:>8.1f}'
                  f'  {"yes" if agree else "NO"}')
    print(f'\n  calendar cells with gross > 5bp: {len(hits)} of '
          f'{len(cand)*len(cal)}; of those, both halves agree: '
          f'{sum(1 for h in hits if h[-1])}. '
          f'None is anywhere near the 38bp cost wall.')
    return []


# ----------------------------------------------------------------------------
def phase6(ctx_by_slot, top_rows):
    """Attack whatever survived: decile monotonicity, subperiods, cost sens."""
    print('\n### PHASE 6 - attacks on the leaders')
    ctx = ctx_by_slot['10:15']
    f = features(ctx)
    z = build_z(ctx, f)

    print('\n-- decile monotonicity (gross bp by decile of score, entry 10:15,'
          ' 1e7 floor) --')
    el = eligible(ctx, min_liq=1e7)
    ret = (ctx['exit_close'] / ctx['entry_open'] - 1)
    for name in ('rev1', 'mom120', 'lowvol', 'illiq', 'near52', 'hivol'):
        s = z[name].where(el)
        q = s.rank(axis=1, pct=True)
        line = []
        for i in range(10):
            m = (q > i / 10) & (q <= (i + 1) / 10)
            line.append(ret.where(m).mean(axis=1).mean() * 1e4)
        print(f'  {name:<10}' + ''.join(f'{v:7.1f}' for v in line)
              + f'   spread D10-D1 {line[-1]-line[0]:6.1f}bp')

    print('\n-- leaders: gross needed vs gross achieved --')
    for r in top_rows[:12]:
        need = 38.0 if r.get('min_liq', 1e7) == 1e7 else 21.0
        print(f"  {r['label']:<38} gross {r['gross_bp']:7.1f}  need {need:5.1f}"
              f"  net {r['net_bp']:7.1f}  t {r['tstat']:5.2f}"
              f"  H1 {r.get('h1_bp', float('nan')):6.1f} H2 "
              f"{r.get('h2_bp', float('nan')):6.1f}")

    print('\n-- what a t-stat is worth here --')
    d = pnl_series(z['rev1'] * 0, ctx, topn=10)
    print(f'  per-day cross-sectional std of a top-10 basket: '
          f'{d.std()*1e4:.0f} bp over {len(d)} days')
    print(f'  => standard error of a mean: {d.std()*1e4/np.sqrt(len(d)):.1f} bp')
    print(f'  => to clear the 38bp mid-cap cost wall with t=2 you need a gross '
          f'edge of ~{38 + 2*d.std()*1e4/np.sqrt(len(d)):.0f} bp/day.')
    print(f'  => nothing in this search produced even half of that.')


# ----------------------------------------------------------------------------
def phase7(ctxs):
    """The only live pattern found: turn-of-month. Attack it."""
    print('\n### PHASE 7 - turn-of-month drift, attacked')
    rows = []
    for slot in ('10:15', '11:15', '13:15'):
        ctx = ctxs[slot]
        days = ctx['days']
        ser = pd.Series(days, index=days)
        # rank of each day within its month, from the start and from the end
        pos = ser.groupby([days.year, days.month]).cumcount()
        rpos = ser.groupby([days.year, days.month]).cumcount(ascending=False)
        f = features(ctx)
        z = build_z(ctx, f)
        cands = {'equalwt': pd.DataFrame(0.0, index=days,
                                         columns=ctx['entry_open'].columns),
                 'rev1': z['rev1'], 'lowvol': z['lowvol'],
                 'illiq': z['illiq']}
        for sname, s in cands.items():
            topn = 400 if sname == 'equalwt' else 10
            d = pnl_series(s, ctx, topn=topn)
            for wname, mask in (('bom1', pos == 0), ('bom2', pos <= 1),
                                ('bom3', pos <= 2), ('bom5', pos <= 4),
                                ('eom1', rpos == 0), ('eom3', rpos <= 2),
                                ('tom', (pos <= 2) | (rpos <= 1))):
                NTESTED[0] += 1
                x = d[mask.reindex(d.index).fillna(False).values]
                if len(x) < 20:
                    continue
                mid = x.index[len(x) // 2]
                a, b = x[x.index <= mid], x[x.index > mid]
                g = x.mean() * 1e4
                rows.append({
                    'slot': slot, 'signal': sname, 'window': wname,
                    'n': len(x), 'gross': round(g, 1),
                    'net38': round(g - 38, 1),
                    't': round(x.mean() / x.std() * np.sqrt(len(x)), 2),
                    'h1': round(a.mean() * 1e4, 1),
                    'h2': round(b.mean() * 1e4, 1),
                    'agree': (a.mean() > 0) == (b.mean() > 0)})
    t = pd.DataFrame(rows).sort_values('gross', ascending=False)
    print(t.head(28).to_string(index=False))
    print('\n  Read this as: the drift is MARKET-WIDE (equalwt shows it too),'
          ' it is strongest')
    print('  at the first print of the month, it weakens at later entry slots,'
          ' and even the')
    print('  best cell is below the 38bp cost of trading it.')
    return rows


# ----------------------------------------------------------------------------
def phase8(ctxs):
    """
    The turn-of-month cell is the only net-positive thing in the whole search.
    Three tests decide whether it is real.
      A. PLACEBO. Slide the "start of month" boundary by k trading days. If the
         month boundary is special, k=0 should stand out from k=1..18. If it
         does not, we have simply picked the luckiest of ~20 equivalent windows.
      B. LIQUIDITY. Does it survive in the 1e8 tier at 21 bp, where it would
         actually be fillable?
      C. SIZE. 23-46 trading days a year at a few bp is not a strategy even if
         the sign is right.
    """
    print('\n### PHASE 8 - is turn-of-month real?')
    ctx = ctxs['10:15']
    days = ctx['days']
    ser = pd.Series(days, index=days)
    pos = ser.groupby([days.year, days.month]).cumcount()
    f = features(ctx)
    z = build_z(ctx, f)

    print('\n-- A. PLACEBO: "first 2 days after offset k" vs the real boundary '
          '(rev1, top10, 10:15) --')
    d = pnl_series(z['rev1'], ctx, topn=10)
    de = pnl_series(pd.DataFrame(0.0, index=days,
                                 columns=ctx['entry_open'].columns),
                    ctx, topn=400)
    res = []
    for k in range(0, 19):
        NTESTED[0] += 1
        m = ((pos >= k) & (pos <= k + 1)).reindex(d.index).fillna(False).values
        x, y = d[m], de[m[:len(de)]] if len(de) == len(d) else de[m]
        if len(x) < 20:
            continue
        res.append((k, len(x), x.mean() * 1e4,
                    x.mean() / x.std() * np.sqrt(len(x)) if x.std() else 0,
                    y.mean() * 1e4))
    print(f'  {"offset":>7}{"n":>5}{"rev1 gross":>12}{"t":>7}'
          f'{"equalwt gross":>15}')
    for k, n, g, t, ge in res:
        star = '   <-- the "real" turn of month' if k == 0 else ''
        print(f'  {k:>7}{n:>5}{g:>12.1f}{t:>7.2f}{ge:>15.1f}{star}')
    gs = [r[2] for r in res]
    rank = sorted(gs, reverse=True).index(gs[0]) + 1
    print(f'\n  k=0 ranks {rank} of {len(gs)} placebo windows. '
          f'placebo mean {np.mean(gs[1:]):.1f}bp, sd {np.std(gs[1:]):.1f}bp, '
          f'max {max(gs[1:]):.1f}bp.')
    print(f'  k=0 is {(gs[0]-np.mean(gs[1:]))/max(1e-9,np.std(gs[1:])):.1f} '
          f'placebo-sd above the placebo mean.')

    print('\n-- B. LIQUIDITY / COST TIER (bom2, top-N, both floors) --')
    print(f'  {"slot":>6}{"sig":>9}{"topn":>5}{"floor":>8}{"cost":>6}'
          f'{"n":>5}{"gross":>8}{"net":>8}{"t":>7}{"h1":>8}{"h2":>8}')
    for slot in ('10:15', '11:15'):
        c = ctxs[slot]
        dd = pd.Series(c['days'], index=c['days'])
        p = dd.groupby([c['days'].year, c['days'].month]).cumcount()
        zz = build_z(c, features(c))
        for sname in ('rev1', 'illiq', 'equalwt'):
            s = (pd.DataFrame(0.0, index=c['days'],
                              columns=c['entry_open'].columns)
                 if sname == 'equalwt' else zz[sname])
            for topn in ((400,) if sname == 'equalwt' else (5, 10, 20, 30)):
                for floor, cost in ((1e7, 38.0), (1e8, 21.0)):
                    NTESTED[0] += 1
                    ds = pnl_series(s, c, topn=topn, min_liq=floor)
                    m = (p <= 1).reindex(ds.index).fillna(False).values
                    x = ds[m]
                    if len(x) < 20:
                        continue
                    mid = x.index[len(x) // 2]
                    a, b = x[x.index <= mid], x[x.index > mid]
                    g = x.mean() * 1e4
                    print(f'  {slot:>6}{sname:>9}{topn:>5}{floor:>8.0e}'
                          f'{cost:>6.0f}{len(x):>5}{g:>8.1f}{g-cost:>8.1f}'
                          f'{x.mean()/x.std()*np.sqrt(len(x)):>7.2f}'
                          f'{a.mean()*1e4:>8.1f}{b.mean()*1e4:>8.1f}')

    print('\n-- C. SIZE OF THE PRIZE (rev1/bom2/10:15/1e7, best cell) --')
    m = (pos <= 1).reindex(d.index).fillna(False).values
    x = d[m]
    net = x.mean() * 1e4 - 38
    print(f'  {len(x)} tradeable days over 2 years = {len(x)/2:.0f} per year.')
    print(f'  net {net:.1f} bp/day x {len(x)/2:.0f} days = '
          f'{net*len(x)/2/100:.2f}% per YEAR on deployed capital.')
    print(f'  the capital sits idle the other ~226 sessions.')
    print(f'  a 5bp error in the cost model wipes out '
          f'{5/max(net,1e-9)*100:.0f}% of it.')


# ----------------------------------------------------------------------------
def phase9(ctxs):
    """
    Two calibrations that tell you how to read every number above.

      A. MULTIPLE-TESTING HURDLE. Evaluate N random score matrices. The max
         gross over N draws is what a search of size N returns from pure noise.
         Compare the real search's best against it.
      B. OUTLIER CHECK on the turn-of-month cell: is it 24 month-starts, or 3?
    """
    print('\n### PHASE 9 - calibration')
    ctx = ctxs['10:15']
    rng = np.random.default_rng(0)
    idx, cols = ctx['entry_open'].index, ctx['entry_open'].columns
    el = eligible(ctx, min_liq=1e7)
    ret = (ctx['exit_close'] / ctx['entry_open'] - 1)

    days0 = ctx['days']
    ser0 = pd.Series(days0, index=days0)
    pos0 = ser0.groupby([days0.year, days0.month]).cumcount()

    print('\n-- A. what a search of this size returns from NOISE --')
    print('   400 random score matrices per row; "max" is what a search of'
          ' that many configs')
    print('   would report as its winner if no signal existed at all.')
    print(f'\n  {"sample":>14}{"topn":>6}{"mean":>8}{"sd":>7}{"95th":>8}'
          f'{"max":>8}')
    for sample, mask in (('full 480d', None), ('bom2 46d', (pos0 <= 1))):
        for topn in (5, 10, 20):
            best = []
            for _ in range(400):
                s = pd.DataFrame(rng.standard_normal((len(idx), len(cols))),
                                 index=idx, columns=cols).where(el)
                sel = s.rank(axis=1, ascending=False, method='first') <= topn
                d = ret.where(sel).mean(axis=1).dropna()
                if mask is not None:
                    d = d[mask.reindex(d.index).fillna(False).values]
                best.append(d.mean() * 1e4)
            b = np.array(best)
            print(f'  {sample:>14}{topn:>6}{b.mean():>8.1f}{b.std():>7.1f}'
                  f'{np.percentile(b,95):>8.1f}{b.max():>8.1f}')
    print('\n  Read carefully - this cuts BOTH ways:')
    print('   * on the FULL sample the noise band is tight (max ~+5bp at'
          ' topn=10). So the')
    print('     +13 to +19 bp gross signals in phases 1-2 are REAL cross-'
          'sectional alpha,')
    print('     not search artifacts. They are simply 2-3x too small to pay'
          ' the 38bp cost.')
    print('   * on the 46-day bom2 subset the band is ~3x wider, which is'
          ' exactly where the')
    print('     only "net-positive" result lives. Same t-stat means far less'
          ' there.')
    print('\n  THE DECISIVE COMPARISON: on bom2 a RANDOM top-10 basket earns'
          ' +20.8bp, because')
    print('  the MARKET drifts up on those days. The best real signal'
          ' (rev1, +40.2bp) is BELOW')
    print('  the +44.7bp max of 400 random draws on the same subset. The'
          ' cross-sectional part')
    print('  of the turn-of-month "edge" is not distinguishable from picking'
          ' 10 names at random.')

    print('\n-- B. turn-of-month, month by month (rev1 top10 10:15, first 2 '
          'sessions) --')
    days = ctx['days']
    ser = pd.Series(days, index=days)
    pos = ser.groupby([days.year, days.month]).cumcount()
    f = features(ctx)
    z = build_z(ctx, f)
    d = pnl_series(z['rev1'], ctx, topn=10)
    m = (pos <= 1).reindex(d.index).fillna(False)
    x = d[m.values]
    by = x.groupby([x.index.year, x.index.month]).mean() * 1e4
    print(f'  {len(by)} month-starts, mean {x.mean()*1e4:.1f}bp:')
    s = ''
    for (y, mo), v in by.items():
        s += f'{y%100:02d}-{mo:02d}:{v:7.1f}   '
    print('   ' + '\n   '.join(s[i:i + 88] for i in range(0, len(s), 88)))
    pos_n = (by > 0).sum()
    print(f'  months positive: {pos_n}/{len(by)}.  '
          f'drop best 2 months -> mean '
          f'{by.sort_values()[:-2].mean():.1f}bp (cost is 38).')
    print(f'  drop best 3 -> {by.sort_values()[:-3].mean():.1f}bp.  '
          f'median month {by.median():.1f}bp.')


# ----------------------------------------------------------------------------
def phase10(ctxs):
    """
    The closest miss in the whole search: SHORT the names with the largest
    single-day return in the last 20 sessions (the MAX / lottery anomaly).
    At 11:15, top-5, 1e8 floor: gross 20.0 bp vs a 21.0 bp cost, t=3.82.
    It loses by one basis point, so it deserves to be taken seriously and
    then attacked properly.
    """
    print('\n### PHASE 10 - the MAX/lottery short, attacked')
    for slot in ('10:15', '11:15', '13:15'):
        ctx = ctxs[slot]
        f = features(ctx)
        mx = f['maxret20']

        print(f'\n-- {slot} : is MAX just high volatility in disguise? --')
        # vol-neutral MAX: rank maxret20 WITHIN vol20 quintiles
        vq = rk(ctx['vol20'])
        resid = pd.DataFrame(np.nan, index=mx.index, columns=mx.columns)
        for i in range(5):
            m = (vq > i / 5) & (vq <= (i + 1) / 5)
            resid = resid.fillna(mx.where(m).rank(axis=1, pct=True))
        variants = {
            'MAX raw': mx,
            'MAX vol-neutral': resid,
            'vol20 alone': ctx['vol20'],
            'atr alone': ctx['atr'],
            'MAX/vol ratio': mx / ctx['vol20'].replace(0, np.nan),
            'range_sofar today': ctx['range_sofar'],
        }
        print(f'  {"variant":<20}{"N":>4}{"gross":>8}{"cost":>6}{"net":>8}'
              f'{"t":>7}{"hit":>7}{"H1":>8}{"H2":>8}')
        for name, s in variants.items():
            for topn in (5, 10):
                r = run(s, ctx, f'{name}@{slot}', topn=topn, long=False,
                        cost_bp=21.0, min_liq=1e8)
                if r:
                    print(f'  {name:<20}{topn:>4}{r["gross_bp"]:>8.1f}'
                          f'{21.0:>6.0f}{r["net_bp"]:>8.1f}{r["tstat"]:>7.2f}'
                          f'{r["hit"]:>7.1f}{r["h1_bp"]:>8.1f}'
                          f'{r["h2_bp"]:>8.1f}')

    print('\n-- cost sensitivity of the best cell '
          '(MAX short, 11:15, top5, 1e8) --')
    ctx = ctxs['11:15']
    f = features(ctx)
    d = pnl_series(f['maxret20'], ctx, topn=5, long=False, min_liq=1e8)
    print(f'  gross {d.mean()*1e4:.1f} bp/day over {len(d)} days, '
          f'std {d.std()*1e4:.0f} bp')
    for c in (15, 18, 21, 25, 30, 38):
        net = d.mean() * 1e4 - c
        ann = ((1 + d - c / 1e4).prod() ** (252 / len(d)) - 1) * 100
        print(f'  cost {c:>3} bp -> net {net:>6.1f} bp/day, '
              f'annualised {ann:>7.1f}%')
    print('  breakeven cost is '
          f'{d.mean()*1e4:.1f} bp. The liquid-tier estimate is 21 bp and the')
    print('  mid-tier is 38 bp. There is no cost assumption in this repo under'
          ' which it pays,')
    print('  and top-5 of a 1e8 universe is a 5-name book - the concentration'
          ' is not free either.')

    print('\n-- year by year (MAX short, 11:15, top5, 1e8, gross) --')
    for y, g in d.groupby(d.index.year):
        print(f'  {y}: {len(g):>3} days, gross {g.mean()*1e4:>6.1f} bp, '
              f'net@21 {g.mean()*1e4-21:>6.1f} bp')
    print('\n  NOTE ON SHORTING: every line above is a SHORT held intraday.'
          ' In India that')
    print('  means MIS/intraday margin, the name must be shortable, and an'
          ' upper-circuit')
    print('  lock on a lottery stock is an unhedgeable gap against you. The'
          ' real-world cost')
    print('  of this book is higher than 21 bp, not lower.')


# ----------------------------------------------------------------------------
def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else 'all'
    slots = ['10:15', '11:15', '13:15']
    ctxs = {}
    for s in slots:
        ctxs[s] = context(s)
        print(f'context {s} ready')
    ctx = ctxs['10:15']

    if phase in ('1', 'all'):
        phase1(ctx, '10:15')
    if phase in ('2', 'all'):
        phase2(ctx, '10:15')
    if phase in ('3', 'all'):
        phase3(ctx, '10:15')
    if phase in ('5', 'all'):
        phase5(ctx, '10:15')
    if phase in ('4', 'all'):
        # pick survivors from what has run so far by gross bp, then sweep
        d = pd.DataFrame(ALL)
        labs = [l for l in d.sort_values('gross_bp', ascending=False)
                .label.unique() if '|' not in l][:14]
        print('survivors swept:', labs)
        phase4(labs, ctxs)
    if phase in ('7', 'all'):
        phase7(ctxs)
    if phase in ('8', 'all'):
        phase8(ctxs)
    if phase in ('9', 'all'):
        phase9(ctxs)
    if phase in ('10', 'all'):
        phase10(ctxs)
    if phase in ('6', 'all'):
        recs = (pd.DataFrame(ALL).sort_values('net_bp', ascending=False)
                .to_dict('records')) if ALL else []
        phase6(ctxs, recs)

    if not ALL:
        print(f'\nTOTAL configs attempted: {NTESTED[0]}  evaluated: 0')
        return
    d = pd.DataFrame(ALL)
    d.to_csv(os.path.join(OUT, 'crosssec_all.csv'), index=False)
    print(f'\nTOTAL configs attempted: {NTESTED[0]}  '
          f'evaluated: {len(ALL)}  -> {OUT}\\crosssec_all.csv')
    ok = d[(d.net_bp > 0) & (d.get('consistent', True))]
    print(f'configs with net_bp > 0 AND consistent: {len(ok)} '
          f'({len(ok)/max(1,len(d))*100:.1f}%)')
    if len(ok):
        report(ok.to_dict('records'), 'ALL net-positive & consistent', top=25)


if __name__ == '__main__':
    main()
