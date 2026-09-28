# Intraday momentum and reversal within the session - findings

**Family:** does what a stock did earlier today predict what it does for the rest
of today?
**Data:** 1h bars, 398 NSE symbols, 490 trading days (2024-09-25 -> 2026-09-24),
7 slots/day. Entry at slot open, exit at 15:15 close, same day.
**Code:** `intraday_lab/agent_momentum.py` - **Raw results:**
`results/intraday_lab/agent_momentum_all.csv`
**Configs evaluated: 2,964** inside the scripted batches, plus ~120 ad-hoc
attack runs (~3,080 total). **Net-positive with statistical support: none.**

## Verdict

**Nothing in this family clears costs.** The intraday continuation effect is
real but small and one-sided, and it is roughly half the size of the round-trip
cost. The single best config found anywhere printed **+7.9 net bp/day** - on 220
days, with a **t-stat on the net return of 1.05**, after a search of ~3,000
configs that needs t ~ 4.3 to mean anything. It is noise.

Three things the search did establish, which are worth keeping:

1. **Intraday momentum is asymmetric.** Buying today's winners earns nothing
   (+0.8 to +5 bp gross at every entry slot, t < 1). Shorting today's losers
   earns something real (+5 to +12 bp gross, t 2-3, both halves positive). The
   information in "what this stock did this morning" is almost entirely on the
   downside.
2. **Even the working side is half a cost.** +12.8 bp gross against a 21 bp
   liquid round trip. Not close.
3. **It decays with executability.** The same signature `FINDINGS.md` recorded
   for the gap-fade: Rs 10cr universe +11.4 bp -> Rs 100cr +9.4 bp -> Rs 300cr
   +4.1 bp. And it lives entirely in the high-volatility half of the universe
   (+11.2 bp vs +1.2 bp in the low-vol half).

## Scale of the problem

Average eligible stock, 10:15 open -> 15:15 close: **-0.55 bp**. There is no
drift to ride; every bp must come from cross-sectional selection. The largest
cross-sectional spread any feature in this family produced was **~12 bp**
top-decile-minus-bottom-decile, against a long/short hurdle of 2 x 21 = **42 bp**.

| Entry | best top-minus-bottom spread | feature | L/S hurdle |
|---|---|---|---|
| 10:15 | 6.7 bp | today_sofar excl. gap | 42 bp |
| 11:15 | 11.6 bp | first-bar return | 42 bp |
| 13:15 | 8.0 bp | first-bar return | 42 bp |

A 4:1 to 6:1 gap between cost and signal is not a tuning problem.

## Top configs

Per-day bp on the eligible universe, net of the matching cost (38 bp at the
Rs 1cr floor, 21 bp at Rs 10cr and above). H1/H2 are the two sample halves.
The `t` column is the gross t-stat the harness reports - the autopsy below
explains why the *net* t-stat is the one that decides.

| # | config | side | N | days | gross | **net** | hit% | t | H1 | H2 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `-slot_ret_0` @11:15, low-dispersion days, liq | S | 5 | 220 | 28.9 | **+7.9** | 53.6 | 3.84 | 28.1 | 29.6 |
| 2 | `-slot_ret_0` @11:15, low-disp, liq>=Rs100cr | S | 5 | 220 | 27.0 | **+6.0** | - | 4.13 | 24.6 | 29.5 |
| 3 | `-slot_ret_0` @11:15, low-disp, liq | S | 10 | 220 | 22.1 | **+1.1** | 65.9 | 4.10 | 21.4 | 22.8 |
| 4 | `-slot_ret_0` @11:15, Thu/Fri only, liq | S | 10 | 190 | 20.3 | -0.7 | 62.6 | 3.09 | 21.7 | 18.9 |
| 5 | `-slot_ret_0` @11:15, big market-down days | S | 10 | 120 | 20.0 | -1.0 | 60.8 | 2.51 | 19.1 | 21.0 |
| 6 | `z(vol20) - z(pos_in_range)` @11:15, liq | S | 5 | 479 | 19.1 | -1.9 | 57.6 | 3.77 | 22.5 | 15.7 |
| 7 | `-slot_ret_0` @11:15, low vol regime, liq | S | 10 | 241 | 18.7 | -2.3 | 63.5 | 3.67 | 19.6 | 17.9 |
| 8 | `-today_sofar/vol20` @11:15, market gapped down | L | 10 | 128 | 17.9 | -3.1 | 57.0 | 2.47 | 17.8 | 18.0 |
| 9 | `z(vol20) - z(pir)` @12:15, liq | S | 5 | 479 | 17.7 | -3.3 | 61.4 | 3.88 | 18.6 | 16.7 |
| 10 | `z(vol20) - z(pir)` @11:15, liq | S | 10 | 479 | 17.1 | -3.9 | 59.9 | 3.93 | 20.4 | 13.9 |
| 11 | `-slot_ret_0` @11:15, market gapped up, liq | S | 10 | 352 | 16.7 | -4.3 | 58.2 | 3.58 | 19.0 | 14.4 |
| 12 | `-slot_ret_0` @11:15, liq>=Rs100cr | S | 5 | 480 | 16.6 | -4.4 | 56.7 | 3.47 | 15.8 | 17.4 |
| 13 | `today_sofar/vol20` @11:15, market-up days | L | 10 | 244 | 16.2 | -4.8 | 54.9 | 2.68 | 21.7 | 10.6 |
| 14 | `d5` @11:15, liq (5-day reversal, not intraday) | S | 5 | 480 | 13.8 | -7.2 | 55.8 | 2.65 | 11.5 | 16.0 |
| 15 | `-slot_ret_0` @11:15, liq (unconditional) | S | 5 | 480 | 12.8 | -8.2 | 56.2 | 2.40 | 11.3 | 14.3 |

Rows 1-3 are the same signal at three settings and are dealt with below. Every
other config in the study is negative after costs. Of the 2,964 scripted
configs, **1** was net-positive. In the flat slot x topn x side x liquidity
sweep of the leading candidates - **1,056 configs** - **zero** were
net-positive, and the best gross in it was 19.1 bp against a 21 bp hurdle.

## The one candidate, and why it does not survive

**Signal:** at 11:15, on days when the cross-sectional dispersion of morning
returns is below its expanding median, short the 5 biggest first-hour losers in
the Rs 10cr+ universe; cover at the 15:15 close.

What held up under attack:

- **Threshold-stable.** Gross 24-30 bp for every dispersion cut from q30 to q70.
- **Not outlier-driven.** Median day +33.6 bp, 10%-trimmed mean +34.0 bp - both
  *above* the mean of +28.9. Dropping the 5 best days still leaves +23.3 gross /
  +2.3 net.
- **Both halves agree.** H1 +28.1, H2 +29.6.
- **Survives liquidity.** +27.0 bp in the Rs 100cr+ tier (136 names).
- **Not name-concentrated.** 292 distinct symbols over 1,100 picks; the top 10
  names are 13% of picks. Median pick liquidity Rs 68cr/day, median price Rs 846.
- **The conditioning is genuine.** The high-dispersion half returns -1.0 bp. The
  whole effect is on calm days.

What kills it:

- **The t-stat that matters is 1.05.** Daily standard deviation is 111 bp
  against a net mean of 7.9 bp. The gross t of 3.84 is beside the point - the
  cost is certain, the mean is not. With ~3,000 configs searched, a
  Bonferroni-style family-wise hurdle sits near t ~ 4.3.
- **Basket-size cliff.** Net bp: top3 +9.9, top5 +7.9, top7 +4.6, top10 +1.1,
  top20 -4.0. The whole result rests on 5 names x 220 days.
- **The regime cut has to be same-day.** Swapping in the previous day's
  dispersion - identical in spirit, strictly knowable - takes it to exactly
  **0.0 net bp** at 11:15 and negative at 10:15 (-4.5), 12:15 (-4.0) and
  13:15 (-9.3). A result that needs the current day's dispersion, chosen from
  12 regimes tried, is a fitted cut.
- **Recent decay.** Net bp by quarter: 2025Q1 +19, Q2 +13, Q3 +24, Q4 +1,
  2026Q1 +19, Q2 -29, Q3 -0.5. The last three quarters average roughly zero.
- **It is a short.** Intraday shorts are placeable in India under MIS, but
  several repeat picks are recent-listing high-beta names (OLAELEC, SWIGGY,
  CARTRADE, QPOWER) where intraday shorting can be restricted or margin-heavy,
  and the book runs 30% more volatile than the universe (vol20 2.58% vs 1.96%).

Net of all that: +8 bp/day, on half the days, in a 5-name short book, needing a
same-day regime cut, faded over the last year. That is what the best of ~3,000
draws looks like when the true edge is zero.

## A look-ahead trap worth recording

The first pass of the day-regime batch used full-sample quantiles for the market
cuts (`mkt > mkt.quantile(.75)`). That produced *momentum on big market-up days*
at **+7.8 net bp, t 3.26, 120 days** - the only long-side winner in the whole
study. Replacing the threshold with an expanding quantile of strictly prior days
killed it outright. A threshold on a *day-level* variable is as much a
look-ahead as a price peek, and far easier to type by accident.

## What was tested

| Batch | Area | Configs |
|---|---|---|
| 1-2 | single features at 10:15 and 11:15, both sides | 96 |
| 3 | bar structure at 12:15 / 13:15: first bar vs cumulative, acceleration, last-minus-first, streaks, up-bar counts, time-weighted bars | 56 |
| 4 | `pos_in_range`, distance to high/low, range, volume ratio and their crosses, all 4 entries | 72 |
| 5 | conditional screens: momentum/reversal only in high-volume, wide/narrow-range, big/small-gap, trending, near-52w, high/low-vol subsets (18 conditions x 2 signs x 3 entries) | 104 |
| 6 | z-score blends, 2-way and 3-way, all sign combinations, 3 entries | 1,000 |
| 7 | invented features: VWAP distance, market-relative and beta-residual intraday move, opening-range breakout, outlier reversal, gap-then-go vs gap-then-fade, stretch-from-VWAP, sign streaks | 132 |
| 8 | full sweep of the leaders: 4 entries x 4 basket sizes x 2 sides x 3 liquidity tiers | 1,056 |
| 9-10 | decomposition, winner/loser asymmetry, volatility and liquidity controls, basket turnover | 220 |
| 11 | day-level regimes: market direction and size, dispersion, gap direction, vol regime, day of week | 240 |
| 12 | autopsy of the survivor | ad hoc |

Entry slots 10:15 / 11:15 / 12:15 / 13:15 (never 09:15). Basket sizes 5/10/20/30.
Both sides. Liquidity floors Rs 1cr (326 names, cost 38 bp), Rs 10cr (311),
Rs 100cr (136) and Rs 300cr (32), the last three at 21 bp.

## Negative results worth not repeating

- **Long intraday momentum is dead at every horizon and every normalisation.**
  `today_sofar`, `/vol20`, `/atr`, `/range`, cross-sectional rank, gap-excluded,
  market-relative, beta-residual - all between +0.3 and +6 bp gross at 10:15 and
  weaker later. Best long-side config found anywhere: +5.7 bp.
- **`pos_in_range` carries no information on its own.** -0.1 bp long, +0.1 bp
  short at 10:15, and it flips between halves at every entry. Buying strength
  and buying weakness are equally worthless.
- **Acceleration is a weak reversal, not a momentum signal.** A stock whose
  second bar beat its first *under*performs (short side +8.8 bp at 11:15;
  last-minus-first short +7.1 bp at 13:15) - and it flips between halves at
  13:15.
- **Volume adds nothing to direction.** `vol_ratio` short is +2.4 to +7.5 bp,
  but that is a volatility tilt, not a momentum conditioner: volume-ratio times
  momentum, and volume-ratio times reversal, are both inside the noise.
- **The best-looking blend is not an intraday signal at all.**
  `z(vol20) - z(pos_in_range)`, top of the 1,056-config sweep at 19.1 bp gross,
  decomposes to `vol20` alone at 11.5 bp - a static tilt with **13% daily basket
  turnover**. Its intraday half (`today_sofar/vol20`) contributes **+2.1 bp**.
  You would be paying a 21 bp daily round trip to re-establish a book that is
  87% unchanged.
- **`d5` short (5-day reversal) beats every intraday feature** at +9.7 to
  +13.8 bp gross. It is not in this family, it still fails the intraday cost
  hurdle, and it belongs to daily-horizon research where it would not pay daily
  costs.

## What would change the answer

- **Minute bars.** This whole family is squeezed onto a 4-observation-per-day
  grid. First-15-minute reversal, VWAP reversion and opening-range breakout -
  where the literature actually puts intraday continuation - are invisible at 1h
  resolution.
- **A round trip below ~12 bp** would make the loser-continuation short
  marginally viable. That is a broker/execution question, not a signal question.
- **The asymmetry is the durable fact here.** If intraday work continues, start
  from "losers continue, winners do not" and look for a form of it that is not a
  5-name short book - an *exit* rule, or a short-side overlay on positions
  already being traded, where acting on it does not cost a full round trip.

## Reproduce

```
py -m intraday_lab.agent_momentum        # all batches, ~4 min
py -m intraday_lab.agent_momentum 10 12  # the asymmetry result and the autopsy
```
