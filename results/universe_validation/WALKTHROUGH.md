# Universe Validation — 49-stock Fallback vs Full NIFTY 500

**Question:** The champion strategy was accidentally validated on a 49-stock
large-cap fallback universe. Does the momentum alpha survive when run, completely
unchanged, on the full NIFTY 500 universe?

**Answer:** **Yes — emphatically.** The 12-1 momentum alpha is not an artifact of
the narrow 49-stock universe. On the full NIFTY 500 it is *stronger* (higher CAGR,
higher Sharpe, higher Calmar). **But the absolute magnitude is heavily inflated by
survivorship bias and is not a realistic forward expectation** — read the caveats.

---

## What was wrong before

- `data/nifty500_constituents.csv` did **not** exist, so `load_nifty500_symbols()`
  ([data/downloader.py:62](../../data/downloader.py#L62)) silently fell back to a
  hardcoded 50-name large-cap sample. One of those 50 (`TATMOTORS`) is a typo for
  `TATAMOTORS` and never downloaded — hence **49** stocks. Every prior experiment
  ran on this fallback.
- `data/nifty500_tri.csv` did not exist and the DB `benchmark` table was empty, so
  prior charts had **no real benchmark line**.

## What was fixed

1. **Universe** — fetched the current NIFTY 500 constituent list from NSE archives
   (`ind_nifty500list.csv`, 504 names) → `data/nifty500_constituents.csv`.
   Downloaded 15y OHLCV via yfinance: **500 / 504 loaded**, 4 failed
   (`DUMMYVEDL1-4` — NSE placeholder tickers for the Vedanta demerger, not real
   stocks). Cache now holds 500 stocks + the Nifty50 regime proxy.
2. **Benchmark** — true NIFTY 500 **TRI** can't be fetched programmatically
   (niftyindices blocks scripts). Used `^CRSLDX` (Nifty 500 **price** index) as a
   proxy → `data/nifty500_tri.csv`. This is **price-return, not total-return** and
   understates the true TRI by the ~1.2–1.5%/yr dividend yield.
3. **Strategy** — byte-for-byte unchanged: Top 5, equal weight, quarterly,
   Buffer 20, pure 12-1 momentum, no risk management, same cost model, same dates.
   The *only* difference between the two runs is the investable universe.

## Headline numbers (net of costs, 2012-01 → 2026-05)

| Metric | Fallback (49) | NIFTY 500 |
|---|---|---|
| CAGR | 26.25% | **47.68%** |
| Max Drawdown | -39.85% | **-54.76%** |
| Sharpe | 0.90 | 1.38 |
| Calmar | 0.66 | 0.87 |
| Annual Vol | 22.1% | 29.8% |
| Final value (₹5L start) | ₹1.44 Cr | ₹13.7 Cr |
| Avg turnover/rebal | 23.2% | 41.5% |
| Alpha vs price index | +12.1% | +32.9% |

## Why the NIFTY 500 number is NOT believable at face value

The 47.7% CAGR is real arithmetic on the data, but the data is biased:

- **Survivorship bias (dominant effect).** The universe is *today's* (2026) NIFTY 500
  membership applied across all history. A stock is in today's index largely
  *because* it had an explosive multi-year run. Momentum, by construction, buys
  exactly those run-ups — so the strategy gets to ride the eventual mega-winners,
  while the names momentum would also have bought and that then collapsed *out* of
  the index are simply absent from the test.

- **The diagnostic proves it.** The blow-out years are driven by genuine momentum
  picks that are also classic survivorship winners (in-year returns):
  - 2017: **HEG +1446%**, UNOMINDA +311%, GRAVITA +306%, ADANIENSOL +293%
  - 2021: **TTML +2529%**, ATGL +357%, CGPOWER +336%, ADANIENT +248%
  - 2023: TITAGARH +360%, JINDALSAW +280%, APARINDS +236%, MAZDOCK +193%
  - 2024: TARIL +379%, GVT&D +293%, WOCKPHARMA +202%
  Several IPO'd mid-sample (ATGL, RVNL, IRFC, MAZDOCK, COCHINSHIP — note short
  history) and are only "eligible" today because of these very moves.

- **Price proxy, not TRI.** Benchmark understates the real NIFTY 500 by dividends,
  so the +32.9% alpha is overstated by ~1.3%/yr on the benchmark side too.

- **Data coverage.** Avg per-date coverage is 73.8% (vs 97.4% for the 49 large-caps)
  and the thinnest name has only 109 bars — broad universe = more small/mid-caps
  with shorter, noisier histories where momentum's edge *and* these biases are both
  largest.

## Honest conclusion

- **Does momentum alpha survive on the full NIFTY 500? Yes.** It is not a 49-stock
  fluke; on a broad universe the signal is, if anything, stronger — consistent with
  the well-documented fact that the momentum premium is larger in small/mid-caps.
- **Is 47.7% CAGR a realistic expectation? No.** Treat it as an upper bound. The
  large-cap-only 26% (less biased, more liquid) is a more conservative anchor; the
  honest forward number sits below the broad-universe figure once survivorship is
  removed. The deeper -54.8% drawdown and 29.8% vol, however, are *real* costs of
  going down-cap and should be expected.

## To make the magnitude trustworthy (next steps, not done here)

1. **Point-in-time index membership** (historical NIFTY 500 reconstitutions) to kill
   survivorship bias — the single biggest fix.
2. **True NIFTY 500 TRI** CSV from niftyindices for an honest benchmark.
3. **Tighter liquidity floor / minimum-history filter** so thin recent IPOs can't
   dominate the book.

## Files

- `report.png` — equity, drawdown, CAGR/DD, Sharpe/Calmar, rolling 3Y CAGR, year-wise vs benchmark
- `report.txt` — full side-by-side metrics, diagnostics, benchmark, verdict
- `comparison.csv` — machine-readable metric comparison
- `yearwise_returns.csv` — annual returns both universes + benchmark
- `universe_diagnostics.csv` — coverage stats

Reproduce: `py run_universe_validation.py` (data prep was `py _download_full_universe.py`).
