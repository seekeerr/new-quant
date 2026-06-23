# Phase 2A — Momentum + Quality Pilot — WALKTHROUGH

## What this is
The smallest possible test of one question: **does a Quality factor add validated value
on top of the frozen Phase-1 champion (Momentum + LowVol, Top10 / quarterly / Buffer20)?**
Nothing in the engine, costs, execution, portfolio, turnover, or universe is modified.
Quality enters only as a new drop-in scorer — exactly as every Phase-1 factor did.

## Files
| File | Role |
|---|---|
| `quality_store.py` | `QualityStore` (PIT-gated reader over the fundamentals CSV) + the two new scorers (`make_quality_scorer`, `make_mom_lowvol_quality_scorer`). The only new dependency. |
| `run_momentum_quality.py` | A/B/C/D runner + validation framework + report/chart/CSV generation. |
| `data/cache_fundamentals/pilot_fundamentals.csv` | **The single data source.** Hand-filled, verified, no network. |
| `results/momentum_quality_pilot/` | All outputs. |

## The four variants
- **A. Momentum** — 12-1 momentum (needs no fundamentals).
- **B. Quality** — equal-weight percentile of gross-profitability (GP/Assets) + ROE.
- **C. Mom + LowVol** — the frozen champion, the bar to beat.
- **D. Mom + LowVol + Quality** — champion tilted by Quality
  (weights mom 0.4 / lowvol 0.4 / quality 0.2).

## Quality metrics (derived here, never imported)
- Gross Profitability = `gross_profit / total_assets` (Novy-Marx 2013).
- ROE = `net_profit / total_equity`.

## Point-in-time rule (the look-ahead gate)
A rebalance at date T may only read a report whose **knowledge date ≤ T − 1d**:
- `knowledge_date = filing_date` when the real exchange announcement date is filled;
- else `period_end + 120 days` (a conservative fixed policy, >3 months,
  per PHASE1_DECISION). Reading by `period_end` alone would leak.
Only rows with `verified == TRUE` are ever used (the Phase-1 data-hygiene gate).

## How to populate the data (the only manual step)
Open `data/cache_fundamentals/pilot_fundamentals.csv`. For each company-year row fill:
`gross_profit, total_assets, net_profit, total_equity` (and `filing_date` where known;
`revenue`+`cogs` optional — `gross_profit` is auto-derived as `revenue − cogs` if blank).
Then set `verified = TRUE` on each checked row.

**Workload at current scope: ~485 rows × ~5 fields ≈ ~2425 cells.**
Currently 0 names are quality-covered per rebalance (need ≥ 10 to form
B/D). If that workload is too large, reduce scope first (see below) — the framework is
scope-independent and will run at any N.

### Reduce scope (optional)
`pilot_select_companies.py` builds the company sample; lower its `TARGET_N` (e.g. 15–20)
and re-run it to regenerate a smaller `pilot_company_list.csv` + `pilot_fundamentals.csv`
template, then fill that. Fewer companies = fewer rows to fill, at the cost of thinner
cross-sectional coverage.

## Run
```
py run_momentum_quality.py
```
- **If the CSV is empty/unverified** → prints a PENDING report + a plumbing self-test
  (proves the scorers execute on the frozen engine) and stops. **No backtest, no verdict.**
- **Once enough rows are verified** → runs A/B/C/D, the full validation framework, and
  emits the verdict.

## Validation framework (same discipline as Phase 1)
full period · split sample (first vs second half — the FIP sign-flip test) · rolling 3-yr
windows · name concentration (HHI, avg # names) · sector concentration · contribution
analysis (per-name P&L from the trade log).

## Success criterion (pre-registered)
**D must improve Sharpe and/or CAGR vs champion C, without worsening drawdown by >3 pts,
AND survive split-sample + rolling-window validation (no sign-flip across halves).**
Otherwise **FAIL**, regardless of full-period performance. The report ends with exactly one of:
- `PASS — Quality adds enough validated value to justify building the PIT fundamentals platform.`
- `FAIL — Quality does not justify building the PIT fundamentals platform.`

## Outputs (`results/momentum_quality_pilot/`)
`report.txt` · `report.png` · `comparison.csv` · `factor_breakdown.csv` · `holdings.csv` ·
`contributions.csv` · `coverage_by_rebalance.csv`.
