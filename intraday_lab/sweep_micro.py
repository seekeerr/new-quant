"""
Volume/microstructure family + market-neutral (long-short) shapes.

Two things the other families do not cover:

1. VOLUME AND PARTICIPATION as the signal itself, rather than as a filter.
2. LONG-SHORT. Every long-only intraday result fights the fact that the average
   stock drifts -20.9 bp from open to close. A long-short book cancels that
   drift, so a signal with no absolute edge can still have a real spread. It
   also doubles the cost, which is the catch.

Long-short caveat stated up front: intraday shorting in Indian equities needs
margin and is only practical in F&O-eligible names; a cash-segment short must be
squared off the same day, which this shape does anyway. Cost is charged on BOTH
legs, so the hurdle is 2x.

    py -m intraday_lab.sweep_micro
"""
import sys
import io
import os
import time

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from intraday_lab.harness import (context, evaluate, eligible, zscore, report,
                                  OUT, SLOTS)


def ls_evaluate(score, ctx, topn=10, cost_bp=38.0, label='',
                min_price=20.0, min_liq=1e7):
    """
    Long the top N, short the bottom N, equal weight each side.
    Cost is charged on BOTH legs, so the hurdle is 2 x cost_bp.
    """
    el = eligible(ctx, min_price, min_liq)
    s = score.where(el)
    up = s.rank(axis=1, ascending=False, method='first') <= topn
    dn = s.rank(axis=1, ascending=True, method='first') <= topn
    ret = (ctx['exit_close'] / ctx['entry_open'] - 1)

    L = ret.where(up).mean(axis=1)
    S = ret.where(dn).mean(axis=1)
    d = (L - S).replace([np.inf, -np.inf], np.nan).dropna()
    n = up.sum(axis=1)
    d = d[n.reindex(d.index).fillna(0) >= max(3, topn // 3)]
    if len(d) < 120:
        return None

    hurdle = cost_bp * 2
    bp = d.mean() * 1e4
    mid = d.index[len(d) // 2]
    a, b = d[d.index <= mid], d[d.index > mid]
    return {
        'label': label, 'days': len(d), 'topn': topn, 'side': 'L/S',
        'gross_bp': round(bp, 2), 'net_bp': round(bp - hurdle, 2),
        'hit': round((d > 0).mean() * 100, 1),
        'std_bp': round(d.std() * 1e4, 1),
        'tstat': round(d.mean() / d.std() * np.sqrt(len(d)), 2) if d.std() else np.nan,
        'ann_net': round((((1 + d - hurdle / 1e4).prod()) ** (252 / len(d)) - 1)
                         * 100, 1),
        'h1_bp': round(a.mean() * 1e4, 2), 'h2_bp': round(b.mean() * 1e4, 2),
        'consistent': bool((a.mean() > 0) == (b.mean() > 0)),
    }


def main():
    t0 = time.time()
    rows, n_cfg = [], 0

    for entry in ('10:15', '11:15', '13:15'):
        ctx = context(entry)
        z = zscore

        feats = {
            'vol_ratio': ctx.get('vol_ratio'),
            'vol_sofar': ctx.get('vol_sofar'),
            'illiq': -ctx['liq'],
            'range_sofar': ctx.get('range_sofar'),
            'pos_in_range': ctx.get('pos_in_range'),
            'today_sofar': ctx.get('today_sofar'),
            'gap': ctx['gap'],
            'vol20': ctx['vol20'],
            'd1': ctx['d1'],
            'd5': ctx['d5'],
        }
        # participation vs the move: high volume but small move = absorption
        if ctx.get('vol_ratio') is not None and ctx.get('today_sofar') is not None:
            feats['vol_per_move'] = (ctx['vol_ratio'] /
                                     ctx['today_sofar'].abs().replace(0, np.nan))
            feats['move_per_vol'] = (ctx['today_sofar'].abs() /
                                     ctx['vol_ratio'].replace(0, np.nan))
            feats['signed_vol'] = (np.sign(ctx['today_sofar']) * ctx['vol_ratio'])
        if ctx.get('range_sofar') is not None:
            feats['range_vs_atr'] = (ctx['range_sofar'] /
                                     ctx['atr'].replace(0, np.nan))

        feats = {k: v for k, v in feats.items() if v is not None}

        for name, f in feats.items():
            for topn in (5, 10, 20):
                for liq, cost in ((1e7, 38.0), (1e8, 21.0)):
                    tag = f'{name}@{entry}'
                    for sign, sl in ((1, ''), (-1, '_inv')):
                        n_cfg += 1
                        r = evaluate(sign * f, ctx, topn=topn, long=True,
                                     cost_bp=cost, min_liq=liq,
                                     label=f'{tag}{sl}/L{int(liq/1e7)}')
                        if r:
                            rows.append(r)
                    n_cfg += 1
                    r = ls_evaluate(f, ctx, topn=topn, cost_bp=cost,
                                    min_liq=liq, label=f'{tag}/LS{int(liq/1e7)}')
                    if r:
                        rows.append(r)

        # two-factor z-score blends, long-short only (drift-neutral)
        keys = [k for k in ('today_sofar', 'vol_ratio', 'gap', 'pos_in_range',
                            'd1', 'range_vs_atr') if k in feats]
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                for w in (0.5,):
                    blend = w * z(feats[a]) + (1 - w) * z(feats[b])
                    for topn in (10, 20):
                        n_cfg += 1
                        r = ls_evaluate(blend, ctx, topn=topn, cost_bp=38.0,
                                        label=f'{a}+{b}@{entry}/LS')
                        if r:
                            rows.append(r)
        print(f'  {entry}: {n_cfg} configs so far ({time.time()-t0:.0f}s)',
              flush=True)

    d = report(rows, 'MICROSTRUCTURE + LONG-SHORT', top=20)
    d.to_csv(os.path.join(OUT, 'micro_ls.csv'), index=False)

    pos = d[(d.net_bp > 0) & (d.consistent)]
    print(f'\n  configs tested        : {n_cfg}')
    print(f'  net-positive AND consistent across halves: {len(pos)}')
    if len(pos):
        print('\n  survivors:')
        for _, r in pos.head(10).iterrows():
            print(f"    {r.label:<34} net {r.net_bp:>7.1f} bp  "
                  f"t {r.tstat:>5.2f}  H1 {r.h1_bp:>6.1f} H2 {r.h2_bp:>6.1f}")
        # multiple-testing reality check
        import math
        exp_max = math.sqrt(2 * math.log(max(n_cfg, 2)))
        print(f'\n  With {n_cfg} configs the expected max |t| under pure noise '
              f'is ~{exp_max:.2f}.')
        print(f'  Best t here is {d.tstat.max():.2f} - '
              f'{"ABOVE" if d.tstat.max() > exp_max else "BELOW"} that bar.')
    else:
        print('  nothing survived both filters.')
    print(f'\n  saved -> {OUT}/micro_ls.csv   ({time.time()-t0:.0f}s)')


if __name__ == '__main__':
    main()
