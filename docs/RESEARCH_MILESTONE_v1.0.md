# Research Milestone v1.0 — Survivorship-Free Momentum Research Complete

**Tag:** `v1.0-research-complete`
**Date:** 2026-06-18
**Status:** Research cycle closed. Conclusions frozen. Phase 2 (PIT fundamentals) deliberately deferred.

This document is the single record of what the v1.0 research cycle did, what it found, and
why we stopped where we did. It ties together the individual experiment walkthroughs under
`results/*/WALKTHROUGH.md` and the Phase 2 plan in `docs/phase2_fundamental_data_pipeline.md`.

---

## 1. The one-line conclusion

After removing survivorship bias and ETF contamination, **naive 12-1 momentum on a broad,
honest Indian universe earns about the market return (~12–13% CAGR) with roughly 2× the
drawdown — i.e. no risk-adjusted edge.** Adding a low-vol leg (Mom+LowVol 50/50) is the only
variant that produced positive alpha, but the alpha is regime-concentrated (post-2019) and
partly a gold-ETF artifact. The earlier headline CAGRs of 19–47% were **bias and universe
artifacts, not alpha.**

The bar for any future work is now this honest baseline, **not** the old inflated numbers.

---

## 2. The journey, in numbers

The core lesson of this cycle is how much "alpha" was actually measurement error. The same
champion config (Top-5 / equal-weight / quarterly / Buffer-20 / 12-1 momentum, net of Indian
costs) was run on three progressively-honest universes:

| Metric | A: Fallback 49 names | B: Biased NIFTY 500 (today's index) | C: Survivorship-Free |
|---|---|---|---|
| CAGR | 26.25% | 47.68% | **12.75%** |
| Max Drawdown | -39.9% | -54.8% | **-62.5%** |
| Sharpe | 0.90 | 1.38 | **0.20** |
| Jensen Alpha (ann.) | +12.1% | +32.9% | **−1.96%** |
| Final value (₹5L) | ₹1.44 Cr | ₹13.7 Cr | ₹28.2 L |

- **Survivorship bias alone inflated CAGR by ~+35 points** (B − C = +34.93%).
- NIFTY 500 *price* index over the period: **11.40% CAGR** (true TRI ≈ 12.70% adding ~1.3%/yr
  dividends). The honest momentum book's excess vs the price index is **+1.35%**, and ≈ **0%**
  against total return — Jensen alpha is in fact slightly **negative (−1.96%)**.

Full detail: [results/survivorship_free/WALKTHROUGH.md](../results/survivorship_free/WALKTHROUGH.md).

---

## 3. What "survivorship-free" cost us to build (the data spine)

The honest number was only possible after replacing the old yfinance "today's survivors"
data with a from-scratch point-in-time universe built from NSE daily bhavcopy:

1. **Full NSE cross-section from daily bhavcopy**, 2011→2026 — **3,799 trading days,
   3,803 distinct symbols including 1,262 now-delisted names** (DHFL, RCOM, Jet Airways, …).
   Every stock that ever traded is present, not just today's index.
2. **Point-in-time, liquidity-defined universe:** at each rebalance, standard liquidity/quality
   filters, then the **top 500 by real ₹ turnover** — no peeking at the future index.
3. **Corporate-action adjusted** via close-gap detection (split/bonus ratios beyond the circuit
   band), **validated against Upstox** adjusted data — median single-day error ~0.25%,
   near-perfect on liquid large-caps.
4. **Benchmark:** real NIFTY 500 *price* index from niftyindices (true TRI endpoint is gated;
   price understates TRI by ~1.3%/yr, so quoted alpha is, if anything, generous).
5. **Engine fix:** the champion's sell logic crashed when a *held* name delisted (NaN price
   poisoned cash) — a dormant bug because old yfinance data never delisted. Delisted holdings
   are now exited at their last traded mark. This is itself a survivorship effect: you *can* be
   left holding a momentum name that dies.

**Pipeline:** `build_bhavcopy_cache.py` → `build_bhav_panels.py` → `adjust_bhav.py`;
benchmark `fetch_nifty500_tri.py`; auth `upstox_auth.py`.

**Identity lesson:** ISIN is the key, not the ticker — 521 symbols carried ≥2 ISINs over time.
ISIN prefix is also how non-equity instruments are identified (see §5).

---

## 4. Two bugs/biases removed

1. **Fallback-universe bug + survivorship bias.** The old runs fell back to a tiny 49-name
   survivor set and/or used today's NIFTY 500 membership as the historical universe — both
   guarantee the multi-baggers that *climbed into* the index are always present, exactly the
   names momentum buys on the way up. Fixed by the bhavcopy PIT spine (§3).

2. **ETF / non-equity contamination.** NSE lists ETFs under bhavcopy `SERIES==EQ`, leaking
   **488 fund/ETF units** (ISIN prefixes `INF`/`IN9`) into the universe. In the Mom+LowVol
   experiment, **~20% of net P&L was gold ETFs** — the low-vol filter loaded sleepy, rallying
   gold, not equity stock-picking. Fixed with `build_equity_universe.py` (an `INE`-only equity
   whitelist, `symbols_equity.txt`); the clean rerun matches the benchmark at lower risk with
   no real equity alpha. Benchmark is now also measured over the strategy's *realized* span,
   correcting a ~2-point excess-CAGR overstatement.

---

## 5. The factor experiments

All variants share the frozen honest shell (survivorship-free universe / Top-5 / quarterly /
Buffer-20 / equal-weight / Indian costs, gross+net); **only the ranking signal varies.** No
parameter was tuned — per the standing anti-overfit decision, the blend weight and lookbacks
were chosen once and left alone.

| Metric (net) | Pure Mom | **Mom+LowVol 50/50** | Low-Vol only | Vol-Managed (Barroso) |
|---|---|---|---|---|
| CAGR | 12.75% | **15.08%** | 0.30% | 10.06% |
| Max Drawdown | -62.46% | **-52.35%** | -43.58% | -49.88% |
| Sharpe | 0.20 | **0.46** | -0.54 | 0.15 |
| Alpha (Jensen) | -1.96% | **+3.52%** | -7.98% | -2.75% |
| Beta | 1.10 | 0.68 | 0.24 | 0.85 |

- **Mom+LowVol 50/50** is the only variant to clear the pre-registered bar (net alpha > 0 *and*
  Sharpe materially above the 0.20 baseline). It raises CAGR, cuts drawdown, and roughly
  doubles Sharpe — the classic momentum-crash diversification signature.
- **Low-Vol only collapses** (negative Sharpe): low vol is the risk filter, momentum is the
  return engine — the value is in the *combination*.
- **Vol-management overlay** cuts drawdown but throttles compounding and creates no alpha —
  same shape as the earlier trend-filter experiment.

Detail: [results/momentum_lowvol/WALKTHROUGH.md](../results/momentum_lowvol/WALKTHROUGH.md).

### Robustness of the Mom+LowVol result — "PARTIALLY ROBUST"

A no-tuning, five-way interrogation of the frozen Mom+LowVol config
([results/momentum_lowvol_validation/WALKTHROUGH.md](../results/momentum_lowvol_validation/WALKTHROUGH.md)):

| Test | Reading | Robust? |
|---|---|---|
| Split sample | Both halves positive, but +0.12% (2012-18) vs +7.16% (2019-26) alpha | ⚠️ time-skewed |
| Rolling 5y (112 windows) | Alpha > 0 in only **44%**; **median 5y alpha −1.4%** | ❌ not persistent |
| Breadth | 90 names, ~4.9/quarter, 69% profitable | ✅ broad |
| Concentration | Top-10 = 57% of P&L | ✅ broad-ish |
| Cap segments | Large 44% / Mid 28% / Small 29% | ✅ spread |
| ETF leakage | Gold ETFs ~20% of net P&L | ❌ confound (since fixed, §4) |

**Verdict: robust across the cross-section, fragile through time, partly a gold trade.** The
+3.52% full-sample alpha is a best-case, regime-favoured figure, not a through-the-cycle
expectation.

---

## 6. Stage-1 Momentum + Quality pilot (scaffolding only)

The natural next factor is Quality (and Value), which needs fundamentals — but free retail
fundamentals (Screener/Tickertape/MoneyControl) are **restated, survivors-only** views, fatal
as a PIT source. Rather than commit to a full point-in-time fundamentals platform on the
strength of a regime-concentrated, partly-gold result, we built only a tiny, honest pilot:

- `pilot_select_companies.py` — pure analysis on the existing price spine. Samples ~40
  representative companies from the Top-100-by-turnover union over every quarterly rebalance
  (2011→2026), deterministically (fixed seed `20260618`), stratified across cap-bucket × status
  (active/delisted) and **force-including real catastrophic failures** (DHFL, RCOM, Jet Airways,
  Yes Bank, Suzlon, …) so the sample is not winners-only.
- Outputs (`data/cache_fundamentals/`):
  - `pilot_company_list.csv` — the ~40-name sample with isin / status / cap_bucket / first_seen /
    last_seen / reason_selected.
  - `pilot_fundamentals.csv` — an **empty template** (all financials blank, `verified=FALSE`)
    to be filled and human-verified before any next step.

It builds **no scraper, no PIT database, no schema, no backtest, and computes no Quality score
or conclusion.** It stops after writing the template and printing coverage stats.

---

## 7. What is deferred, and why

The full bitemporal, survivorship-free, look-ahead-free PIT fundamental data pipeline is
designed but **intentionally postponed** — see [docs/phase2_fundamental_data_pipeline.md](phase2_fundamental_data_pipeline.md).

**Why defer:** the only positive equity result (Mom+LowVol) is regime-concentrated, has a
negative median rolling-5y alpha, and was ~20% gold. Building an institutional-grade PIT
fundamentals panel (CMIE Prowess-class data or a self-built NSE/BSE primary-filing pipeline) is
a large investment. We will only make it once there is **stronger evidence** that a fundamentals
factor would clear the same honest bar that momentum failed.

---

## 8. How to reproduce

Run with the `py` launcher (not bare `python`); the run scripts self-fix Windows UTF-8 encoding.

| Step | Command |
|---|---|
| Build the survivorship-free spine | `py build_bhavcopy_cache.py` → `py build_bhav_panels.py` → `py adjust_bhav.py` |
| Equity-only whitelist (drop ETFs) | `py build_equity_universe.py` |
| Benchmark (NIFTY 500 price index) | `py fetch_nifty500_tri.py` |
| Survivorship-free champion validation | `py run_survivorship_validation.py` |
| Momentum + LowVol (+ bookends) | `py run_momentum_lowvol.py` |
| Mom+LowVol robustness (no tuning) | `py validate_momentum_lowvol.py` |
| Stage-1 pilot sample + empty template | `py pilot_select_companies.py` |

Each writes a `results/<experiment>/` folder with `report.png`, `report.txt`, CSVs, and a
`WALKTHROUGH.md`.

---

## 9. File index

- **Milestone record:** this file.
- **Phase 2 plan (deferred):** [docs/phase2_fundamental_data_pipeline.md](phase2_fundamental_data_pipeline.md)
- **Experiment walkthroughs:** `results/survivorship_free/`, `results/momentum_lowvol/`,
  `results/momentum_lowvol_validation/`, `results/trend_filter/`, `results/factor_research/`,
  `results/universe_validation/` (each has a `WALKTHROUGH.md`).
- **Data pipeline:** `build_bhavcopy_cache.py`, `build_bhav_panels.py`, `adjust_bhav.py`,
  `build_equity_universe.py`, `fetch_nifty500_tri.py`, `upstox_auth.py`.
- **Pilot:** `pilot_select_companies.py`, `data/cache_fundamentals/`.
