# strategy_live — isolated tracker for the frozen strategy

Self-contained. Nothing in the main research tree imports from here, and this
package only *reads* from it (`signals.py`, `research_harness.py`, the cached
panels). You can keep experimenting elsewhere without disturbing what is tracked
here.

## Start it

```bash
py -m strategy_live.server            # dashboard at http://127.0.0.1:8765
py -m strategy_live.track             # recompute every 6 hours
py -m strategy_live.track --once      # single run
py -m strategy_live.compute           # snapshot only, no server
```

Run the server and the tracker in two terminals. The server renders whatever the
tracker last wrote; the dashboard's **Recompute** button also triggers a run.

Bound to `127.0.0.1` on purpose — this shows a live book and should not be
reachable from the network.

## The strategy (frozen 2026-09-22)

| | |
|---|---|
| Signals | Momentum 37.5% · LowVol 37.5% · Amihud 25% |
| Lookbacks | mom 252d skip 21d · vol 252d · amihud 60d |
| Portfolio | Top 10, equal weight |
| Entry | rank ≤ 10 |
| Exit | rank > 20 (the buffer) |
| Rebalance | monthly |
| Universe | top 500 NSE by 20d turnover, PIT-filtered |
| Stop loss | none — tested, it reduced returns |

Validated once on data the search never saw (2022-01-01 → 2026-05-30):
**30.08% CAGR, Sharpe 1.32, MaxDD −16.2%**, against a 16.90% champion and a
13.63% index. Capacity verified to ₹50 crore (23.64%).

## Files

| file | role |
|---|---|
| `frozen.py` | the locked parameters + `param_hash()` |
| `compute.py` | builds one dated snapshot (ranks, actions, performance) |
| `track.py` | scheduled recompute + drift log |
| `server.py` | localhost dashboard (stdlib `http.server`) |
| `snapshots/*.json` | one per data date, append-only; `latest.json` is what the server reads |
| `state.json` | the book being tracked |
| `drift_log.jsonl` | one line per run: target book, what changed, why |

## Why the snapshots matter

Each run is written to disk with the date of the data it used. When you later
ask "what did the model actually say on the 23rd", the answer is a file, not a
reconstruction. `drift_log.jsonl` records every change to the target book with
the reason a name was dropped (`rank 34 > buffer 20`, or `left universe`).

## Changing parameters

Don't — not in `FROZEN`. The 30.08% figure describes *these* numbers, validated
on one clean holdout. Editing them in place means you are running something that
has never been tested out of sample, while still looking at the old number on
the dashboard.

To try a variant, add an entry to `VARIANTS` in `frozen.py`. `param_hash()`
changes whenever the parameters do, and `track.py` flags it loudly in the drift
log — so accidental drift is visible rather than silent.

## Reading the dashboard

- **Next rebalance** — the actual orders. SELL first (frees cash), then BUY.
- **Ranking table** — green rail = ranks 1–10 (buy zone), amber rail = 11–20
  (buffer: hold, don't buy), highlighted rows = currently held.
- **Component percentiles** — why a name ranks where it does. A stock can be top
  10 on a strong Amihud/LowVol score with only middling momentum; that is the
  blend working, not a bug.
- Names disappear from the universe when their turnover drops out of the top 500.
  That forces an exit regardless of rank, and shows as `left universe`.

## Honest limits

- Every number here is **backtested**. No order has been placed.
- The −16.2% holdout drawdown is the friendliest figure in the record; the same
  strategy drew −34.6% over 2012–2021. Plan around −35%.
- 2022–2026 was a strong Indian small/mid-cap market, which flatters an
  illiquidity tilt.
- Run it at ₹1 crore or more. At ₹1 lakh, fixed per-order brokerage alone costs
  roughly 2 percentage points a year.
- Signals are computed from the cached bhavcopy panels. Refresh the data before
  trusting a snapshot: if `asof` is stale, so is the book.
