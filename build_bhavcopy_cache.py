"""
Download NSE daily bhavcopy (EOD) for a date range and cache a normalized
parquet per trading day. Survivorship-bias-free: every stock that traded that
day is included, including names now delisted.

Handles BOTH archive formats:
  * OLD   (pre Jul-2024): .../EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip
  * UDiFF (Jul-2024+)   : .../cm/BhavCopy_NSE_CM_0_0_0_{YYYYMMDD}_F_0000.csv.zip

Normalized schema per day -> data/bhavcopy_cache/{YYYY-MM-DD}.parquet:
  columns: SYMBOL, OPEN, HIGH, LOW, CLOSE, VOLUME, TURNOVER, ISIN   (SERIES==EQ only)

Resumable: a day already cached is skipped. Weekends are skipped; holidays 404
and are recorded as empty markers so they aren't retried.

Run:
  py build_bhavcopy_cache.py 2011-01-01 2026-05-30
  py build_bhavcopy_cache.py 2015-01-01 2015-01-20   # small test
"""
import io, ssl, sys, time, zipfile, urllib.request, urllib.error, http.cookiejar
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "data" / "bhavcopy_cache"
CACHE.mkdir(parents=True, exist_ok=True)
EMPTY = ROOT / "data" / "bhavcopy_cache" / "_holidays.txt"   # dates known to 404

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
MONTHS = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
UDIFF_CUTOVER = date(2024, 7, 8)   # UDiFF becomes the format around Jul-2024

_ctx = ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE


def _make_opener():
    H = {'User-Agent': UA, 'Accept': '*/*', 'Referer': 'https://www.nseindia.com/'}
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj),
                                     urllib.request.HTTPSHandler(context=_ctx))
    op.addheaders = list(H.items())
    try: op.open('https://www.nseindia.com/', timeout=25)
    except Exception: pass
    return op


def _url(d: date):
    if d >= UDIFF_CUTOVER:
        return f"https://archives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    return (f"https://archives.nseindia.com/content/historical/EQUITIES/{d.year}/"
            f"{MONTHS[d.month-1]}/cm{d.day:02d}{MONTHS[d.month-1]}{d.year}bhav.csv.zip")


def _normalize(df: pd.DataFrame, d: date) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    if "TckrSymb" in df.columns:   # UDiFF
        df = df[df["SctySrs"].astype(str).str.strip() == "EQ"]
        out = pd.DataFrame({
            "SYMBOL": df["TckrSymb"].astype(str).str.strip(),
            "OPEN": pd.to_numeric(df["OpnPric"], errors="coerce"),
            "HIGH": pd.to_numeric(df["HghPric"], errors="coerce"),
            "LOW": pd.to_numeric(df["LwPric"], errors="coerce"),
            "CLOSE": pd.to_numeric(df["ClsPric"], errors="coerce"),
            "VOLUME": pd.to_numeric(df["TtlTradgVol"], errors="coerce"),
            "TURNOVER": pd.to_numeric(df["TtlTrfVal"], errors="coerce"),
            "ISIN": df["ISIN"].astype(str).str.strip(),
        })
    else:                           # OLD (note: pre-~2012 files have no ISIN col)
        df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
        out = pd.DataFrame({
            "SYMBOL": df["SYMBOL"].astype(str).str.strip(),
            "OPEN": pd.to_numeric(df["OPEN"], errors="coerce"),
            "HIGH": pd.to_numeric(df["HIGH"], errors="coerce"),
            "LOW": pd.to_numeric(df["LOW"], errors="coerce"),
            "CLOSE": pd.to_numeric(df["CLOSE"], errors="coerce"),
            "VOLUME": pd.to_numeric(df["TOTTRDQTY"], errors="coerce"),
            "TURNOVER": pd.to_numeric(df["TOTTRDVAL"], errors="coerce"),
            "ISIN": (df["ISIN"].astype(str).str.strip() if "ISIN" in df.columns else ""),
        })
    return out.dropna(subset=["CLOSE"]).reset_index(drop=True)


def fetch_day(op, d: date, retries=3):
    url = _url(d)
    for a in range(1, retries + 1):
        try:
            raw = op.open(urllib.request.Request(url), timeout=40).read()
            z = zipfile.ZipFile(io.BytesIO(raw))
            df = pd.read_csv(z.open(z.namelist()[0]))
            return _normalize(df, d)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None          # holiday / no trading
            if a == retries:
                raise
            time.sleep(2 * a)
        except Exception:
            if a == retries:
                raise
            time.sleep(2 * a)


def load_holidays():
    if EMPTY.exists():
        return set(EMPTY.read_text().split())
    return set()


def main():
    start = pd.Timestamp(sys.argv[1]).date() if len(sys.argv) > 1 else date(2011, 1, 1)
    end   = pd.Timestamp(sys.argv[2]).date() if len(sys.argv) > 2 else date(2026, 5, 30)

    op = _make_opener()
    holidays = load_holidays()
    new_holidays = []

    d = start
    n_fetch = n_skip = n_hol = n_fail = 0
    t0 = time.time()
    while d <= end:
        if d.weekday() >= 5:                       # Sat/Sun
            d += timedelta(days=1); continue
        key = d.isoformat()
        out_f = CACHE / f"{key}.parquet"
        if out_f.exists() or key in holidays:
            n_skip += 1; d += timedelta(days=1); continue
        try:
            df = fetch_day(op, d)
        except Exception as e:
            n_fail += 1
            print(f"  {key} FAIL: {repr(e)[:80]}", flush=True)
            d += timedelta(days=1); continue
        if df is None:
            n_hol += 1; new_holidays.append(key)
        else:
            df.to_parquet(out_f); n_fetch += 1
            if n_fetch % 50 == 0:
                rate = n_fetch / (time.time() - t0)
                print(f"  ...{n_fetch} days fetched ({rate:.1f}/s), at {key}", flush=True)
        d += timedelta(days=1)

    if new_holidays:
        with open(EMPTY, "a") as f:
            f.write("\n".join(new_holidays) + "\n")

    dt = time.time() - t0
    print(f"\nDONE {start}..{end} in {dt:.0f}s  |  fetched={n_fetch} "
          f"skipped(cached)={n_skip} holidays={n_hol} failed={n_fail}", flush=True)
    if n_fetch:
        print(f"  avg {n_fetch/dt:.2f} days/sec", flush=True)


if __name__ == "__main__":
    main()
