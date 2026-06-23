# Phase 2B — Alternative Strategy Landscape

**Status:** Research-design exercise only. **Nothing here is implemented or backtested.**
**Date:** 2026-06-22
**Goal:** Identify strategy families that (a) do **not** depend on momentum and (b) do **not**
require manual fundamentals collection — to keep research moving while the Quality track is
PAUSED (`PHASE2A_STATUS.md`).

**The bar to beat (frozen champion):** Momentum + LowVol / Top10 / Quarterly / Buffer20 —
**17.4% net CAGR · Sharpe 0.69 · MaxDD −33.5% · Beta 0.74 · +3.8% excess vs NIFTY 500**,
cash only, net of the full Indian delivery cost model. Never a losing 3-year window.

---

## 0. What the repo actually has (the feasibility anchor)

Every "data availability" verdict below is measured against this inventory — verified, not assumed.

| Available (✅) | Detail |
|---|---|
| Survivorship-free daily price panels | `adj_close/high/low`, `raw_close/high/low`, `raw_volume`, `raw_turnover`; **2011-01 → 2026-05**, **3,291 equity symbols** (ISIN `INE`), top-500-liquid point-in-time. |
| ISIN / equity classification | `symbol_isin.csv`, `symbols_equity.txt`, active/delisted lists — clean equity-only whitelist. |
| Benchmark | `nifty500_tri.csv` (price + TRI), date-parse bug fixed; CAGR 13.6% / TRI ≈14.9%. |
| Realized vol, covariance, trend, RSI, ATR | Derivable from price panels; helpers already in `utils/indicators.py`. |
| Position sizing | `portfolio/constructor.py` already implements **equal / inverse_volatility / risk_parity**. |
| Regime proxy | `regime/regime_filter.py`: BULL/NEUTRAL/BEAR from Nifty 200/50 SMA + ADX. |

| Missing / contaminated (❌ / ⚠) | Consequence |
|---|---|
| **Fundamentals** (earnings, book value, profitability) | ❌ Only the empty pilot template. Blocks Quality / Value / Multi-factor. yfinance/Screener = survivors-only = **banned**. |
| **Shares outstanding / market cap / float** | ❌ Not in repo. No honest size factor (turnover ≠ size). |
| **Clean dividend feed** | ❌ `adj_close ÷ raw_close` mixes splits+bonus+dividends; cash dividends can't be isolated. |
| **Sector / industry labels** | ⚠ Only **500 of 3,291** equities (15%) are labelled, and that set is the **current survivor** list → survivorship + look-ahead baked into the map. |

**Implication:** the *only* families that are fundamentals-free **and** clean-data-ready **today**
are the **price-only** ones. Everything fundamental (A, B, C, K), the size factor (I), dividends (J),
and honest sector work (F) require a new data project of varying size.

---

## 1. Candidate families — full evaluation

Each family is assessed on the 7 required dimensions. "Repo sufficient?" answers the user's
core constraint. Bias risk uses the Phase-1 hard-won standard (survivorship + look-ahead are the
dominant sources of fake alpha here).

> Legend for the score tables in §2: 1 = poor/high-effort, 5 = excellent/low-effort.

---

### A. Quality-only
1. **Economic rationale.** Profitable, stable firms (high gross-profitability, ROE) earn a premium — Novy-Marx (2013), QMJ (Asness-Frazzini-Pedersen). Robust globally and documented in India.
2. **Required data.** Annual financials: gross profit, total assets, net profit, total equity, + PIT filing dates.
3. **Repo sufficient?** ❌ **No.** Identical blocker to the paused Phase 2A track — only the empty template exists.
4. **Effort.** Code ≈ 0 (scorer already built in `quality_store.py`). Effort is entirely the **data** (~485 manual rows or paid Prowess/XBRL).
5. **Bias risk.** **HIGH** on data — fundamentals are exactly where survivorship/look-ahead hide. Methodology is already PIT-gated (filing_date else period_end +120d, verified-only).
6. **Clean experiment.** *Is the paused Phase 2A pilot* — A/B/C/D on the frozen shell. No new design needed.
7. **Success vs champion.** D (Mom+LowVol+Quality) beats C on Sharpe and/or CAGR, DD not >3 pts worse, no split-sample sign-flip. (Pre-registered.)
   → **Verdict: duplicate of the PAUSED track. Not actionable without the fundamentals project.**

### B. Value-only
1. **Economic rationale.** Cheap stocks (high E/P, B/M) outperform — the canonical *negatively-correlated* offensive diversifier of momentum (Asness-Moskowitz-Pedersen). Strong, well-documented Indian value premium. **Phase-1 named this the single highest-expected-payoff open hypothesis.**
2. **Required data.** Earnings (E/P) and/or book value (B/M) per share, PIT. (Price — the P — is present; E and B are not.)
3. **Repo sufficient?** ❌ **No.** Same fundamentals wall as Quality.
4. **Effort.** Scorer trivial (drop-in like quality). Data effort = the same fundamentals project; value also needs careful restatement/PIT handling.
5. **Bias risk.** **HIGH** — value leans on stale, restated balance-sheet items; highest look-ahead exposure of the fundamental factors.
6. **Clean experiment.** A/B/C/D clone of the Quality pilot, value composite (E/P + B/M) as the offensive leg, same frozen shell, same pre-registered bar.
7. **Success vs champion.** Same bar; the *expected* winner among fundamental factors given momentum-value negative correlation.
   → **Verdict: highest alpha potential of all — but gated behind the same data wall. Not fundamentals-free.**

### C. Quality + Value
1. **Economic rationale.** Buy cheap **and** good — pairing value with quality screens out value traps; QV is among the most robust composite premia.
2. **Required data.** Both value *and* quality fundamentals (superset of A + B).
3. **Repo sufficient?** ❌ **No** — most data-hungry of the fundamental set.
4. **Effort.** Scorer trivial; data effort largest (two fundamental factors).
5. **Bias risk.** **HIGH** (two fundamental legs).
6. **Clean experiment.** A/B/C/D with a QV composite offensive leg on the frozen shell.
7. **Success vs champion.** Same bar; theoretically strong but blocked.
   → **Verdict: strong thesis, most data-hungry, blocked.**

### D. Mean Reversion (short-term reversal)
1. **Economic rationale.** Short-horizon (1-week to 1-month) losers bounce — overreaction / liquidity-provision premium. **Negatively correlated with 12-1 momentum**, so a *genuine price-only diversifier* of the champion's offensive leg. Real and documented on Indian equities. Phase-1 explicitly left "1-month reversal" as an open price-only hypothesis.
2. **Required data.** **Prices only.**
3. **Repo sufficient?** ✅ **Yes — fully.** Strategy already coded (`strategies/mean_reversion.py`, mean-revert *within* an uptrend to avoid falling knives).
4. **Effort.** **LOW.** Drop-in scorer; the one real change is a **monthly** rebalance (reversal decays in weeks → conflicts with the frozen *quarterly* shell, so run it as a **separate shell**, not a champion modification).
5. **Bias risk.** **LOW** — price-only on the survivorship-free panel. The real pitfall is **transaction cost**: short-horizon reversal is high-turnover and decays fast; it must be judged **net** of the full Indian cost model (which the engine already applies).
6. **Clean experiment.** A/B/C/D, monthly shell: A = 12-1 momentum, B = short-term reversal standalone, C = frozen champion (the bar), D = champion + a reversal sleeve (or a mom/reversal blend). Pre-register; report **net-of-cost** front and centre; split-sample for sign-flip.
7. **Success vs champion.** B or D adds **net** Sharpe and/or CAGR vs C **after costs**, without worsening DD >3 pts, and survives split-sample. The cost hurdle is the live question.
   → **Verdict: the BEST fundamentals-free, genuinely non-momentum, data-sufficient candidate.**

### E. Trend Following (time-series / "managed-trend" momentum)
1. **Economic rationale.** Absolute (time-series) momentum — hold names with positive trailing return, exit on downtrend; classic crisis-alpha / convexity in bear markets.
2. **Required data.** **Prices only.**
3. **Repo sufficient?** ✅ **Yes.** `strategies/trend_following.py` coded; regime filter available.
4. **Effort.** LOW-MEDIUM. **Caveat: it is a momentum cousin** (time-series vs cross-sectional) → only *partially* satisfies "not momentum." Phase-1 already tested trend as an **overlay = null** (risk-only); standalone TSMOM as its *own product* is untested.
5. **Bias risk.** **LOW** (price-only).
6. **Clean experiment.** Build managed-trend as a standalone product and measure its **correlation to the champion in BEAR regimes** (crisis-alpha test), rather than re-running the null overlay. Pre-register a diversification (Calmar/DD) bar, not a raw-CAGR bar.
7. **Success vs champion.** Materially improves blended Calmar/DD when combined with the champion, without CAGR loss. Phase-1 prior on the overlay form is null → modest expectation.
   → **Verdict: data-clean but low novelty (momentum cousin) and an unfavourable Phase-1 prior.**

### F. Sector Rotation
1. **Economic rationale.** Rotate into leading sectors by relative strength — sector-level momentum / dispersion premium.
2. **Required data.** PIT sector/industry labels for the full pool + sector indices built from member prices.
3. **Repo sufficient?** ⚠ **No, not cleanly.** Sector labels exist for only **500 / 3,291** equities (15%), and that set is the **current survivor** universe → survivorship + look-ahead in the very mapping. Cannot build honest PIT sector indices from it.
4. **Effort.** MEDIUM-HIGH (source a historical PIT industry classification, then build sector indices).
5. **Bias risk.** **HIGH** — the only sector source is the current survivor list (precisely the bias Phase-1 fought and removed).
6. **Clean experiment.** Only sound *after* sourcing a PIT industry map for the full bhav pool (a real, if smaller-than-fundamentals, data project); then sector-momentum overlay or sector-neutralized momentum vs champion.
7. **Success vs champion.** Sector overlay beats C net of costs.
   → **Verdict: momentum-flavoured AND blocked on honest sector labels. Defer.**

### G. Volatility Targeting
1. **Economic rationale.** Scale gross exposure inversely to realized/forecast vol to stabilise risk and time the vol cycle (Moreira-Muir managed volatility).
2. **Required data.** **Prices only** (realized vol).
3. **Repo sufficient?** ✅ **Yes.**
4. **Effort.** LOW. **But:** it is an *exposure overlay*, not a selection alpha — and scaling *up* requires leverage. **User is cash-only**, so only the *de-risking* leg (scale ≤ 1×, hold cash when vol is high) is permitted → upside is capped. Phase-1 vol-managed momentum = **null**.
5. **Bias risk.** **LOW** (price-only).
6. **Clean experiment.** Apply vol-target scaling (cap 1×, cash buffer in high-vol) to the champion's exposure; compare Sharpe/Calmar/DD.
7. **Success vs champion.** Lifts champion Sharpe/Calmar without material CAGR loss. Phase-1 prior: null.
   → **Verdict: data-clean and trivial, but Phase-1 says overlays don't add Sharpe and cash-only blocks the upside leg. Low alpha; useful only as a risk-shaping add-on.**

### H. Equal Risk Contribution (ERC / risk-parity weighting)
1. **Economic rationale.** Weight names so each contributes equal portfolio risk → better diversification than equal-weight; can raise Sharpe on the *same* holdings.
2. **Required data.** **Prices only** (covariance / vol).
3. **Repo sufficient?** ✅ **Yes.** `portfolio/constructor.py` **already implements** equal / inverse-vol / risk-parity. The champion is currently **equal-weight** → ERC is the **one untested weighting degree-of-freedom** on the frozen champion.
4. **Effort.** **VERY LOW** — change the weighting method on the existing Top10; no new data, no new factor.
5. **Bias risk.** **LOW.**
6. **Clean experiment.** Frozen champion Top10, swap equal-weight → inverse-vol / ERC / min-variance; compare **net** Sharpe / DD / turnover (ERC adds turnover → must check net of cost).
7. **Success vs champion.** ERC/inv-vol lifts champion Sharpe or cuts DD without net-CAGR loss after the added turnover cost.
   → **Verdict: cheapest possible experiment; fully data-sufficient; attacks the champion's last untested assumption. High info-per-effort, modest expected magnitude.**

### I. Small Cap Premium
1. **Economic rationale.** Smaller firms earn a size premium (Fama-French SMB) — though weak/contested post-2000 and concentrated in illiquid micro-caps.
2. **Required data.** Market cap = price × **shares outstanding** (or free float).
3. **Repo sufficient?** ❌ **No** — shares-outstanding/float not in repo; turnover is a *liquidity* proxy, not size. The champion universe is already **top-500 liquid** (large/mid tilt) → a size tilt fights the liquidity filter.
4. **Effort.** MEDIUM (need a shares-outstanding history) for an honest version.
5. **Bias risk.** **HIGH** — small/micro is where survivorship + illiquidity bite hardest, and Phase-1 *directly* showed micro-cap concentration blows up (honest Top3 = 3% CAGR / −72% DD).
6. **Clean experiment.** Only honest with a shares-outstanding panel + a strict liquidity floor; otherwise unsound.
7. **Success vs champion.** A small-tilt sleeve beats the champion net of (large) small-cap trading costs — unlikely given Phase-1 evidence.
   → **Verdict: data-limited and Phase-1 evidence is actively against it. Low priority.**

### J. Dividend Yield
1. **Economic rationale.** High-dividend stocks proxy value/quality and pay income — a defensive premium.
2. **Required data.** Cash-dividend-per-share history, PIT.
3. **Repo sufficient?** ❌ **No.** No clean dividend feed; the adj/raw price ratio mixes splits+bonus+dividends and can't isolate cash dividends → no honest yield.
4. **Effort.** MEDIUM (source a dividend / corporate-action feed that separates cash dividends).
5. **Bias risk.** MEDIUM-HIGH (survivor-sourced dividend data; yield traps).
6. **Clean experiment.** Needs a dividend dataset first; then a yield-factor A/B/C/D.
7. **Success vs champion.** Dividend tilt adds net Sharpe vs C.
   → **Verdict: semi-fundamental and data-blocked (no clean dividend source). Defer.**

### K. Multi-factor (Momentum + Quality + Value + LowVol)
1. **Economic rationale.** Diversify across lowly-correlated premia → the most robust long-only equity construction; theoretically the highest risk-adjusted ceiling and the natural end-state of the Phase-2 thesis.
2. **Required data.** Prices (mom, lowvol) **+ fundamentals** (quality, value).
3. **Repo sufficient?** ❌ **No** — inherits the fundamentals blocker (needs both quality *and* value).
4. **Effort.** Scorer trivial (compose existing legs); data = the full fundamentals project (superset of A+B+C).
5. **Bias risk.** **HIGH** (two fundamental legs).
6. **Clean experiment.** The destination *after* B and C pass — all four legs as equal-risk factors on the frozen shell.
7. **Success vs champion.** 4-factor D beats C on Sharpe with no sign-flip — the strongest form of the Phase-2 thesis.
   → **Verdict: highest theoretical ceiling, fully gated behind fundamentals. The destination, not the next step.**

---

## 2. Rankings

Scores are 1–5 (5 = best / easiest). "Engineering effort" scores the **code** only; data-collection
burden is captured in "Data availability" so the two don't double-count.

| Family | Expected alpha | Data availability (repo as-is) | Eng. effort (5=easiest) | Research value | Fundamentals-free? | Non-momentum? |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| **D. Mean Reversion** | 3.5 | **5** | 4 | **4.5** | ✅ | ✅ |
| **H. ERC / risk weighting** | 2.0 | **5** | **5** | 3.5 | ✅ | ✅ (weighting) |
| **E. Trend Following** | 2.0 | **5** | 4 | 2.5 | ✅ | ⚠ momentum cousin |
| **G. Vol Targeting** | 1.5 | **5** | 4.5 | 2.0 | ✅ | ✅ (overlay) |
| F. Sector Rotation | 2.5 | 2 | 2.5 | 3.0 | ✅ | ⚠ sector-momentum |
| J. Dividend Yield | 3.0 | 2 | 3 | 2.5 | ❌ semi | ✅ |
| I. Small Cap | 2.0 | 2 | 3 | 2.0 | ✅ | ✅ |
| **B. Value** | **5** | 1 | 4 | **5** | ❌ | ✅ |
| K. Multi-factor | **5** | 1 | 3.5 | 4.0 | ❌ | ⚠ includes momentum |
| C. Quality + Value | 4.5 | 1 | 3.5 | 4.0 | ❌ | ✅ |
| A. Quality | 4.0 | 1 | 4 | 4.0 | ❌ | ✅ |

**Ranked by expected alpha potential:** B ≈ K > C > A > D > J > F ≈ I ≈ E > H > G.
**Ranked by data availability (repo as-is):** {D, E, G, H} (all 5) > {F, I, J} (2) > {A, B, C, K} (1).
**Ranked by engineering effort (easiest first):** H > G > D ≈ E ≈ A ≈ B > C ≈ K ≈ I ≈ J > F.
**Ranked by research value:** B > D > {A, C, K} > H > F > J > E > {G, I}.

**The tension in one line:** the highest-alpha families (B, K, C, A) are exactly the ones the repo
*cannot* feed without a fundamentals project — while the data-ready families (D, E, G, H) are mostly
risk-shaping or momentum cousins. **Mean Reversion (D) is the only family that scores well on
alpha, data-availability, low effort, *and* research value simultaneously** — the sweet spot for the
stated goal.

---

## 3. Recommended top 3 next experiments

All three are **fundamentals-free and data-sufficient today**, ordered by information-per-effort.
*(Design only — none to be run yet.)*

### 🥇 1. Short-Term Reversal sleeve — Family D
The single genuinely **non-momentum, negatively-correlated, price-only** diversifier of the
champion's offensive leg, and a real Indian anomaly. Run A/B/C/D on a **monthly** shell
(standalone reversal **B**, and champion + reversal sleeve **D**). **Costs are the whole question**
— short-horizon reversal is high-turnover and decays in weeks, so the verdict must be net of the
full Indian cost model and survive split-sample. Highest research value in the fundamentals-free set;
settles a hypothesis Phase-1 explicitly left open.

### 🥈 2. Risk-based weighting on the frozen Top10 — Families H (+ G)
Swap the champion's **equal-weight** for **inverse-vol / ERC / min-variance**, optionally
vol-target-capped at 1× (cash-only-safe). `portfolio/constructor.py` already supports all three, so
this is **near-zero engineering** — it directly tests the champion's last untested degree of freedom.
Expected magnitude is modest, but it is the **cheapest information** available and either tightens the
product or closes the question for good.

### 🥉 3. Standalone Trend-Following / TSMOM as a defensive product — Family E
Build managed-trend as its *own* product and measure its **correlation to the champion in BEAR
regimes** (crisis-alpha), rather than re-running the null overlay. Data-clean and low-effort, but
**honestly flagged** as a momentum cousin with an unfavourable Phase-1 prior — so it is a
portfolio-diversification test, not a new-alpha hunt. Pursue only if #1 and #2 underwhelm.

> **Held above the line, but out of scope by constraint:** **Value (B)** is the highest-expected-alpha
> family overall and the natural successor to the paused Quality track — but it is gated behind the
> **same fundamentals data wall**. It is *not* in the fundamentals-free top-3; it is the prize to unlock
> *if and when* a verified, point-in-time fundamentals source is funded (paid Prowess or an XBRL
> scraper — never survivors-only yfinance/Screener). When that data exists, the priority order
> becomes **B → C → K**, reusing the frozen `quality_store` plumbing.

---

## 4. What this exercise deliberately does **not** do
- No code written, no backtest run, no parameter chosen — design only.
- The frozen champion and the paused Quality framework are untouched (`PHASE2A_STATUS.md`).
- No survivor-biased data source is endorsed for any "data-blocked" family.
- Success bars mirror Phase-1 discipline: **net of cost, split-sample no-sign-flip, DD not >3 pts worse** —
  the same gate that correctly killed Frog-in-the-Pan.
