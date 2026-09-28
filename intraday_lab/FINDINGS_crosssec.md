# Cross-sectional daily signals, held for one intraday session — findings

**Family:** multi-day / cross-sectional signals (momentum, reversal, volatility,
liquidity, 52w-high, price level) evaluated over a **single session**: rank at
entry slot E, buy or short the top N at E's open, flatten at the 15:15 close.

**Code:** `intraday_lab/agent_crosssec.py` (`py -m intraday_lab.agent_crosssec all`)
**Data:** 1h bars, 398 NSE symbols, 490 trading days (2024-09-25 to 2026-09-24).
**Configs tested:** **1,621** attempted, 1,364 evaluated (the rest rejected by the
harness 120-day minimum). Full grid in `results/intraday_lab/crosssec_all.csv`.

---

## Verdict

**Negative. Nothing in this family is tradeable.**

**Configs with `net_bp > 0` and `consistent=True`: 0 of 1,364.**

The negative is more informative than "no signal exists", so read these two
lines rather than just the headline:

1. **Real intraday cross-sectional alpha does exist** and is measurable with
   confidence — shorting high-volatility / lottery names earns ~13-20 bp/day
   gross, t up to 3.8, both halves agreeing. This is **not** a search artifact:
   a 400-draw noise calibration puts the best random result at 5.3 bp.
2. **It is 2-3x too small to pay for itself.** The cheapest realistic round trip
   is 21 bp. The best gross edge found anywhere in 1,621 configs is 20.0 bp.
   The closest config in the entire search **loses by one basis point.**

The repo monthly edge does not survive being chopped into daily slices. The
prior expectation was correct.

---

## Top 15 configs (sorted by net bp — every one is negative)

At the 1e8 (>=Rs 10cr/day) floor with the matching 21 bp cost, unless the cost
column says 38.

| # | strategy | slot | side | N | days | gross | cost | **net** | t | hit% | H1 | H2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | maxret20 (MAX / lottery) | 11:15 | **S** | 5 | 479 | 20.0 | 21 | **-1.0** | 3.82 | 58.2 | 18.3 | 21.8 |
| 2 | maxret20 | 10:15 | **S** | 5 | 479 | 18.4 | 21 | **-2.5** | 3.02 | 58.0 | 13.0 | 23.9 |
| 3 | maxret20 | 11:15 | **S** | 10 | 479 | 15.9 | 21 | -5.1 | 3.74 | 58.5 | 15.4 | 16.5 |
| 4 | d10 (10-day momentum) | 11:15 | **S** | 5 | 479 | 15.2 | 21 | -5.8 | 2.61 | 56.6 | 10.9 | 19.4 |
| 5 | maxret20 | 13:15 | **S** | 5 | 479 | 14.2 | 21 | -6.8 | 3.78 | 58.0 | 17.2 | 11.1 |
| 6 | d5 (short weekly winners) | 11:15 | **S** | 5 | 480 | 13.8 | 21 | -7.2 | 2.65 | 55.8 | 11.5 | 16.0 |
| 7 | maxret20 | 10:15 | **S** | 10 | 479 | 13.1 | 21 | -7.9 | 2.54 | 56.2 | 7.6 | 18.6 |
| 8 | vol20 (short high-vol) | 11:15 | **S** | 10 | 479 | 13.0 | 21 | -8.0 | 2.71 | 56.8 | 13.0 | 13.0 |
| 9 | pct52_lo | 10:15 | **S** | 5 | 430 | 12.7 | 21 | -8.3 | 1.89 | 52.8 | 18.2 | 7.1 |
| 10 | atr (short high-ATR) | 11:15 | **S** | 10 | 479 | 12.5 | 21 | -8.5 | 2.74 | 54.8 | 12.3 | 12.7 |
| 11 | d120 (short 6m winners) | 10:15 | **S** | 5 | 369 | 12.1 | 21 | -8.9 | 1.67 | 51.2 | 14.9 | 9.2 |
| 12 | skew20 | 10:15 | **S** | 5 | 479 | 11.2 | 21 | -9.8 | 2.54 | 59.1 | 11.1 | 11.4 |
| 13 | -d2, only when gap < -1.5% | 10:15 | L | 5 | 306 | 18.5 | 38 | -19.5 | 2.23 | 53.6 | 32.7 | 4.1 |
| 14 | -d5, only when gap < -1.5% | 10:15 | L | 5 | 306 | 15.3 | 38 | -22.7 | 1.91 | 52.9 | 24.6 | 5.9 |
| 15 | rev1+gapdn+lowvol blend | 10:15 | L | 5 | 479 | 10.2 | 38 | -27.8 | 2.17 | 53.0 | 17.7 | 2.7 |

Two structural facts fall out of this table:

- **Everything that works is a SHORT.** The long side is empty. The average
  eligible stock returns -0.6 bp from the 10:15 open to the close, so a long
  book starts behind and no daily signal makes up the difference.
- **Everything that works is on the volatility axis** — not momentum, not
  liquidity. See the decile test below.

---

## The brief, answered point by point

**Short-term reversal (-d1, -d2, -d5) — do yesterday losers bounce?**
No. `-d1` long top-10 = **+2.5 bp gross** (t=0.52, sign flips between halves).
Decile spread D10-D1 = +6.1 bp, roughly monotone but an order of magnitude
short of costs. The only reversal variant with real size (`-d2` among big
gap-downs, +18.5 bp) is a residue of the already-dead gap-fade and decays
H1 32.7 to H2 4.1.

**Daily momentum (d5 / d10 / d20 / d120) — does a trending stock drift up
intraday?** No, and if anything the reverse. `mom120` decile spread is
**+0.5 bp, i.e. exactly zero**, and the only momentum configs that make gross
money are on the **short** side (short 10-day and 6-month winners, 12-15 bp).
Intraday, recent winners give a little back.

**Low-vol / high-vol tilts.** This is the whole finding. **Short high-vol** pays:
`vol20` short 11.5-13.0 bp (t=2.7), `atr` short 12.5 bp, `maxret20` short 20.0 bp.
The long-low-vol mirror is much weaker (`lowvol` decile spread +7.6 bp).
Direction is stable across all three entry slots and both halves.

**52-week-high proximity (pct52), both directions.** Dead — decile spread
**-1.3 bp**. The `pct52_lo` short at #9 is a volatility proxy, not a 52w effect.

**Illiquidity tilt.** **Exactly zero.** Amihud decile spread = **-0.2 bp**. The
illiquidity premium the daily book harvests over months contributes literally
nothing over a session — and the tilt pushes toward names where the cost
assumption is most optimistic, so the true figure is worse than zero.

**Price level, cheap vs expensive.** Nothing. `-price` long never exceeds 5 bp
gross and flips between halves.

**Interaction with the session** (reversal only on gap-downs, momentum only on
gap-ups, conditioning on `vol_ratio`, `pos_in_range`, `range_sofar`): 264 configs.
Best is +18.5 bp gross against a 38 bp wall, and it is the gap-fade residue
again. Conditioning buys size at the cost of sample and decay; nothing survives.

**Blends** (182 two-way + 30 three-way z-score blends): blending makes things
worse — it averages one weak real signal against dead ones. Notably, **the repo
own daily champion shape (mom120 + lowvol + illiq) returns +1.5 bp gross,
t=0.31, and flips sign between halves.** That is the cleanest single statement
of this study: the monthly winner is worth nothing intraday.

**Day-of-week / time-of-month.** Weekdays are noise — no signal shows a
consistent weekday and the pattern differs per signal, the signature of
overfitting a ~96-day cell. **Turn-of-month is real but not cross-sectional**,
see below.

---

## The two things that looked like winners, and why neither is

### 1. Turn-of-month — the only positive net bp in the search

`-d1` long top-10 at 10:15, first 2 sessions of each month: **+40.2 bp gross,
net +2.2, t=2.92, n=46, both halves agree (31.1 / 50.1)**. At the liquid tier
with top-5 it looks better still: net **+19.8**, t=2.27. It is robust to the
window (bom1 39.2, bom2 40.2, bom3 33.8, bom5 18.4 — a smooth decay, not a
knife-edge), to the entry slot, and to outliers (17/23 month-starts positive,
median 33 bp; dropping the best 3 months still leaves 28 bp).

**One test kills it.** A **random** top-10 basket on those same 46 days earns
**+20.8 bp**, because the whole market drifts up at the turn of the month. And
the **maximum over 400 random signals on that subset is +44.7 bp — higher than
the +40.2 the best real signal achieved.**

So the cross-sectional part of the edge is not distinguishable from picking 10
names at random. What remains is a market-wide drift of ~21 bp on 23 days a
year, itself below the cost of trading it (equal-weight, liquid tier: net
**-0.2 bp**). The placebo test agrees it is marginal: sliding the month boundary
by k trading days, k=0 ranks 1 of 19 windows — p ~ 0.05 for a single
pre-specified test, meaningless as the best of a 1,600-config search.

Even at face value the prize was 0.51%/year on deployed capital, with capital
idle the other ~226 sessions, and a 5 bp cost-model error erasing all of it.

### 2. The MAX / lottery short — the closest miss, -1 bp

Short the 5 names with the largest single-day return of the last 20 sessions,
enter 11:15, 1e8 floor: **gross 20.0 bp, t=3.82, hit 58.2%, H1 18.3 / H2 21.8**,
monotone in every direction tested (topn 5/10/20, slots 10:15/11:15/13:15). A
genuine, well-measured effect — the MAX anomaly showing up intraday.

**Three things sink it:**

- **Breakeven cost is 20.0 bp** against a 21 bp liquid round trip. It loses
  before anything goes wrong. At 18 bp it makes 3.5%/yr; at 25 bp it loses
  13%/yr. A strategy whose sign depends on the third significant figure of a
  cost model is not a strategy.
- **It is ~70% just a short-volatility trade.** Ranking MAX *within* `vol20`
  quintiles collapses it from 20.0 bp (t=3.82) to **5.9 bp (t=1.68)**. `vol20`
  alone gets 11.5-13.0 bp. Little lottery-specific alpha is left over.
- **The one full calendar year in sample is negative.** Gross by year: 2024
  (54d) 37.5, 2025 (247d) **15.1**, 2026 (178d) 21.6. Net of 21 bp:
  +16.5 / **-5.9** / +0.6.

It is also a **short** book: MIS margin, shortability constraints, and an
upper-circuit lock on a lottery stock is an unhedgeable gap against you. Real
cost is above 21 bp, not below.

---

## Why this family cannot work here — the arithmetic

- Per-day cross-sectional std of a top-10 basket: **63 bp**. Over 480 days the
  standard error of a mean is **2.9 bp**.
- To clear the 38 bp mid-cap wall with t=2 you need a gross edge of **~44 bp/day**;
  to clear the 21 bp liquid wall, ~27 bp/day.
- The largest gross edge found in 1,621 configs is **20.0 bp**.
- The monthly book earns ~1.5%/month, about **7 bp/day of drift**. Harvesting one
  day of it costs 21-38 bp. The trade is structurally upside-down: you pay a
  month of alpha to collect a day of it.

**Noise calibration** (400 random score matrices), which keeps the above honest:

| sample | topn | mean | sd | 95th | max |
|---|---|---|---|---|---|
| full 480d | 5 | -0.5 | 2.8 | 4.1 | 7.5 |
| full 480d | 10 | -0.6 | 2.0 | 2.8 | 5.3 |
| full 480d | 20 | -0.6 | 1.4 | 1.7 | 3.1 |
| bom2 46d | 5 | 20.1 | 9.3 | 34.8 | 51.1 |
| bom2 46d | 10 | 20.8 | 6.9 | 32.5 | 44.7 |

This cuts both ways and both directions matter. On the **full** sample the band
is tight, so the 13-20 bp signals above are real rather than mined. On the
**46-day** subset the band is 3x wider and centred on +21 — precisely where the
only net-positive result lived, and why it died.

---

## Consistency with the rest of the lab

An independent confirmation of `FINDINGS.md` from a different direction. That
study killed the gap-fade by showing the edge vanishes as executability rises.
This one shows the *daily-horizon factor* edge — the thing the repo actually
earns from over months — is between 0 and 20 bp per session against a 21-38 bp
toll. Different signal family, same wall.

The 09:15 gap-fade was not retested; it is settled and dead. 09:15 was never
used as an entry slot anywhere in this study.

---

## What would change the answer

Only the cost side, not the signal side. A 20 bp gross edge at t=3.8 is real; it
needs the round trip to fall to ~15 bp to be worth trading. That is an
execution / brokerage question (direct market access, lower realised impact than
the modelled slippage, larger and more patient orders), not a research one.
Searching more signals in this family is not the move — the ceiling has been
measured, and it is 20 bp.

## Reproduce

```
py -m intraday_lab.agent_crosssec all      # full campaign, ~6 min
py -m intraday_lab.agent_crosssec 10       # just the MAX/lottery attack
```
Phases: 1 single features, 2 conditional, 3 blends, 4 survivor sweep,
5 calendar, 6 decile/attack, 7 turn-of-month, 8 turn-of-month placebo,
9 noise calibration, 10 MAX-short attack.
Writes `results/intraday_lab/crosssec_all.csv` only.
