"""
Back-adjust raw bhavcopy close/high/low for splits & bonuses using gap detection,
then VALIDATE the detector against Upstox adjusted data on a random sample.

Why gap detection works for Indian equities: daily circuit limits cap real moves
(~5/10/20%). A clean overnight ratio near a known split/bonus fraction (0.5, 0.333,
0.25, 0.2, 0.1, ...) far outside the circuit band is almost certainly a corporate
action, not a real return. We snap to the nearest clean fraction within tolerance.

Output: data/cache_bhav/adj_{close,high,low}.parquet  (+ raw_volume reused as-is)
Run:    py adjust_bhav.py            # builds adjusted panels + validates vs Upstox
"""
import json, ssl, urllib.request, urllib.parse, random
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "cache_bhav"

# Clean corporate-action ratios (close[t]/close[t-1] on ex-date) with a PER-RATIO
# relative tolerance. The observed ratio = clean_factor x (1 + that day's real move),
# so we allow a band for a normal move on the ex-date. Deep ratios (<=0.5) get a wide
# band (nothing legitimate sits near -50% to -90%); 1:2 bonus (0.667, -33%) gets a
# TIGHT band because it is close to the ~20-25% circuit zone where real crashes live.
# Smaller bonuses (1:4=-20%, 1:5=-17%) are deliberately NOT detected (inside circuit
# band -> would false-positive on many names). Adjustment uses the EXACT clean factor,
# so the ex-date's genuine price move is preserved. (Tuned & validated vs Upstox.)
CLEAN = [          # (factor, relative tolerance)
    (2/3,   0.05),   # 1:2 bonus            (-33%)  tight: near circuit
    (0.5,   0.13),   # 1:1 bonus / 2->1 / 10->5 split  (-50%)
    (0.4,   0.13),   # 3:2 bonus / 5->2     (-60%)
    (1/3,   0.13),   # 2:1 bonus            (-67%)
    (0.25,  0.13),   # 3:1 bonus            (-75%)
    (0.2,   0.13),   # 4:1 / 5->1 / 10->2   (-80%)
    (1/6,   0.13),   # 5:1 bonus            (-83%)
    (0.125, 0.13),   # 7:1 bonus            (-87.5%)
    (0.1,   0.13),   # 9:1 / 10->1          (-90%)
]
LO_GAP = 0.72          # candidate only if ratio < 0.72 (drop >28%, beyond circuit)


def _snap(val):
    """Return the clean corporate-action factor for an observed gap ratio, or None."""
    for c, tol in CLEAN:
        if abs(val / c - 1) < tol:
            return c
    return None


def detect_factors(close: pd.Series):
    """Return list of (ex_date, factor) corporate actions for a raw close series."""
    s = close.dropna()
    if len(s) < 5:
        return []
    r = (s / s.shift(1)).iloc[1:]
    actions = []
    for dt, val in r.items():
        # Only DOWN gaps (splits/bonuses). Reverse-splits are rare in India and
        # detecting them turns a legitimate large UP day into a fake price jump that
        # would inflate momentum and wrongly select the stock — so we skip them.
        if val < LO_GAP:
            cand = _snap(val)
            if cand is not None:
                actions.append((dt, cand))
    return actions


def back_adjust(close: pd.Series):
    """Back-adjusted series: prices before each ex-date scaled by the action ratio."""
    actions = detect_factors(close)
    adj = pd.Series(1.0, index=close.index)
    for ad, c in actions:
        adj[close.index < ad] *= c
    return close * adj, actions


def build_adjusted_panels():
    cp = pd.read_parquet(OUT / "raw_close.parquet")
    hp = pd.read_parquet(OUT / "raw_high.parquet")
    lp = pd.read_parquet(OUT / "raw_low.parquet")
    print(f"Raw close panel: {cp.shape}")

    adj_c = pd.DataFrame(index=cp.index, columns=cp.columns, dtype="float32")
    n_actions = {}
    for sym in cp.columns:
        adj_series, actions = back_adjust(cp[sym])
        adj_c[sym] = adj_series
        if actions:
            n_actions[sym] = len(actions)
        # apply the SAME per-date factor to high/low
        factor = (adj_series / cp[sym]).reindex(cp.index)
        hp[sym] = hp[sym] * factor
        lp[sym] = lp[sym] * factor

    adj_c.to_parquet(OUT / "adj_close.parquet")
    hp.astype("float32").to_parquet(OUT / "adj_high.parquet")
    lp.astype("float32").to_parquet(OUT / "adj_low.parquet")
    print(f"Adjusted {len(cp.columns)} symbols; {len(n_actions)} had >=1 detected action.")
    print(f"Total actions detected: {sum(n_actions.values())}")
    return adj_c


# ─────────────────────────────────────────────────────────────────────
# VALIDATION vs Upstox adjusted close
# ─────────────────────────────────────────────────────────────────────
_ctx = ssl.create_default_context(); _ctx.check_hostname=False; _ctx.verify_mode=ssl.CERT_NONE
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def upstox_close(isin: str, token: str):
    candles = []
    for frm, to in [("2011-01-01", "2020-12-31"), ("2021-01-01", "2026-05-30")]:
        ik = urllib.parse.quote(f"NSE_EQ|{isin}", safe="")
        url = f"https://api.upstox.com/v3/historical-candle/{ik}/days/1/{to}/{frm}"
        req = urllib.request.Request(url, headers={"Accept": "application/json",
              "Authorization": f"Bearer {token}", "User-Agent": UA})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=40, context=_ctx).read().decode())
            candles += d["data"]["candles"]
        except Exception:
            return pd.Series(dtype=float)
    if not candles:
        return pd.Series(dtype=float)
    df = pd.DataFrame(candles, columns=["ts","o","h","l","c","v","oi"])
    df["d"] = pd.to_datetime(df["ts"].str[:10])
    s = df.set_index("d")["c"].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def validate(adj_c, n_sample=40, seed=1):
    tokf = ROOT / "data" / ".upstox_token.json"
    if not tokf.exists():
        print("No Upstox token -> skipping validation."); return
    token = json.loads(tokf.read_text())["access_token"]
    isin_map = pd.read_csv(OUT / "symbol_isin.csv").set_index("SYMBOL")["ISIN"].to_dict()
    active = (OUT / "symbols_active.txt").read_text().split()
    cand = [s for s in active if s in isin_map and adj_c[s].notna().sum() > 500]
    random.seed(seed); sample = random.sample(cand, min(n_sample, len(cand)))

    print(f"\nValidating gap-detect adjustment vs Upstox on {len(sample)} active names...")
    rows = []
    for sym in sample:
        ups = upstox_close(isin_map[sym], token)
        ours = adj_c[sym].dropna()
        common = ours.index.intersection(ups.index)
        if len(common) < 250:
            continue
        a = ours.reindex(common); b = ups.reindex(common)
        # compare on RETURNS (adjustment-invariant to absolute scale)
        ra = a.pct_change().dropna(); rb = b.pct_change().dropna()
        ci = ra.index.intersection(rb.index)
        corr = ra.reindex(ci).corr(rb.reindex(ci))
        # max abs daily-return diff (a corporate-action mis-adjust shows as a huge spike)
        maxdiff = (ra.reindex(ci) - rb.reindex(ci)).abs().max()
        rows.append({"symbol": sym, "n": len(ci), "ret_corr": corr, "max_ret_diff": maxdiff})
    res = pd.DataFrame(rows).sort_values("ret_corr")
    res.to_csv(ROOT / "_adj_validation.csv", index=False)
    print(res.to_string(index=False))
    ok = (res["ret_corr"] > 0.999).mean() * 100
    print(f"\n{ok:.0f}% of sample have return-corr > 0.999 vs Upstox.")
    print(f"Median max single-day return diff: {res['max_ret_diff'].median():.4f}  "
          f"(large values => a missed/wrong corporate action)")
    flag = res[res["max_ret_diff"] > 0.15]
    if len(flag):
        print(f"Names with a >15% single-day mismatch (investigate): {flag['symbol'].tolist()}")


if __name__ == "__main__":
    adj_c = build_adjusted_panels()
    validate(adj_c)
