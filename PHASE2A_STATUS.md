# Phase 2A — Momentum + Quality Pilot — STATUS: ⏸ PAUSED

**Decision date:** 2026-06-22
**Decision:** *Stop here for now.* The Quality track is **PAUSED pending verified, point-in-time
fundamentals data.** Nothing is deleted. The framework is frozen and preserved, ready to resume
the instant a bias-free fundamentals panel exists.

---

## Why paused (not failed, not abandoned)

The Phase 2A framework is **built and end-to-end verified** — it is blocked on *data*, not code.
The only honest data sources are paid (CMIE Prowess) or a real NSE/BSE XBRL scraper; yfinance /
Screener are survivors-only and **banned** under the project's survivorship-bias discipline
(see `PHASE1_FINAL_REPORT.md` §5 and the honest-return-ceiling rule). The manual fill
(~485 company-year rows × 5 fields ≈ 2,425 cells) is not justified right now.

Rather than sit idle, research pivots to **Phase 2B — Alternative Strategy Research**
(`PHASE2B_STRATEGY_LANDSCAPE.md`): strategy families that need **no fundamentals** and **no
manual data collection**.

---

## Frozen & preserved (DO NOT DELETE)

| Artifact | Path | State |
|---|---|---|
| **Phase 1 champion** | Mom + LowVol / Top10 / Quarterly / Buffer20 | FROZEN — the bar to beat |
| Phase 1 reports | `PHASE1_FINAL_REPORT.md`, `PHASE1_DECISION.md`, `RESEARCH_TIMELINE.md` | FROZEN |
| Champion result set | `results/pure_momentum/`, `results/momentum_lowvol*/`, `results/concentration_honest/` | FROZEN |
| Quality pilot framework | `quality_store.py`, `run_momentum_quality.py`, `pilot_select_companies.py` | FROZEN — runs at any scope |
| Company sample | `data/cache_fundamentals/pilot_company_list.csv` | PRESERVED |
| Fundamentals template | `data/cache_fundamentals/pilot_fundamentals.csv` | PRESERVED (empty/unverified) |
| Pilot outputs (PENDING) | `results/momentum_quality_pilot/` | PRESERVED |

## Resume condition

When a **verified, point-in-time, survivorship-free** fundamentals panel is available
(≥ 10 quality-covered names per rebalance), fill + verify `pilot_fundamentals.csv` and re-run
`py run_momentum_quality.py`. The data gate then opens and the A/B/C/D verdict is produced
automatically. No code change required.

---

*The champion ships as-is in the meantime: Mom + LowVol / Top10 / Quarterly / Buffer20,
~17.4% net CAGR, Sharpe 0.69, MaxDD −33.5%, cash only.*
