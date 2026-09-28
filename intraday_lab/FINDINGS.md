# Intraday lab — findings

**Date:** 2026-09-24 · **Isolated:** imports nothing from `strategy_live`,
`research_harness` or `signals`; writes only to `results/intraday_lab/`.
Nothing here can disturb the frozen strategy or the paper-trading run.

## Verdict first

**No tradeable intraday strategy found.** One signal — fading overnight gap-downs
— shows a very large edge in the data, but it exists only where it cannot be
executed. Detail below, because the *way* it fails is the useful part.

## What the data allows

The repo has **daily OHLCV bhavcopy only**. No minute bars, no ticks, no order
book, and no BSE exchange feed (`data/cache/BSE.parquet` is the stock *BSE Ltd*,
not BSE market data).

So the only honest intraday shape is **buy at the official open, sell at the
official close** — real, tradeable, no overnight risk. Not testable, and not
attempted: VWAP entries, intraday stops, first-30-minute breakouts, scalping,
or anything needing the path between open and close.

## The cost wall

Intraday charges are lower than delivery (STT 0.025% sell-side only vs 0.1%
both sides; stamp 0.003% vs 0.015%), modelled properly:

| Liquidity | ₹25k order | ₹1 lakh order |
|---|---|---|
| liquid | 20.7 bp | 18.3 bp |
| mid | 40.7 bp | 38.3 bp |
| illiquid | 80.7 bp | 78.3 bp |

Trading ~250 times a year multiplies this by 250. A mid-liquidity book needs
**> 38 bp per day, every day**, before it earns anything.

For scale: the average eligible stock moves **−20.9 bp** from open to close. The
intraday drift is negative before costs.

## The one signal that appeared to work

Rank by most-negative overnight gap, buy the 10 worst at the open, sell at the
close. Train 2017–2023: **+120.7 bp/day, 76.6% hit rate, t-stat 25**. That is
~656% annualised net. Numbers like that are always a bug or an artifact, so it
was attacked rather than reported.

**It is not a corporate-action artifact.** Raw gaps match adjusted-overnight
returns to a 0.00% median difference — the gaps are genuine price moves.

**It is a fillability artifact.** Two tests settle it.

*Where the open sits in the day's range* — for gap-down picks the open is at
median **0.203** of the range (vs 0.546 for all stock-days), and the 25th
percentile is **0.000**: a quarter of these picks open at the exact low of the
day. The strategy is "buy at the day's low", which is not an order you can place.

*Edge vs entry price* (≥₹1cr/day universe, train):

| Entry | Gross | Net of 38 bp |
|---|---|---|
| exact open print | +120.7 bp | +82.7 bp |
| open + 10% of range | +59.0 bp | +21.0 bp |
| open + 25% of range | −34.8 bp | negative |

Half the edge is gone by the time you are 10% of the day's range away from the
open print.

## The decisive test: edge vs liquidity

If this were alpha, it would survive in liquid names. It does the opposite.

| Universe | Entry | TRAIN | HOLDOUT 2024-26 |
|---|---|---|---|
| ≥₹1cr/day | open | +120.7 bp | +107.4 bp |
| ≥₹10cr/day | open | +53.5 bp | +60.7 bp |
| ≥₹10cr/day | open+10% | +3.0 bp | +7.5 bp |
| **top-100 by turnover** | **open** | **+18.3 bp** | **+1.1 bp** |
| top-100 | open+10% | −19.5 bp | −30.6 bp |

In the top 100 names — precisely where a pre-open auction fill is realistic —
the holdout edge is **+1.1 bp/day against a 21 bp cost**. Zero.

**Edge falls monotonically as executability rises.** That inverse relationship is
the signature of a microstructure artifact, not of alpha. The measured return is
compensation for providing liquidity into a disorderly open, and it is only
available to someone who can actually be filled at that print.

## Other signals tested

21 signal families × 3 basket sizes, all on data knowable at the open
(previous-close features plus today's gap): gap-up follow, gap in sigmas,
previous-day momentum and reversal, weekly and monthly reversal, close-position
in range, volume surge and dry-up, range expansion and compression, realised
vol, 52-week-high proximity, price level.

**Every one of them is below the cost hurdle.** The best non-gap signal
(narrow range, top 10) returns **−9.5 bp/day** gross. Nothing else came close to
even the liquid-tier 21 bp hurdle.

## Can news be followed intraday?

Two separate questions, with different answers.

**Backtesting a news strategy: no.** There is no historical news archive here,
and news trading needs the *timestamp* of each headline to the minute — whether
you could have traded before or after the market absorbed it. Daily bars cannot
answer that even if headlines were available. Any news backtest built on this
data would be fabricated.

**Using news live: possible, but unvalidated.** Headlines can be fetched during
the session. But an unbacktested rule is a guess, and the discipline that makes
the frozen strategy trustworthy — search on one period, validate once on
untouched data — cannot be applied to it. It would also put a discretionary
override in front of a systematic book, which is the most common way such a book
dies.

If news trading is genuinely wanted, the prerequisite is a timestamped historical
archive (a vendor feed, or a scraper run forward for six-plus months before any
conclusion). That is a data project, not a strategy project.

## UPDATE 2026-09-24 — hourly data fetched, question settled directly

The daily study could only *infer* that the gap-fade needed the opening print.
Hourly bars were then fetched (yfinance, 1h, 2 years, 398 symbols, 494 trading
days, 79 seconds) and the question was tested head-on: enter at the open of each
hourly bar instead of at 09:15, exit at the 15:15 close.

**The edge is consumed inside the first hour.**

| Entry | gross bp | net of 38 bp | hit% |
|---|---|---|---|
| 09:15 (idealised, unplaceable) | +18.7 | −19.3 | 54.0 |
| **10:15 (first placeable entry)** | **+2.1** | **−35.9** | 47.7 |
| 11:15 | −0.5 | −38.5 | 48.5 |
| 13:15 | −1.1 | −39.1 | 49.6 |

Same shape in the ≥₹10cr/day tier: +15.9 bp at 09:15, +3.5 bp by 10:15.

Split-half check (first year vs second), entry at 10:15: **+10.9 bp → −6.4 bp**.
Decaying, and already negative in the recent half.

Note the 09:15 figure here (+18.7 bp) is far below the daily study's +107 bp,
because this universe is the top 400 by turnover — consistent with the daily
finding that the edge vanishes in liquid names. Two independent datasets, same
conclusion.

**Verdict unchanged and now directly evidenced:** the gap-fade is an opening-
auction phenomenon. By the time a normal order can be placed, it is gone. This
is what an efficient market should do to a well-known effect.

## What intraday data can be fetched

Measured, not assumed:

| Interval | History | Bars/day | Backtestable today? |
|---|---|---|---|
| 1m | 7 days | ~375 | no — forward collection only |
| 5m | 60 days | 75 | no — forward collection only |
| 15m | 60 days | 25 | no — forward collection only |
| 30m | 60 days | 13 | no — forward collection only |
| **1h** | **730 days** | **7** | **yes** |

400 symbols of 1h/2y takes ~80 seconds (`py -m intraday_lab.fetch`).

To get finer history you must accumulate it forward: the 60-day window slides,
so running a collector every ~50 days builds an archive that is a year old in a
year. There is no shortcut to history you did not save.

Two biases this data has that the bhavcopy spine does not: **survivorship**
(yfinance serves only currently-listed symbols) and a **thin sample** (~500
trading days total).

## What would change the answer

- **Minute bars** would make real intraday strategies testable. Without them
  this lab is limited to open→close, which is one coarse shape.
- **Opening-auction access** is the specific capability the gap-fade needs. If
  orders can genuinely be placed into the pre-open call and filled at the
  discovered price, the ≥₹1cr/day result deserves a fresh look — as an
  execution question, not a signal question.
- **BSE data** would widen the universe, but would not change the cost wall,
  which is what kills this.

## Reproduce

```
py -m intraday_lab.research
```
Outputs `results/intraday_lab/train_signals.csv`.
