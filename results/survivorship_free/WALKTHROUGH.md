# Survivorship-Free Validation — the honest number

**Question:** After fixing the universe to the full NIFTY 500 we got 47.7% CAGR, but
flagged it as inflated by survivorship bias. So what does the champion *really* earn
once we (a) include stocks that later delisted and (b) stop using today's index
membership as a crystal ball?

**Answer:** **~12.75% CAGR — essentially market-level, with NO meaningful alpha and
far worse risk.** Survivorship bias alone was inflating the result by **+35 CAGR
points**. The champion's apparent edge was almost entirely an artifact.

## The three universes (identical champion: Top5 / EW / quarterly / Buffer20 / 12-1 momentum, net)

| Metric | A: Fallback 49 | B: Biased NIFTY 500 | C: Survivorship-Free |
|---|---|---|---|
| CAGR | 26.25% | 47.68% | **12.75%** |
| Max Drawdown | -39.9% | -54.8% | **-62.5%** |
| Sharpe | 0.90 | 1.38 | **0.20** |
| Calmar | 0.66 | 0.87 | 0.20 |
| Annual Vol | 22.1% | 29.8% | 31.5% |
| Jensen Alpha (ann.) | +12.1% | +32.9% | **−1.96%** |
| Excess vs price index | +14.9% | +36.3% | **+1.35%** |
| Final value (₹5L) | ₹1.44 Cr | ₹13.7 Cr | ₹28.2 L |

- **NIFTY 500 price index CAGR (period): 11.40%** → true TRI ≈ 12.70% (add ~1.3%/yr dividends).
- **Survivorship bias cost (B − C) = +34.93% CAGR.**
- **Honest edge of C vs benchmark:** +1.35% on price, ≈ **0% on total-return**. The Jensen
  alpha is actually slightly **negative** (−1.96%).

## What "survivorship-free" means here (the data work)

1. **Universe = full NSE cross-section from daily bhavcopy**, 2011→2026 (3,799 trading
   days, **3,803 distinct symbols incl. 1,262 now delisted**). Every stock that traded
   is present — DHFL, RCOM, Jet Airways, etc. — not just today's survivors.
2. **Point-in-time, liquidity-defined**: each rebalance, standard liquidity/quality
   filters, then the **top 500 by real ₹ turnover** (no peeking at the future index).
3. **Corporate-action adjusted** via gap-detection on close (split/bonus ratios beyond
   the circuit band), **validated against Upstox** adjusted data — median single-day
   error ~0.25%; near-perfect on liquid large-caps (TRENT, JSWSTEEL, TVSMOTOR, …).
4. **Benchmark**: real NIFTY 500 **price** index from niftyindices (the true TRI
   endpoint is gated; price understates TRI by ~1.3%/yr).
5. **Engine fix (necessary, backward-compatible):** the champion's sell logic crashed
   on a held name that *delists* (NaN price poisoned cash) — the old yfinance data
   never delisted, so the bug was dormant. Delisted holdings are now exited at their
   last traded mark. This is itself a survivorship effect: you *can* be left holding a
   momentum name that then dies.

## Why the alpha collapses

- **Survivorship (the big one):** today's NIFTY 500 contains the multi-baggers that
  *climbed into* the index (HEG, TTML, Adani names, defence/rail PSUs). Momentum buys
  exactly those run-ups, and in the biased test they're guaranteed present. In reality
  momentum *also* buys names that then collapse and leave the index — and now those
  losses are counted.
- **Down-cap exposure:** a bias-free top-500-by-liquidity book holds far more volatile
  mid/small-caps. Momentum there whipsaws hard — look at the year-wise: +98.5% (2020),
  +103% (2023) but −41.5% (2016), −33.4% (2025). The −62% max drawdown is the price.
- **No risk management:** the champion deliberately has no stops/regime/sizing, so it
  rides every crash fully.

## Honest verdict

Naive concentrated (Top-5) 12-1 momentum, run without bias on a broad liquid Indian
universe, returns **about the same as the index (~12–13%)** while taking **roughly 2×
the drawdown** — i.e., **no risk-adjusted edge** (Sharpe 0.20 vs the index's own ~0.5+).
The strategy is not "broken," but the headline 19–47% CAGRs from earlier experiments
were **survivorship- and universe-artifacts, not alpha.** Any future work should be
measured against *this* ~12.75% / −62% DD baseline, on this bias-free data.

## Caveats

- **Turnover-ranked, not market-cap-ranked** top-500 (bhavcopy has no shares-outstanding).
  A market-cap universe might tilt larger-cap and behave a bit differently.
- Benchmark is price-return, not TRI (≈ +1.3%/yr understated) — so the true excess is if
  anything *worse* than the +1.35% shown.
- A minority of illiquid names have residual corporate-action mis-adjustments (validated
  median error is tiny; worst offenders are filtered out by liquidity).

## Files
- `report.png` — equity / drawdown / CAGR-vs-DD / Sharpe-Calmar / rolling-3Y / year-wise
- `report.txt`, `comparison.csv`, `yearwise_returns.csv`
- Data pipeline: `build_bhavcopy_cache.py` → `build_bhav_panels.py` → `adjust_bhav.py`;
  benchmark `fetch_nifty500_tri.py`; run `run_survivorship_validation.py`.
