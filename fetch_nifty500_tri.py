"""
Fetch the TRUE NIFTY 500 Total Return Index (TRI) from niftyindices.com and
save as data/nifty500_tri.csv (Date, Close) — the format data/benchmark.py reads.
Replaces the earlier ^CRSLDX price-index proxy with the real dividend-inclusive TRI.
"""
import json, ssl, time, urllib.request, http.cookiejar
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUTCSV = ROOT / "data" / "nifty500_tri.csv"

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
H = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36',
     'Accept':'application/json, text/javascript, */*; q=0.01',
     'Referer':'https://niftyindices.com/reports/historical-data',
     'Accept-Language':'en-US,en;q=0.9','X-Requested-With':'XMLHttpRequest',
     'Content-Type':'application/json; charset=UTF-8','Origin':'https://niftyindices.com'}
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj), urllib.request.HTTPSHandler(context=ctx))
op.addheaders = [(k, v) for k, v in H.items() if k != 'Content-Type']
for seed in ['https://niftyindices.com/', 'https://niftyindices.com/reports/historical-data']:
    try: op.open(seed, timeout=30)
    except Exception: pass

URL = 'https://niftyindices.com/Backpage.aspx/getHistoricaldatatabletoString'
MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

def fetch_chunk(start, end):
    body = {'cinfo': "{'name':'NIFTY 500','startDate':'%s','endDate':'%s','indexName':'NIFTY 500 - TRI'}" % (start, end)}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=H, method='POST')
    raw = op.open(req, timeout=60).read().decode('utf-8', 'replace')
    inner = json.loads(raw)["d"]
    return json.loads(inner)

rows = []
for yr in range(2011, 2027):
    s = f"01-Jan-{yr}"; e = f"31-Dec-{yr}"
    if yr == 2026: e = "30-May-2026"
    for attempt in range(3):
        try:
            data = fetch_chunk(s, e)
            rows += [{"Date": r["HistoricalDate"], "Close": float(r["CLOSE"])} for r in data]
            print(f"  {yr}: {len(data)} rows", flush=True)
            break
        except Exception as ex:
            print(f"  {yr} attempt {attempt} fail: {repr(ex)[:80]}", flush=True); time.sleep(3)
    time.sleep(1)

df = pd.DataFrame(rows)
df["Date"] = pd.to_datetime(df["Date"], format="%d %b %Y")
df = df.drop_duplicates("Date").sort_values("Date").reset_index(drop=True)
df.to_csv(OUTCSV, index=False)
cagr = (df["Close"].iloc[-1] / df["Close"].iloc[0]) ** (365.25 / (df["Date"].iloc[-1] - df["Date"].iloc[0]).days) - 1
print(f"\nSaved {len(df)} rows -> {OUTCSV}")
print(f"Range {df['Date'].min().date()}..{df['Date'].max().date()}  TRI CAGR={cagr:.2%}")
