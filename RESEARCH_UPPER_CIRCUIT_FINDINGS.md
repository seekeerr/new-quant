# Research: why stocks lock at a +10% upper circuit — and can tomorrow's be predicted?

**Run date:** 2026-09-21 (Mon) · **Signal date:** 2026-09-21 close · **Target:** 2026-09-22 (Tue)
**Code:** `study_upper_circuit.py`, `predict_upper_circuit.py`, `score_today.py`, `build_open_panel.py`
**Output:** `results/upper_circuit/{drivers,validation}.txt`, `candidates_today.csv`

Universe: full survivorship-free NSE bhavcopy spine, 3,502 equity symbols incl. delisted,
2018-04 → 2026-09. No fundamental screen — every listed stock is in scope, as asked.

---

## 1. The mechanical answer to "kis basis par?"

A stock does not choose to hit +10%. The exchange assigns it a **price band**, and the
band is what makes +10% a wall instead of a number.

- NSE bands are **2% / 5% / 10% / 20%**, measured off the previous close.
- **F&O stocks have no band at all** — only a 10% *dynamic operating range* that
  **flexes another 5% each time it is touched**. An F&O name printing +10% is *not*
  circuit-locked; it can and does keep going.
- Bands are reviewed periodically and tightened on surveillance (GSM/ASM) names.

So a "+10% upper circuit" can only happen to a stock **currently in the 10% band**.
This single fact does most of the filtering work:

| As of 2026-09-21 | count |
|---|---|
| 20% band (or wider) | 1,513 |
| **10% band — the only eligible pool** | **736** |
| 5% band | 56 |
| unbanded / F&O-like | 11 |

**Verification that the band is real, not an artifact:** the distribution of daily returns
piles up sharply at 9.9–10.0% — 3,179 observations in that bucket versus a ~600 baseline
in neighbouring buckets. That is a hard wall, not a continuous distribution.

### A +10% lock is the *minority* circuit event

| band | stock-days | UC locks | lock rate/day | share of all locks |
|---|---|---|---|---|
| 5% | 89,983 | 1,757 | **1.953%** | 20.1% |
| 10% | 1,085,221 | 2,067 | 0.190% | **23.7%** |
| 20% | 2,422,022 | 4,909 | 0.203% | 56.2% |

A 5%-band stock locks up **10x more often** than a 10%-band stock. And only **24% of all
upper-circuit locks in the market are the +10% kind** — most are 20% band.

This was confirmed against live news for 21-Sep-2026: the day's circuit hitters were
Taneja Aerospace and Protean eGov (both **20%**), HMT at 4.99% and Optivalue at 5.0%
(both **5%**). Almost none were genuine 10% locks.

> **Trap this exposes.** Detecting a UC as "closed +10% at the high" is wrong — it admits
> 20%-band stocks that merely *passed through* +10%. Only **25% of +10% closes are true
> 10%-band locks** (2,067 of 8,396). An earlier version of this study had a 4x contaminated
> target until band inference was fixed. QUINT, for example, has printed exactly 20.00%,
> so its "+10% UC" on 17/18-Sep was never a lock at all.

---

## 2. What precedes a +10% lock — the empirical drivers

Base rate: **P(a 10%-band stock locks +10% tomorrow) = 0.171%** — about **1 in 584
stock-days**. Every number below must be read against that floor.
All features are measured at day T's close; the target is a lock on T+1.

| driver | best bucket | P(UC tomorrow) | lift |
|---|---|---|---|
| **Locked UC today** | yes | **26.85%** | **157x** |
| Today's return | in the UC zone | 14.21% | 88x |
| UC count in last 20d | 1 in 20d | 3.65% | 22x |
| Volume surge | 5–10x median | 0.75% | 4.6x |
| Price level | ₹5–20 | 0.75% | 4.6x |
| 20-day momentum | +20–50% | 0.70% | 4.3x |
| Liquidity | micro-cap (<₹25L/day) | 0.51% | 3.1x |
| Distance to 52w high | at the high | 0.48% | 2.9x |
| Range expansion | 5d ATR > 60d ATR | 0.25% | 1.6x |

**The answer to "why":** one factor dominates everything else. A stock that locked today
has a **~27% chance of locking again tomorrow** — 157x the base rate. Every other signal
is a rounding error next to it. Upper circuits are a **serially clustered, self-reinforcing
event**, not an independent daily draw.

The supporting profile is consistent and unflattering: **cheap** (₹5–20), **illiquid**
(micro-cap), **already running** (+20–50% over 20d), on **expanding volume**. Proximity to
the 52-week high is U-shaped — both fresh breakouts *and* beaten-down names (<50% of 52wH)
lock more often than the quiet middle. That second group is the low-float
pump pattern, not a fundamental re-rating.

---

## 3. Out-of-sample validation — does it actually predict?

Model: additive log-odds (naive Bayes) over coarse buckets — deliberately not a black box,
since at a 0.17% base rate a flexible learner memorises noise.
**Train 2018→2023 · Test 2024-01-01→2026-09-18, never touched during fitting.**

| basket | picks | hit rate | lift | mean next-day ret | excess | win% |
|---|---|---|---|---|---|---|
| top-1 | 670 | **12.24%** | 108x | +1.90% | +1.85% | 57.0% |
| top-3 | 2,010 | 6.92% | 61x | +1.04% | +0.99% | 52.6% |
| top-5 | 3,350 | 4.72% | 42x | +0.73% | +0.68% | 50.7% |
| **top-10** | 6,700 | **2.84%** | **25x** | **+0.41%** | +0.36% | 48.1% |
| top-50 | 33,500 | 0.90% | 7.9x | +0.15% | +0.10% | 46.2% |
| rest | 353,357 | 0.04% | 0.3x | +0.03% | −0.01% | 47.4% |

The ranking is **monotone and genuinely predictive** — 25x lift at top-10 is not noise.
But read the absolute number: **2.84%**. Picking 10 names, you should expect
**~0.3 of them** to actually lock. Not 10. Not 5.

**Stability — the edge is decaying:**

| year | top-10 hit rate | mean ret |
|---|---|---|
| 2024 | 3.66% | +0.65% |
| 2025 | 2.98% | +0.23% |
| 2026 | **1.48%** | +0.34% |

2026 is less than half of 2024. Direction is one way.

### The economics kill the basket

- Top-10 gross next-day return: **+0.41%**
- Repo cost model, round-trip, illiquid tier: **0.66–0.75%**
- **Net: negative.**

And the repo's tier-3 slippage assumption (0.2%/side) is *optimistic* for a stock with
₹14 lakh median daily turnover that is about to gap. Only the **top-1** basket (+1.90%
gross) clears costs — a single name, one stock a day, with a visibly decaying edge.

### Fillability — the recurring trap

The good news, against expectation: **92.8%** of true 10%-band UC days traded *below* the
circuit at some point, so they are not all unbuyable. Only **7.2%** were fully locked
(H==L) from the open.

The bad news is where the edge actually lives. The tradeable version of the signal has none:

| cohort | n | mean next-day ret | P(UC) |
|---|---|---|---|
| Locked UC today (buy at close = buy a limit-up stock) | 1,717 | **+3.82%** | 26.8% |
| 1 UC in last 20d, **not today** (freely buyable) | 11,245 | **+0.08%** | 1.8% |

The entire edge sits in the row where you must buy a stock that is **locked limit-up with
no sellers**. The row you can actually transact in pays **+0.08%** — nothing.
Median turnover on a UC day is **₹50.1 lakh**, and 10% of them are under **₹2.5 lakh**.
This is the same **fillability mirage** flagged in the earlier `rs1lakh-universe-breadth`
work: the backtest fills at a price the market would not have given you.

---

## 4. Prediction for Tue 2026-09-22

**Honest framing first: today gives an unusually weak setup.** The dominant predictor —
a stock locking UC today — is **absent from the eligible pool**. Not one of the 676
scored 10%-band names locked today. So the model is working from second-tier signals
only, and the calibrated probabilities are correspondingly low.

Raw naive-Bayes scores overstate probability by up to **41x** (98.8% claimed vs 20.0%
actual) because the features are correlated. Everything below is **calibrated against
actual out-of-sample hit rates**.

### Top 10 — numbers-driven

| # | symbol | **P(UC)** | price | 1d | 5d | vol×20d | %52wH | turnover/day |
|---|---|---|---|---|---|---|---|---|
| 1 | **LIBAS** | **1.2%** | ₹12.8 | +5.7% | +14.2% | 2.9x | 94% | ₹8.0L |
| 2 | TARAPUR | 0.7% | ₹12.3 | −1.9% | −5.1% | 1.7x | 32% | ₹3.9L |
| 3 | VIRINCHI | 0.7% | ₹14.0 | −1.3% | −1.9% | 0.4x | 44% | ₹9.7L |
| 4 | BOHRAIND | 0.7% | ₹12.7 | −0.1% | −5.4% | 0.3x | 48% | ₹2.3L |
| 5 | THAKDEV | 0.7% | ₹118.4 | −7.1% | −7.6% | 3.6x | 74% | ₹0.1L |
| 6 | RRIL | 0.6% | ₹16.4 | +5.3% | +2.4% | 2.9x | 78% | ₹2.3L |
| 7 | ZENITHSTL | 0.6% | ₹5.3 | −4.8% | −9.2% | 3.4x | 58% | ₹4.2L |
| 8 | UNITEDPOLY | 0.6% | ₹46.1 | +0.4% | +6.4% | 4.7x | 100% | ₹62.0L |
| 9 | DIGISPICE | 0.6% | ₹16.3 | −4.0% | −3.3% | 4.7x | 50% | ₹10.4L |
| 10 | BONLON | 0.6% | ₹39.4 | +0.6% | −1.9% | 9.2x | 71% | ₹2.2L |

**Expected outcome: ~0.07 of these 10 lock tomorrow.** Most likely, none do.

### News layer

- **LIBAS** (#1) — ₹28cr market cap, **0% FII / 0% DII**, 61% public float, +24% in a
  month. No catalyst found for the move. Textbook low-float drift on ₹8L/day turnover.
- **NAGREEKCAP** — scored #1 before the band fix and is now **correctly excluded** (20%
  band). Worth noting anyway: **book closure 22–28 Sep**, AGM 28 Sep, and **FY26 net
  profit −60% YoY**. The rally is not earnings-driven.
- **ALKALI** — also excluded post-fix (printed 19.99%, so 20% band). Rated *Sell*.
- Nothing in the top 10 has a scheduled result, order win, or corporate action I could
  find. These are **momentum/float setups, not news setups.**

### The name the model excluded — and shouldn't have

**INDOMIM (Indo-MIM Ltd)** locked at **exactly +10.00% today** and is the single most
interesting candidate on the board:

- It is the **only** stock with the dominant signal (UC today, ~27% base case) present.
- It is genuinely **liquid: ~₹200 crore/day** — unlike every name in the table above.
- Listed 30-Jul-2026; **+137% over its ₹485 IPO price**; +21% in 3 days; new high ₹1,148.
- Returns cap at exactly +10.00% / −5.00% → consistent with a 10% band.

It was dropped **only** because it has 37 trading days of history and band inference
requires 60. That is a technicality, not a judgement. On the research's own logic it is
the strongest single candidate for 22-Sep — with the caveat that a 2-month-old IPO up
137% has no stable band history, and a newly listed stock's band can be revised without
warning.

---

## 5. Verdict

1. **The "why" is answered and it is mechanical.** A +10% lock requires the 10% band, and
   the single dominant cause is **that it locked yesterday** (27%, 157x). The rest of the
   profile is cheap + illiquid + already running + volume surge. Fundamentals are not in
   the story at all.
2. **Prediction works statistically, not economically.** 25x lift at top-10 is real and
   out-of-sample. But 2.84% absolute, +0.41% gross against 0.66–0.75% costs = **net
   negative**, and decaying year over year.
3. **The edge is unfillable where it is strongest.** +3.65% only if you can buy a
   limit-up stock; +0.14% in the version you can actually trade.
4. **Do not trade this basket.** The honest use of this research is as a *watchlist and an
   exclusion filter*, which is what the main system already does via
   `apply_circuit_filter`. This study is the inverse of that filter, and it confirms the
   filter is load-bearing.
5. **If anything is worth watching tomorrow, it is INDOMIM** — not because the model
   picked it (it didn't), but because it is the one name where the dominant signal and
   actual liquidity coexist.

### Caveats

- Bands are **inferred** from 250d return history, not read from an NSE band file. A
  freshly revised band will be misclassified until it prints evidence. Wiring the real
  NSE price-band CSV into `data/` would remove this entire class of error and is the
  highest-value next step.
- Calibration is non-monotonic in the middle score buckets (small-sample noise), so ranks
  2–10 above are close to indistinguishable from each other.
- Micro-cap circuit names carry **GSM/ASM surveillance risk** — the same characteristics
  that make them lock (low float, thin volume) are what attracts exchange action.
