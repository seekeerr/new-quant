# Phase 2 — Institutional Factor Research Platform: Architecture & Implementation Roadmap

**Status:** Architecture and implementation plan only. *No new code, no backtests, no parameter
tuning in this document.*

**Objective.** Transform the current single-strategy momentum backtester into a **reusable,
validated, institutional-grade quant research platform** for Indian equities — one engine that
supports Momentum, Quality, Value, Profitability, Low Volatility, Size, composites, multiple
portfolio constructions, and risk models, with survivorship- and look-ahead-bias designed out at
the foundation. Target: **50+ future factor experiments with zero code duplication.**

This document is the umbrella roadmap. It **incorporates by reference** the already-written
data/identity/corporate-action design in [phase2_fundamental_data_pipeline.md](phase2_fundamental_data_pipeline.md)
(Modules 1, 2, 6 are largely specified there) and extends it into a full platform across all nine
requested modules.

---

## 0. Guiding principles (these govern every module)

1. **One validated engine, many experiments.** A factor is a small, declarative object; the
   engine, portfolio construction, costs, and metrics are shared infrastructure. Adding a factor
   must touch *one* file and *zero* engine code.
2. **Bitemporal everywhere.** Every fact carries *valid-time* (the period it describes) and
   *knowledge-time* (when it became public). Reads at backtest date `T` see only knowledge-time
   ≤ `T`. Nothing is ever overwritten; revisions append a new version. (Detailed in the
   fundamental-data doc, §3–4.)
3. **`company_id` is the only join key.** Never join on ticker. Symbol/ISIN resolve to
   `security_id`/`company_id` through history tables.
4. **Separation of concerns = independence.** Factor engine knows nothing about portfolio
   construction; portfolio engine knows nothing about which factor produced the scores; risk and
   cost engines are pluggable. Each can be tested in isolation.
5. **Validation is a gate, not a report.** A strategy that fails any bias check cannot emit
   results — the API raises, it does not warn-and-continue.
6. **Reproducibility.** Every backtest result is keyed by a config hash + data-snapshot hash, so
   any number in `results/` can be regenerated bit-for-bit.
7. **Migration over rewrite.** Phase-1 code is mostly correct and validated (12-1 momentum, the
   cost model, the metrics). We *refactor it into* the platform's interfaces, we don't throw it
   away. The risky parts (yfinance survivorship, ticker joins, gap-based corp actions) are the
   parts being replaced.

---

## 1. Where we are today → where each piece lands

| Phase-1 asset (today) | Status | Target home in platform |
|---|---|---|
| `data/downloader.py` (yfinance) | Replace as primary; keep as cross-check | `dataplatform/ingest/yfinance_source.py` (validation-only) |
| Bhavcopy spine `data/bhavcopy_cache/`, `build_bhav_panels.py` | **Keep — this is the survivorship-free price spine** | `dataplatform/prices/` |
| `symbol_isin.csv`, `symbols_equity.txt`, `build_equity_universe.py` | Keep, formalize | Module 2 Identity Layer |
| `config.py` (dataclasses) | Keep pattern, split per-engine | `core/config/` + per-experiment config files |
| `strategies/base.py` (`compute_scores` → 0–100 rank) | **Keep contract, generalize** | Module 3 `factors/base.py` |
| `strategies/momentum.py` etc. | Refactor to the new `Factor` interface | `factors/momentum.py`, … |
| `portfolio/ranker.py`, `portfolio/constructor.py` | Refactor; split blending from weighting | Module 4 Portfolio Engine |
| `regime/regime_filter.py` | Keep as optional overlay | Module 5 (risk/regime) |
| `risk/risk_manager.py`, `risk/rebalancer.py` | Keep rebalancer; demote stop-loss (proven to hurt) | Module 5 Risk Engine |
| `costs/cost_model.py` | **Keep — already institutional-grade** | Module 6 Cost Engine (wrap interface) |
| `analytics/metrics.py`, `analytics/visualizer.py` | Keep | Module 8 metrics/plots |
| `backtest/engine.py` | Refactor into composable services | Module 8 `run_backtest()` |
| `backtest/anti_overfit.py` | Keep, extend | Module 7 Validation Suite |
| `docs/phase2_fundamental_data_pipeline.md` | **Authoritative for data/identity/CA** | Modules 1, 2, 6 |

**Key realization:** the existing `BaseStrategy.compute_scores()` already returns a
cross-sectional 0–100 rank per `(date, universe)`. That is *exactly* the `score(time, company_id)`
contract Module 3 asks for — the platform generalizes it from "price panels only" to "any data via
an as-of accessor." Most of Phase 1 is reusable; the work is **decoupling and hardening**, not
reinventing.

---

## 2. Module 1 — Data Layer

**Fully specified in [phase2_fundamental_data_pipeline.md](phase2_fundamental_data_pipeline.md)
§1–4 & §6.** Summary of what the platform consumes, plus the parts that doc doesn't yet cover.

### Datasets and storage format

| Dataset | Source (primary → cross-check) | Store | Update cadence |
|---|---|---|---|
| **Prices** (OHLCV + turnover) | NSE bhavcopy (have) → yfinance | Parquet panels + `prices` table | Daily append |
| **Corporate actions** | NSE/BSE CA feed → Prowess | `corporate_actions` table | Daily |
| **PIT fundamentals** | NSE/BSE XBRL filings → Screener (sanity only) | `financial_reports` + `financial_line_items` (bitemporal) | On announcement |
| **Announcements** | NSE/BSE announcement log | `announcements` table (the PIT backbone) | Daily |
| **Shareholding (SHP)** | NSE/BSE SHP filings | `shareholding` table (promoter/pledge %) | Quarterly |
| **Market cap** | **Computed** = price × PIT shares | Derived view, never stored as truth | Daily |
| **Universe membership** | NSE index constituents + bhavcopy-derived | `index_constituents` (from/to dates) | On rebalance |
| **Benchmarks** | NIFTY 500 TRI CSV (have) + index closes | `benchmarks` table | Daily |

### Storage strategy (decision)

- **Two-tier store.** *System of record* = **SQLite → (later) DuckDB/Postgres** with the
  bitemporal schema. *Compute layer* = **Parquet panels** materialized from the DB for the
  vectorized engine (wide `date × company_id` matrices). The DB guarantees correctness/PIT; the
  panels guarantee speed. Panels are a cache, regenerable from the DB.
- **Why DuckDB as the upgrade path:** zero-server, reads Parquet natively, columnar, handles the
  whole bitemporal store on a laptop, and the DDL from the fundamental-data doc ports almost
  verbatim. Postgres only if this ever becomes multi-user.
- **Update process:** idempotent ingest jobs (`ingest_prices`, `ingest_fundamentals`,
  `ingest_corporate_actions`, `ingest_shp`, `ingest_universe`) each (1) resolve identity, (2)
  append with knowledge-time, (3) run Module-7 structural checks, (4) on pass, invalidate/rebuild
  the affected Parquet panels. Every run logs a `data_snapshot_id` (content hash) for
  reproducibility.

### The one accessor that matters

All factor/backtest reads go through a single PIT accessor (see fundamental-data doc §3):

```
as_of(company_id, T, item) -> value | None     # latest knowledge-time ≤ T − SAFETY_LAG
panel(item, start, end, universe) -> DataFrame  # PIT-correct wide panel for the engine
```

No factor, no portfolio rule, no risk model ever touches raw tables — only these accessors. This
is the single chokepoint where look-ahead bias is prevented and tested.

---

## 3. Module 2 — Identity Layer

**Fully specified in [phase2_fundamental_data_pipeline.md](phase2_fundamental_data_pipeline.md)
§2, §4 (DDL), §5.** Platform-level summary:

- Tables: `companies` (with `primary_cin`), `securities`, `isin_history`, `symbol_history`,
  `mergers`, plus `status` + `delisting_date` on securities. (DDL already written.)
- **Single resolution service:** `resolve(symbol_or_isin, exchange, date) -> security_id`. Every
  ingest job and every universe build calls it; identity is decided in exactly one place. This
  kills the Phase-1 risk of stitching two unrelated companies into one ticker column (e.g. ticker
  reuse) and of breaking series on renames/demergers.
- **No ticker-based joins anywhere in the codebase** — enforced by a Module-7 lint test that
  greps factor/portfolio code for raw symbol joins.
- Handles: ISIN change on face-value split (`isin_history`), rename (`symbol_history`), merger
  (target keeps history, acquirer steps), demerger/spin-off (parent adjusted, child new
  `company_id`), delisting (status + recorded exit value, no silent NaN).

> The platform's internal matrices are keyed by `company_id`, **not** ticker. Tickers exist only
> at the ingest boundary and the human-facing report boundary.

---

## 4. Module 3 — Factor Engine

**Design contract (generalizes the existing `BaseStrategy`):**

```
class Factor(ABC):
    name: str
    requires: list[str]        # data items it needs, e.g. ["close"], ["net_profit","equity"]
    direction: +1 | -1         # +1 = higher raw is better, -1 = invert (e.g. low-vol, P/E)

    def compute_raw(ctx: DataContext, T, universe) -> Series[company_id -> float]
    # base class provides:
    def score(ctx, T, universe) -> Series[company_id -> 0..100]   # winsorize → rank → orient
```

- `score(time, company_id)` is the universal output (0–100 cross-sectional rank), identical to
  today's contract — so the existing engine, ranker, and metrics keep working.
- **Each factor is one independent file**, declares its `requires`, and reads **only** through the
  `as_of`/`panel` accessors. A factor that needs fundamentals cannot accidentally see the future.
- **Shared post-processing in the base class** (so no factor re-implements it): NaN handling,
  winsorization, cross-sectional z-score/percentile, direction orientation, min-coverage guard.

| Factor | `requires` | Definition (PIT) | Reuses |
|---|---|---|---|
| **Momentum** | close | 12-1 total return (skip last month) | `strategies/momentum.py` ✅ |
| **Low Volatility** | close | −1 × trailing vol (or beta) of daily returns | price-only, clean |
| **Size** | close, shares | −1 × log(PIT market cap) | needs share series |
| **Profitability** | gross_profit, assets | Novy-Marx GP/Assets | quality data |
| **Quality** | net_profit, equity, debt, ocf | composite: ROE, leverage⁻¹, accruals⁻¹, OCF/NP | quality data |
| **Value** | price, shares, eps_ttm, book | −1 × (P/E, P/B, EV/EBITDA blend) | hardest (PIT MC) |

- **Composite factors** are themselves `Factor` objects (`CompositeFactor([f1, f2], weights)`),
  so a multi-factor blend is built from single-factor scores with zero new machinery — and is
  validated by the same suite. This is how "50+ experiments, zero duplication" is achieved.
- **Build order (from fundamental-data doc §8):** Momentum + Low Vol + Size first (price-only,
  clean). Then Profitability/Quality (cheapest, most reliable fundamentals → unlocks Mom+Quality,
  the highest-ranked India combo). Value last (needs the PIT share-count/market-cap machinery,
  where bugs hide).

---

## 5. Module 4 — Portfolio Engine

**Independent of the factor engine.** Input = a score `Series[company_id -> 0..100]` + a config.
Output = target weights `Series[company_id -> weight]` summing to ≤ 1.

```
class WeightScheme(ABC):
    def weights(scores, ctx, T, selected) -> Series[company_id -> float]
```

| Scheme | Rule | Reuses |
|---|---|---|
| **Equal Weight** | 1/N over selected | `portfolio/constructor.py` ✅ |
| **Rank Weight** | weight ∝ score (or rank) | new, trivial |
| **Volatility Weight** | weight ∝ 1/σ (inverse-vol) | inverse-vol path exists ✅ |
| **Risk Parity** | equal risk contribution (cov-based) | risk-parity path exists ✅ |

- **Selection vs weighting are separated:** `select_top_stocks(scores, n)` → then a `WeightScheme`.
  Today these are tangled in `ranker.py` + `constructor.py`; the refactor splits them so any factor
  pairs with any weighting.
- Whole-share rounding, min-position, and sector caps are post-weight adjustments (reuse existing
  constructor logic).
- The engine receives a `WeightScheme` instance — swapping equal-weight → risk-parity is a
  one-line config change, no engine edit.

---

## 6. Module 5 — Risk Engine

Two roles: **measure** risk (ex-post analytics) and **constrain** the portfolio (ex-ante limits).

| Capability | Where | Reuses |
|---|---|---|
| Beta, Volatility | analytics (vs benchmark) | `analytics/metrics.py` (has alpha/beta) ✅ |
| Max Drawdown, Tracking Error | analytics | metrics has MaxDD; add TE |
| Sector Exposure | constraint at portfolio build | sector-cap logic exists in ranker ✅ |
| Position Limits | constraint | constructor min/max ✅ |
| Liquidity Limits | constraint (ADTV-based) | `universe/filters.py` liquidity tiers ✅ |
| Regime overlay | optional capital scaling | `regime/regime_filter.py` ✅ |

- **Constraints are pluggable hooks** applied to target weights *before* trade generation:
  `apply_constraints(target, ctx, T) -> adjusted_target`. Each constraint is independent and
  individually toggle-able.
- **Stop-losses / drawdown liquidation are demoted to opt-in.** Phase-1 finding (recorded in
  memory: *"risk management destroyed 16% CAGR"*) means these default **off** and are flagged in
  any result that enables them.
- Risk **measurement** (beta/vol/TE/MaxDD) always runs and is reported regardless of constraints.

---

## 7. Module 6 — Cost Engine

**Already institutional-grade** in `costs/cost_model.py` (STT, stamp, exchange, SEBI, GST,
₹20 brokerage, ₹15.93 DP, slippage by liquidity tier, impact cost). Work = wrap it behind a clean
interface and make every component configurable per experiment.

```
class CostModel:
    def trade_cost(symbol, side, shares, price, liquidity_tier) -> CostBreakdown
```

- All rates live in `CostConfig` (already a dataclass) — each experiment can override.
- `CostBreakdown` itemizes brokerage / STT / exchange / GST / slippage / impact so reports can
  attribute net-vs-gross drag (the project already reports gross + net).
- **Impact cost** scales with position-size-vs-ADTV (exists) — important now that the platform
  spans small/illiquid names in the survivorship-free universe.

No redesign needed — this module is "lift, wrap, expose config."

---

## 8. Module 7 — Validation Suite

**The gate.** Runs at two layers: (a) **data ingest** (structural/temporal, from fundamental-data
doc §7) and (b) **per-experiment** (bias checks) — a strategy that fails cannot report.

| Check | Layer | How |
|---|---|---|
| **Survivorship bias** | data + experiment | Universe drawn from bhavcopy spine incl. delisted; assert delisted names have data to delisting; assert no "current constituents" leak into past dates |
| **Look-ahead bias** | experiment | For sampled `(company, T)`, assert `as_of(T)` never returns `knowledge_time > T`; result invisible before announcement, visible after (extends `backtest/anti_overfit.py`) |
| **ETF / non-equity leakage** | data | ISIN-prefix + instrument-type filter; assert universe contains only EQ. *(Directly addresses the memory finding: ~20% of Mom+LowVol P&L was gold ETFs leaking in)* |
| **Benchmark alignment** | experiment | Assert backtest dates ⊆ benchmark dates; TRI vs price-return consistency; no NaN-filled benchmark stretches |
| **Corporate-action errors** | data | Split/bonus adj-factor sanity (no 10× overnight jumps post-adjust); reconcile adj series vs raw + CA table |
| **Duplicate symbols** | data | Unique `(company_id, period, type, consolidated, version)`; ticker-reuse resolved by date |
| **ISIN changes** | data | `isin_history` continuity; series unbroken across face-value splits |
| **Missing data** | data | Per-(company, period) completeness; flag NULL mandatory items; warmup-coverage guard |
| **Delisting handling** | data | Recorded exit/recovery value, not silent NaN-to-zero (Phase-1 gap) |

- Implemented as `pytest`-style assertions + a `validate(strategy_run) -> ValidationReport`. The
  Research API (`run_backtest`) calls it and **raises on any failure**.
- Extends, doesn't replace, the existing `backtest/anti_overfit.py` (walk-forward + parameter
  stability) — those become the *robustness* tier on top of the *correctness* tier.

---

## 9. Module 8 — Research API

The thin façade that makes experiments a few lines. Every function is pure-ish and composes:

```python
scores  = get_factor_scores(factor, T, universe)            # Module 3
target  = build_portfolio(scores, scheme, n, constraints)   # Modules 4 + 5
result  = run_backtest(factor, scheme, period, costs, ...)  # Module 8 (gated by Module 7)
metrics = compute_metrics(result)                           # analytics/metrics.py ✅
cmp     = compare_benchmark(result, "NIFTY500_TRI")         # data/benchmark.py ✅
plot_results(result, out_dir)                               # analytics/visualizer.py ✅
```

- `run_backtest` orchestrates: build PIT universe → score (Module 3) → select+weight (Module 4) →
  constrain (Module 5) → rebalance trades → apply costs (Module 6) → equity curve. It is the
  refactor of today's `backtest/engine.py` into composable services (factor, scheme, constraints,
  costs all injected, not hard-wired as they are today in `BacktestEngine.__init__`).
- **A full experiment becomes ~5 lines**, e.g.:
  ```python
  run_backtest(factor=CompositeFactor([Momentum(), Quality()], [.5,.5]),
               scheme=EqualWeight(), n=30, period=("2012","2026"),
               costs=CostConfig(), out="results/mom_quality/")
  ```
- Results auto-write to `results/<experiment>/` per the repo's **Results Convention**
  (PNG + CSV + TXT + WALKTHROUGH.md) recorded in memory.

---

## 10. Module 9 — Documentation deliverables

To be generated as the platform is built (this roadmap is the first piece):

- **Architecture diagrams** — module dependency graph (data → identity → factor → portfolio →
  risk → cost → backtest → metrics) and a backtest data-flow sequence diagram (Mermaid, in
  `docs/architecture.md`).
- **Folder structure** — see §11 below (authoritative).
- **Database schema** — already written (fundamental-data doc §4 DDL); to be exported as
  `docs/schema.sql` + an ER diagram.
- **Testing strategy** — see §12.
- **Coding standards** — see §13.

---

## 11. Target folder structure

```
core/
  config/              # per-engine dataclasses (split from today's config.py)
  context.py           # DataContext: holds accessors, hands them to factors/engine
dataplatform/
  db/                  # bitemporal store (SQLite→DuckDB), schema.sql, migrations
  identity/            # resolve(), companies/securities/isin/symbol history  [Module 2]
  ingest/              # ingest_prices, _fundamentals, _corporate_actions, _shp, _universe
  prices/              # bhavcopy spine → adjusted + total-return panels      [keep Phase-1]
  accessors.py         # as_of(), panel()  ← the single PIT chokepoint        [Module 1]
factors/               # one file per factor, all subclass Factor             [Module 3]
  base.py  momentum.py  low_vol.py  size.py  profitability.py  quality.py  value.py  composite.py
portfolio/             # selection + weight schemes                           [Module 4]
  select.py  schemes.py  (equal, rank, vol, risk_parity)
risk/                  # measurement + constraints + regime overlay           [Module 5]
costs/                 # cost_model.py (lifted from Phase-1)                  [Module 6]
validation/            # data checks + bias gate                              [Module 7]
research/              # the public API: get_factor_scores, build_portfolio…  [Module 8]
analytics/             # metrics.py, visualizer.py (kept)
experiments/           # one config-driven script per experiment (thin)
results/               # one folder per experiment (PNG+CSV+TXT+WALKTHROUGH)
docs/                  # architecture.md, schema.sql, this roadmap, fundamental-data doc
tests/                 # pytest suite (unit + bias + golden-master)
```

Phase-1 files migrate into these homes (mapping table in §1). Old root-level `run_*.py` /
`analyze_*.py` scripts are reproduced as thin `experiments/` entries calling the Research API.

---

## 12. Testing strategy

- **Unit tests** per factor/scheme/cost-component: deterministic small fixtures, assert exact
  scores/weights/costs.
- **Bias/contract tests** (Module 7): the look-ahead, survivorship, ETF-leakage, and
  benchmark-alignment assertions run in CI on every change.
- **Golden-master / regression test:** lock the validated pure-12-1-momentum result (the
  ~19–22% CAGR baseline) as a fixture; after the refactor, the platform must **reproduce it within
  tolerance**. This proves the decoupling didn't change behavior — the single most important test
  of the whole migration.
- **Property tests:** weights sum to ≤1, no negative shares, scores ∈ [0,100], `as_of` monotonic
  in `T`.
- **Reproducibility test:** same config + data snapshot → identical equity curve hash.

---

## 13. Coding standards

- Python 3.9, type hints on all public functions, dataclasses for config (extend today's pattern).
- Pure functions where possible; the engine injects dependencies (factor, scheme, costs) rather
  than constructing them — enables isolation testing and the "swap by config" goal.
- **No raw ticker joins; no raw table reads outside accessors** — enforced by lint tests.
- Vectorized pandas/numpy in the compute layer (match existing `utils/indicators.py` style).
- Every experiment writes the Results-Convention bundle; every result carries its config hash.
- Logging per-module (existing `setup_logging` pattern). UTF-8 guard retained (the ₹/cp1252 issue).

---

## 14. Implementation sequence (phased, dependency-ordered)

> Effort is relative sizing, not calendar commitments.

| Phase | Deliverable | Depends on | Notes |
|---|---|---|---|
| **P0 — Skeleton & migration** | Folder structure, `core/config` split, lift cost_model + metrics + visualizer; **golden-master test of current momentum** | — | De-risks everything: prove we can reproduce the baseline before refactoring |
| **P1 — Identity + price spine** | `dataplatform/db` schema, identity tables + `resolve()`, bhavcopy → adjusted + TR panels, `as_of`/`panel` accessors | P0 | Modules 1, 2 (DDL already designed). Replaces ticker joins + gap-based CA |
| **P2 — Factor engine** | `Factor` base + Momentum, Low Vol, Size (price-only, clean) | P1 | Module 3. Refactor existing momentum to new contract; golden-master must still pass |
| **P3 — Portfolio + risk + API** | Weight schemes, selection split, constraints, `run_backtest()` orchestrator, Research API | P2 | Modules 4, 5, 8. Engine becomes composable |
| **P4 — Validation gate** | Bias suite wired into the API (raises on failure); ETF-leakage + survivorship + look-ahead tests | P3 | Module 7. *First experiment that re-validates Mom+LowVol with ETF leakage fixed* |
| **P5 — Fundamentals** | XBRL ingest, `financial_reports`/line items, SHP, share-count step series; Profitability + Quality factors | P1, P4 | Unlocks Mom+Quality (#1 India combo). Value deferred until share-count/MC machinery validated |
| **P6 — Composites & scale** | `CompositeFactor`, Value factor, experiment templates, architecture diagrams + schema.sql export | P5 | Module 9 docs; platform now supports 50+ experiments |

**Critical path & risk callouts**
- **P0 golden-master first.** Do not refactor a validated strategy without a regression lock on
  its numbers. This is the cheapest insurance in the whole plan.
- **P1 before any factor work.** The accessor chokepoint is what makes look-ahead bias
  *structurally impossible* rather than *carefully avoided*.
- **ETF leakage (P4) is a known live bug** (memory: ~20% of Mom+LowVol P&L was gold ETFs). The
  instrument-type filter in identity + the leakage test together close it.
- **Value/market-cap is last on purpose** — it depends on the PIT share-count step series, which
  is exactly where units bugs (₹ vs lakh vs crore) and look-ahead hide.

---

## 15. How this satisfies the final goal

- **Zero duplication:** a new factor = one file subclassing `Factor`; a new weighting = one
  `WeightScheme`; a composite = a list. Engine, costs, metrics, validation are shared and untouched.
- **Survivorship-bias-free by construction:** universe is the bhavcopy spine incl. delisted/merged
  names, keyed by `company_id`; a validation test fails the run if "current constituents" leak.
- **Look-ahead-free by construction:** the single `as_of` accessor gates every read by
  knowledge-time; an assertion test proves the boundary on every change.
- **50+ experiments:** the Research API turns an experiment into ~5 lines, each auto-validated and
  auto-documented under `results/`.

---

### Appendix — open decisions to confirm before P1

1. **DB engine:** stay on SQLite for P1 and adopt **DuckDB** at P5 when fundamentals/joins grow,
   or go DuckDB immediately? (Recommendation: SQLite P1 → DuckDB P5; both run the same DDL.)
2. **Fundamental data source:** budget for **CMIE Prowess** (lowest build risk, PIT + delisted out
   of the box) vs the free NSE/BSE-XBRL self-build (more engineering, same correctness if done
   right)? This gates P5 scope. (See fundamental-data doc §1 for the full cost/coverage matrix.)
3. **Consolidated vs standalone fundamentals:** default to **consolidated** for groups, store both?
   (Recommendation: store both, read consolidated, never mix within a series.)
```
