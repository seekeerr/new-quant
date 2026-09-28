# Sub-hourly resolution — the campaign's last open question, closed

**2026-09-24 · 5m and 15m bars · 249 NSE symbols · 59 trading days (2026-07-03 → 09-24)**

`CAMPAIGN_VERDICT.md` ended with one caveat: 14,667 configs proved nothing works
at *hourly* resolution, and the literature puts intraday reversal at horizons
much shorter than an hour. So the hourly result could not rule out minute-scale
effects. It said getting that data was "a six-month lead time".

That was wrong on the data — yfinance serves 5m and 15m bars for a trailing
60-day window, available immediately. 59 days is thin, but it is enough to
answer the question, because the answer does not depend on sample size.

---

## The answer

**Finer resolution makes it strictly worse, and the reason is structural.**

| resolution | best gross edge | cost floor | ratio |
|---|---|---|---|
| 1 hour (14,667 configs) | 22.1 bp | 21 bp | **1.05x** |
| 15 min (960 configs) | 13.3 bp | 21 bp | **0.63x** |
| 5 min (960 configs) | 5.2 bp | 21 bp | **0.25x** |
| 5 min, single-bar hold | 0.2 bp | 21 bp | **0.01x** |

Zero of the 1,920 sub-hourly configs were net-positive with both halves
agreeing. Not one. The ladder is monotone in resolution, and it points the
wrong way: **every step finer costs you roughly half the gross edge and none of
the fee.**

Both sub-hourly batteries put their best configs at the *longest* horizon in
their grid — h8 of 8, at both resolutions. The search kept trying to walk back
toward daily and the grid would not let it.

---

## Why — alpha accrues in time, cost accrues in trades

Hold one signal fixed (short the biggest losers of the last 3 hours, top-10,
top-100 by liquidity) and move **only** the holding period:

| hold | 5m panel gross | 15m panel gross | bp per hour |
|---|---|---|---|
| 5 min | 0.2 | — | 3.0 |
| 15 min | 1.4 | 1.1 | 4.6–5.6 |
| 30 min | 2.8 | 3.0 | 5.2–6.1 |
| 1 hour | 6.7 | 6.8 | 6.7–6.8 |
| 2 hours | 12.1 | 11.6 | 5.8–6.0 |

**The two panels agree to within a fraction of a basis point at every horizon
they share** (5m at 1 hour: 6.7 bp; 15m at 1 hour: 6.8 bp). This is not two results, it is one effect measured twice: the edge
accrues at a near-constant **~6 bp per hour of exposure**, and the resolution of
the bars you look at has nothing to do with it.

The cost does not work that way. One round trip is 21 bp whether you hold it for
five minutes or five hours. So:

> **break-even holding period = 21 bp ÷ 6 bp/hour ≈ 3.5 hours**

The NSE session is 6.25 hours. Break-even is over half of it, which means the
only viable version of this trade is *hold it all day* — and holding all day is
exactly the open→close shape that the hourly campaign already searched 14,667
ways and rejected at 22.1 bp.

The grid was telling us this before the curve confirmed it: all 25 of the 15m
battery's top configs were at the two **longest** horizons tested. Nothing short
was anywhere near the top.

---

## Half of even that is a bet on a falling market

The 59-day window is one regime. Shorting losers collects the market's drift for
free if the market fell — and it did. Measured against the equal-weighted return
of the same eligible universe over the same bars:

| hold | raw short | market | market-neutral | t | neutral bp/hr |
|---|---|---|---|---|---|
| 30 min | 3.0 | −1.6 | **1.5** | 1.99 | 2.9 |
| 1 hour | 6.7 | −3.3 | **3.4** | 3.28 | 3.4 |
| 90 min | 9.5 | −5.2 | **4.3** | 2.95 | 2.8 |
| 2 hours | 11.6 | −6.7 | **5.0** | 2.63 | 2.5 |

**Roughly half the edge is the market going down**, not cross-sectional skill.
The genuine residual is ~3 bp/hour — and a market-neutral book pays the round
trip on both legs, 42 bp. Break-even holding for the honest version:

> **42 bp ÷ 3 bp/hour = 14 hours of exposure — more than two full sessions.**

The long leg (buy the winners, market-neutral) earns +1.3 to +3.5 bp. The
asymmetry the hourly campaign reported — only the short side works — reproduces
here exactly.

---

## What is real here

The effect itself is not noise. `rev8|h8|top100 S top20` shows t = 6.09 at
N = 960, against a √(2·ln N) = 3.71 noise bar, both halves positive (7.4 / 10.7).
The 5m battery clears its own noise bar too (t = 6.61 on `rev1_x_vol|h8` long).
Both reproduce independently, at different resolutions, on different sides. The
hourly campaign found the same family ("short the morning's biggest losers") and
so did the breakout study, wearing a costume.

So this is now four independent measurements of one real phenomenon:
**liquidity provision pays about 3 bp/hour, market-neutral, to whoever absorbs
the selling.** That is a genuine number about this market. It is also, at every
resolution tested, between a third and a seventh of what it costs to collect.

---

## Data notes

- **The 09:15 `volume == 0` defect is specific to the 1h feed.** In the 15m
  panel the opening bar is 0.2% zero-volume, and every other bar is 0.0%. The
  hourly feed's 74.9% was an aggregation artifact, not a source problem. Volume
  features are safe to build on the finer panels.
- Opening-bar moves are ~3x midday: 48.5 bp median |return| at 09:15, decaying
  monotonically to 9.8 bp at 14:15, rising to 17.5 bp into the close.
- 291,304 tradeable bar-symbol cells at 15m (~197 names per bar).
- Next-bar open→open sd is 31.4 bp, so the 21 bp cost floor is **0.67 sd of a
  single name's move**. A signal has to predict two-thirds of a standard
  deviation, per trade, just to break even.

## Limits of this result

- 59 days, one regime (Jul–Sep 2026), yfinance survivorship. Thin.
- It does not need to be thick. The break-even arithmetic is driven by the
  *accrual rate*, which two independent panels agree on to a fraction of a bp,
  and by the cost floor, which is a fee schedule, not an estimate.
- What this cannot see: order-book state, queue position, latency arbitrage.
  Those are not signals built from OHLCV bars and no amount of bar data will
  test them. Ruling them in or out needs tick/depth data and a colocated
  execution assumption — a different business, not a different backtest.

## Files

| | |
|---|---|
| `harness_fine.py` | bar-index harness, next-bar-open entry, same-day exits |
| `agent_fine.py` | the battery (12 signals × 4 horizons × 3 sizes × 2 sides × 2 tiers) |
| `probe_fine.py` | panel quality, the volume-defect check |
| `study_horizon.py` | the edge-vs-holding-period curve — the actual finding |
| `study_neutral.py` | the market-drift attack |
| `study_long_only.py` | long-only same-day sweep (492 configs) |
| `study_long_only_period.py` | 1h panel split by period — what resolved the conflict |
| `study_long_only_attack.py` | month-by-month and outlier attacks on the winner |
| `study_exit_rules.py` | stop / target / trailing / signal exits |
| `study_liq_ladder.py` | liquidity floor ladder on the winning config |
| `groww_costs.py` | Groww's real intraday rate card (replaces the earlier guess) |
| `run_capital.py` | the rupee simulation at Rs 1 lakh and Rs 5 lakh |
| `show_trades.py` | one real day's trades, name by name |
| `results/intraday_lab/fine_*_battery.csv` | every config |
---

## Long-only, same day — tested separately, because it is the cheapest shape

Requested directly: no shorting. Buy in the morning, sell the same day. This
deserves its own answer because it is the **best case for intraday** — one round
trip a day (21 bp once, not 63) and the longest holding the session allows, so
it collects the most of the 6 bp/hour accrual.

**On the 15m panel it looks like the campaign's first real winner:**

`mom2|10:15|top5` — at 10:15 buy the 5 biggest gainers of the prior 30 minutes,
sell at the close: **+47.7 bp gross, +26.7 bp net**, 57 days, all three months
positive (+37.8 / +43.4 / +64.0), median day +45.1 vs mean +47.7 (so not
outlier-driven), and it still pays +7.0 bp net after deleting the best 3 days.
13 of 492 configs were net-positive with both halves agreeing.

**On 490 days of 1h data the same trade is dead:** +0.9 bp gross at top-5,
t = 0.13. Against a 21 bp cost.

### Resolving the conflict

The two panels overlap on exactly one stretch. Running the 1h version on only
those days:

| period | days | strategy | market | vs mkt | net | t |
|---|---|---|---|---|---|---|
| **Jul–Sep 2026 only** | 59 | **+32.5** | −1.3 | +33.8 | **+11.5** | 2.06 |
| everything before Jul 2026 | 421 | **−3.5** | −0.5 | −3.0 | −24.5 | −0.44 |
| full sample | 480 | +0.9 | −0.6 | +1.5 | −20.1 | 0.13 |

Year by year, top-5: 2024 **−5.9**, 2025 **−2.6**, 2026 **+8.0**.

So both panels agree with each other. **Jul–Sep 2026 genuinely had a strong
intraday momentum regime** — the 15m number is not an artifact and not a bug.
It is an honest measurement of three months. Over the 421 days before it, the
identical strategy loses money *gross*, before paying a rupee of costs.

### The trap this exposes, which is worse than the result

The 5m/15m feeds have a hard 60-day window. **That window can only ever show
you the last three months** — and it will always look like whatever regime the
market is currently in. A researcher who had only the fine data would have
found a +47.7 bp strategy, seen it hold up across every month available,
survive an outlier check and a both-halves check, and shipped it.

The 2-year panel is the only thing that catches it. Any future work on the fine
panels must confirm on the 1h panel or it means nothing.

### Verdict

Long-only same-day is the strongest intraday result in the whole campaign, and
it is still a bet that a 3-month-old regime persists — against a 2-year record
where it does not. It is the one shape cheap enough to be worth *watching*
(one round trip a day, paper, costs nothing), but not one to fund.
### Exit rules — tested, because "sell at the close" was never the strategy's choice

Fair objection: every test above exits on a clock, not on a signal. So the
position was walked bar by bar and exited on a rule instead — stop loss, take
profit, trailing stop, first down bar, or a close below VWAP. Anything not
triggered still exits at the close. Where a bar's high clears the target *and*
its low breaks the stop, the stop is assumed to fill, so every ambiguity is
resolved against the strategy.

**In the good regime (15m panel, Jul–Sep 2026) every exit rule LOST money
against simply holding:**

| exit rule | bars held | gross |
|---|---|---|
| **hold to close** | 21.0 | **+51.7** |
| stop 2.0% | 18.2 | +43.2 |
| stop 1.0% | 13.0 | +35.0 |
| below VWAP | 10.5 | +26.0 |
| take profit 1.0% | 11.2 | +16.5 |
| first down bar | 3.3 | +17.9 |
| trailing 0.5% | 2.5 | +6.9 |
| trailing 1.0% | 5.3 | −6.4 |

Gross runs at roughly **2.5 bp per bar held**, almost monotonically. That is the
6-bp-per-hour accrual again, seen from a third direction: any rule that gets you
out early cuts the alpha and leaves the 21 bp cost untouched. Take-profits are
worse than their holding time implies, because they truncate the right tail that
momentum depends on.

**Over 488 days (1h panel) nothing works with or without an exit rule:**

| exit rule | gross | net |
|---|---|---|
| hold to close | +0.6 | −20.4 |
| stop 1.0% | **+7.7** | −13.3 |
| below VWAP | +6.7 | −14.3 |
| take profit 1.0% | −5.9 | −26.9 |
| trailing 1.5% | −22.8 | −43.8 |
| stop 1% + target 0.5% | −22.9 | −43.9 |

One honest nuance: over the full sample stops *improve* gross (+7.7 vs +0.6),
because in a regime where the signal is wrong, cutting losers helps. In the
regime where the signal works, the same stops destroy the edge. That is the
usual trade — stops buy you regime insurance and charge you alpha — and here the
insurance is not enough either. Best rule anywhere on the long sample is still
**13 bp short** of the cost floor.
### Run as an actual book at Rs 1 lakh and Rs 5 lakh

Every number above is in basis points, which hides three things a real book
cannot avoid: whole shares, per-order brokerage, and cash that cannot be
deployed. Re-run as a rupee simulation — buy at the entry bar's open +5 bp,
sell at the closing price −5 bp, brokerage `min(0.03%, Rs 20)` per order,
intraday statutory rates (STT 0.025% sell-side, stamp 0.003% buy-side), on a
universe filtered to >= Rs 50 crore/day turnover so fills are realistic:

| panel | capital | days | Rs/day | final | total | annualised | win% | maxDD |
|---|---|---|---|---|---|---|---|---|
| Jul–Sep 2026 | Rs 1 lakh | 57 | **+258** | 1,14,712 | **+14.7%** | +82.6% | 57.9 | −3.5% |
| Jul–Sep 2026 | Rs 5 lakh | 57 | **+1,473** | 5,83,974 | **+16.8%** | +97.6% | 56.1 | −3.5% |
| **2 years** | Rs 1 lakh | 489 | **−95** | 53,316 | **−46.7%** | −27.5% | 42.7 | **−59.3%** |
| **2 years** | Rs 5 lakh | 489 | **−509** | 2,50,920 | **−49.8%** | −29.7% | 41.3 | **−61.6%** |

Same code, same strategy, same costs. Fifty-seven days say +83% a year. Four
hundred and eighty-nine days — which *contain* those fifty-seven — say you end
with **half your money** and sit through a 59% drawdown to get there.

**Costs are not what kills it at this size.** The simulation's realised cost is
10.7 bp per round trip excluding slippage, ~21 bp including it, and the Rs 20
brokerage cap means a Rs 1 lakh book pays only ~2 bp more than a Rs 50 lakh one.
Idle cash from whole-share rounding is 4–9% at Rs 1 lakh and under 2% at
Rs 5 lakh. Neither is the problem. The problem is that the signal does not work
outside one quarter.

### The liquidity ladder, on the winner itself

| turnover floor | gross | net | t |
|---|---|---|---|
| none | +45.6 | +24.6 | 2.22 |
| >= Rs 10 cr | +45.2 | +24.2 | 2.23 |
| >= Rs 50 cr | +46.7 | +25.7 | 2.70 |
| **>= Rs 100 cr** | **+13.3** | **−7.7** | **0.87** |

Holds through Rs 50 crore and dies in the top ~140 names. So at Rs 1–5 lakh
**execution is genuinely not the constraint** — this is one of the few results
in the campaign where the fill assumption is safe. That makes the verdict
cleaner, not softer: the strategy is not failing because we cannot trade it.
It is failing because it does not have an edge outside Jul–Sep 2026.

### Correction: the cost model was wrong, checked against Groww's rate card

The rupee simulation above used a guessed cost model. Checked against
groww.in/pricing (2026-09-24), it was wrong in three ways, all in the same
direction:

| | assumed | actual (Groww) |
|---|---|---|
| brokerage | 0.03% per order, cap Rs 20 | **0.1% per order, cap Rs 20, floor Rs 5** |
| exchange txn | 0.00345% | 0.00297% (NSE) |
| IPFT | *missing* | 0.0001% both sides |

Brokerage is the one that matters. **Below Rs 20,000 per order the Rs 20 cap
never binds, so a small book pays a flat 0.1% per leg — 20 bp per round trip,
before anything else.** A Rs 1 lakh book split 5 ways sits exactly at the kink.

| capital | per name | round trip (excl. slip) | was assumed |
|---|---|---|---|
| Rs 1 lakh | 20,000 | **27.1 bp** | 10.7 bp |
| Rs 2 lakh | 40,000 | 15.3 bp | 10.7 bp |
| Rs 5 lakh | 1,00,000 | 8.3 bp | 8.7 bp |
| Rs 10 lakh | 2,00,000 | 5.9 bp | 6.7 bp |

The 21 bp figure used throughout this lab turns out to be right for a **Rs 5
lakh** book (8.3 bp + 10 bp slippage = 18.3) and far too kind for a Rs 1 lakh
one (37.1 bp all-in). Re-running with the real rates:

| panel | capital | days | Rs/day | total | maxDD | costs paid |
|---|---|---|---|---|---|---|
| Jul–Sep 2026 | Rs 1 lakh | 57 | +93 | **+5.3%** | −6.6% | Rs 14,646 |
| Jul–Sep 2026 | Rs 5 lakh | 57 | +1,480 | **+16.9%** | −3.5% | Rs 23,967 |
| 2 years | Rs 1 lakh | 489 | −150 | **−73.6%** | −75.6% | Rs 57,753 |
| 2 years | Rs 5 lakh | 489 | −545 | **−53.3%** | −62.6% | Rs 1,68,416 |

At Rs 1 lakh the correction ate two thirds of the good regime: +14.7% became
**+5.3%**, because Rs 14,646 of costs was paid on a Rs 1 lakh book in 57 days.

**Concentration is the only lever that beats the kink**, and it does not save it:

| names | per name | brokerage | regime | 2 years |
|---|---|---|---|---|
| 2 | 50,000 | 8 bp | **+33.2%** | **−79.8%** |
| 3 | 33,333 | 12 bp | +17.0% | −77.7% |
| 5 | 20,000 | 20 bp | +5.3% | −73.6% |
| 10 | 10,000 | 20 bp | −10.0% | −82.2% |

Fewer names cut the fee and lift the good regime, and change nothing about the
two-year answer except to add single-stock risk on top of it.

**Not modelled:** Rs 50 per position for a system auto-square-off. This strategy
exits deliberately, but one missed exit on a Rs 20,000 position is 25 bp — more
than a day's edge.
