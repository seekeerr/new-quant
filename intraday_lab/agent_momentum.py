"""
INTRADAY MOMENTUM AND REVERSAL WITHIN THE SESSION
=================================================

Question: does what a stock did earlier today predict what it does for the rest
of today?

Every strategy here: at entry slot E, rank eligible symbols by a score built only
from bars strictly before E (plus E's own open), buy/short the top N at E's open,
exit at the 15:15 close. Costs charged every day (21 bp liquid / 38 bp mid).

Run:
    py -m intraday_lab.agent_momentum            # everything (~3 min)
    py -m intraday_lab.agent_momentum 1 2 3      # selected batches

Batches
  1  single features, 10:15, long and short
  2  vol-normalised and rank-transformed variants
  3  bar structure: first bar vs cumulative, acceleration, reversal-of-reversal
  4  pos_in_range and range/volume features
  5  conditional / interaction screens (only trade when X)
  6  two- and three-way z-score blends
  7  entry-slot sweep for the survivors
  8  topn / liquidity / cost sweep for the survivors
  9  robustness attack on anything that looks good
"""
import sys
import itertools
import numpy as np
import pandas as pd

sys.path.insert(0, '.')
from intraday_lab.harness import (context, evaluate, zscore, report, SLOTS,
                                  COST_BP, eligible)

ENTRIES = ['10:15', '11:15', '12:15', '13:15']
_CTX = {}


def ctx_for(slot):
    if slot not in _CTX:
        _CTX[slot] = context(slot)
    return _CTX[slot]


def nbars(slot):
    return SLOTS.index(slot)


# ----------------------------------------------------------------- features
def features(ctx, slot):
    """Named score DataFrames. Sign convention: raw feature, not 'attractive'.
    evaluate() buys the HIGHEST, so a mirror is tested by negating."""
    k = nbars(slot)
    f = {}
    ts = ctx['today_sofar']
    v20 = ctx['vol20'].replace(0, np.nan)

    f['today_sofar'] = ts
    f['ts_over_vol20'] = ts / v20
    f['ts_over_atr'] = ts / ctx['atr'].replace(0, np.nan)
    f['ts_over_range'] = ts / ctx['range_sofar'].replace(0, np.nan)
    f['ts_rank'] = ts.rank(axis=1, pct=True)
    f['ts_abs'] = ts.abs()
    f['ts_ex_gap'] = ts - ctx['gap'].fillna(0)          # intraday move excl. gap
    f['ts_ex_gap_vol'] = (ts - ctx['gap'].fillna(0)) / v20

    f['gap'] = ctx['gap']
    f['gap_over_vol20'] = ctx['gap'] / v20
    f['entry_gap'] = ctx['entry_gap']
    f['entry_gap_vol'] = ctx['entry_gap'] / v20

    f['pos_in_range'] = ctx['pos_in_range']
    f['range_sofar'] = ctx['range_sofar']
    f['range_over_atr'] = ctx['range_sofar'] / ctx['atr'].replace(0, np.nan)
    f['vol_ratio'] = ctx['vol_ratio']
    f['log_vol_ratio'] = np.log(ctx['vol_ratio'].replace(0, np.nan))

    for j in range(k):
        f[f'slot_ret_{j}'] = ctx[f'slot_ret_{j}']
        f[f'slot_ret_{j}_vol'] = ctx[f'slot_ret_{j}'] / v20
    if k >= 2:
        last, prev = ctx[f'slot_ret_{k-1}'], ctx[f'slot_ret_{k-2}']
        f['accel'] = last - prev                       # 2nd bar stronger?
        f['accel_vol'] = (last - prev) / v20
        f['last_bar'] = last
        f['last_bar_vol'] = last / v20
        f['both_bars_up'] = ((last > 0).astype(float) + (prev > 0).astype(float)
                             + ts.rank(axis=1, pct=True))
        f['reverse_then_go'] = (-prev).where(last * prev < 0, np.nan)
    f['d1'] = ctx['d1']
    f['d5'] = ctx['d5']
    return f


# ------------------------------------------------------------------ helpers
def run(score, ctx, label, **kw):
    return evaluate(score, ctx, label=label, **kw)


def batch(pairs, ctx, topn=10, cost_bp=38.0, min_liq=1e7, sides=(True, False)):
    rows = []
    for name, s in pairs:
        for lg in sides:
            r = run(s, ctx, name, topn=topn, long=lg, cost_bp=cost_bp,
                    min_liq=min_liq)
            if r:
                rows.append(r)
    return rows


ALL = []


def show(rows, title, top=18):
    ALL.extend([r for r in rows if r])
    return report(rows, title, top=top)


# ================================================================== batch 1
def batch1():
    ctx = ctx_for('10:15')
    f = features(ctx, '10:15')
    rows = batch(list(f.items()), ctx, topn=10)
    show(rows, 'B1  single features, entry 10:15, top10, mid cost 38bp')
    return rows


# ================================================================== batch 2
def batch2():
    """Normalisation variants of the core intraday move."""
    ctx = ctx_for('11:15')
    f = features(ctx, '11:15')
    rows = batch(list(f.items()), ctx, topn=10)
    show(rows, 'B2  single features, entry 11:15, top10')
    return rows


# ================================================================== batch 3
def batch3():
    """Bar structure at 13:15 where there are 4 completed bars."""
    out = []
    for slot in ('12:15', '13:15'):
        ctx = ctx_for(slot)
        k = nbars(slot)
        f = {}
        v20 = ctx['vol20'].replace(0, np.nan)
        rets = [ctx[f'slot_ret_{j}'] for j in range(k)]
        f['sum_all_bars'] = sum(rets)
        f['sum_all_vol'] = sum(rets) / v20
        f['last_minus_first'] = rets[-1] - rets[0]
        f['last2_minus_first'] = (rets[-1] + rets[-2]) - rets[0]
        f['first_only'] = rets[0]
        f['first_only_vol'] = rets[0] / v20
        f['ex_first'] = sum(rets[1:])
        f['ex_first_vol'] = sum(rets[1:]) / v20
        f['n_up_bars'] = sum((r > 0).astype(float) for r in rets)
        f['monotone_up'] = sum((r > 0).astype(float) for r in rets) \
            + ctx['today_sofar'].rank(axis=1, pct=True)
        f['bar_dispersion'] = pd.concat(rets).groupby(level=0).std() \
            if False else None
        f.pop('bar_dispersion')
        f['accel'] = rets[-1] - rets[-2]
        f['accel_vol'] = (rets[-1] - rets[-2]) / v20
        f['wavg_recent'] = sum((j + 1) * r for j, r in enumerate(rets)) / v20
        f['wavg_early'] = sum((k - j) * r for j, r in enumerate(rets)) / v20
        rows = batch(list(f.items()), ctx, topn=10)
        show(rows, f'B3  bar structure, entry {slot}, top10')
        out += rows
    return out


# ================================================================== batch 4
def batch4():
    """Position in range / range / volume, all entries."""
    out = []
    for slot in ENTRIES:
        ctx = ctx_for(slot)
        v20 = ctx['vol20'].replace(0, np.nan)
        pir = ctx['pos_in_range']
        f = {
            'pos_in_range': pir,
            'pir_x_range': pir * ctx['range_sofar'],
            'pir_x_volratio': pir * ctx['vol_ratio'],
            'near_hi': (ctx['entry_open'] / ctx['hi_sofar'] - 1),
            'near_lo': (ctx['entry_open'] / ctx['lo_sofar'] - 1),
            'range_sofar': ctx['range_sofar'],
            'range_over_vol': ctx['range_sofar'] / v20,
            'vol_ratio': ctx['vol_ratio'],
            'volratio_x_ts': ctx['vol_ratio'].rank(axis=1, pct=True)
                             * ctx['today_sofar'].rank(axis=1, pct=True),
            'volratio_x_rev': ctx['vol_ratio'].rank(axis=1, pct=True)
                              * (-ctx['today_sofar']).rank(axis=1, pct=True),
        }
        rows = batch(list(f.items()), ctx, topn=10)
        show(rows, f'B4  range/volume features, entry {slot}, top10', top=10)
        out += rows
    return out


# ================================================================== batch 5
def batch5():
    """Conditional screens: trade the signal only inside a filtered subset."""
    out = []
    for slot in ('10:15', '11:15', '12:15'):
        ctx = ctx_for(slot)
        v20 = ctx['vol20'].replace(0, np.nan)
        ts = ctx['today_sofar']
        tsv = ts / v20
        pr = lambda x: x.rank(axis=1, pct=True)
        conds = {
            'hivol': pr(ctx['vol_ratio']) > .7,
            'lovol': pr(ctx['vol_ratio']) < .3,
            'wide_range': pr(ctx['range_sofar']) > .7,
            'narrow_range': pr(ctx['range_sofar']) < .3,
            'biggap': ctx['gap'].abs() > 0.015,
            'smallgap': ctx['gap'].abs() < 0.005,
            'gapdown': ctx['gap'] < -0.005,
            'gapup': ctx['gap'] > 0.005,
            'd5up': ctx['d5'] > 0,
            'd5dn': ctx['d5'] < 0,
            'd20up': ctx['d20'] > 0,
            'd20dn': ctx['d20'] < 0,
            'near52h': ctx['pct52'] > .9,
            'far52h': ctx['pct52'] < .75,
            'hivol20': pr(ctx['vol20']) > .7,
            'lovol20': pr(ctx['vol20']) < .3,
            'pir_hi': ctx['pos_in_range'] > .7,
            'pir_lo': ctx['pos_in_range'] < .3,
        }
        pairs = []
        for cname, c in conds.items():
            pairs.append((f'tsv|{cname}', tsv.where(c)))
            pairs.append((f'-tsv|{cname}', (-tsv).where(c)))
        rows = batch(pairs, ctx, topn=10, sides=(True,))
        show(rows, f'B5  conditional intraday mom/rev, entry {slot}, top10',
             top=12)
        out += rows
    return out


# ================================================================== batch 6
def batch6():
    """Z-score blends."""
    out = []
    for slot in ('10:15', '11:15', '12:15'):
        ctx = ctx_for(slot)
        v20 = ctx['vol20'].replace(0, np.nan)
        base = {
            'tsv': zscore(ctx['today_sofar'] / v20),
            'pir': zscore(ctx['pos_in_range']),
            'vr': zscore(np.log(ctx['vol_ratio'].replace(0, np.nan))),
            'rng': zscore(ctx['range_sofar'] / v20),
            'gapv': zscore(ctx['gap'] / v20),
            'd5': zscore(ctx['d5']),
            'd20': zscore(ctx['d20']),
            'v20': zscore(ctx['vol20']),
            'p52': zscore(ctx['pct52']),
        }
        pairs = []
        keys = list(base)
        for a, b in itertools.combinations(keys, 2):
            for wa in (1, -1):
                for wb in (1, -1):
                    if (a, wa, b, wb) and wa == -1 and wb == -1:
                        continue      # pure mirror of (+,+), evaluate covers it
                    pairs.append((f'{wa:+d}{a}{wb:+d}{b}',
                                  wa * base[a] + wb * base[b]))
        rows = batch(pairs, ctx, topn=10, sides=(True, False))
        show(rows, f'B6  2-way z blends, entry {slot}, top10', top=12)
        out += rows

        # 3-way around the two strongest 2-way ingredients
        tri = []
        for a, b, c in itertools.combinations(['tsv', 'pir', 'vr', 'rng',
                                               'gapv', 'd5'], 3):
            for sg in itertools.product((1, -1), repeat=3):
                if sg[0] == -1:
                    continue
                tri.append((f'{sg[0]:+d}{a}{sg[1]:+d}{b}{sg[2]:+d}{c}',
                            sg[0] * base[a] + sg[1] * base[b] + sg[2] * base[c]))
        rows = batch(tri, ctx, topn=10, sides=(True, False))
        show(rows, f'B6b 3-way z blends, entry {slot}, top10', top=12)
        out += rows
    return out


# ================================================================== batch 7/8
def sweep(pairs_fn, title):
    """pairs_fn(ctx, slot) -> [(name, score)]; sweep slot x topn x side x liq."""
    rows = []
    for slot in ENTRIES:
        ctx = ctx_for(slot)
        for name, s in pairs_fn(ctx, slot):
            for topn in (5, 10, 20, 30):
                for lg in (True, False):
                    for liq, cb in ((1e7, 38.0), (1e8, 21.0)):
                        tag = 'mid' if liq == 1e7 else 'liq'
                        r = run(s, ctx, f'{name}@{slot}.{tag}', topn=topn,
                                long=lg, cost_bp=cb, min_liq=liq)
                        if r:
                            rows.append(r)
    show(rows, title, top=25)
    return rows


# ================================================================== batch 7
def invented(ctx, slot):
    """Features beyond the brief: VWAP distance, market-relative move,
    opening-range breakout, streaks, outlier reversal."""
    from intraday_lab.harness import load, bars_before
    data, days = load()
    O, H, L, C, V = (data[k] for k in ('open', 'high', 'low', 'close', 'volume'))
    before = bars_before(slot)
    v20 = ctx['vol20'].replace(0, np.nan)
    ts = ctx['today_sofar']
    eo = ctx['entry_open']

    tpv = sum(((H[s] + L[s] + C[s]) / 3) * V[s] for s in before)
    vv = sum(V[s] for s in before).replace(0, np.nan)
    vwap = tpv / vv
    mkt = ts.mean(axis=1)
    beta = ctx['vol20'].div(ctx['vol20'].median(axis=1), axis=0)

    f = {
        'vwap_dist': (eo / vwap - 1),
        'vwap_dist_vol': (eo / vwap - 1) / v20,
        'mkt_rel': ts.sub(mkt, axis=0),
        'mkt_rel_vol': ts.sub(mkt, axis=0) / v20,
        'beta_resid': ts - beta.mul(mkt, axis=0),
        'beta_resid_vol': (ts - beta.mul(mkt, axis=0)) / v20,
        'orb_up': (eo / ctx['hi_sofar'] - 1).clip(lower=0) * 1e4
                  + ts.rank(axis=1, pct=True),
        'orb_dn': (ctx['lo_sofar'] / eo - 1).clip(lower=0) * 1e4
                  + (-ts).rank(axis=1, pct=True),
        'outlier_rev': (-ts / v20).where((ts / v20).abs() > 2),
        'outlier_mom': (ts / v20).where((ts / v20).abs() > 2),
        'ts_x_volratio': (ts / v20) * np.log(ctx['vol_ratio'].clip(lower=.05)),
        'rev_x_volratio': (-ts / v20) * np.log(ctx['vol_ratio'].clip(lower=.05)),
        'gap_then_mom': zscore(ctx['gap'] / v20) + zscore(ts - ctx['gap'].fillna(0)),
        'gap_then_fade': zscore(ctx['gap'] / v20)
                         - zscore(ts - ctx['gap'].fillna(0)),
        'stretch': (eo - vwap) / (ctx['range_sofar'] * ctx['prev_close']),
    }
    if len(before) >= 2:
        rets = [ctx[f'slot_ret_{j}'] for j in range(len(before))]
        f['streak'] = sum(np.sign(r).fillna(0) for r in rets)
        f['streak_x_ts'] = sum(np.sign(r).fillna(0) for r in rets) \
            + (ts / v20).rank(axis=1, pct=True)
    return list(f.items())


def batch7():
    out = []
    for slot in ENTRIES:
        ctx = ctx_for(slot)
        rows = batch(invented(ctx, slot), ctx, topn=10)
        show(rows, f'B7  invented features, entry {slot}, top10', top=12)
        out += rows
    return out


# ---------------------------------------------------------- spread diagnostic
def spread_table(slot='10:15', min_liq=1e7, topn=10):
    """Top-minus-bottom gross spread: the raw predictive power of a feature,
    before any cost. A long/short book earns spread/2 per rupee of gross and
    pays cost on BOTH legs, so it needs spread > 2 x cost."""
    ctx = ctx_for(slot)
    f = features(ctx, slot)
    f.update(dict(invented(ctx, slot)))
    rows = []
    for name, s in f.items():
        a = evaluate(s, ctx, topn=topn, long=True, cost_bp=0, min_liq=min_liq,
                     label=name)
        b = evaluate(-s, ctx, topn=topn, long=False, cost_bp=0, min_liq=min_liq,
                     label=name)
        if a and b:
            rows.append({'feature': name, 'top_bp': a['gross_bp'],
                         'bot_bp': -b['gross_bp'],
                         'spread_bp': round(a['gross_bp'] + b['gross_bp'], 2),
                         't_top': a['tstat'], 'h1': a.get('h1_bp'),
                         'h2': a.get('h2_bp')})
    d = pd.DataFrame(rows).sort_values('spread_bp', key=abs, ascending=False)
    print(f'\n--- top-minus-bottom spread, entry {slot}, top{topn}, '
          f'liq>={min_liq:.0e} (cost hurdle for L/S = 2x21=42 or 2x38=76 bp) ---')
    print(d.head(20).to_string(index=False))
    return d


# ================================================================== batch 8
def candidates(ctx, slot):
    """The signals that showed the largest raw effect, for the full sweep."""
    v20 = ctx['vol20'].replace(0, np.nan)
    ts = ctx['today_sofar']
    c = {
        'ts': ts,
        'tsv': ts / v20,
        'sr0': ctx['slot_ret_0'],
        'sr0v': ctx['slot_ret_0'] / v20,
        'pir': ctx['pos_in_range'],
        'vr': np.log(ctx['vol_ratio'].replace(0, np.nan)),
        'd5': ctx['d5'],
        'rev_x_vr': (-ts / v20) * np.log(ctx['vol_ratio'].clip(lower=.05)),
        'z_v20_m_pir': zscore(ctx['vol20']) - zscore(ctx['pos_in_range']),
        'z_tsv_m_pir_p_d5': (zscore(ts / v20) - zscore(ctx['pos_in_range'])
                             + zscore(ctx['d5'])),
    }
    k = nbars(slot)
    if k >= 2:
        c['accel'] = ctx[f'slot_ret_{k-1}'] - ctx[f'slot_ret_{k-2}']
        c['last_m_first'] = ctx[f'slot_ret_{k-1}'] - ctx['slot_ret_0']
    return list(c.items())


def batch8():
    rows = []
    tiers = ((1e7, 38.0, 'mid'), (1e8, 21.0, 'liq'), (1e9, 21.0, 'top'))
    for slot in ENTRIES:
        ctx = ctx_for(slot)
        for name, s in candidates(ctx, slot):
            for topn in (5, 10, 20, 30):
                for lg in (True, False):
                    for liq, cb, tag in tiers:
                        r = run(s, ctx, f'{name}@{slot}.{tag}', topn=topn,
                                long=lg, cost_bp=cb, min_liq=liq)
                        if r:
                            rows.append(r)
    show(rows, 'B8  full sweep: slot x topn x side x liquidity tier', top=30)
    d = pd.DataFrame(rows)
    print(f'\n  configs in sweep: {len(d)} | net_bp > 0: {(d.net_bp > 0).sum()} '
          f'| net_bp > 0 AND consistent: '
          f'{((d.net_bp > 0) & d.consistent).sum()}')
    print(f'  best gross in whole sweep: {d.gross_bp.max():.1f} bp '
          f'(hurdle 21 liquid / 38 mid)')
    return rows


# ================================================================== batch 9
def turnover_of(score, ctx, topn=10, min_liq=1e8):
    """Fraction of the basket that changes from one day to the next.
    A low number means the daily cost is being paid to re-buy the same names."""
    el = eligible(ctx, 20.0, min_liq)
    rk = score.where(el).rank(axis=1, ascending=False, method='first')
    sel = rk <= topn
    prev = sel.shift(1)
    keep = (sel & prev).sum(axis=1) / sel.sum(axis=1).replace(0, np.nan)
    return float(1 - keep.mean())


def batch9():
    """Attack the leaders: decompose, stability by year-quarter, turnover."""
    print('\n' + '=' * 104)
    print('  B9  ATTACK ON THE LEADERS')
    print('=' * 104)

    # --- 1. decompose the best blend into its two ingredients
    ctx = ctx_for('11:15')
    parts = {
        'v20 alone': ctx['vol20'],
        'pir alone (neg)': -ctx['pos_in_range'],
        'v20 - pir (blend)': zscore(ctx['vol20']) - zscore(ctx['pos_in_range']),
        'tsv alone (neg)': -(ctx['today_sofar'] / ctx['vol20'].replace(0, np.nan)),
        'sr0 alone (neg)': -ctx['slot_ret_0'],
    }
    rows = [run(s, ctx, n, topn=5, long=False, cost_bp=21.0, min_liq=1e8)
            for n, s in parts.items()]
    report(rows, 'B9a decomposition of the best blend (short, top5, liq tier)')

    # --- 2. is the intraday part load-bearing at all?
    print('\n  Intraday-only component (no vol20, no prior-day): short the top5 by'
          '\n  today_sofar/vol20, liquid tier, every entry slot:')
    for slot in ENTRIES:
        c = ctx_for(slot)
        r = run(c['today_sofar'] / c['vol20'].replace(0, np.nan), c,
                f'tsv@{slot}', topn=5, long=False, cost_bp=21.0, min_liq=1e8)
        if r:
            print(f'    {slot}  gross {r["gross_bp"]:6.1f}  net {r["net_bp"]:6.1f}'
                  f'  t {r["tstat"]:5.2f}  H1 {r["h1_bp"]:6.1f}  H2 {r["h2_bp"]:6.1f}')

    # --- 3. quarterly stability of the single best config
    ctx = ctx_for('11:15')
    best = zscore(ctx['vol20']) - zscore(ctx['pos_in_range'])
    el = eligible(ctx, 20.0, 1e8)
    rk = best.where(el).rank(axis=1, ascending=False, method='first')
    sel = rk <= 5
    ret = -(ctx['exit_close'] / ctx['entry_open'] - 1)
    d = ret.where(sel).mean(axis=1).dropna()
    q = d.groupby(pd.PeriodIndex(d.index, freq='Q')).agg(['mean', 'count'])
    q['gross_bp'] = (q['mean'] * 1e4).round(1)
    q['net_bp'] = (q['gross_bp'] - 21).round(1)
    print('\n  B9c quarterly gross/net of the single best config '
          '(z_v20_m_pir @11:15, short, top5, liq):')
    print(q[['count', 'gross_bp', 'net_bp']].to_string())

    # --- 4. turnover: are we paying daily cost for a static book?
    print('\n  B9d daily basket turnover (fraction of names replaced each day):')
    for n, s in [('z_v20_m_pir', best),
                 ('vol20', ctx['vol20']),
                 ('today_sofar/vol20', ctx['today_sofar']
                  / ctx['vol20'].replace(0, np.nan)),
                 ('slot_ret_0', ctx['slot_ret_0'])]:
        print(f'    {n:<22}{turnover_of(s, ctx, 5):6.1%}   (top5)   '
              f'{turnover_of(s, ctx, 20):6.1%}  (top20)')

    # --- 5. cost breakeven
    print('\n  B9e break-even: what round-trip cost would the best config need?')
    print('    best gross found anywhere in this family: 19.1 bp/day')
    print('    actual round trip: 21 bp liquid, 38 bp mid -> needs costs cut '
          '~10-50%')


# ================================================================= batch 10
def batch10():
    """The one real intraday effect: asymmetric continuation.
    Winners do nothing; losers keep losing. Is it big enough, and is it real?"""
    print('\n' + '=' * 104)
    print('  B10  ASYMMETRY: do intraday winners continue, or only losers?')
    print('=' * 104)
    print('  gross bp, top10 basket, liq>=1e8. "long winners" = buy the top of '
          'the feature;\n  "short losers" = short the bottom. Hurdle 21 bp each.')
    print(f'\n  {"feature":<16}{"slot":>7}{"long winners":>15}{"short losers":>15}'
          f'{"spread":>9}{"t(short)":>10}{"H1":>8}{"H2":>8}')
    print('  ' + '-' * 88)
    rows = []
    for name in ('slot_ret_0', 'today_sofar', 'ts_ex_gap', 'tsv'):
        for slot in ENTRIES:
            ctx = ctx_for(slot)
            v20 = ctx['vol20'].replace(0, np.nan)
            s = {'slot_ret_0': ctx['slot_ret_0'],
                 'today_sofar': ctx['today_sofar'],
                 'ts_ex_gap': ctx['today_sofar'] - ctx['gap'].fillna(0),
                 'tsv': ctx['today_sofar'] / v20}[name]
            a = run(s, ctx, f'{name}@{slot}.L', topn=10, long=True,
                    cost_bp=21.0, min_liq=1e8)
            b = run(-s, ctx, f'{name}@{slot}.S', topn=10, long=False,
                    cost_bp=21.0, min_liq=1e8)
            if a and b:
                rows += [a, b]
                print(f'  {name:<16}{slot:>7}{a["gross_bp"]:>15.1f}'
                      f'{b["gross_bp"]:>15.1f}'
                      f'{a["gross_bp"]+b["gross_bp"]:>9.1f}{b["tstat"]:>10.2f}'
                      f'{b["h1_bp"]:>8.1f}{b["h2_bp"]:>8.1f}')
    ALL.extend(rows)

    # full sweep of the loser-continuation short
    sw = []
    for slot in ENTRIES:
        ctx = ctx_for(slot)
        v20 = ctx['vol20'].replace(0, np.nan)
        cands = {'-sr0': -ctx['slot_ret_0'], '-ts': -ctx['today_sofar'],
                 '-tsv': -(ctx['today_sofar'] / v20),
                 '-ts_x_vr': -(ctx['today_sofar'] / v20)
                             * np.log(ctx['vol_ratio'].clip(lower=.05))}
        for n, s in cands.items():
            for topn in (5, 10, 20, 30):
                for liq, cb, tag in ((1e7, 38.0, 'mid'), (1e8, 21.0, 'liq'),
                                     (1e9, 21.0, 'top')):
                    r = run(s, ctx, f'{n}@{slot}.{tag}', topn=topn, long=False,
                            cost_bp=cb, min_liq=liq)
                    if r:
                        sw.append(r)
    show(sw, 'B10b loser-continuation short: full sweep', top=15)

    # control: is it just high-vol names?
    print('\n  B10c control - short intraday losers INSIDE a volatility bucket'
          '\n  (if the effect is only in the high-vol half it is a vol tilt, '
          'not intraday info):')
    ctx = ctx_for('11:15')
    pr = ctx['vol20'].rank(axis=1, pct=True)
    for bname, mask in (('low-vol half', pr <= .5), ('high-vol half', pr > .5)):
        r = run((-ctx['slot_ret_0']).where(mask), ctx, bname, topn=10,
                long=False, cost_bp=21.0, min_liq=1e8)
        if r:
            print(f'    {bname:<16}gross {r["gross_bp"]:6.1f}  net '
                  f'{r["net_bp"]:6.1f}  t {r["tstat"]:5.2f}  H1 {r["h1_bp"]:6.1f}'
                  f'  H2 {r["h2_bp"]:6.1f}')
    print('\n  B10d control - same, inside a liquidity bucket:')
    for lname, liq in (('liq>=1e8 (311)', 1e8), ('liq>=1e9 (136)', 1e9),
                       ('liq>=3e9 (32)', 3e9)):
        r = run(-ctx['slot_ret_0'], ctx, lname, topn=10, long=False,
                cost_bp=21.0, min_liq=liq)
        if r:
            print(f'    {lname:<16}gross {r["gross_bp"]:6.1f}  net '
                  f'{r["net_bp"]:6.1f}  t {r["tstat"]:5.2f}  H1 {r["h1_bp"]:6.1f}'
                  f'  H2 {r["h2_bp"]:6.1f}')
    return sw


# ================================================================= batch 11
def batch11():
    """Day-level regime conditioning: does intraday continuation only work on
    certain kinds of day? (Masks whole rows, so the day count drops.)"""
    out = []
    for slot in ('10:15', '11:15', '12:15'):
        ctx = ctx_for(slot)
        v20 = ctx['vol20'].replace(0, np.nan)
        ts = ctx['today_sofar']
        mkt = ts.mean(axis=1)                       # market move so far today
        disp = ts.std(axis=1)                       # cross-sectional dispersion
        mgap = ctx['gap'].mean(axis=1)
        mvol = ctx['vol20'].median(axis=1)
        dow = pd.Series(ctx['days'].dayofweek, index=ctx['days'])
        # NOTE: thresholds must be knowable on the day. A full-sample
        # quantile is look-ahead, so every cut here is either a fixed number
        # or an EXPANDING quantile of strictly prior days.
        def exq(x, q):
            return x.expanding(min_periods=60).quantile(q).shift(1)
        regimes = {
            'mkt_up': mkt > 0, 'mkt_dn': mkt < 0,
            'mkt_bigup': mkt > exq(mkt, .75),
            'mkt_bigdn': mkt < exq(mkt, .25),
            'mkt_up50bp': mkt > 0.005, 'mkt_dn50bp': mkt < -0.005,
            'hi_disp': disp > exq(disp, .5), 'lo_disp': disp <= exq(disp, .5),
            'mkt_gapup': mgap > 0, 'mkt_gapdn': mgap < 0,
            'hi_volreg': mvol > exq(mvol, .5), 'lo_volreg': mvol <= exq(mvol, .5),
            'mon_tue': dow <= 1, 'thu_fri': dow >= 3,
        }
        sig = {'mom_long': (ts / v20, True),
               'rev_long': (-(ts / v20), True),
               'loser_short': (-ctx['slot_ret_0'], False),
               'winner_short': (ctx['slot_ret_0'], False)}
        pairs = []
        for rn, rm in regimes.items():
            for sn, (s, lg) in sig.items():
                pairs.append((f'{sn}|{rn}', s.where(rm, axis=0), lg))
        rows = []
        for n, s, lg in pairs:
            for topn in (10, 20):
                r = run(s, ctx, n, topn=topn, long=lg, cost_bp=21.0,
                        min_liq=1e8)
                if r:
                    rows.append(r)
        show(rows, f'B11 day-regime conditioning, entry {slot}, liq tier',
             top=12)
        out += rows
    return out


# ===================================================================== main
def main(which=None):
    order = [batch1, batch2, batch3, batch4, batch5, batch6, batch7,
             batch8, batch9, batch10, batch11, batch12]
    sel = order if not which else [order[int(i) - 1] for i in which]
    for fn in sel:
        fn()
    if len(ALL) > 50:
        d = pd.DataFrame(ALL)
        print('\n' + '=' * 104)
        print(f'  GRAND TOTAL CONFIGS EVALUATED: {len(d)}')
        print(f'  net_bp > 0                   : {(d.net_bp > 0).sum()}')
        print(f'  net_bp > 0 and consistent    : '
              f'{((d.net_bp > 0) & d.consistent.fillna(False)).sum()}')
        print(f'  best gross_bp anywhere       : {d.gross_bp.max():.1f}')
        print(f'  best net_bp anywhere         : {d.net_bp.max():.1f}')
        print('=' * 104)
        report(ALL, 'GLOBAL TOP 15 BY NET BP (all batches)', top=15)
        d.to_csv('results/intraday_lab/agent_momentum_all.csv', index=False)
        print('\n  saved results/intraday_lab/agent_momentum_all.csv')




# ================================================================= batch 12
def batch12():
    """Autopsy of the single best config found anywhere in this family:
    short the top-5 first-hour losers at 11:15, on low-dispersion days,
    liquid tier. It is the only thing that printed a positive net number."""
    print('\n' + '=' * 104)
    print('  B12  AUTOPSY: -slot_ret_0 @11:15, short, top5, liq>=1e8, '
          'low-dispersion days')
    print('=' * 104)
    ctx = ctx_for('11:15')
    ts = ctx['today_sofar']
    disp = ts.std(axis=1)

    def dmask(q=.5, lag=0):
        x = disp.shift(lag)
        return x <= x.expanding(min_periods=60).quantile(q).shift(1)

    el = eligible(ctx, 20.0, 1e8)

    def pnl(score, topn=5, mask=None, c=ctx, liq=1e8):
        s = score if mask is None else score.where(mask, axis=0)
        e = eligible(c, 20.0, liq)
        sel = s.where(e).rank(axis=1, ascending=False, method='first') <= topn
        return (-(c['exit_close'] / c['entry_open'] - 1)).where(sel) \
            .mean(axis=1).dropna() * 1e4

    print('\n  a) threshold sensitivity (gross bp, hurdle 21):')
    for q in (.3, .4, .5, .6, .7, .8):
        d = pnl(-ctx['slot_ret_0'], mask=dmask(q))
        print(f'     disp<=q{q}  n={len(d):>4}  gross {d.mean():6.1f}  '
              f'net {d.mean()-21:6.1f}')
    d = pnl(-ctx['slot_ret_0'],
            mask=~dmask(.5).fillna(False) & disp.notna())
    print(f'     HIGH-disp   n={len(d):>4}  gross {d.mean():6.1f}  '
          f'net {d.mean()-21:6.1f}   <- effect is entirely on calm days')

    print('\n  b) basket-size sensitivity and the t-stat that matters '
          '(t of NET, not gross):')
    for topn in (3, 5, 7, 10, 20):
        d = pnl(-ctx['slot_ret_0'], topn=topn, mask=dmask())
        n = d - 21
        print(f'     top{topn:<3} gross {d.mean():6.1f}  net {n.mean():6.1f}  '
              f'std {d.std():5.0f}  t_net {n.mean()/n.std()*np.sqrt(len(n)):5.2f}')
    print('     Bonferroni over ~3,000 configs needs t ~ 4.3. Best t_net = 1.05.')

    print('\n  c) strictly LAGGED regime (yesterday\'s dispersion - no same-day '
          'peek at all):')
    lm = dmask(.5, lag=1)
    for slot in ENTRIES:
        c = ctx_for(slot)
        d = pnl(-c['slot_ret_0'], mask=lm, c=c)
        print(f'     {slot}  n={len(d):>4}  gross {d.mean():6.1f}  '
              f'net {d.mean()-21:6.1f}')
    print('     The edge evaporates. It needed the same-day dispersion cut, '
          'which is\n     one of 12 regimes tried.')

    print('\n  d) is it an illiquidity artifact? gross by liquidity floor:')
    for liq, lbl in ((1e7, 'Rs 1cr  (326 names)'), (1e8, 'Rs 10cr (311)'),
                     (1e9, 'Rs 100cr (136)'), (3e9, 'Rs 300cr (32)')):
        d = pnl(-ctx['slot_ret_0'], mask=dmask(), liq=liq)
        cb = 38 if liq == 1e7 else 21
        print(f'     {lbl:<22} gross {d.mean():6.1f}  net of {cb}bp '
              f'{d.mean()-cb:6.1f}')

    print('\n  e) the long mirror (buy first-hour winners, same filter): '
          f'{pnl(ctx["slot_ret_0"], mask=dmask()).mean():.1f} bp gross.')
    print('     One-sided. Only losers continue; winners do nothing.')


if __name__ == '__main__':
    main(sys.argv[1:] or None)
