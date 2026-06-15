# Momentum + LowVol 50/50 — Robustness Validation

**Date:** 2026-06-05
**Script:** `validate_momentum_lowvol.py`
**Nature:** Validation only. **Nothing was tuned.** The exact winning config was run
once and interrogated five ways.

**Frozen config:** survivorship-free universe / Top 5 / quarterly / Buffer 20 / equal
weight / 12-1 momentum + 252-day low-vol, 50/50 blend / net of Indian costs.
Full sample: **CAGR 15.08%, Sharpe 0.46, Alpha +3.52%, MaxDD -52.35%, Beta 0.68.**

---

## Verdict: PARTIALLY ROBUST

The result is **not** a two-stock or single-year fluke — it is broad across names and
cap segments. But two real caveats stop it being unconditionally robust: the *alpha* is
**regime-concentrated (post-2019)**, and **~20% of the profit is a gold-ETF allocation**
that leaked into the universe via the low-vol filter, not equity stock-picking.

| Test | Reading | Robust? |
|---|---|---|
| 1. Split sample | Both halves positive alpha, but **+0.12% vs +7.16%** | ⚠️ time-skewed |
| 2. Rolling 5y | Only **44%** of windows alpha>0; **median alpha −1.4%** | ❌ alpha not persistent |
| 3. Breadth | 90 unique names, ~4.9/quarter, 69% profitable | ✅ broad |
| 4. Concentration | Top-10 = **57%** of P&L (46% of gross gains) | ✅ broad-ish |
| 5. Cap segments | Large 44% / Mid 28% / Small 29% of P&L | ✅ spread |
| (bonus) ETF leakage | **Gold ETFs = ~20%** of net P&L | ❌ confound |

---

## Test 1 — Split sample

| Period | CAGR | Sharpe | Alpha | MaxDD | Beta |
|---|---|---|---|---|---|
| 2012-2018 | 11.14% | 0.30 | **+0.12%** | -36.60% | 0.58 |
| 2019-2026 | 18.96% | 0.58 | **+7.16%** | -37.77% | 0.74 |

Both halves clear zero alpha, so it isn't a single-regime artifact in the binary sense.
**But nearly all the edge is in the second half** — 2012-2018 alpha is effectively zero.
The strategy *kept pace* with the index in the first half and *beat* it in the second.

## Test 2 — Rolling 5-year windows (112 windows, monthly step)

| Metric | min | median | max |
|---|---|---|---|
| CAGR | -4.39% | +10.17% | +31.32% |
| Sharpe | -0.53 | 0.19 | 1.29 |
| **Alpha** | **-11.68%** | **-1.39%** | **+17.53%** |
| MaxDD | -52.35% | -37.77% | -22.63% |

- **CAGR positive in 91%** of 5y windows — the strategy reliably makes money.
- **Alpha positive in only 44%** of windows; the *median* 5y alpha is **negative (−1.4%)**.

This is the single most important caveat. The headline +3.52% full-sample alpha is
**driven by a minority of strong (recent) windows**, not earned evenly through time. On
a risk-adjusted basis the strategy more often *matched or trailed* the index over any
given 5-year holding period. An investor entering in the wrong window would have seen no
alpha for years. (Note: benchmark is the NIFTY 500 *price* index; the true TRI is
~1.3%/yr higher, which would push more windows' alpha negative — so this is, if
anything, generous.)

## Test 3 — Holdings breadth

90 unique stocks held over 58 quarters, **~4.9 names per quarter** (out of 5 slots),
median name held **2 quarters** (max 12: BRITANNIA). The portfolio genuinely rotates
through a wide set — it is not quietly holding the same 5 names. Good breadth.

## Test 4 — Return concentration

- Total net P&L **₹3.28M**; **62/90 (69%)** of names profitable.
- **Top-10 winners = 57%** of net P&L (46% of gross gains). Largest single name TRENT
  = 13.8%. Gross winners ₹4.06M vs gross losers −₹0.78M.

57% from the top 10 is moderate concentration — healthy for a 5-stock book, not a red
flag. The return is broad-based at the stock level.

## Test 5 — Cap segmentation (ADTV-rank proxy)

| Segment | Hold-quarters | % hold | Unique names | P&L | % P&L |
|---|---|---|---|---|---|
| Large (ADTV 1-100) | 125 | 44% | 34 | ₹1.43M | 44% |
| Mid (101-250) | 80 | 28% | 24 | ₹0.90M | 28% |
| Small (251-500) | 80 | 28% | 32 | ₹0.94M | 29% |

P&L share tracks holding time almost exactly — the edge is **not** dependent on a single
cap tier, and notably not a small-cap illiquidity mirage. (Cap is proxied by
point-in-time ADTV rank within the 500-name universe; free bhavcopy has no free-float
market cap.)

---

## ⚠️ Material confound found during the audit: GOLD ETFs

The low-vol leg pulled **non-equity ETFs** into the universe (they trade on NSE and
appear in bhavcopy). Gold is low-volatility and rallied hard, so the low-vol filter
loaded it:

| Bucket | P&L | % of net P&L |
|---|---|---|
| Pure gold ETFs (GOLDIETF, SETFGOLD, HDFCGOLD, GOLDBEES, GOLDSHARE, RELGOLD, HDFCMFGETF) | ₹652k | **~20%** |
| All ETFs incl. bank ETFs (some lost money) | ₹576k | ~18% |

Four gold ETFs sit in the **top-6 winners**. So roughly **one-fifth of the strategy's
profit is effectively a gold allocation**, not equity momentum+low-vol stock selection.
This also explains part of the attractive low beta (0.68) and the diversification
benefit over pure momentum: some of it is a stock/gold blend in disguise.

This is not "wrong" — gold genuinely diversified — but it means the **equity-only**
Mom+LowVol edge is smaller than the headline. The honest equity alpha is lower once the
gold sleeve is removed.

---

## What this means / next steps (NOT done here — validation only)

1. **The strategy is genuinely broad** across stocks and cap tiers — it survives the
   "few-stock artifact" test cleanly.
2. **The alpha is not time-stationary.** It is concentrated post-2019, with a negative
   median rolling-5y alpha. Treat the +3.5% as a best-case, regime-favoured figure, not
   a through-the-cycle expectation.
3. **~20% of the profit is gold ETFs.** Before trusting this as an equity strategy, the
   universe should exclude ETFs / non-equity instruments and the test re-run. That is a
   universe-definition fix, not a parameter tune — flagging it for a future run, not
   doing it now.

Bottom line: **robust at the cross-section, fragile through time, and partly a gold
trade.** Worth keeping, but the case for spending on a fundamentals panel (Mom+Quality /
Mom+Value) should be weighed against first cleaning ETFs out of the universe and
re-checking how much equity alpha actually remains.

---

## Files
- `report.png` — equity, rolling 5y CAGR/alpha/Sharpe/MaxDD, top-20 holdings, P&L
  concentration curve, cap-segment P&L.
- `report.txt` — full text report + verdict.
- `split_sample.csv`, `rolling_5y.csv`, `holdings_breadth.csv`, `stock_pnl.csv`.
