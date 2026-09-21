# Research Program #3 — ML "Top-Mover" Pipeline: Pressure Test

**Status:** Design critique, pre-code. No implementation authorized yet.
**Date:** 2026-07-30
**Author:** Claude (pressure-test requested by Karan)

---

## 0. The proposed pipeline

```
Every trading day
  → Universe (~3,000–5,000 stocks)
  → Remove illiquid names
  → Generate hundreds of features
  → Predict P(becomes a top mover)
  → Rank all stocks
  → Take top 10–20
  → Backtest → Learn → Improve
```

This is a **daily, cross-sectional, ML-ranked** system. That is a large pivot from the
repo's validated design (monthly/quarterly 12-1 momentum, ~17–22% CAGR). The plumbing
to host it is cheap — a new `BaseStrategy` subclass returning `P(top mover)` from
`compute_raw_scores()` plugs straight into the existing ranker, universe builder, cost
model, and walk-forward harness. **The design, not the code, is what can kill this.**

Verdict up front: **three of the boxes are load-bearing and currently underspecified.
As drawn, this design is expected to be net-negative after costs. It is salvageable —
but only after redefining the label, the horizon, and the CV protocol.**

---

## 1. The turnover bomb (the decisive objection)

**Fact from `costs/cost_model.py` + `CostConfig`:** round-trip cost for a tier-2 name at
a ₹50k position is **~0.55%** (STT 0.10%×2, stamp 0.015%, exchange/SEBI, ₹20×2 brokerage,
GST, ₹15.93 DP, slippage 0.10%×2). Tier-3 (the illiquid tail this pipeline will keep
drifting into) is **~0.8–1.0%**.

Now apply that to "take top 10–20, every trading day":

| Avg holding period | Portfolio round-trips / yr | Annual cost drag @0.55% | @0.9% (tier-3 tilt) |
|---|---|---|---|
| 2 days | ~126 | **~35%** | ~57% |
| 3 days | ~84 | **~23%** | ~38% |
| 5 days | ~50 | **~14%** | ~23% |
| 10 days | ~25 | **~7%** | ~11% |

A daily top-10 with realistic 2–5 day holds must generate **14–35% gross alpha per year
just to break even.** Your own memory (`program2-highcagr-findings`, `rs1lakh-universe-breadth`)
says the *honest gross* ceiling for price/volume families is ~20–25%, and that fillability
mirages are exactly where paper alpha dies. A daily rebalance spends the entire alpha budget
on costs. This is not a tuning problem; it is arithmetic.

**Implication:** "Every trading day" + "top 10–20" as literally drawn is dead on arrival.
The design only lives if turnover is a *first-class constraint*, not an afterthought
(hysteresis bands, min-hold, trade only on rank-threshold crossings — see §5).

## 2. The label is undefined — and the definition decides everything

"Probability of becoming a top mover" hides the single most important modelling choice:

- **Top mover of *what horizon*?**
  - *Next-day top-decile return* → almost pure noise from price/volume, and it selects for
    **lottery / high-idiosyncratic-vol names** — empirically the *worst* risk-adjusted
    bucket (the low-vol anomaly, and your own `honest-return-ceiling` Mom+LowVol finding,
    both point the other way). You would be systematically buying the tail you want to avoid.
  - *Top mover over next 20–60 days* → you have re-derived momentum with hundreds of extra
    knobs and hundreds of extra ways to overfit.
- **Top mover by raw return or risk-adjusted?** Raw-return labels reward volatility; the model
  learns "predict volatility," which is easy and unprofitable after costs.
- **Threshold vs. continuous?** A binary "top-decile: yes/no" throws away information and makes
  the label wildly imbalanced (10% positives) and regime-dependent (in a crash, "top mover"
  means "fell least").

**The label must be specified before any feature is computed.** Recommended default (§5):
predict *forward N-day residual return after neutralizing beta/size/sector*, N chosen so that
the implied turnover survives §1 — i.e. **N ≈ 20 trading days, not 1.**

## 3. "Hundreds of features → Learn → Improve" is an overfitting engine

Your entire research record is a monument to this exact failure mode:
`honest-return-ceiling` ("30% target is a survivorship-bias mirage"),
`rs1lakh-universe-breadth` ("filters are load-bearing; unfiltered momentum 26% is a
fillability mirage"), `program2-highcagr-findings` (the "mirage" caveats). Hundreds of
features on a noisy daily label, iterated toward a single backtest number, will manufacture
a beautiful equity curve that is **survivorship-of-the-search**: you overfit the *model
selection*, not just the parameters.

Two concrete hazards specific to this repo:

1. **`deflated_sharpe_ratio` needs an honest `n_trials`.** Every feature set, every horizon,
   every hyperparameter sweep is a trial. "Hundreds of features + Learn/Improve loop" pushes
   effective `n_trials` into the thousands, which crushes the deflated Sharpe. If you don't
   count trials honestly, the DSR is theatre.
2. **Leakage vectors are everywhere in daily ML:** using T's close to predict T's move;
   feature normalization fit on the full sample; the universe/illiquidity filter using
   forward information; labels that overlap across adjacent days (autocorrelated → naive CV
   leaks). The current `generate_walk_forward_windows` does **not** purge or embargo — for
   overlapping N-day labels it will leak train into test.

## 4. Point-in-time & survivorship (the one area you're already strong)

Genuinely good news: the hard infrastructure this needs already exists and is validated —
PIT universe builder, liquidity/anti-manipulation filters, a real Indian cost model, T+1
open execution (`execution_delay_days=1`, `execute_at="open"`), and delisted-symbol tracking
(`symbols_delisted.txt`). **Do not rebuild these.** The ML layer must consume the *same*
PIT panels the momentum strategy does, and features must be computed only from data
`≤ date`. The "~3,000–5,000 stocks" universe is larger than the current NIFTY-500 focus,
which reopens the small-cap fillability problem your `rs1lakh` memory already flagged — the
liquidity filter has to be *tighter* here, not looser, precisely because the model will hunt
for edge in the illiquid tail.

## 5. A de-risked version worth actually testing

Keep the skeleton; change the three load-bearing boxes.

**Label (fixes §2):**
- Target = **forward 20-trading-day return, residualized** against market beta, size, and
  sector (so the model can't win by just buying high-vol/high-beta names).
- Continuous regression target, not binary. Rank-transform per date for a robust loss.

**Horizon & turnover (fixes §1):**
- Rebalance **weekly or on a 20-day cycle**, not daily. Signals may update daily, but
  *trades* fire only when a name crosses a hysteresis band (e.g., enter on rank ≥ 90,
  exit only on rank < 70) with a **minimum 15-trading-day hold**. Turnover becomes a
  budgeted constraint targeting ≤ ~5% one-way/day, i.e. cost drag in the ~7–10% range,
  not 30%+.
- Position count 15–20 (not 10) for cost amortization and idiosyncratic-risk diversification.

**Features (fixes §3):**
- **Start with ~15–30 features, not hundreds.** Momentum multi-horizon (you already have
  12/6/3-month), volatility, liquidity/turnover trend, distance-from-52w-high, short-term
  reversal, and a couple of volume-structure features. Add features only when they survive
  out-of-sample, one at a time. "Hundreds of features" is postponed until the pipeline is
  proven net-positive with a handful.
- Model: start with a **linear/logistic or gradient-boosted tree with heavy regularization**
  and monotonic constraints where sign is known. No deep nets until there's signal to explain.

**Validation (fixes §3):**
- Replace naive walk-forward with **purged + embargoed walk-forward** (embargo ≥ label
  horizon = 20 days) to kill overlap leakage. This is a required change to
  `backtest/anti_overfit.py` before any ML result is trustworthy.
- Track `n_trials` honestly and report **deflated Sharpe** on every candidate.
- Feature normalization and label residualization fit **inside each train fold only.**

**Go/No-Go gates (before spending real effort):**
1. **G0 — Cost sanity:** with the turnover constraint above, model an idealized *perfect*
   top-20 selector and confirm it clears costs by a wide margin. If even a cheating oracle
   barely beats costs at your turnover, stop.
2. **G1 — Signal existence:** does the residualized 20-day label have *any* out-of-fold
   rank IC > ~0.03 from the 15-feature set? No IC → no product; abandon before building the
   full harness.
3. **G2 — Net beats champion:** net-of-cost CAGR/Sharpe must beat the frozen 17–18% momentum
   champion out-of-sample across walk-forward folds, with deflated Sharpe > 0.95.
4. **G3 — Robustness:** parameter/feature ±20% perturbation doesn't collapse Sharpe by >50%
   (your existing `parameter_stability_test` standard).

## 6. Recommendation

- **Do not** build the daily top-10 as drawn. It is expected-negative after costs (§1).
- **Do** run a *small* research spike on the de-risked variant (§5), gated hard at **G0 → G1**
  before any model tuning. G0 is a half-day of arithmetic on the existing cost model; G1 is
  a single-feature-set IC test. If either fails, you've spent a day, not a program.
- The most likely honest outcome, given your prior research, is that this converges back
  toward **residualized momentum with a slightly better multi-feature blend** — a modest
  improvement on the champion, *not* a new return regime. Size expectations accordingly:
  the win condition is "beats 17–18% net, out-of-sample, after honest deflation," and
  anything promising 30%+ should be treated as a leakage bug until proven otherwise.

---

### Integration notes (when/if G1 passes)
- New strategy: `strategies/ml_ranker.py` subclassing `BaseStrategy`; `compute_raw_scores`
  returns predicted residual return / probability. Base class handles ranking. No engine change.
- Turnover control belongs in `risk/rebalancer.py` (hysteresis + min-hold), not the model.
- CV upgrade (purge/embargo) belongs in `backtest/anti_overfit.py` — this is the one
  genuinely new piece of infrastructure required and should be built *first*, before the model.
