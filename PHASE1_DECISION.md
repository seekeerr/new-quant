# Phase 1 — Decision

**Question:** After the price-only research phase, what next?
**Options:** A. Stop research · B. Run Momentum + Quality pilot · C. Build full PIT fundamentals platform.

## Decision: **B — Run a Momentum + Quality pilot.**

---

## Why, from the evidence

### The price-only search space is genuinely exhausted
Six signal experiments beyond the champion (residual momentum, 52-Week-High, Low-MAX, Frog-in-the-Pan) plus three overlays (trend, vol-managed, leverage) all failed to beat **Mom + LowVol / Top10 / quarterly / Buffer20** (Sharpe 0.69, 17.4% CAGR, −33% MaxDD). The failures are *informative*, not random:
- refinements of the **momentum leg** never beat plain 12-1 momentum;
- a second **defensive** factor (Low-MAX) just doubles up on defence;
- the one strong standalone alternative (52-Week-High) is **redundant** with low-vol.

There is no obvious price-only stone left unturned that the evidence points to.

### The one thing that worked tells us what to try next
Low-vol is the *only* addition that lifted risk-adjusted return — because it is an **offence + defence pairing** of two lowly-correlated legs. The champion already has its defensive leg. The missing piece is a **second, lowly-correlated *offensive* return factor**, and the literature + the Indian evidence point squarely at **Value and Quality**. Those need fundamentals — which price-only work, by definition, could never test. This is not a new guess; it is the direct continuation of the only successful result.

### Why not A (Stop)
Stopping would abandon the single avenue the evidence actively recommends, with a known, well-documented expected payoff (Value/Quality premia are among the most robust globally and present in India). The honest ceiling is ~17–18% on price-only/cash; Quality is the one credible lever to add a few points of *risk-adjusted* return. Premature to quit.

### Why not C (Full PIT platform) — yet
A full point-in-time fundamentals platform is the **expensive** path: bias-free historical financials, restatement handling, announcement-date alignment, vendor data, and ongoing maintenance. The whole Phase-1 lesson is that **fundamentals data is exactly where survivorship/look-ahead bias hides** — and we just spent this phase proving how badly unaudited data corrupts results (47% mirages, a benchmark bug that faked +12% alpha). Committing to a full platform before a single validated fundamental signal exists would repeat the mistake of building before testing. The project's own standing principle is *"run cheap hypothesis tests before heavy engineering."*

### Why B is the disciplined middle
A pilot de-risks C while honouring A's caution. It answers one question cheaply: **does a quality tilt add validated Sharpe/CAGR on top of the champion, net of costs, on honest data?** If yes → C is justified with evidence. If no → stop, and the champion ships as-is — at a tiny fraction of a platform's cost.

---

## Pilot scope (bounded, cheap, frozen engine)

**Keep frozen:** backtest engine, costs, universe construction, rebalance schedule, Buffer20, position sizing, execution. The quality factor enters only as a new **drop-in scorer**, exactly as every Phase-1 factor did (`make_blend_scorer`).

**Minimal data:** one or two robust, hard-to-misstate quality metrics that need only annual financials — **gross profitability (gross profits / total assets)** and/or **ROE** — for the ~500 names in the liquid pool. Lag every fundamental by ≥3 months after fiscal year-end to avoid look-ahead. No estimates, no platform.

**Variants (mirror the proven A/B/C/D protocol):**
- A. Momentum
- B. Quality (standalone)
- C. Momentum + LowVol *(champion — the bar to beat)*
- D. Quality-tilted champion (e.g. Mom + LowVol + Quality, or Mom + Quality)

**Pre-registered success criterion (same discipline as Phase 1):** D improves **Sharpe and/or CAGR** vs champion C **without materially worsening drawdown** (>3 pts), **and survives split-sample + rolling-window validation** (no sign-flip across halves — the test that killed FIP).

**Hard data-quality gate before trusting any result:** confirm the fundamentals panel is point-in-time and free of survivorship/look-ahead bias — the same audit standard that this phase showed is non-negotiable.

---

## Decision tree after the pilot
- **Pilot PASS (validated):** escalate to **C**, a full PIT fundamentals platform, now justified by a positive, bias-checked signal.
- **Pilot FAIL or fragile:** fall back to **A** — freeze and ship the price-only champion (~17.4% CAGR, Sharpe 0.69, cash, no leverage); fundamentals were a few points at best and aren't worth the platform.

**Estimated effort:** pilot = days of data assembly + a single frozen-engine run, vs months for a full platform. The expected information gain per unit effort is highest for B by a wide margin.
