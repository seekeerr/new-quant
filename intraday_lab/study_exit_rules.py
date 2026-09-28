"""
Exit when the STRATEGY says, not when the bell rings.

Every test so far used a fixed exit - h bars later, or at the close. That was a
real gap. This walks each position bar by bar and exits on a rule:

  close      hold to the close (the baseline everything else used)
  tp         take profit at +X%
  sl         stop loss at -X%
  tp+sl      whichever comes first
  trail      exit when price falls X% from its running high
  signal     exit on the first DOWN bar (momentum broke)
  vwap       exit when price closes below the day's VWAP

anything not triggered still exits at the close - no overnight carry.

INTRABAR HONESTY: when a bar's high clears the target AND its low breaches the
stop, we do not know which came first, so this assumes the STOP filled. Same
for trailing vs target. Every ambiguity is resolved against the strategy, so
these numbers are a floor, not a hope.

Stops also assume you get filled AT the stop price. In a fast move you do not.
That makes the stop variants optimistic in a way the close-exit baseline is not.
"""
import sys, io, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
if __name__ == '__main__':   # importing this module must not touch stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                  errors='replace')
from intraday_lab import harness_fine as HF

COST = 21.0


def panel(interval):
    d = HF.load(interval)
    npd = HF.bars_per_day(d)
    pos = d['date'].groupby(d['date']).cumcount()
    return d, npd, pos


def walk(d, npd, pos, entry_pos, picks_fn, rule, param):
    """Simulate every day: pick names at entry_pos, walk bars, apply `rule`."""
    O, Hi, Lo, C, V = d['open'], d['high'], d['low'], d['close'], d['volume']
    date = d['date']
    idx = C.index
    days = sorted(date.unique())
    out = []

    for day in days:
        rows = np.where((date == day).values)[0]
        if len(rows) < entry_pos + 3:
            continue
        e = rows[entry_pos]
        names = picks_fn(idx[e])
        if len(names) < 3:
            continue
        path = rows[entry_pos:]
        rets, bars_held = [], []
        for s in names:
            ent = O.iat[e, C.columns.get_loc(s)]
            if not np.isfinite(ent) or ent <= 0:
                continue
            col = C.columns.get_loc(s)
            runmax = -np.inf
            px_exit, held = None, 0
            for j, b in enumerate(path):
                hi, lo, cl = Hi.iat[b, col], Lo.iat[b, col], C.iat[b, col]
                if not np.isfinite(cl):
                    continue
                held = j + 1
                runmax = max(runmax, hi if np.isfinite(hi) else cl)
                if rule == 'sl' or rule == 'tp+sl':
                    stop = ent * (1 - param[0] / 100)
                    if np.isfinite(lo) and lo <= stop:      # stop wins ties
                        px_exit = stop
                        break
                if rule == 'tp' or rule == 'tp+sl':
                    tgt = ent * (1 + (param[1] if rule == 'tp+sl' else param[0]) / 100)
                    if np.isfinite(hi) and hi >= tgt:
                        px_exit = tgt
                        break
                if rule == 'trail':
                    tstop = runmax * (1 - param[0] / 100)
                    if np.isfinite(lo) and lo <= tstop and j > 0:
                        px_exit = min(tstop, cl) if lo <= tstop else tstop
                        break
                if rule == 'signal' and j > 0:
                    if cl < C.iat[path[j - 1], col]:
                        px_exit = cl
                        break
                if rule == 'vwap' and j > 0:
                    sub = slice(rows[0], b + 1)
                    vv = V.iloc[sub, col].values
                    cc = C.iloc[sub, col].values
                    tot = np.nansum(vv)
                    if tot > 0:
                        vw = np.nansum(cc * vv) / tot
                        if cl < vw:
                            px_exit = cl
                            break
            if px_exit is None:
                px_exit = C.iat[path[-1], col]
            if np.isfinite(px_exit):
                rets.append(px_exit / ent - 1)
                bars_held.append(held)
        if len(rets) >= 3:
            out.append((pd.Timestamp(day), float(np.mean(rets)),
                        float(np.mean(bars_held))))
    if not out:
        return None
    r = pd.DataFrame(out, columns=['day', 'ret', 'held']).set_index('day')
    return r


def make_picker(d, pos, entry_pos, lookback, topn):
    C, O = d['close'], d['open']
    date = d['date']
    el = HF.eligible(d, drop_first=1, drop_last=0)
    # close of bar t vs the OPEN `lookback-1` bars back. Anchoring on an open
    # keeps the window inside the day even on the day's first bar; a
    # close-to-close window there reaches into yesterday and gets masked away,
    # which silently emptied every pick on the 1h panel.
    r = C / O.shift(lookback - 1) - 1
    r = r.where(HF.bcast(date.shift(lookback - 1) == date, r)).shift(1)
    sc = r.where(el)

    def pick(ts):
        if ts not in sc.index:
            return []
        row = sc.loc[ts].dropna()
        return list(row.sort_values(ascending=False).index[:topn])
    return pick


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', default='15m')
    a = ap.parse_args()
    d, npd, pos = panel(a.interval)
    entry_pos = {'15m': 4, '1h': 1}[a.interval]      # 10:15 either way
    lookback = {'15m': 2, '1h': 1}[a.interval]
    pick = make_picker(d, pos, entry_pos, lookback, 5)

    rules = [('close', None), ('signal', None), ('vwap', None)]
    rules += [('sl', (x,)) for x in (0.5, 1.0, 1.5, 2.0)]
    rules += [('tp', (x,)) for x in (0.5, 1.0, 1.5, 2.0)]
    rules += [('trail', (x,)) for x in (0.3, 0.5, 0.75, 1.0, 1.5)]
    rules += [('tp+sl', (sl, tp)) for sl in (0.5, 1.0) for tp in (0.5, 1.0, 2.0)]

    print(f'  {a.interval}  entry 10:15  top-5 momentum  exit rule varies '
          f'(cost {COST} bp)')
    print(f'  {"exit rule":<18}{"days":>6}{"gross":>9}{"net":>8}{"hit%":>7}'
          f'{"t":>7}{"bars held":>11}{"H1":>8}{"H2":>8}')
    print('  ' + '-' * 84)
    base = None
    for rule, param in rules:
        r = walk(d, npd, pos, entry_pos, pick, rule, param)
        if r is None or len(r) < 30:
            continue
        b = r.ret
        g = b.mean() * 1e4
        mid = b.index[len(b) // 2]
        h1, h2 = b[b.index <= mid].mean() * 1e4, b[b.index > mid].mean() * 1e4
        t = b.mean() / b.std() * np.sqrt(len(b))
        tag = rule if param is None else f'{rule} {"/".join(str(x) for x in param)}%'
        if rule == 'close':
            base = g
        print(f'  {tag:<18}{len(b):>6}{g:>+9.1f}{g-COST:>+8.1f}'
              f'{(b>0).mean()*100:>7.1f}{t:>7.2f}{r.held.mean():>11.1f}'
              f'{h1:>+8.1f}{h2:>+8.1f}')
    print(f'\n  baseline (hold to close) = {base:+.1f} bp gross')


if __name__ == '__main__':
    main()
