"""Build raw_open panel from bhavcopy dailies (missing from cache_bhav)."""
import sys, io, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import pandas as pd

OUT = 'data/cache_bhav/raw_open.parquet'
files = sorted(glob.glob('data/bhavcopy_cache/*.parquet'))
files = [f for f in files if os.path.basename(f)[:10] >= '2017-01-01']
print(f'{len(files)} files')
rows = {}
for i, fp in enumerate(files):
    d = pd.read_parquet(fp, columns=['SYMBOL', 'OPEN'])
    dt = pd.Timestamp(os.path.basename(fp)[:10])
    rows[dt] = d.drop_duplicates('SYMBOL').set_index('SYMBOL')['OPEN']
    if i % 400 == 0:
        print(f'  {i}/{len(files)}', flush=True)
panel = pd.DataFrame(rows).T.sort_index()
panel.index.name = None
panel.to_parquet(OUT)
print('saved', OUT, panel.shape)
