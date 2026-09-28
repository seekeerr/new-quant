"""
Fetch intraday bars for the NSE universe (yfinance) into the isolated lab cache.

WHAT IS ACTUALLY AVAILABLE - measured, not assumed:

    interval   history      bars/day    use
    1m         7 days       ~375        forward collection only
    5m         60 days      75          forward collection only
    15m        60 days      25          forward collection only
    30m        60 days      13          forward collection only
    1h         730 days     7           BACKTESTABLE (2 years)
    1d         decades      1           already in data/cache_bhav

So 1-hour is the only interval with enough history to test anything today.
Everything shorter has to be accumulated going forward: run this on a schedule
and the window keeps sliding, so a year of 15m data takes a year to collect.

TWO BIASES THIS DATA HAS THAT THE DAILY PANELS DO NOT:
  1. Survivorship. yfinance serves currently-listed symbols. Anything delisted
     in the last two years is simply absent, so results here are optimistic in
     a way the bhavcopy spine is not.
  2. Two years is ~500 trading days. Split in half that is ~250 days per side -
     a thin sample for a strategy that trades daily. Treat conclusions as
     provisional.

    py -m intraday_lab.fetch --interval 1h --period 2y --top 400
    py -m intraday_lab.fetch --interval 15m --period 60d --top 200
"""
import sys
import io
import os
import time
import argparse
import warnings

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')
    except Exception:
        pass

import numpy as np
import pandas as pd

CACHE = os.path.join(ROOT, 'data', 'cache_bhav')
OUT = os.path.join(ROOT, 'data', 'cache_intraday')
os.makedirs(OUT, exist_ok=True)

LIMITS = {'1m': 7, '5m': 60, '15m': 60, '30m': 60, '1h': 730, '60m': 730}


def universe(top=400):
    """Most-liquid NSE names by recent median turnover, as yfinance tickers."""
    turn = pd.read_parquet(os.path.join(CACHE, 'raw_turnover.parquet'))
    close = pd.read_parquet(os.path.join(CACHE, 'raw_close.parquet'))
    med = turn.tail(60).median()
    px = close.tail(1).iloc[0]
    ok = med[(med > 0) & (px >= 20)].sort_values(ascending=False)
    syms = list(ok.index[:top])
    return syms


def fetch(syms, interval, period, chunk=60):
    import yfinance as yf
    frames, failed = {}, []
    for i in range(0, len(syms), chunk):
        part = syms[i:i + chunk]
        tick = [f'{s}.NS' for s in part]
        try:
            d = yf.download(tick, interval=interval, period=period,
                            progress=False, auto_adjust=False,
                            group_by='ticker', threads=True)
        except Exception as e:
            print(f'  chunk {i//chunk+1}: ERROR {str(e)[:60]}')
            failed += part
            continue
        for s, t in zip(part, tick):
            try:
                sub = d[t] if isinstance(d.columns, pd.MultiIndex) else d
                sub = sub.dropna(how='all')
                if len(sub) < 20:
                    failed.append(s)
                    continue
                frames[s] = sub
            except Exception:
                failed.append(s)
        print(f'  chunk {i//chunk+1}/{(len(syms)-1)//chunk+1}: '
              f'{len(frames)} ok, {len(failed)} failed', flush=True)
        time.sleep(0.4)
    return frames, failed


def to_panels(frames, interval):
    """One parquet per field, rows = timestamps, cols = symbols."""
    out = {}
    for field in ('Open', 'High', 'Low', 'Close', 'Volume'):
        cols = {}
        for s, d in frames.items():
            if field in d.columns:
                cols[s] = d[field]
        if cols:
            out[field.lower()] = pd.DataFrame(cols).sort_index()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--interval', default='1h')
    ap.add_argument('--period', default='2y')
    ap.add_argument('--top', type=int, default=400)
    a = ap.parse_args()

    if a.interval in LIMITS:
        print(f'{a.interval} history cap: {LIMITS[a.interval]} days')

    syms = universe(a.top)
    print(f'fetching {a.interval} / {a.period} for {len(syms)} symbols...')
    t0 = time.time()
    frames, failed = fetch(syms, a.interval, a.period)
    print(f'  {len(frames)} fetched, {len(failed)} failed  ({time.time()-t0:.0f}s)')
    if not frames:
        return print('nothing fetched')

    panels = to_panels(frames, a.interval)
    tag = a.interval
    for name, df in panels.items():
        p = os.path.join(OUT, f'{tag}_{name}.parquet')
        df.to_parquet(p)
    idx = next(iter(panels.values())).index
    print(f'  saved {len(panels)} panels -> {OUT}/{tag}_*.parquet')
    print(f'  shape {next(iter(panels.values())).shape}')
    print(f'  range {idx.min()} .. {idx.max()}')
    bars = pd.Series(idx.date).value_counts()
    print(f'  trading days {len(bars)}   bars/day {bars.mode().iloc[0]}')
    if failed:
        print(f'  failed: {", ".join(failed[:12])}'
              f'{" ..." if len(failed) > 12 else ""}')


if __name__ == '__main__':
    main()
