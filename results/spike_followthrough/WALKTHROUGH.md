# 5-Day Spike Follow-Through Study

**Question asked:** stocks that go up ~10–12% within 5 trading days — what do they do over
the *next* 5 trading days?

**Script:** `study_spike_followthrough.py` (repo root) · **Run:** `py study_spike_followthrough.py`

---

## What was tested

| | |
|---|---|
| Data | Survivorship-free NSE bhavcopy spine, `data/cache_bhav/adj_close.parquet` (split/bonus back-adjusted) |
| Universe | 3,291 equities — ISIN `INE` only, so ETFs/funds/DVRs are excluded (the known leakage bug) |
| Period | 2022-01-03 → 2026-05-21 (~4.4 years, 1,085 sessions) |
| Signal | `close[t] / close[t-5] - 1` falls in the 10–12% bucket |
| Forward | `close[t+h] / close[t] - 1`, h ∈ {1, 3, 5, 10, 20}. You see the spike at t's close and buy at t's close — no look-ahead |
| Filters | Traded on every session t−5…t+5; close ≥ ₹10; median 20-day turnover ≥ ₹5 cr (primary tier) |
| Sample | 835,636 eligible stock-days; **16,508** land in the 10–12% bucket |

**The control that matters.** A raw forward return is meaningless in a bull market — every stock
drifts up. So every number is also reported **date-demeaned**: the stock's forward return minus
the *cross-sectional mean forward return of all eligible stocks on the same date*. That strips out
market direction completely. The demeaned baseline is 0.00% by construction, median −0.48%,
win rate 45.0%.

---

## Headline result

**There is no follow-through. A 10–12% five-day pop is followed by mild *under*performance.**

| 10–12% bucket, next 5 days | Value | vs baseline |
|---|---|---|
| Raw mean | **+0.27%** | baseline +0.34% |
| Raw median | −0.26% | baseline −0.04% |
| **Excess mean** | **−0.15%** | baseline 0.00% |
| **Excess median** | **−0.87%** | baseline −0.48% |
| **Win rate vs cross-section** | **42.9%** | baseline 45.0% |
| Excess std | 6.49% | baseline 5.18% |
| p10 / p90 excess | −6.64% / +7.08% | −5.30% / +5.77% |

The +0.27% raw mean is *just market drift* — you'd have got +0.34% picking a stock at random that
day. Adjusted for that, the spike bucket loses about **0.15% on the mean and 0.39pt on the median**
versus the average stock, and wins only 42.9% of the time instead of 45%.

Two things get meaningfully worse, though: **volatility rises 25%** (6.49% vs 5.18% std) and the
tails fatten. You take more risk for a slightly worse expected outcome.

**Statistical check.** On non-overlapping signals only (≥7 calendar days apart per stock,
n=12,084), collapsing to one observation per date to avoid pseudo-replication: mean daily excess
**−0.303% over 1,034 dates, t-stat −2.89**. The negative drift is small but statistically real,
not noise.

---

## The shape of the whole curve (this is the interesting part)

Excess forward-5d return by size of the prior 5-day move:

| prior 5d move | n | excess mean | excess median | win % |
|---|---|---|---|---|
| down (<0%) | 414,073 | **+0.03** | −0.39 | **45.8** |
| flat 0–5% | 278,332 | −0.03 | −0.51 | 44.5 |
| up 5–10% | 95,319 | −0.04 | −0.66 | 44.1 |
| **up 10–12%** | **16,508** | **−0.15** | **−0.87** | **42.9** |
| up 12–15% | 13,957 | −0.02 | −0.84 | 43.7 |
| up 15–20% | 10,383 | +0.16 | −0.84 | 44.2 |
| up 20–30% | 5,543 | +0.26 | −0.91 | 44.2 |
| up 30%+ | 1,521 | **−0.53** | **−2.16** | **39.7** |

Read it as: **short-horizon (5-day) returns in India mean-revert, they don't continue.** Losers do
best, the whole up-move range is flat-to-negative, and 30%+ blow-off moves are actively punished
(−2.16% median, 39.7% win). The mild positive means at 15–30% are a *skew* artifact — the medians
stay negative and the win rates stay below baseline, i.e. a handful of runaway winners drag the
average up while most names fade. Do not confuse that with an edge.

This is completely consistent with the rest of this project: the 12-1 momentum that works
(12-month lookback, 1-month skip) deliberately *skips* the most recent month precisely because
short-term returns reverse. This study is the direct measurement of that reversal.

## Horizon — does it show up later?

| horizon | raw mean | excess mean | excess median | excess win % |
|---|---|---|---|---|
| 1d | +0.15 | −0.01 | −0.35 | 43.6 |
| 3d | +0.25 | −0.11 | −0.67 | 42.6 |
| 5d | +0.27 | −0.15 | −0.87 | 42.9 |
| 10d | +0.51 | −0.16 | −1.18 | 42.8 |
| 20d | +1.46 | −0.08 | −1.64 | 43.2 |

No. Holding longer just collects more market drift (raw +1.46% at 20d) while the excess stays
negative and the median keeps sinking. There is no delayed continuation.

## Year by year (excess fwd-5d, %)

| year | n | raw mean | excess mean | excess median | win % |
|---|---|---|---|---|---|
| 2022 | 2,787 | −0.22 | −0.28 | −0.83 | 42.5 |
| 2023 | 3,108 | +1.12 | **+0.19** | −0.57 | 45.4 |
| 2024 | 4,977 | +0.22 | −0.24 | −1.16 | 41.0 |
| 2025 | 3,717 | −0.72 | −0.26 | −0.84 | 43.1 |
| 2026 | 1,919 | +1.64 | −0.08 | −0.73 | 44.4 |

Negative in 4 of 5 years; the median is negative in **all five**. Stable, not a regime artifact.

## Liquidity and context cuts — nothing rescues it

| liquidity tier | n | excess mean | excess median | win % |
|---|---|---|---|---|
| ≥ ₹1 cr ADV | 24,956 | −0.19 | −1.06 | 41.8 |
| ≥ ₹5 cr ADV | 16,508 | −0.15 | −0.87 | 42.9 |
| ≥ ₹25 cr ADV | 7,230 | −0.08 | −0.67 | 43.6 |

More liquid = less bad, never good. The effect is *worse* in small/illiquid names, which is the
classic signature of noise-driven pops.

Context cuts inside the 10–12% bucket:

| cut | n | excess mean | excess median | win % |
|---|---|---|---|---|
| above 200-DMA | 10,773 | −0.03 | −0.78 | 43.5 |
| below 200-DMA | 3,313 | **−0.55** | −1.07 | 39.8 |
| 12-1 momentum > 0 | 10,333 | −0.01 | −0.76 | 43.7 |
| 12-1 momentum ≤ 0 | 4,147 | **−0.46** | −1.06 | 40.9 |
| **above 200-DMA AND mom > 0** | 8,601 | **+0.06** | −0.73 | 43.8 |
| smooth spike (max 1d < 5%) | 4,565 | −0.30 | −0.88 | 42.4 |
| gappy spike (max 1d ≥ 8%) | 4,573 | +0.03 | −0.86 | 43.0 |

The most useful line here: trend context tells you where the *damage* is, not where the edge is.
A 10–12% pop in a **downtrending** stock is a genuine fade signal (−0.55% excess, 39.8% win).
A pop in an uptrending stock is merely *neutral* (+0.06% mean, but median still −0.73% and win
still 43.8% vs 45% baseline). Best case = break-even, and that's before costs.

## Cost reality check

Round-trip cost (STT, stamp, GST, brokerage, slippage — `costs/cost_model.py`):
**0.55% on a ₹50k position, 0.49% on ₹1L.**

Even the best context cut (+0.06% mean excess) is **~9× underwater against costs** on a 5-day
round trip. There is no version of "buy the 5-day pop" that survives.

---

## Recommendation

1. **Do not build a 5-day-spike continuation strategy.** The measured effect is negative before
   costs and deeply negative after them.
2. **The tradeable read of this data is the opposite one:** a big 5-day pop in a stock that is
   *below its 200-DMA / has negative 12-1 momentum* underperforms by ~0.5% in 5 days with a 39.8%
   win rate. That is still under the 0.5% cost hurdle for a long/short retail implementation, so
   it is not a standalone strategy either — but it is a legitimate **avoid/defer filter**: don't
   buy into a recent 5-day pop, especially in a downtrend.
3. **Practical use in the existing momentum book:** this is empirical support for a *rebalance
   timing* rule — if a name qualifies on 12-1 momentum but has just popped 10%+ in 5 days, waiting
   a week has historically cost nothing and saved ~0.9% of median entry price. Worth testing as
   an entry-timing overlay, not as a signal.
4. **Do not tune the bucket edges.** The whole 5–30% range tells the same story; the result is a
   property of short-horizon reversal in India, not of the 10–12% cut point. Searching for a
   bucket that "works" here would be exactly the overfitting the project has already banned.

## Caveats

- Prices are bhavcopy back-adjusted by gap detection (`adjust_bhav.py`, median single-day error
  ~0.25% vs Upstox). A handful of unadjusted corporate actions could sit inside the spike buckets;
  the effect is small at this sample size but is a known source of noise in the 30%+ bucket.
- Entry is assumed at close[t] with no slippage beyond the cost model. A real implementation
  chasing a spiking stock would fill worse, making the result *more* negative.
- Excess is measured vs the equal-weighted eligible cross-section, not vs a sector-neutral or
  beta-adjusted benchmark. High-beta names dominate the spike bucket, so part of the 25% higher
  volatility is beta, not idiosyncratic risk.
- Overlapping signals were handled by the non-overlap + per-date collapse in section D; the main
  tables (A–C, E–G) still use overlapping events, so treat their *n* as effective-sample-inflated.

---

## File index

| File | What |
|---|---|
| `report.png` | 4-panel chart: bucket means/medians, win rates, 10–12% distribution, context cuts |
| `report.txt` | Full console output of the run |
| `buckets_raw_fwd5.csv` | Raw forward-5d stats for every prior-move bucket |
| `buckets_excess_fwd5.csv` | Date-demeaned forward-5d stats for every bucket (**the honest table**) |
| `horizons_10_12.csv` | 10–12% bucket at h = 1, 3, 5, 10, 20 days |
| `by_year_10_12.csv` | Year-by-year stability of the 10–12% bucket |
| `by_liquidity_10_12.csv` | 10–12% bucket across the three liquidity tiers |
| `by_context_10_12.csv` | 10–12% bucket split by 200-DMA / 12-1 momentum / spike shape |
| `events_10_12.csv` | All 16,508 raw events (date, symbol, past5, liq, trend context, fwd returns) |
