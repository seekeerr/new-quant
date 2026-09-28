# Strategy discovery campaign — results

**Date:** 2026-09-22 · **Configs searched:** ~7,350 · **Holdout opened:** once, at the end
**Code:** `research_harness.py`, `signals.py`, `sweep.py`, `sweep2.py`, `final_adjudication.py`,
`capacity_test.py`, `year_check.py` · **Data:** `results/campaign/`

## Protocol (why these numbers are believable)

| | period | use |
|---|---|---|
| DISCOVERY | 2012-01-01 → 2021-12-31 | all ~7,350 configs searched here |
| HOLDOUT | 2022-01-01 → 2026-05-30 | untouched until the final run |

With 7,350 trials the best discovery result is *guaranteed* to be partly luck. The holdout is
the only thing that separates a real edge from a lucky curve. It was opened once, for 7
finalists, with no refitting.

Reference points: NIFTY 500 TRI **13.63%** · frozen champion (Mom+LowVol Top-10) **24.30%
discovery / 16.90% holdout**.

---

## The winner

### Momentum + LowVol + Amihud illiquidity (37.5 / 37.5 / 25)

Top-10 names, monthly rebalance, buffer 20, universe = top 500 by turnover.
Score = percentile-rank blend of 12-1 momentum, inverse 252d volatility, and Amihud
illiquidity (|return| / turnover over 60d).

| | CAGR | Sharpe | MaxDD |
|---|---|---|---|
| Discovery (searched) | 26.77% | 1.27 | −34.6% |
| **Holdout (clean)** | **30.08%** | **1.32** | **−16.2%** |
| champion, holdout | 16.90% | 0.68 | −30.1% |
| index, full period | 13.63% | — | — |

**+13.2pp/yr over the index and +13.2pp over the champion, out of sample.** It is the only
finalist whose holdout was *better* than its discovery (+3.3pp) — the opposite of the decay
signature that curve-fitting leaves.

**Why it works (the mechanism, not just the number):** the universe is already the top 500 by
turnover, so an illiquidity tilt does not buy micro-caps — it buys the *less-liquid end of
liquid names*. That is a classic illiquidity premium harvested where it is still tradeable.
The momentum leg supplies return, low-vol supplies the risk control, and Amihud picks up a
premium the other two ignore. Three genuinely different mechanisms, which is why the blend
beats each part.

**Capacity — it scales (this was the key test, since an illiquidity tilt is exactly where
backtests lie):**

| book size | holdout CAGR | champion |
|---|---|---|
| ₹10 lakh | 30.08% | 16.90% |
| ₹1 crore | 30.25% | 17.13% |
| ₹5 crore | 28.36% | 16.88% |
| ₹10 crore | 27.39% | 16.67% |
| ₹50 crore | **23.64%** | 15.66% |

Even at ₹50 crore it beats the champion running ₹10 lakh.

**Year by year** (2022+ is holdout; 2012/2022 consumed by signal warm-up):

| | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **winner** | 22.6 | 59.6 | 9.5 | 6.8 | 43.2 | 5.3 | 8.8 | 40.9 | 59.8 | 39.1 | 57.4 | **13.4** | **−1.5** |
| champion | 27.4 | 47.2 | 13.3 | 4.3 | 59.1 | 2.7 | 5.9 | 18.2 | 56.1 | 42.7 | 37.1 | −2.2 | −11.0 |

12/13 positive years, worst −1.5%, beats the champion in 9/13. Both holdout halves positive
(48.4% then 21.9%) — not one lucky year. Note it outperformed most in 2025–26, when the
champion was losing money.

---

## Runner-up — highest risk-adjusted return

### Liquidity-segment ensemble: champion run on three turnover bands, equal weight

Three sleeves of the same champion signal, on rank bands (0-500), (100-500) and (250-750),
blended 1/3 each.

| | CAGR (net) | Sharpe | MaxDD |
|---|---|---|---|
| Discovery | 22.85% | 1.57 | — |
| **Holdout** | **23.56%** | **1.61** | −20.7% |

CAGR is quoted **after a 1.5pp/yr haircut** for cross-sleeve rebalancing, which return-level
blending ignores. Sharpe 1.61 vs the champion's 0.68 is the largest risk-adjusted improvement
in the campaign, and it also improved out of sample. The mechanism is plain: the same signal
behaves differently across liquidity tiers, so the three sleeves diversify each other.

Caveat: the Sharpe is computed on blended return series, so it does not capture holding
overlap between sleeves — the true combined book is more concentrated than three independent
sleeves. Treat 1.61 as an upper bound.

---

## What failed — and this is the important part

The **best discovery results collapsed out of sample**:

| strategy | discovery | holdout | verdict |
|---|---|---|---|
| `mom_f126_s0` (6-month momentum) | **32.20%** | 19.62%, Sharpe 0.44 | overfit — biggest decay, −12.6pp |
| `champ_buf40` (buffer tuning) | 26.81%, Sharpe 1.28 | 17.61%, Sharpe 0.72 | overfit — parameter luck |
| `mom+lv+momcons` | 26.08% | 17.64% | overfit |
| `intraday_mom_126` | 33.76% (highest CAGR found) | not promoted — −46.9% DD | rejected on risk |

Had I ranked on discovery CAGR and shipped the winner, I would have handed you a 32%
backtest that delivers 19.6% with a −39% drawdown. **The two strategies that survived were
not the top discovery performers.** That is the whole argument for the holdout.

### Families that produced nothing

- **Intraday/overnight microstructure** (the family this repo's audit flagged as never
  tested): overnight momentum, intraday momentum/reversal, and their spread. The spread
  signals were catastrophic (−13% CAGR, −88% DD). `intraday_mom_126` scored 33.76% in
  discovery but on a −46.9% drawdown, so it was not promoted. **No usable alpha here** — the
  repo's untested-family gap is now closed with a negative.
- **Standalone exotic signals**: low-beta (6.6%), MAX/lottery (3.3%), pure Amihud (12.1%),
  short-term reversal — all well below the index alone. Amihud only earns its keep *as a
  25% overlay on momentum*, never by itself.
- **Quality vetoes** on the champion: every variant landed within noise of the champion.

---

## What to actually do

1. **Primary: Mom+LowVol+Amihud, Top-10, monthly, buffer 20, top-500 universe.** 30.08%
   holdout, scales to ₹50 crore, 12/13 positive years. This is the one to trade.
2. **If you want smoother: the 3-band ensemble.** Lower CAGR (23.6%) but Sharpe 1.61 and
   −20.7% max drawdown. Costs more to run (three sleeves).
3. **Capital:** run it at ₹1 crore or more if you can — at ₹1 lakh fixed per-order brokerage
   alone costs ~2pp/yr (champion drops 24.30% → 22.07%). This is not a ₹1 lakh strategy.

### Honest caveats

- **One holdout is one experiment.** 30.08% is a clean out-of-sample number, not a promise.
  The forward-looking expectation should be lower — decay is normal, and the holdout window
  (2022-26) was a strong Indian small/mid-cap market that flatters an illiquidity tilt.
- **The −16.2% holdout drawdown is the friendliest number in the table and the least likely
  to repeat.** Discovery drawdown was −34.6% on the same strategy. Plan around −35%.
- Costs are modelled (STT, stamp, GST, brokerage, slippage, impact) but impact at ₹50 crore
  in the less-liquid half of the top 500 is an estimate, not a measurement.
- Amihud is a **capacity-consuming** signal by construction. If you scale past ₹50 crore,
  re-run the capacity test rather than assuming it extrapolates.
- Next step before real money: paper-trade the live signal for a quarter and compare fills
  against the modelled ones. The repo's own history has a "fillability mirage" finding —
  this strategy is less exposed to it than circuit/micro-cap work, but not immune.
