"""
OPENING RANGE, BREAKOUTS AND VOLATILITY STRUCTURE
=================================================
Agent family study on the 1h intraday lab data (398 NSE names, 490 days).

Why this file adds its own features instead of only using harness ctx
---------------------------------------------------------------------
Hourly bars are contiguous: O[E] ~= C[E-1] (median difference 0.000). Since
harness `hi_sofar` includes the bar immediately before entry, the entry price
is inside [lo_sofar, hi_sofar] 98.6% of the time. So "rank by distance above
hi_sofar" degenerates into `pos_in_range` and cannot express a real breakout.

A real opening-range breakout freezes the range on the first k bars and then
asks, at a LATER slot, whether price has pushed through it. That is what
`orb_features()` builds:

    OR      = high/low of the first k bars of the day  (k = 1 or 2)
    interim = the bars between the OR and the entry slot
    brk     = (entry_open - or_hi) / or_width      > 0  => broken out, long side
    poke    = (interim_high - or_hi) / or_width    > 0  => traded above the OR
    fail    = poked above but came back below      => failed breakout, fade it

Everything is knowable at the entry slot's open. No bar at or after the entry
slot is read except that open. Entry 09:15 is never used.

Run:  py -m intraday_lab.agent_breakout <phase>
      phases: probe | sweep | attack | all
"""
import sys
import os
import itertools
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intraday_lab.harness import (context, evaluate, zscore, report, load,
                                  SLOTS, EXIT_SLOT, eligible)

pd.options.mode.chained_assignment = None
ENTRIES = ['10:15', '11:15', '12:15', '13:15']


# --------------------------------------------------------------------------
# extra features
# --------------------------------------------------------------------------
_FC = {}


def orb_features(entry_slot, k_or=1):
    """
    Opening-range features with the range frozen on the first `k_or` bars.
    Requires at least one completed bar between the OR and the entry slot,
    otherwise the 'breakout' is just the OR's own closing position.
    """
    key = (entry_slot, k_or)
    if key in _FC:
        return _FC[key]
    data, days = load()
    O, H, L, C, V = (data[x] for x in ('open', 'high', 'low', 'close', 'volume'))
    ei = SLOTS.index(entry_slot)
    or_slots = SLOTS[:k_or]
    interim = SLOTS[k_or:ei]
    eod = C[EXIT_SLOT]
    pc = eod.shift(1)
    eo = O[entry_slot]

    or_hi = pd.concat([H[s] for s in or_slots]).groupby(level=0).max()
    or_lo = pd.concat([L[s] for s in or_slots]).groupby(level=0).min()
    or_w = (or_hi - or_lo).replace(0, np.nan)
    or_open = O[SLOTS[0]]
    or_close = C[or_slots[-1]]

    f = {}
    f['or_hi'], f['or_lo'], f['or_w'] = or_hi, or_lo, or_w
    f['or_w_pc'] = or_w / pc                      # OR width as % of prev close
    f['or_ret'] = or_close / or_open - 1          # direction of the OR itself
    f['or_close_pos'] = (or_close - or_lo) / or_w

    # true daily range -> a proper volatility normaliser (10d mean, shifted)
    full_h = pd.concat([H[s] for s in SLOTS]).groupby(level=0).max()
    full_l = pd.concat([L[s] for s in SLOTS]).groupby(level=0).min()
    trng = ((full_h - full_l) / eod)
    f['atr_true'] = trng.shift(1).rolling(10, min_periods=5).mean()
    f['atr20'] = trng.shift(1).rolling(20, min_periods=10).mean()
    f['or_w_sig'] = f['or_w_pc'] / f['atr_true'].replace(0, np.nan)
    # OR width vs this stock's OWN typical OR width (20d)
    f['or_w_rel'] = f['or_w_pc'] / (f['or_w_pc'].shift(1)
                                    .rolling(20, min_periods=8).median()
                                    .replace(0, np.nan))

    # ---- breakout state at the entry open -------------------------------
    f['brk_up'] = (eo - or_hi) / or_w             # >0 long breakout
    f['brk_dn'] = (or_lo - eo) / or_w             # >0 short breakdown
    f['pos_in_or'] = (eo - or_lo) / or_w          # unclipped: >1 = above OR
    f['brk_up_pc'] = (eo / or_hi - 1)             # breakout size in % of price
    f['brk_dn_pc'] = (or_lo / eo - 1)
    f['brk_up_sig'] = f['brk_up_pc'] / f['atr_true'].replace(0, np.nan)
    f['brk_dn_sig'] = f['brk_dn_pc'] / f['atr_true'].replace(0, np.nan)

    if interim:
        ih = pd.concat([H[s] for s in interim]).groupby(level=0).max()
        il = pd.concat([L[s] for s in interim]).groupby(level=0).min()
        f['int_hi'], f['int_lo'] = ih, il
        f['poke_up'] = (ih - or_hi) / or_w        # how far above OR it traded
        f['poke_dn'] = (or_lo - il) / or_w
        # failed breakout: poked out then came back inside
        f['fail_up'] = ((f['poke_up'] > 0) & (eo < or_hi)) * 1.0
        f['fail_dn'] = ((f['poke_dn'] > 0) & (eo > or_lo)) * 1.0
        f['giveback_up'] = (ih - eo) / or_w       # retrace from the day's push
        f['giveback_dn'] = (eo - il) / or_w
        f['ext_up'] = f['poke_up'] - f['brk_up']  # poke minus where we are now
    else:
        for kk in ('poke_up', 'poke_dn', 'fail_up', 'fail_dn',
                   'giveback_up', 'giveback_dn', 'ext_up'):
            f[kk] = pd.DataFrame(np.nan, index=days, columns=eo.columns)

    # ---- volume: the 09:15 bar carries volume 0 on 75% of rows in this
    # feed, so any volume feature must start at 10:15 to mean anything.
    vslots = [s for s in SLOTS[:ei] if s != '09:15']
    if vslots:
        vt = sum(V[s] for s in vslots)
        base = vt.shift(1).rolling(20, min_periods=8).median().replace(0, np.nan)
        f['rvol'] = vt / base
        dv = sum(C[s] * V[s] for s in vslots)
        f['dv_sofar'] = dv
    else:
        f['rvol'] = pd.DataFrame(np.nan, index=days, columns=eo.columns)
        f['dv_sofar'] = f['rvol']

    _FC[key] = f
    return f


def turnover_rank(ctx):
    """Rank 1 = most liquid. Used to attack results with a real liquidity test."""
    return ctx['liq'].rank(axis=1, ascending=False, method='first')


def masked(score, cond):
    """Keep score only where cond holds; everything else drops out of the top-N."""
    return score.where(cond)


def dump(rows, path):
    if not rows:
        return
    d = pd.DataFrame([r for r in rows if r])
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'results', 'intraday_lab')
    os.makedirs(out, exist_ok=True)
    d.to_csv(os.path.join(out, path), index=False)
    print(f'  -> {path}  ({len(d)} rows)')


# --------------------------------------------------------------------------
# phase 1 - broad probe
# --------------------------------------------------------------------------
def run_probe(entries=ENTRIES, topn=10, cost=38.0, min_liq=1e7, verbose=True):
    from intraday_lab._battery import battery
    rows = []
    for e in entries:
        ctx = context(e)
        for k in (1, 2):
            if SLOTS.index(e) < k:
                continue
            f = orb_features(e, k)
            bat = battery(ctx, f)
            for name, (sc, L) in bat.items():
                r = evaluate(sc, ctx, topn=topn, long=L, cost_bp=cost,
                             min_liq=min_liq, label=f'{name}|E{e[:2]}|k{k}')
                if r:
                    r.update(sig=name, entry=e, k=k, min_liq=min_liq)
                    rows.append(r)
            if verbose:
                print(f'  probe E={e} k={k}: {len(bat)} signals  (cum {len(rows)})')
    return rows


# --------------------------------------------------------------------------
# phase 2 - full grid: signal x entry x OR length x basket size x liq tier
# --------------------------------------------------------------------------
GRID_LIQ = [(1e7, 38.0), (1e8, 21.0)]   # cost always matched to the floor


def run_sweep(entries=ENTRIES, topns=(5, 10, 20, 30), liqs=GRID_LIQ,
              verbose=True):
    from intraday_lab._battery import battery
    rows = []
    for e in entries:
        ctx = context(e)
        for k in (1, 2):
            if SLOTS.index(e) < k:
                continue
            f = orb_features(e, k)
            bat = battery(ctx, f)
            for (ml, cb) in liqs:
                tag = 'A' if ml < 5e7 else 'B'
                for topn in topns:
                    for name, (sc, L) in bat.items():
                        r = evaluate(sc, ctx, topn=topn, long=L, cost_bp=cb,
                                     min_liq=ml,
                                     label=f'{name}|E{e[:2]}|k{k}|N{topn}|{tag}')
                        if r:
                            r.update(sig=name, entry=e, k=k, min_liq=ml,
                                     cost=cb, tier=tag)
                            rows.append(r)
            if verbose:
                print(f'  sweep E={e} k={k} done  (cum {len(rows)})', flush=True)
    return rows


# --------------------------------------------------------------------------
# phase 3 - attack the survivors
# --------------------------------------------------------------------------
def named_score(ctx, f, name):
    from intraday_lab._battery import battery
    return battery(ctx, f)[name]


def attack(sig_names, topn=10, verbose=True):
    """For each named signal: entry-slot decay, liquidity tiers, sub-periods,
    pick profile, and the slippage yardstick."""
    from intraday_lab import _attack as AT
    out = []
    for name in sig_names:
        print(f'\n{"#"*92}\n#  ATTACK  {name}   (topn={topn})\n{"#"*92}')
        for e in ['10:15', '11:15', '12:15', '13:15', '14:15']:
            ctx = context(e)
            for k in (1, 2):
                if SLOTS.index(e) < k:
                    continue
                f = orb_features(e, k)
                try:
                    sc, L = named_score(ctx, f, name)
                except KeyError:
                    continue
                base = evaluate(sc, ctx, topn=topn, long=L, cost_bp=38.0,
                                min_liq=1e7, label=f'{name}|E{e[:2]}|k{k}|A')
                liq = evaluate(sc, ctx, topn=topn, long=L, cost_bp=21.0,
                               min_liq=1e8, label=f'{name}|E{e[:2]}|k{k}|B')
                t100 = AT.eval_topliq(sc, ctx, 100, topn, L, 21.0,
                                      f'{name}|E{e[:2]}|k{k}')
                t50 = AT.eval_topliq(sc, ctx, 50, topn, L, 21.0,
                                     f'{name}|E{e[:2]}|k{k}')
                sp = AT.subperiods(sc, ctx, topn, L, 38.0, 1e7)
                g = lambda r, key: (r[key] if r else np.nan)
                print(f'  E={e} k={k} side={"L" if L else "S"}  '
                      f'gross {g(base,"gross_bp"):>7.1f} | '
                      f'net(1cr,38) {g(base,"net_bp"):>7.1f} | '
                      f'net(10cr,21) {g(liq,"net_bp"):>7.1f} | '
                      f'top100 gross {g(t100,"gross_bp"):>7.1f} | '
                      f'top50 gross {g(t50,"gross_bp"):>7.1f} | '
                      f'quarters {sp[0] if sp else None}')
                for r, tag in ((base, 'A'), (liq, 'B'), (t100, 'top100'),
                               (t50, 'top50')):
                    if r:
                        r.update(sig=name, entry=e, k=k, variant=tag)
                        out.append(r)
        # pick profile at the family's natural slot
        ctx = context('11:15')
        f = orb_features('11:15', 1)
        try:
            sc, L = named_score(ctx, f, name)
        except KeyError:
            continue
        print('  pick profile (median pick vs median eligible, E=11:15):')
        for kk, (a, b) in AT.pick_profile(sc, ctx, f, topn).items():
            print(f'     {kk:<16} picks {a:>12}   universe {b:>12}')
        print('  slippage yardstick:', AT.bar_range_cost(ctx, sc, topn,
                                                         entry='11:15'))
    return out


def main():
    phase = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if phase in ('probe', 'all'):
        rows = run_probe()
        report(rows, 'PHASE 1 PROBE  topn=10 liq>=1cr cost=38bp', top=25)
        dump(rows, 'brk_probe.csv')
    if phase in ('sweep', 'all'):
        rows = run_sweep()
        report(rows, 'PHASE 2 FULL GRID  entry x OR-len x basket x liq tier', top=25)
        dump(rows, 'brk_sweep.csv')
    if phase in ('deciles', 'all'):
        run_deciles()
    if phase in ('thresh', 'all'):
        rows = run_thresholds()
        report(rows, 'PHASE 4 breakout-size thresholds and conditioning bands',
               top=20)
        dump(rows, 'brk_thresholds.csv')
    if phase in ('attack', 'all'):
        rows = attack(['vol20_hi_sh', 'atr_hi_sh', 'orb_wideOR', 'orb_gapup',
                       'orbT_up', 'orb_up', 'fail_up_sh', 'pos_in_or',
                       'rvol_hi_sh', 'orb_narrowOR'])
        dump(rows, 'brk_attack.csv')
    if phase in ('beta', 'all'):
        run_beta()


def run_beta():
    """Is the best survivor just a short-beta bet? Decompose it."""
    ctx = context('11:15')
    f = orb_features('11:15', 1)
    el = eligible(ctx, 20.0, 1e8)
    ret = (ctx['exit_close'] / ctx['entry_open'] - 1).where(el)
    mkt = ret.mean(axis=1)
    print(f'  equal-weight market drift 11:15->close: '
          f'{mkt.mean() * 1e4:.2f} bp/day')
    for nm, sc, L in (('vol20_hi_sh', ctx['vol20'], False),
                      ('atr_hi_sh', f['atr_true'], False)):
        sel = sc.where(el).rank(axis=1, ascending=False, method='first') <= 10
        d = ret.where(sel).mean(axis=1)
        d = (d if L else -d).dropna()
        m = mkt.reindex(d.index)
        beta = np.polyfit(m, d, 1)[0]
        print(f'  {nm:<14} gross {d.mean()*1e4:6.2f} bp | beta {beta:5.2f} | '
              f'market-neutral alpha {(d - beta*m).mean()*1e4:6.2f} bp')


if __name__ == '__main__':
    main()
