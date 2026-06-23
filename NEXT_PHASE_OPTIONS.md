# Next-Phase Options — Project-Level Decision

**Context:** the price-only research program is complete (`PRICE_ONLY_FINAL_CONCLUSION.md`). The frozen
champion — Momentum + LowVol / Top10 / Quarterly / Buffer20 — is a validated product
(~17.4% net CAGR, Sharpe 0.69, MaxDD −33.5%, cash only). This document compares the four ways forward.
**No implementation, no new backtests — a decision document only.**

The four options:

| | Option | One line |
|---|---|---|
| **A** | Stop project & deploy champion | Ship the validated price-only product; do no further research. |
| **B** | Build Quality pilot | Test gross-profitability/ROE as an added factor (framework already built, paused). |
| **C** | Build Value pilot | Test E/P, B/M — the canonical negatively-correlated complement to momentum. |
| **D** | Build full PIT fundamentals platform | Vendor-grade point-in-time financials for the whole universe; multi-factor end-state. |

---

## 1. Scoring (1 = worst, 5 = best on each axis as labelled)

> "Expected alpha" = additional **risk-adjusted** return on top of the champion (not raw CAGR).
> "Engineering effort" and "Data requirements" are scored 5 = least burden. "Prob. of success" = chance
> the option achieves its *own* goal (A: ship a real product; B/C: a validated factor that beats the
> champion; D: a positive multi-factor product justifying the platform cost).

| Option | Expected alpha | Eng. effort (5=easiest) | Data req. (5=lightest) | Prob. of success | Notes |
|---|:--:|:--:|:--:|:--:|---|
| **A. Stop & deploy** | 1 | 5 | 5 | 5 | Zero new alpha, but the champion is already real & shippable. |
| **B. Quality pilot** | 3 | 4 | 2 | 3 | Code done (`quality_store.py`); blocked on ~485-row PIT panel. Redundancy risk vs low-vol. |
| **C. Value pilot** | 4 | 4 | 2 | 3.5 | Highest-payoff factor; same data wall as B; value is volatile/regime-dependent. |
| **D. Full PIT platform** | 5 | 1 | 1 | 2 | Highest ceiling, but premature & costly before any fundamental signal validates. |

### Axis-by-axis

**Expected alpha**
`D > C > B > A`. D's multi-factor end-state has the highest theoretical ceiling; **Value (C)** is the
single highest-payoff *factor* (offensive *and* negatively correlated with momentum — the ideal
complement). **Quality (B)** is robust globally but partly *defensive*, so it risks redundancy with the
champion's existing low-vol leg (the exact failure mode that sank Low-MAX). **A** adds nothing — you keep
the 17.4% you already have.

**Engineering effort (easiest first)**
`A > B ≈ C > D`. A is deploy/ops only. B's pilot is **already built and verified** (paused on data); C is
a near-clone (swap the scorer, reuse the frozen A/B/C/D harness). D is months of work — bias-free
historical financials, restatement handling, announcement-date alignment, vendor integration, ongoing
maintenance.

**Data requirements (lightest first)**
`A > B ≈ C > D`. A needs nothing. **B and C share the same wall:** a clean, point-in-time,
survivorship-free fundamentals panel (~485 company-years for a pilot) from paid CMIE Prowess or an
NSE/BSE XBRL scraper — **never** yfinance/Screener (survivors-only = banned). C additionally leans on
balance-sheet items with higher restatement/look-ahead sensitivity. D needs that same data for the
*entire* universe, continuously.

**Probability of success**
`A > C > B > D`. A is near-certain (the product already passed validation). C is a moderate-to-good bet
(strong Indian value premium; the right kind of complement). B is moderate but discounted by the
defence-on-defence redundancy risk. D is the lowest near-term bet because building the platform *before*
a validated fundamental signal repeats the Phase-1 mistake (build-before-test) and only pays off if B/C
succeed anyway.

---

## 2. The key structural insight

**B and C are not independent of D — they are the cheap test *of* D.** The expensive, risky part of every
fundamental option is the *same clean PIT dataset*. So the real decision is **not** "which factor," it is:

> *Is it worth funding a clean point-in-time Indian fundamentals dataset at all?*

If **no** → the answer collapses to **A** (deploy the champion; fundamentals were a few risk-adjusted
points at best and not worth the data cost).

If **yes** → fund a **bounded pilot dataset once** and use it to test **Value and Quality together** off
the same panel (C and B), exactly as the paused Phase-2A harness already supports. That is a *bounded*
slice of D's data layer **without** D's full platform engineering. Only escalate to **D** if a
fundamental signal validates.

This makes B-vs-C a false binary: one data effort answers both. Value leads on expected payoff, so the
pilot should be **Value-first, Quality-alongside**.

---

## 3. Recommendation

**Do A and (a Value-first fundamentals pilot) in parallel; defer D.**

1. **A now — ship the champion.** Deploy / paper-trade Momentum + LowVol / Top10 / Quarterly / Buffer20,
   cash only. It is the real product and does not depend on any further research.
2. **C as the lead research bet, scoped to also cover B.** If (and only if) a clean PIT fundamentals
   source is funded, run the bounded pilot **Value-first**, collecting enough fields to test Quality off
   the same panel. Reuse the frozen Phase-2A A/B/C/D harness and pre-registered bar (beat the champion on
   Sharpe/CAGR, drawdown not >3 pts worse, no split-sample sign-flip).
3. **D only after a PASS.** Escalate to a full PIT platform **only** once a fundamental factor clears the
   pilot bar. Building it first is premature and high-cost.

**Ranked overall (risk-adjusted attractiveness of the next step):** **A ≈ C  >  B  >  D.**
A is the safe, certain product; C is the highest-expected-value research bet (and drags B along for free
on the same data); B alone is dominated by C; D is the destination, not the next move.

**If forced to a single choice with no new data budget:** **A** — deploy the champion and stop. The honest
ceiling on this data is ~17–18% cash, the champion captures it, and no price-only or sizing lever moved it.
