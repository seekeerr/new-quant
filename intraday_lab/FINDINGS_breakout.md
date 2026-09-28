# Opening range, breakouts and volatility structure - findings

**Date:** 2026-09-24 - **Code:** `intraday_lab/agent_breakout.py` (+ `_battery.py`,
`_attack.py`, `_deciles.py`) - **Data:** 1h bars, 398 NSE names, 490 trading days
(2024-09-25 -> 2026-09-24) - **Outputs:** `results/intraday_lab/brk_*.csv`

Reproduce: `py -m intraday_lab.agent_breakout all`
(phases: `probe | sweep | deciles | thresh | attack | beta`)

---

## Verdict

**Clean negative. 9,198 configurations tested, zero net-positive.**

The best gross number in the entire family is **+13.7 bp/day**, against a cost
floor of **21 bp** in the most liquid tier and **38 bp** mid-tier. This is not
"thin edge eaten by costs at the margin" - the best gross result is below two
thirds of the cheapest possible round trip. The whole classic intraday toolkit -
opening-range breakout, breakdown, range position, range width, range
expansion/compression, failed-breakout fades, volume confirmation, gap
interactions, volatility regime - produces nothing that would survive being
free, let alone at Indian intraday costs.

Best |t-stat| anywhere is 3.75, on a signal worth **+2.0 bp gross**. With
~7,500 distinct configs the multiple-testing hurdle sits above t ~ 3.9 even on a
generous estimate of independence. Nothing clears it.

---

## A measurement problem the harness hides, and how it was fixed

`ctx['hi_sofar']` includes the bar immediately before entry, and hourly bars are
contiguous (`O[E] / C[E-1] - 1` has median 0.00000). So the entry price sits
*inside* `[lo_sofar, hi_sofar]` 98.6% of the time - only **0.53%** of stock-days
have `entry_open > hi_sofar`. Ranking by "distance beyond `hi_sofar`" therefore
collapses into `pos_in_range` and cannot express a breakout at all.

A real ORB freezes the range and tests it **later**. `orb_features()` builds:

```
OR      = high/low of the first k bars (k = 1 -> 09:15-10:15, k = 2 -> to 11:15)
interim = the completed bars between the OR and the entry slot
brk_up  = (entry_open - or_hi) / or_width     > 0  -> genuinely broken out
poke_up = (interim_high - or_hi) / or_width   > 0  -> traded above the OR
fail_up = poked above, then came back inside       -> the failed-breakout fade
```

Event rates are healthy: 11-18% of stock-days are broken out at entry, 23-37%
poked outside at some point, so a top-10 basket is always real breakouts, never
padding.

**Data caveat found and worked around:** the 09:15 hourly bar carries
`volume == 0` on **74.9%** of rows in this yfinance feed. Harness `vol_ratio` is
consequently 93.9% NaN at a 10:15 entry. All volume features here are rebuilt
from 10:15 onward, so volume tests only run at entry 11:15 and later.

---

## What was tested

| Dimension | Values |
|---|---|
| Signals | 139 distinct scores per (entry, OR length) |
| Entry slot | 10:15, 11:15, 12:15, 13:15 (+ 14:15 in the attack phase). Never 09:15 |
| Opening range | k = 1 bar and k = 2 bars |
| Basket size | 5, 10, 20, 30 |
| Side | long and short for every score |
| Liquidity / cost | >=Rs1cr @ 38 bp - >=Rs10cr @ 21 bp - top-100 and top-50 by turnover @ 21 bp |

Signal groups: raw ORB extension (in OR widths and in ATR sigmas) - breakdown -
breakout-confirmed subsets - position-in-range and position-in-OR - OR width in
sigmas and vs the name's own 20-day OR width - range expansion/compression -
realised-vol and ATR regime - failed breakout / giveback / poke-and-fade -
held breakouts - relative volume and volume-confirmed breakouts at 1.25x/1.5x/2x
- breakout x gap-up / gap-down / no-gap - breakout x high-vol / low-vol -
breakout x wide-OR / narrow-OR / coiled - z-score blends with 20-day momentum,
52-week position and OR width - breakout-size thresholds at 0-1.5 ATR sigmas -
quintile bands of OR width, rvol, vol20 and relative OR width.

**Totals:** probe 695 - full grid 6,662 - thresholds & bands 1,528 - attack 313
= **9,198 evaluations**, 7,558 of them distinct. (The grid contains exact
duplicates where a signal does not depend on the OR length; those are counted
once in the distinct figure.)

---

## Top 15 configs, ranked by net bp

Cost is matched to the liquidity floor: tier **A** = >=Rs1cr @ 38 bp, tier **B** =
>=Rs10cr @ 21 bp. Every row is a loss.

| # | config | side | N | days | gross bp | **net bp** | hit% | t | H1 | H2 | consistent |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `vol20_hi_sh` E11 N10 B | S | 10 | 479 | 13.0 | **-8.0** | 56.8 | 2.71 | 13.0 | 13.0 | yes |
| 2 | `orb wideOR-Q5` E12 N20 B | L | 20 | 326 | 12.4 | **-8.6** | 61.0 | 3.48 | 12.9 | 11.9 | yes |
| 3 | `vol20_hi_sh` E12 N10 B | S | 10 | 479 | 12.2 | **-8.8** | 57.2 | 3.14 | 12.1 | 12.3 | yes |
| 4 | `atr_hi_sh` E11 N20 B | S | 20 | 480 | 12.1 | **-8.9** | 53.3 | 2.87 | 15.3 | 8.9 | yes |
| 5 | `vol20_hi_sh` E11 N20 B | S | 20 | 479 | 12.0 | **-9.1** | 55.5 | 2.91 | 13.8 | 10.1 | yes |
| 6 | `orbdn_hivol_sh` E12 k2 N30 B | S | 30 | 234 | 11.8 | **-9.2** | 58.1 | 2.47 | 18.3 | 5.3 | yes |
| 7 | `brkSig>=1.0 fade` E13 N5 B | S | 5 | 122 | 11.7 | **-9.3** | 59.0 | 1.67 | 14.8 | 8.5 | yes |
| 8 | `brkSig>=0.75 fade` E12 N10 B | S | 10 | 192 | 11.7 | **-9.3** | 54.2 | 1.58 | 9.7 | 13.7 | yes |
| 9 | `brkSig>=0.75 fade` E12 N5 B | S | 5 | 192 | 11.6 | **-9.4** | 55.7 | 1.54 | 9.9 | 13.4 | yes |
| 10 | `vol20_hi_sh` E11 N5 B | S | 5 | 479 | 11.5 | **-9.5** | 56.6 | 2.04 | 12.4 | 10.5 | yes |
| 11 | `atr_hi_sh` E11 N5 B | S | 5 | 480 | 11.5 | **-9.6** | 56.0 | 1.97 | 6.6 | 16.4 | yes |
| 12 | `atr_hi_sh` E12 N20 B | S | 20 | 480 | 11.4 | **-9.6** | 56.2 | 3.24 | 13.5 | 9.2 | yes |
| 13 | `brkSig>=1.0 fade` E13 N10 B | S | 10 | 122 | 11.3 | **-9.7** | 58.2 | 1.69 | 14.9 | 7.6 | yes |
| 14 | `orb_wideOR` E12 N20 B | L | 20 | 383 | 11.1 | **-9.9** | 60.8 | 3.66 | 8.2 | 14.0 | yes |
| 15 | `orb_hivol` E13 k2 N30 B | L | 30 | 245 | 10.8 | **-10.2** | 58.8 | 3.15 | 11.2 | 10.5 | yes |

Note what the leaderboard is made of. Ranks 1, 3, 4, 5, 10, 11 and 12 are
`vol20_hi_sh` / `atr_hi_sh` - **short the highest-volatility names** - which is
not a breakout signal at all; it is the volatility-regime control that happened
to be in the battery. The genuinely breakout-shaped entries (2, 14, 15) all
require a *wide* or *high-vol* opening range, i.e. they are the same volatility
effect wearing a breakout costume.

---

## Best gross result per signal group

Nothing reaches the 21 bp floor. Sorted by best gross, over the 6,662-config grid.

| group | configs | best gross bp | best net bp | best t |
|---|---|---|---|---|
| ORB up, conditioned | 1742 | 13.7 | -9.9 | 3.66 |
| volatility regime (vol20 / ATR) | 392 | 13.0 | -8.0 | 3.75 |
| ORB breakdown | 616 | 11.8 | -9.2 | 2.69 |
| relative volume | 192 | 11.8 | -10.6 | 2.80 |
| ORB confirmed-breakout only | 352 | 10.9 | -10.1 | 2.08 |
| OR width (wide / narrow / coiled) | 448 | 10.2 | -12.4 | 2.79 |
| gap | 224 | 9.6 | -14.7 | 1.65 |
| **volume-confirmed breakout** | 240 | **8.2** | -12.8 | 2.50 |
| range expansion | 224 | 8.0 | -14.8 | 1.99 |
| position in opening range | 224 | 6.4 | -15.9 | 2.15 |
| position in range-so-far | 448 | 6.4 | -15.6 | 2.37 |
| poke / extension | 240 | 6.1 | -15.7 | 1.67 |
| held breakout | 160 | 5.4 | -15.8 | 1.65 |
| **failed breakout / fade** | 320 | **4.9** | -16.1 | 1.67 |
| OR direction | 112 | 4.1 | -17.1 | 1.05 |
| intraday momentum so far | 168 | 3.7 | -17.4 | 0.89 |
| OR close position | 168 | 3.3 | -18.0 | 1.48 |

Two of the family's headline claims die here specifically. **Volume
confirmation does not help**: requiring `rvol >= 1.25/1.5/2.0` on top of a
breakout caps out at +8.2 bp gross, *worse* than the unconditional breakout
group. **The failed-breakout fade is the weakest group in the study** at
+4.9 bp best gross across 320 configs.

---

## The decile picture - where the "no signal" really shows

Top-N baskets can hide a signal's shape. Deciles cannot. Mean gross
open->close bp per cross-sectional decile, entry 11:15, >=Rs1cr universe:

| feature | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | D9 | D10 | D10-D1 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `brk_up` (ORB extension) | 1.5 | -2.9 | -2.6 | -4.9 | -4.8 | -4.2 | -3.4 | 0.7 | -0.8 | -0.0 | **-1.5** |
| `brk_up_sig` (ORB in ATR) | -1.9 | -0.5 | -2.4 | -3.3 | -4.7 | -4.0 | -2.4 | -1.6 | -1.1 | 0.3 | **+2.2** |
| `pos_in_range` | 0.1 | -4.1 | -2.1 | -3.3 | -4.3 | -4.6 | -2.9 | -0.8 | -0.3 | 0.6 | **+0.5** |
| `or_w_sig` (OR width) | -4.0 | -3.4 | -1.6 | -2.5 | -3.3 | -0.7 | -3.8 | -0.3 | -0.2 | -1.9 | **+2.1** |
| `range_sofar / atr` | -3.5 | -4.9 | -3.3 | -3.6 | -2.1 | -2.0 | -2.0 | -0.0 | 0.1 | -0.2 | **+3.3** |
| `rvol` | -4.1 | -3.8 | -4.0 | -2.7 | -2.4 | -2.3 | -0.9 | -2.4 | 1.5 | -0.5 | **+3.6** |
| `giveback_up` (failed-breakout size) | -2.6 | -3.5 | -1.9 | -3.5 | -0.1 | -3.5 | -2.9 | -1.9 | -2.6 | 0.8 | **+3.4** |
| `vol20` | -0.3 | 0.0 | -1.2 | -0.3 | -2.1 | 0.1 | -2.8 | -1.5 | -3.6 | **-9.4** | **-9.1** |
| `atr_true` | 0.6 | 0.1 | 0.2 | -2.0 | -0.9 | -1.7 | -2.5 | -2.6 | -3.1 | **-9.5** | **-10.1** |

Everything breakout-shaped is a flat line inside +/-4 bp with no monotone ramp -
that is what an absent signal looks like. The only real structure in the table
is volatility, and it is not a ramp either: it is a single bad decile. Only the
top 10% by realised vol / ATR underperforms, by ~9 bp; deciles 1-9 are
indistinguishable. Same shape at 12:15 (-8.6 bp) and 13:15 (-6.3 bp), so it is
not a one-slot fluke - but 9 bp is less than half the cheapest round trip.

## Does a BIGGER breakout work? No.

Requiring the breakout to exceed a threshold in ATR sigmas (entry 11:15, N=10,
>=Rs10cr tier), long side:

| threshold | days | gross bp | net bp (21) | t |
|---|---|---|---|---|
| >= 0.0 sigma | 478 | +1.9 | -19.1 | 0.54 |
| >= 0.1 sigma | 458 | +2.4 | -18.6 | 0.62 |
| >= 0.2 sigma | 435 | +5.9 | -15.2 | 1.34 |
| >= 0.3 sigma | 375 | +2.2 | -18.9 | 0.48 |
| >= 0.5 sigma | 214 | **-6.5** | -27.5 | -0.84 |

Non-monotone, peaks at a t-stat of 1.34, then turns negative exactly where the
"real" breakouts live. The mirror image - *fading* breakouts above 0.75 sigma -
reaches +11.7 bp gross on 122-192 days at t ~ 1.6, which is the same noise read
backwards and is not offered as a finding.

---

## Attacking the survivors

Every signal that got above +10 bp gross was put through entry-slot decay,
liquidity tiers, and quarter-by-quarter stability.

**`vol20_hi_sh` (short the 10 highest-vol names), gross bp:**

| entry | >=Rs1cr | top-100 | top-50 | net(>=Rs10cr, 21bp) | quarters (net, 38 bp) |
|---|---|---|---|---|---|
| 10:15 | 5.8 | 4.4 | 2.7 | -13.6 | -32, -37, -14, -46 |
| 11:15 | 11.7 | 7.2 | 4.9 | -8.0 | -21, -29, -21, -34 |
| 12:15 | 11.8 | 7.8 | 4.2 | -8.8 | -24, -25, -18, -37 |
| 13:15 | 9.9 | 6.6 | 3.7 | -10.8 | -23, -24, -24, -42 |
| 14:15 | 5.5 | 1.4 | 1.1 | -16.1 | -31, -29, -26, -44 |

**The edge falls monotonically as executability rises** - 11.7 -> 7.2 -> 4.9 bp
as the universe narrows to the top 100 then top 50 by turnover. That is the
exact signature `FINDINGS.md` identified for the gap-fade: a microstructure
artifact, not alpha. `atr_hi_sh` behaves identically (10.5 -> 9.3 -> 5.3).
`orb_wideOR` and `orb_gapup` degrade the same way (at 13:15, 4.9 -> 0.9 in the
top 100). **All 40 quarters across all attacked signals are net-negative.**

**It is not simply a short-beta bet.** Against the equal-weight universe return
(which drifts -2.2 bp from 11:15 to the close), `vol20_hi_sh` has beta -1.29 and
a market-neutral residual of **+10.3 bp** - so ~79% of it is genuine
cross-sectional residual. It is real, and still far too small to trade.

---

## The cost model probably UNDERSTATES cost for this family

This is the family-specific warning, quantified rather than asserted.

A breakout basket by construction buys names that have just moved hard on heavy
volume - precisely where the spread is widest and the book thinnest. Median
pick vs median eligible stock, entry 11:15, N=10:

| | `orb_wideOR` | `orb_gapup` | `orb_up` | universe |
|---|---|---|---|---|
| relative volume (`rvol`) | **3.13x** | **2.44x** | **2.15x** | 0.98x |
| absolute move so far | 2.70% | 1.72% | 1.65% | 0.80% |
| range so far | 3.62% | 2.87% | 2.55% | 1.88% |
| **previous bar's range** | **162 bp** | **165 bp** | **167 bp** | **87 bp** |

The picks' previous bar spans **~1.9x the universe's** range. Using that as the
yardstick for how fast the tape is moving at the moment of entry:

| adverse fill | cost to `orb_wideOR` | its entire gross edge |
|---|---|---|
| 10% of one bar's range | **16.2 bp** | 4.9-11.1 bp |
| 25% of one bar's range | **40.5 bp** | 4.9-11.1 bp |

**Being filled one tenth of a single bar's range away from the print costs more
than the whole gross edge.** The harness's flat 21/38 bp is a market-average
assumption; for this family the true number is higher, so the negative results
above are, if anything, optimistic.

(One partial exception: `fail_up_sh` picks are *calm* names - previous-bar range
122 bp, rvol 1.35 - because a failed breakout has by definition stopped moving.
It is also the weakest group in the study, at +4.9 bp best gross.)

---

## What would have counted as a result, and why nothing did

A result needed `net_bp > 0`, `consistent = True`, and a non-trivial t-stat.
Several configs are consistent with respectable t-stats - `orb_wideOR|E12|N20`
is +8.2 / +14.0 bp across halves at t = 3.66 - and every one of them is still
~10 bp per day short of paying for itself. The binding constraint is not
stability and not sample size. It is that the largest cross-sectional
open-to-close spread this family can generate is ~13 bp while the cheapest
round trip is 21 bp.

## Honest caveats

- **~490 days is thin**, and 9,198 configs on it guarantee the top of the
  leaderboard is luck. That cuts the same way as the verdict, so it rescues
  nothing: the luckiest of 9,198 tries is still a loss.
- **Hourly bars are coarse for this family.** A real ORB trader uses 5-minute
  bars, a stop under the range, and does not hold to the close. This study can
  only test "rank at slot E, hold to 15:15". A minute-bar archive could change
  the answer, and per `FINDINGS.md` that requires forward collection.
- **Survivorship**: yfinance serves only currently-listed symbols, so this
  universe is biased *toward* winners, which would flatter long breakouts if
  anything. It didn't.
- The **exit is fixed at the 15:15 close**. Intraday stops and profit targets -
  the other half of the classic toolkit - are untestable on hourly bars.
- The liquidity floors barely bite on this universe (it is already the top ~400
  by turnover: >=Rs10cr/day removes only ~5% of names). The meaningful
  liquidity attack is therefore the top-100 / top-50 turnover cut, which is what
  the attack table uses.

## One thing worth keeping

Not a strategy, but a fact for whoever studies this data next: **the top decile
of realised volatility loses ~6-9 bp intraday from mid-morning to the close, at
every entry slot, in both halves of the sample, with a market-neutral residual
of ~10 bp.** It is too small to trade and it shrinks as the universe gets more
liquid. But it is the only stable cross-sectional structure this family found -
and it is a *volatility* effect, not a breakout one. Every "breakout" config on
the leaderboard turned out to be this effect in disguise.
