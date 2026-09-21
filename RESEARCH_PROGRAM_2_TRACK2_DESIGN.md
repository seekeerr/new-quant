# Research Program #2 — Track 2: New-Style High-CAGR Hunt (Pre-Registration)

**Opened:** 2026-06-30
**Status:** OPEN — pre-registration of experiments. No backtests judged yet.
**Parent:** `RESEARCH_PROGRAM_2_CHARTER.md` (constraints, gates, frozen shell).

Track 1 asks *"is the standing 21.8% small-cap lead real?"*. **Track 2 asks the independent
question: can a genuinely DIFFERENT trading style — not a momentum refinement — earn materially
higher robust CAGR than the champion?** Both run in parallel; this document designs Track 2.

---

## 0. Two hard lessons that shape every Track 2 design

1. **High-turnover long-only CONTRARIAN buying is dead** (short-term reversal: negative even
   *gross*, −82% DD). It loaded on falling knives. **Any new style must avoid buying absolute
   losers.** The winning contrarian variant, if one exists, buys *dips inside uptrends*, never
   outright decliners.
2. **The frozen engine disables impact cost** (`run_buffered_backtest` never passes
   `avg_daily_value`). So a fast/small-cap edge can look free in the base engine and be a
   fillability mirage. **Every Track 2 PASS candidate must additionally clear (a) the ×5/×10
   slippage stress AND (b) the impact-aware capacity ladder** (`run_impact_aware_backtest`, built
   in Track 1's `run_program2_smallcap_validation.py`). This is a standing requirement, stated up front.

---

## 1. Engine-fit reality

The existing engine is a **fixed-N, cross-sectional rank, scheduled-rebalance** machine: at each
rebalance date it scores the universe, takes Top-N with a buffer, equal-weights. Two classes of
Track 2 idea map differently onto it:

- **Class R (rank-native):** any style expressible as "score every name today, hold the Top-N" —
  runs on the existing engine by swapping the scorer + rebalance frequency. **Cheap, no new engine.**
- **Class E (event-native):** "enter the day an event fires, exit on a time/stop rule, hold a
  variable number of names." Needs a small new **event-execution engine** (entries on arbitrary
  days, per-position time/trailing-stop exits). **A scoped prerequisite build.**

Sequencing exploits this: exhaust the cheap Class-R ideas first; build the event engine only if the
evidence warrants chasing a Class-E style.

---

## 2. The five candidate experiments (ranked by expected robust payoff ÷ cost)

All use the survivorship-free bhavcopy panels, equity-only, NET of the full Indian cost model, and
are judged on the **identical six gates** in charter §4 (CAGR > 17.4%, Sharpe ≥ 0.69, DD not >5pts
worse, no split-sample sign-flip, survives cost stress, no losing 3-yr window) **plus** the §0.2
capacity requirement.

### 2C — Pullback-in-Uptrend  *(LEAD — highest expected payoff, rank-native)*
- **Hypothesis.** Buying short-term *dips in strong stocks* captures a mean-reversion bounce
  **without** the falling-knife risk that killed standalone reversal. It is the disciplined cousin
  of the dead reversal style — same contrarian entry, opposite quality of name.
- **Signal (Class R).** Universe filter: `close > SMA200` AND 12-1 momentum in the top half
  (confirmed uptrend). Among those, rank by **short-term pullback depth** — e.g. lowest 3–5 day
  return, or RSI(3) low, or close in the bottom quartile of its 10-day range. Top-10, **weekly or
  biweekly** rebalance, Buffer.
- **Why not pre-doomed.** Reversal failed because it bought absolute losers (distressed micro-caps).
  This buys temporary weakness in confirmed winners — a structurally different population.
- **Pre-registered prior.** Most promising new style. Risk = turnover (weekly) → cost drag; the
  cost gates decide it. Expect Sharpe-competitive; CAGR edge uncertain.

### 2B — Breakout / Donchian (volume-confirmed)  *(rank-native first)*
- **Hypothesis.** Volume-confirmed breakouts to new highs ignite fresh momentum legs; entering at
  ignition (not after a quarter of drift) captures more of the move.
- **Signal (Class R first).** Rank by breakout strength = `close / 252-day-high` combined with a
  **volume surge** filter (volume > 1.5× 50-day average). Top-10, monthly rebalance. `strategies/
  breakout.py` (Donchian + volume) already exists and has **never been tested net** — wire it in.
- **Distinct from the failed 52WH factor.** 52-Week-High *proximity* failed only *blended into
  low-vol* (it became low-vol-only). Here it is an **offensive standalone breakout-event** signal
  at its natural frequency, with volume confirmation — a different test.
- **Pre-registered prior.** Directional, not contrarian → not pre-doomed. Cost-sensitive; small-cap
  breakouts especially need the capacity gate.

### 2A — Holding-period / horizon grid  *(cheap "rule-out", rank-native)*
- **Hypothesis.** Faster trend capture (shorter formation, faster rebalance) nets MORE than the
  quarterly champion — or it does not, and we close the axis.
- **Design.** Grid: formation ∈ {3-1, 6-1, 12-1} × rebalance ∈ {monthly, quarterly} on the
  Mom+LowVol scorer. The one axis the closed price-only work never swept cleanly (it only varied
  the buffer, not formation×frequency).
- **Pre-registered prior.** Turnover rises ~3–4×; honest expectation is **net CAGR falls** under
  the Indian cost model (the reversal lesson). Value is in *decisively* ruling it in or out, cheaply.

### 2E — Event-driven gap+volume drift (PEAD proxy)  *(Class E — needs event engine)*
- **Hypothesis.** Post-earnings-announcement drift is among the most robust global anomalies.
  Without earnings dates, a **large up-gap + volume surge** is a price-only proxy for a positive
  surprise; the stock drifts up for weeks.
- **Signal (Class E).** Event = 1-day return > +8% on volume > 3× 50-day average. Enter next open,
  hold a fixed drift window (e.g. 40 trading days) or trailing stop, long-only.
- **Prerequisite.** Build the lightweight event-execution engine (§1, Class E).
- **Pre-registered prior.** Strong economic basis; main risks are cost (event churn) and that the
  gap proxy is noisier than true earnings surprise. Highest-payoff Class-E idea.

### 2D — Volatility-expansion / squeeze breakout  *(Class E — needs event engine)*
- **Hypothesis.** A volatility *contraction* (squeeze) resolving into *expansion* with a directional
  break precedes sustained moves.
- **Signal (Class E).** Bollinger/Donchian-width percentile low (squeeze) → enter on the directional
  break confirmed by ATR(20) > ATR(60); time/stop exit.
- **Pre-registered prior.** Lower priority than PEAD; thinner cross-sectional evidence, same event
  engine dependency. Test only if 2C/2B/2E leave the ceiling question open.

---

## 3. Ranked sequencing

| Order | Experiment | Class | New engine? | Expected payoff | Why this order |
|---|---|---|:--:|:--:|---|
| 1 | **2C Pullback-in-uptrend** | R | no | **High** | Fixes the exact failure that killed reversal; cheap. |
| 2 | **2B Breakout (volume-confirmed)** | R | no | Medium-High | Strong basis, engine-native, untested net. |
| 3 | **2A Horizon/turnover grid** | R | no | Low (rule-out) | Cheap; decisively closes the "faster=better?" axis. |
| 4 | **2E PEAD gap+volume drift** | E | **yes** | Medium-High | Best Class-E basis; gated on event-engine build. |
| 5 | **2D Vol-expansion squeeze** | E | yes | Medium | Only if the ceiling is still open after 1–4. |

**Build dependency:** experiments 4–5 require a scoped **event-execution engine** (arbitrary-day
entries, per-position time/trailing-stop exits, variable position count). Build it only after the
Class-R results (1–3) justify chasing a Class-E style.

---

## 4. Pre-registered program-level expectation (goalposts fixed now)

- Most likely, **2C is the one with a real shot**; 2A is expected to *fail* (cost drag); 2B is a
  coin-flip; the Class-E styles are higher-variance bets gated on a build.
- If **none** of 2A–2E clears the gates, the honest conclusion is that the robust ceiling sits where
  Track 1 lands (champion ~17.4%, or ~22% if the small-cap tail validates) and **no different
  *style* beats a well-built momentum/low-vol product net of Indian costs** — itself a valuable,
  publishable result, not a failure.
- A disappointing-but-honest ceiling is a SUCCESS under this program's own success criterion.

---

## 5. Immediate next action

Track 1 (`run_program2_smallcap_validation.py`) is running. The Track-2 lead, **2C
Pullback-in-Uptrend**, is rank-native and can be built now and queued to run as soon as Track 1
frees the CPU. Recommended: build `run_program2_pullback.py` next, pre-registering the exact signal
above, reusing the frozen engine + the six gates + the impact-aware capacity pass.
