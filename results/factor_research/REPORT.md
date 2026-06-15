# Factor-Combination Research Study

**Date:** 2026-06-05
**Status:** Research only — no backtests run. All parameter tuning is frozen per decision.
**Author:** Quant research note

---

## 0. Why this study exists

We have run the strategy line as far as single-factor tuning can take it. The
honest, survivorship-free result for pure 12-1 momentum on the Indian universe is:

| Metric | Value |
|---|---|
| CAGR | 12.75% |
| Max Drawdown | -62.46% |
| Sharpe | 0.20 |
| Alpha (vs NIFTY 500 TRI) | **-1.96%** |

That is the verdict that matters: **negative alpha and a 62% drawdown.** Once
survivorship bias is removed, pure price-momentum in India does not beat the index
on a risk-adjusted basis, and trend overlays cut drawdown without manufacturing
alpha (see [[trend-filter-experiment]]). More tuning of the *same* single signal
will not fix a structural alpha problem — it will only overfit.

The relevant research question is therefore **not** "what knob next?" but **"which
*second factor*, combined with momentum, has the strongest historical evidence of
persistent, real alpha in long-only equity portfolios — and which of those can we
actually test on free Indian data without re-introducing survivorship bias?"**

This report evaluates six momentum pairings, scores each on seven dimensions, ranks
them, and recommends a single next experiment.

---

## 1. The two questions are different — keep them separate

There is a trap here. The combination with the *strongest academic evidence* is not
necessarily the *highest-probability next experiment for us*. Two filters decide our
ranking:

1. **Evidence of persistent alpha** — depth and out-of-sample robustness of the
   academic record, and the economic reason it should persist.
2. **Feasibility on our stack** — can we build it from **free, point-in-time,
   survivorship-free data**? Anything requiring paid or hard-to-get-historical
   fundamentals carries a large hidden cost: a *new* survivorship/look-ahead bias,
   which is exactly the bias we just spent effort eliminating.

A combination can be academically superb and operationally a trap. The
recommendation at the end weights both.

### What data we actually have, free

| Data type | Source we already use | Factors it can build |
|---|---|---|
| Daily OHLCV, full history, **survivorship-free** | NSE bhavcopy cache (`data/bhavcopy_cache/`, `build_bhav_panels.py`) | Momentum, **Low Volatility**, **Trend**, **Size** (price × shares), short-term reversal, liquidity |
| Index TRI | user CSV (`data/nifty500_tri.csv`) | benchmark, beta |
| Fundamentals (earnings, book value, margins, debt) | **none in repo, not free point-in-time** | Quality, Value, Profitability |

This single table drives most of the ranking. Price-only factors are *buildable
today on the bias-free panel we already trust*. Fundamental factors require a data
acquisition project first, and free Indian fundamental history is shallow,
unstandardized, and survivorship-contaminated (screeners only carry currently-listed
companies).

---

## 2. The six combinations

Scoring legend (1 = weak/hard, 5 = strong/easy):

| # | Combination | Evidence | India fit | Free-data feasible | Implementation ease | Survivorship risk* | 
|---|---|---|---|---|---|---|
| A | Momentum + **Low Volatility** | 4 | 4 | **5** | **5** | 5 |
| B | Momentum + **Quality** | 5 | 4 | 2 | 3 | 2 |
| C | Momentum + **Value** | 5 | 4 | 2 | 3 | 2 |
| D | Momentum + **Profitability** | 4 | 3 | 2 | 3 | 2 |
| E | Momentum + **Trend** | 3 | 3 | 5 | 5 | 5 |
| F | Momentum + **Size** | 2 | 4 | 4 | 4 | 3 |

\* *Survivorship-risk score = how easy it is to keep the data bias-free. 5 = we
already have bias-free data; 2 = free fundamental history is structurally
survivorship-contaminated.*

The detailed case for each follows.

---

### A. Momentum + Low Volatility

**Economic rationale.** Two independent anomalies that are *negatively correlated in
their failure modes*. Momentum loads on high-beta winners and crashes hard at
turning points (the "momentum crash" — exactly our -62% drawdown). Low-volatility
stocks are defensive and rally relatively during exactly those reversals. The
low-vol anomaly itself is driven by leverage constraints (Frazzini–Pedersen
"Betting Against Beta") and lottery-preference behaviour: constrained investors bid
up high-beta names, leaving low-beta stocks with abnormally high risk-adjusted
returns. Stacking momentum's return engine on a low-vol risk filter directly targets
the *one weakness we measured*.

**Academic evidence.** Strong and broad. Baker–Bradley–Wurgler (2011) and Blitz–van
Vliet on the volatility effect; Frazzini–Pedersen (2014) "Betting Against Beta" (32
markets); Barroso–Santa-Clara (2015) "Momentum has its moments" shows that
**volatility-managing momentum roughly doubles its Sharpe** by cutting exposure
before crashes. The momentum-crash literature is the single most relevant body of
work to our specific result.

**Why it may work in India.** Indian markets are retail-heavy and lottery-seeking;
the low-vol / BAB premium tends to be *larger* in markets with binding leverage
constraints and speculative retail flow. Several India studies (e.g. low-vol indices
run by NSE/Nifty) show low-vol portfolios beating the cap-weighted index with lower
drawdown.

**Data requirements.** Daily returns only. Both signals come from the price panel we
already have.

**Difficulty.** Trivial. Compute trailing realized volatility (or beta to NIFTY)
over 6–12 months per name; combine with the existing 12-1 momentum rank, or use
volatility to scale exposure (Barroso-style) rather than as a second cross-sectional
score. Both fit the existing `strategies/base.py` → `portfolio/ranker.py` flow.

**Survivorship-bias risk.** None new. Built entirely on the bias-free bhavcopy panel.

**Free-data feasible?** **Yes, completely.**

---

### B. Momentum + Quality

**Economic rationale.** Quality (profitability, low accruals, low leverage, stable
earnings, conservative investment) captures durable franchises. The classic
synergy: momentum tells you *what the market is rewarding now*; quality tells you
*whether the business deserves it*, filtering out junk rallies and pump-and-dump
momentum (a real problem in Indian small caps). AQR's "Quality Minus Junk"
(Asness–Frazzini–Pedersen) is the canonical framework.

**Academic evidence.** Among the strongest of any factor pairing. QMJ is robust
across 24 countries and decades. Momentum+Quality is the backbone of multiple live
"quality-momentum" indices and AQR/Robeco multi-factor products. Quality also
behaves defensively in drawdowns, partially addressing our crash problem.

**Why it may work in India.** Promoter-driven governance issues, accounting fraud,
and pump-and-dump micro-caps make a quality screen unusually valuable in India —
it removes precisely the names that generate spurious momentum. Indian "quality"
indices (Nifty200 Quality 30) have historically outperformed.

**Data requirements.** Point-in-time fundamentals: ROE/ROA, gross profitability,
debt/equity, accruals, earnings stability. Needs several years of *as-reported*
quarterly/annual statements aligned to the correct as-of date.

**Difficulty.** Moderate-to-hard, dominated by data, not code. The scoring is
straightforward once the fundamentals panel exists; building that panel cleanly is
the project.

**Survivorship-bias risk.** **High and subtle.** Free Indian fundamental sources
(screeners, scraped statements) almost always cover only *currently listed*
companies and lack point-in-time snapshots — they show *restated* numbers and drop
delisted firms. Naively merging them onto our bias-free price panel would silently
re-introduce both survivorship and look-ahead bias, contaminating the one thing we
just fixed.

**Free-data feasible?** Partially / poorly. Possible to scrape, but free
*point-in-time, survivorship-free* fundamental history is the hard part and is the
core risk.

---

### C. Momentum + Value

**Economic rationale.** The most celebrated negative correlation in factor
investing. Value (cheap on B/P, E/P, CF/P) and momentum are individually strong and
move out of phase: value loads on beaten-down names, momentum on recent winners.
When momentum crashes (sharp reversals off a bottom), value rebounds — so a
50/50 blend has historically had a far higher Sharpe than either alone.

**Academic evidence.** Asness–Moskowitz–Pedersen (2013) "Value and Momentum
Everywhere" is the landmark — the combination works across 8 markets and asset
classes, and the diversification benefit is the headline result. This is arguably
the **single strongest piece of evidence** for *any* two-factor long-only combo.

**Why it may work in India.** Value has a documented premium in India; combining it
with momentum gives genuine diversification across the cycle. The reversal-protection
property again targets our drawdown.

**Data requirements.** Point-in-time book value, earnings, cash flow → valuation
ratios. Same fundamental-data burden as Quality.

**Difficulty.** Moderate, data-dominated (same as B).

**Survivorship-bias risk.** **High** — identical concern to Quality. Free value data
is restated and survivorship-contaminated.

**Free-data feasible?** Partially / poorly, same caveat as B.

---

### D. Momentum + Profitability

**Economic rationale.** Novy-Marx (2013): gross profitability (gross profit /
assets) is "the other side of value" and a clean predictor of returns. Pairing it
with momentum is a narrower, cleaner version of the Quality combo — profitable firms
with positive momentum.

**Academic evidence.** Strong for gross profitability as a standalone factor
(Novy-Marx; incorporated into the Fama–French 5-factor model as RMW). Evidence for
the *specific momentum+profitability pair* is thinner than for momentum+value or the
broader momentum+quality — it is essentially a quality sub-case.

**Why it may work in India.** Same junk-filtering logic as Quality, slightly less
governance coverage (profitability alone misses leverage/accrual red flags).

**Data requirements.** Gross profit and total assets, point-in-time. Lighter than
full quality but still fundamental.

**Difficulty.** Moderate, data-dominated.

**Survivorship-bias risk.** **High** — same fundamental-data problem.

**Free-data feasible?** Partially / poorly.

---

### E. Momentum + Trend

**Economic rationale.** Cross-sectional momentum (relative winners) plus
time-series trend (own-price uptrend / regime filter). Trend is meant to keep you
out of bear markets and dampen the crash.

**Academic evidence.** Time-series momentum (Moskowitz–Ooi–Pedersen 2012) is real,
but as a *risk overlay* on cross-sectional momentum it mostly reduces drawdown
rather than adding alpha — the two signals are highly correlated.

**Why it may work in India.** Limited incremental value: it addresses risk, not the
alpha deficit.

**Data requirements.** Price only.

**Difficulty.** Trivial — and `strategies/trend_following.py` already exists.

**Survivorship-bias risk.** None new.

**Free-data feasible?** Yes.

**But — we already tested this.** [[trend-filter-experiment]]: MA trend overlays cut
drawdown ~12pts but **did not lift Sharpe or alpha**, and the 200-DMA whipsawed.
This combination is effectively *spent* for our purposes. Listing it for
completeness; it is not a candidate for the "next experiment."

---

### F. Momentum + Size

**Economic rationale.** Small caps historically earn a premium (SMB) and momentum is
*stronger* in small caps. Tilting momentum toward smaller names could amplify
returns.

**Academic evidence.** **Weakest of the six.** The standalone size premium has
largely failed out-of-sample since the 1980s (Asness et al., "Size Matters, If You
Control Your Junk" — size only works *after* a quality control). Momentum-in-small-
caps is real but is mostly a liquidity/transaction-cost illusion: the paper alpha
evaporates under realistic Indian costs and impact, which our cost model
(`costs/cost_model.py`) would expose.

**Why it may work in India.** India does have a persistent small/mid-cap premium and
strong micro-cap momentum — but that is exactly where pump-and-dump, low liquidity,
and our existing anti-manipulation filters fight hardest.

**Data requirements.** Price × shares outstanding for market cap. Shares-outstanding
history is the one mild data gap (partially derivable, partially needs a free
corporate-action/shares source).

**Difficulty.** Easy-moderate.

**Survivorship-bias risk.** Moderate — small caps delist most often, so this combo
is the *most sensitive of all* to survivorship bias. Our bias-free panel handles it,
but it is the combination where getting the universe wrong does the most damage.

**Free-data feasible?** Mostly yes (price-based), with a shares-outstanding caveat.

---

## 3. Ranking — most to least promising

Ranking blends evidence strength **and** feasibility-without-new-bias. A combo we
cannot test cleanly is not "promising" for *us*, however good the academic record.

| Rank | Combination | One-line verdict |
|---|---|---|
| **1** | **Momentum + Low Volatility** | Best evidence *that we can actually test today*; directly attacks the -62% drawdown crash; zero new data risk. |
| **2** | **Momentum + Quality** | Strongest long-run evidence overall and ideal for India's junk problem — but gated behind a real, bias-prone fundamental-data project. |
| **3** | **Momentum + Value** | Equally elite evidence (the canonical diversifier); same fundamental-data gate and survivorship risk as Quality. |
| **4** | **Momentum + Profitability** | A clean, narrower quality variant; thinner pair-specific evidence; same data gate. |
| **5** | **Momentum + Size** | Weak/ fragile standalone evidence, highest survivorship sensitivity, most exposed to costs and manipulation. |
| **6** | **Momentum + Trend** | Already tested — cuts drawdown, adds no alpha. Spent. Not a candidate. |

**Note on the split:** if the question were *purely* "strongest academic evidence,"
the order at the top would be **Quality ≈ Value > Low Vol**. They drop below Low Vol
here *only* because of the data-feasibility and survivorship-risk filter. That gap is
the whole point of the recommendation below.

---

## 4. Recommendation — the single next experiment

> **Run Momentum + Low Volatility next.**
> Combine the existing survivorship-free 12-1 momentum rank with a trailing
> realized-volatility (or beta-to-NIFTY) signal — both as a **second cross-sectional
> screen** and, separately, as a **Barroso-style volatility-scaling overlay** that
> dials exposure down before crashes.

**Why this and not Quality/Value (the higher-evidence pair):**

1. **It is the only top-evidence combo we can test *right now* on the data we
   already trust.** No fundamental-data acquisition, no new survivorship bias. We
   keep the clean panel we just earned.
2. **It targets the exact failure we measured.** Our problem is not low return
   (12.75% CAGR is fine) — it is a -62% drawdown and 0.20 Sharpe driven by momentum
   crashes. Vol-management is the single most documented fix for momentum crashes
   (Barroso–Santa-Clara roughly doubled momentum's Sharpe). This is the
   highest-probability *Sharpe/alpha* improvement available.
3. **It is a fast, cheap, decisive test.** Days of work, not a data project. If it
   lifts Sharpe and trims drawdown, we have proven that *factor blending works on our
   data* — which then justifies the larger investment of building a clean,
   point-in-time fundamental panel to chase the higher-evidence Quality/Value combos
   (ranks 2–3). If it fails, we have learned something cheaply before spending weeks
   on fundamental data.

**Sequencing the whole program:**
1. **Now:** Momentum + Low Volatility (price-only, decisive, attacks the crash).
2. **If (1) works → invest in data:** build a bias-free point-in-time fundamentals
   panel, then test **Momentum + Quality** (rank 2), then **Momentum + Value** (rank 3).
3. Treat Size and Trend as closed.

The discipline holds: no DMA/SMA/rebalance/buffer tuning. This is a *new factor
test*, not a re-parameterization of the old one.

---

## 5. One caution before we run anything

When we do test Momentum + Low Vol, the right success criterion is **risk-adjusted
alpha vs NIFTY 500 TRI, net of our Indian cost model**, not raw CAGR or drawdown
alone. Low-vol blends can look great on drawdown while quietly shedding return; the
bar is *positive net alpha and a Sharpe materially above 0.20*. If it only fixes
drawdown (like Trend did) without lifting Sharpe/alpha, we treat it as another
risk-overlay null result and move to the fundamental-data track — not as a reason to
start tuning vol lookbacks.
