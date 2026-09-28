# Intraday campaign — verdict

**2026-09-24 · 16,587 configurations searched · 0 tradeable strategies**

Data: 1-hour bars, 398 NSE symbols, 490 trading days (Sep 2024 – Sep 2026),
plus 15m and 5m bars, 249 symbols, 59 days (Jul – Sep 2026).
All work isolated in `intraday_lab/`; nothing outside it was touched.

---

## The answer

**No intraday strategy clears costs.** This is not "we didn't find one" — it is a
measured ceiling, hit from four independent directions:

| | best gross edge | cost floor | verdict |
|---|---|---|---|
| Momentum / reversal (3,084 configs) | 22.1 bp | 21 bp | 1 survivor, killed on attack |
| Opening range / breakout (9,198) | 13.7 bp | 21 bp | 0 |
| Cross-sectional daily→intraday (1,621) | 20.0 bp | 21 bp | 0 |
| Microstructure + long-short (846) | 10.6 bp | 21 bp (42 for L/S) | 0 |

**Best gross edge found anywhere: 22.1 bp/day. Cheapest possible round trip: 21 bp.**
The luckiest of 14,667 attempts beats the cost floor by 1.05x — before any
correction for having searched 14,667 times.

### The multiple-testing arithmetic

With N configs, the expected maximum |t| under pure noise is ≈ √(2·ln N).

- N = 14,667 → noise bar **t = 4.38**
- Best t-stat actually found: **4.10**

The single net-positive result sits **below** what you would expect to get from
searching this hard on random data. It is indistinguishable from chance.

---

## The one survivor, and how it died

`-slot_ret_0 @ 11:15, top-5, low-dispersion days, liquid tier` — short the
morning's biggest losers. Gross 28.9 bp, net **+7.9 bp**, t = 3.84, both halves
agreeing (28.1 / 29.6). It passed threshold-stability, was not outlier-driven,
spanned 292 distinct names, and survived to a ₹100cr liquidity floor.

Three attacks killed it:

1. **t-stat of the NET return is 1.05.** Daily σ is 111 bp; a +7.9 bp mean is
   noise at that dispersion.
2. **Basket-size cliff:** top-3 +9.9 → top-5 +7.9 → top-10 +1.1 → top-20 −4.0.
   A real effect degrades smoothly; this falls off a shelf.
3. **Using the *previous* day's dispersion instead of the same day's takes it to
   exactly 0.0 net bp.** The filter was reading the present.

Plus quarterly decay: the last three quarters average ~0.

---

## What all four researchers found independently

**1. Edge decays monotonically as execution becomes possible.** Every promising
signal shrank as the liquidity floor rose:

- gap-fade: ₹1cr +107 bp → ₹10cr +61 bp → top-100 +1.1 bp
- short-losers: ₹10cr +11.4 → ₹100cr +9.4 → ₹300cr +4.1
- short-high-vol: 11.7 → 7.2 (top-100) → 4.9 (top-50)

Alpha does not behave this way. Liquidity-provision compensation does. This is
the same signature `FINDINGS.md` recorded for the gap-fade, now found three more
times by three separate searches.

**2. The only stable cross-sectional structure is a short-volatility effect.**
The top decile of realised vol loses 6–20 bp intraday, at every entry slot, in
both halves, with a ~10 bp market-neutral residual after beta. Real, measurable,
and still half the cost floor. Seven of the breakout family's top 12 turned out
to be this effect wearing a breakout costume.

**3. Intraday momentum is asymmetric — only the losing side works.** Buying
today's winners: +0.8 to +5 bp, t < 1. Shorting today's losers: +5 to +12 bp,
t 2–3. The working side is still half a round trip.

**4. Monthly factor alpha does not survive being sliced into days.** The repo's
own daily champion (`mom + lowvol + illiquidity`) returns **+1.5 bp/day, t=0.31,
sign-flipping** when held for one session. The illiquidity leg — the component
that makes the monthly strategy work — has a decile spread of **−0.2 bp**
intraday. Exactly zero.

---

## Why this is structural, not a tuning problem

Top-10 basket daily σ is ~63 bp, so the standard error of a mean over 480 days
is 2.9 bp. To clear a 38 bp cost with t = 2 you need a **~44 bp/day** gross edge;
to clear 21 bp you need ~27.

**The measured ceiling across 14,667 configs is 22.**

Meanwhile the monthly book earns ~1.5%/month ≈ 7 bp/day of drift. Trading daily,
you would pay a month of alpha to collect a day of it.

---

## Two methodology traps caught mid-campaign

Recording these because they would have produced fake winners:

**Day-level look-ahead.** A regime filter written as `mkt > mkt.quantile(.75)`
uses the *whole sample* to set the threshold and produced the only long-side
winner in the momentum study (+7.8 net bp, t 3.26). Switching to an expanding
quantile over strictly prior days killed it outright. The harness's
`bars_before()` guards price look-ahead but cannot catch a threshold on a
day-level variable.

**Subset-specific nulls.** A turn-of-month result (+40.2 gross, net +2.2, t=2.92,
both halves agreeing) looked like the campaign's one win. But on those same 46
days a *random* basket earns +20.8 bp, and the max over 400 random draws is
**+44.7 bp — higher than the real signal.** The cross-sectional part was
indistinguishable from random picking. Any subset-conditioned result needs a
null computed on that subset, not on the full sample.

**Data defect found:** the 09:15 hourly bar has `volume == 0` on **74.9%** of
rows in this feed, which silently made `vol_ratio` 93.9% NaN at a 10:15 entry.
Volume features must be rebuilt from 10:15 onward. *(Update: this is an
aggregation artifact of the 1h feed alone. The 15m panel's opening bar is 0.2%
zero-volume and every later bar is 0.0%, so volume features are safe to build
on the finer panels.)*

---

## What would change the answer

One thing, and it is not "search more signals".

**Lower costs.** The round trip would need to fall to roughly **15 bp**. That is
a brokerage and execution question, not a research one.

~~**Minute bars.**~~ **TESTED AND CLOSED, same day — see `FINDINGS_fine.md`.**

This section originally said finer resolution was the one thing that could
change the answer, and that getting the data was a six-month project. Both
halves of that were wrong. yfinance serves 5m/15m bars on a trailing 60-day
window, available immediately; 249 symbols fetched in minutes.

The result is the opposite of the hope:

| resolution | best gross | cost floor | ratio |
|---|---|---|---|
| 1 hour (14,667 configs) | 22.1 bp | 21 bp | 1.05x |
| 15 min (960 configs) | 13.3 bp | 21 bp | 0.63x |
| 5 min (960 configs) | 5.2 bp | 21 bp | 0.25x |

**Alpha accrues in time; cost accrues in trades.** Holding one signal fixed and
moving only the holding period, the edge builds at ~6 bp per hour of exposure —
and the 5m and 15m panels agree on that rate to a fraction of a basis point at
every shared horizon. One round trip is 21 bp whether you hold five minutes or
five hours. Break-even is therefore ~3.5 hours of a 6.25-hour session, i.e.
hold-all-day, i.e. the open→close shape this campaign already rejected.

Market-neutralised, ~half of that 6 bp/hour is just the July–September drift;
the honest residual is ~3 bp/hour against a 42 bp two-legged round trip, so
break-even becomes **14 hours — more than two full sessions.**

Searching more signals is not worth it, at any resolution. Six independent
searches now converge on the same ceiling, and the two finest ones converge on
the same *number*.

---

## Files

| | |
|---|---|
| `harness.py` | shared fast harness (0.03s/config) |
| `research.py` | daily-bar open→close study |
| `hourly_test.py` | gap-fade entry-slot test |
| `agent_momentum.py` · `FINDINGS_momentum.md` | 3,084 configs |
| `agent_breakout.py` · `FINDINGS_breakout.md` | 9,198 configs |
| `agent_crosssec.py` · `FINDINGS_crosssec.md` | 1,621 configs |
| `sweep_micro.py` | 846 configs, microstructure + long-short |
| `harness_fine.py` · `agent_fine.py` · `FINDINGS_fine.md` | 1,920 configs at 5m/15m |
| `study_horizon.py` | the edge-vs-holding-period curve — why finer loses |
| `study_neutral.py` | the market-drift attack on the short-losers family |
| `results/intraday_lab/*.csv` | every config's numbers |

Nothing here touches `strategy_live/`, the frozen strategy, or the paper-trading
run. Those remain exactly as they were.
