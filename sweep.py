"""
Sweep runner for the discovery campaign.

Runs a named batch of configs on DISCOVERY only, appending each result to
results/campaign/<batch>.csv as it finishes - so a crash or a kill never loses
completed work, and progress can be watched from outside.

    py sweep.py signals       # standalone signal zoo
    py sweep.py structure     # n_stocks / buffer / rebalance / rank_band
    py sweep.py blends        # champion x best signals
    py sweep.py vetoes        # quality filters layered on the champion

HOLDOUT is never touched here. Only adjudicate.py may use it, and only for the
final handful of candidates.
"""
import sys
import io
import os
import time
import traceback

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')

import numpy as np
import pandas as pd

from research_harness import (load_panels, evaluate, champion_scorer,
                              rolling_3y_min)
import signals as S

OUT = 'results/campaign'
os.makedirs(OUT, exist_ok=True)


def run_batch(name, configs):
    """configs: list of (label, scorer, kwargs). Appends rows incrementally."""
    close, high, low, vol, turn = load_panels()
    path = os.path.join(OUT, f'{name}.csv')
    done = set()
    if os.path.exists(path):
        done = set(pd.read_csv(path)['label'])
        print(f'resuming: {len(done)} already done')

    t0 = time.time()
    for i, (label, scorer, kw) in enumerate(configs, 1):
        if label in done:
            continue
        try:
            m = evaluate(scorer, close, high, low, vol, turn,
                         split='discovery', label=label, **kw)
            row = {
                'label': label,
                'cagr': m['cagr'], 'sharpe': m['sharpe'], 'maxdd': m['maxdd'],
                'calmar': m['calmar'], 'roll3y_min': rolling_3y_min(m['returns']),
                'n_trades': m['n_trades'], 'final': m['final'],
                **{k: str(v) for k, v in kw.items()},
            }
        except Exception as e:
            row = {'label': label, 'cagr': np.nan, 'error': str(e)[:120]}
            print(f'  [{i}/{len(configs)}] {label}: ERROR {str(e)[:80]}')
        pd.DataFrame([row]).to_csv(path, mode='a', header=not os.path.exists(path),
                                   index=False)
        if not np.isnan(row.get('cagr', np.nan)):
            print(f'  [{i}/{len(configs)}] {label:<38} '
                  f'CAGR {row["cagr"]*100:6.2f}%  Sh {row["sharpe"]:.2f}  '
                  f'DD {row["maxdd"]*100:6.1f}%  ({time.time()-t0:.0f}s)',
                  flush=True)
    print(f'BATCH {name} DONE in {time.time()-t0:.0f}s -> {path}')


# ── batches ──────────────────────────────────────────────────────────────

def batch_signals(close, high, low, vol, turn):
    """Every signal standalone, at the champion's structure, so the comparison
    isolates the SIGNAL and nothing else."""
    base = dict(n_stocks=10, rebalance='monthly', buffer=20, rank_band=(0, 500))
    c = []
    for form in (63, 126, 189, 252, 378):
        for skip in (0, 21, 42):
            c.append((f'mom_f{form}_s{skip}', S.momentum(form, skip), base))
    for lb in (63, 126, 252):
        c.append((f'lowvol_{lb}', S.low_vol(lb), base))
        c.append((f'lowidio_{lb}', S.low_idio_vol(lb=lb), base))
        c.append((f'lowbeta_{lb}', S.low_beta(lb), base))
    for lb in (21, 63):
        c.append((f'lowmax_{lb}', S.low_max_ret(lb), base))
    c.append(('downdev_252', S.low_downside_dev(252), base))
    for lb in (126, 252, 504):
        c.append((f'prox52wh_{lb}', S.prox_52wh(lb), base))
    for ma in (50, 100, 200):
        c.append((f'distma_{ma}', S.dist_from_ma(ma), base))
    for lb in (1, 3, 5, 10, 21):
        c.append((f'reversal_{lb}', S.reversal(lb), base))
    for lb in (30, 60, 120):
        c.append((f'amihud_{lb}', S.amihud(lb)(turn), base))
    c.append(('turntrend_20_100', S.turnover_trend(20, 100)(turn), base))
    for lb in (30, 60):
        c.append((f'rangevol_{lb}', S.range_vol(lb)(high, low), base))
    for form in (126, 252):
        c.append((f'momcons_f{form}', S.momentum_consistency(form), base))
        for w in (0.3, 0.5, 0.7):
            c.append((f'momxcons_f{form}_w{w}',
                      S.momentum_x_consistency(form, 21, w), base))
    return c


def batch_structure(close, high, low, vol, turn):
    """Champion signal, every structural knob. Tests packaging, not alpha."""
    ch = champion_scorer()
    c = []
    for n in (3, 5, 8, 10, 15, 20, 25, 30):
        c.append((f'champ_n{n}', ch, dict(n_stocks=n, rebalance='monthly',
                                          buffer=20, rank_band=(0, 500))))
    for b in (0, 10, 30, 40, 60):
        c.append((f'champ_buf{b}', ch, dict(n_stocks=10, rebalance='monthly',
                                            buffer=b, rank_band=(0, 500))))
    for rb in ('quarterly',):
        for b in (0, 20, 40):
            c.append((f'champ_{rb}_buf{b}', ch,
                      dict(n_stocks=10, rebalance=rb, buffer=b,
                           rank_band=(0, 500))))
    for band in ((0, 100), (0, 250), (0, 750), (100, 500), (250, 750),
                 (50, 300), (150, 600)):
        c.append((f'champ_band{band[0]}_{band[1]}', ch,
                  dict(n_stocks=10, rebalance='monthly', buffer=20,
                       rank_band=band)))
    return c


def batch_blends(close, high, low, vol, turn):
    """Champion combined with the mechanisms most likely to be independent."""
    mom = S.momentum(252, 21)
    lv = S.low_vol(252)
    c = []
    combos = {
        'prox52': S.prox_52wh(252),
        'lowidio': S.low_idio_vol(lb=252),
        'lowmax': S.low_max_ret(21),
        'rev5': S.reversal(5),
        'momcons': S.momentum_consistency(252),
        'amihud': S.amihud(60)(turn),
        'rangevol': S.range_vol(60)(high, low),
    }
    base = dict(n_stocks=10, rebalance='monthly', buffer=20, rank_band=(0, 500))
    for nm, sig in combos.items():
        for w in (0.25, 0.5):
            c.append((f'mom+lv+{nm}_w{w}',
                      S.blend([(mom, (1 - w) / 2), (lv, (1 - w) / 2), (sig, w)]),
                      base))
    # three-way without low-vol, to see if lowvol is actually pulling weight
    for nm, sig in combos.items():
        c.append((f'mom+{nm}_50', S.blend([(mom, .5), (sig, .5)]), base))
    return c


def batch_vetoes(close, high, low, vol, turn):
    """Quality filters layered on the champion ranking."""
    ch = champion_scorer()
    base = dict(n_stocks=10, rebalance='monthly', buffer=20, rank_band=(0, 500))
    c = []
    bads = {
        'hi_max': S.low_max_ret(21),
        'hi_vol': S.low_vol(63),
        'hi_amihud': S.amihud(60)(turn),
        'extended': S.dist_from_ma(50),
    }
    for nm, bad in bads.items():
        for frac in (0.1, 0.2, 0.3):
            c.append((f'champ_veto_{nm}_{frac}', S.veto(ch, bad, frac), base))
    return c


BATCHES = {
    'signals': batch_signals,
    'structure': batch_structure,
    'blends': batch_blends,
    'vetoes': batch_vetoes,
}


if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'signals'
    close, high, low, vol, turn = load_panels()
    cfgs = BATCHES[which](close, high, low, vol, turn)
    print(f'batch={which}  configs={len(cfgs)}')
    run_batch(which, cfgs)
