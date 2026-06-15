# Momentum + Low Volatility — Walkthrough

**Date:** 2026-06-05
**Script:** `run_momentum_lowvol.py`
**Universe:** Survivorship-free (full NSE bhavcopy cross-section, corp-action adjusted,
top-500 by point-in-time liquidity) — the same honest universe as the survivorship
validation.
**Shell (frozen, identical to the champion):** Top 5 / quarterly / equal weight /
Buffer 20 / Indian cost model, gross + net. The **only** thing that varies across
variants is the ranking signal / exposure rule.

This is the experiment recommended by [results/factor_research/REPORT.md](../factor_research/REPORT.md):
the first test of a *second factor* after we froze single-signal tuning.

---

## What was tested

| Variant | Signal |
|---|---|
| Pure Momentum | 12-1 momentum (the champion — reference baseline) |
| **Mom + LowVol 50/50** | `0.5·momentum-pctile + 0.5·lowvol-pctile`, Top-5 by blend |
| Low-Vol only | rank by lowest 252-day realized vol (bookend) |
| Vol-Managed Mom | pure-momentum selection, exposure scaled to 18% vol target (Barroso); excess in cash |

- **Low-vol signal:** trailing **252-day** annualized realized volatility, lower = better.
- **Vol-management overlay:** exposure = `min(1.0, 18% / trailing-126d strategy vol)` —
  a separate, conventionally-shorter (Barroso) window on the strategy's *own* returns,
  long-only, capped at 1.0.

**Pre-registered success bar:** a variant passes only if **net alpha > 0 AND Sharpe
materially above the 0.20 baseline** — not merely a shallower drawdown.

---

## Headline result

| Metric (net) | Pure Mom | **Mom+LowVol 50/50** | Low-Vol only | Vol-Managed |
|---|---|---|---|---|
| CAGR | 12.75% | **15.08%** | 0.30% | 10.06% |
| Max Drawdown | -62.46% | **-52.35%** | -43.58% | -49.88% |
| Sharpe | 0.20 | **0.46** | -0.54 | 0.15 |
| Alpha (Jensen) | -1.96% | **+3.52%** | -7.98% | -2.75% |
| Annual Vol | 31.46% | 18.84% | 11.40% | 24.27% |
| Beta | 1.10 | 0.68 | 0.24 | 0.85 |
| Final value (Rs) | 2,815,366 | **3,778,788** | 522,188 | 1,988,816 |

Benchmark NIFTY 500 *price* index CAGR over the period: **11.40%** (true TRI ~12.70%).

---

## Verdict

**Momentum + Low Volatility (50/50) is the first variant in this whole research line
to produce positive alpha on the honest universe — and it does so while *also*
raising CAGR and cutting drawdown.** It is a strict improvement, not a trade-off:

- **Alpha turns positive:** -1.96% → **+3.52%** Jensen alpha.
- **Sharpe more than doubles:** 0.20 → **0.46**.
- **Higher return:** 15.08% vs 12.75% CAGR — and it beats the price index by +3.68%/yr
  (still ahead of the true TRI ~12.70%).
- **Lower risk:** drawdown -62% → -52%, vol 31% → 19%, beta 1.10 → 0.68.

This is the signature of genuine factor diversification (the momentum-crash literature):
low-vol rallies relatively when momentum reverses, so the blend keeps momentum's return
engine while removing its worst high-beta tail.

**The two bookends confirm the mechanism rather than contradict it:**

- **Low-Vol only collapses** (0.30% CAGR, -7.98% alpha, negative Sharpe). Low volatility
  alone is *not* a return engine in this universe — it just buys sleepy defensives.
  **Momentum is doing the work; low-vol is the risk filter.** The value is in the
  *combination*, exactly the thesis.
- **Vol-Managed (Barroso) cuts drawdown but loses return** (10.06% CAGR, Sharpe 0.15,
  alpha still negative). Scaling *total* exposure dampens the crash but also throttles
  the compounding and does not create alpha — same shape of result as the trend-filter
  experiment ([[trend-filter-experiment]]). The cross-sectional blend beats the
  exposure overlay decisively.

**Year-wise, the blend's edge is the crash years:** 2016 (-41.5% → -9.1%), 2018
(+19.8% vs... actually pure mom won 2018), 2022 (-12.6% → -0.3%), and especially
**2025 (-33.4% → +13.6%)**. It gives back some upside in momentum's blow-out years
(2020: +98% → +11%, 2023: +103% → +43%) — that is the price of lower vol — but the
smoother path compounds to more money.

---

## Caveats

- Benchmark is the NIFTY 500 *price* index; the true TRI is ~1.3%/yr higher. The blend
  still clears the true TRI (15.08% vs ~12.70%), but the price-index alpha slightly
  flatters all variants.
- 50/50 is a single, deliberately un-tuned weight chosen to avoid overfitting. We did
  **not** grid-search the blend ratio or the vol lookback — and per the standing
  decision we should not start now.
- Time-underwater is still ~90% and the drawdown is still -52%: improved, not "safe."

---

## Recommendation / next step

The result **clears the pre-registered bar**, which per the research report is the
trigger to **invest in building a bias-free, point-in-time fundamentals panel** so we
can test the higher-evidence combinations next: **Momentum + Quality** (rank 2) and
**Momentum + Value** (rank 3). We now have direct evidence on *our own* data that
factor blending lifts risk-adjusted return — that de-risks the bigger data investment.

Do **not** tune the blend weight / vol lookback. The clean finding is enough.

---

## Files
- `report.png` — equity, drawdown, CAGR-vs-DD, Sharpe/alpha, rolling 3Y CAGR, year-wise.
- `report.txt` — full metrics table + verdict.
- `comparison.csv` — machine-readable per-variant metrics.
- `yearwise_returns.csv` — annual returns per variant vs benchmark.
