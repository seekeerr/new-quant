"""Rebalance preflight — runs all five controls as a single GO / HALT gate.

This is the operational wrapper the operator runs *before* acting on a generated
trade list. It does NOT generate signals or touch the strategy; it validates the
conditions under which a (separately generated) trade list may be executed.

Sequence (fail-closed — any HALT blocks GO):
  C2 data source  ->  C3 corp actions (watch = holdings)  ->  C4 broker recon
  ->  freshness & rebalance-due checks  ->  C1 approval gate  ->  C5 deliver alerts

Returns GO only if C1–C4 and the freshness gate are all non-HALT.
Writes paper_trading/controls/reports/preflight_<date>.json.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from . import (c1_approval, c2_data_source, c3_corp_actions, c4_broker_recon,
               c5_alerts, common, config)


def _holdings_symbols() -> list[str]:
    try:
        df = pd.read_csv(config.HOLDINGS_FILE)
        return sorted(df["symbol"].dropna().astype(str).tolist())
    except Exception:
        return []


def _freshness_alerts(c2: common.ControlResult, state: dict) -> list[dict]:
    alerts = []
    age = c2.details.get("primary_age_days")
    if isinstance(age, int) and age > config.FRESHNESS_MAX_TRADING_DAYS + 2:
        alerts.append(c5_alerts.make_alert(
            common.HALT, c5_alerts.CAT_FRESHNESS, "Stale price data",
            f"Primary cache last close is {age} days old "
            f"(limit {config.FRESHNESS_MAX_TRADING_DAYS} trading days)."))
    nxt = state.get("next_rebalance")
    if nxt:
        try:
            days = (pd.Timestamp(nxt).normalize()
                    - pd.Timestamp(datetime.now().date())).days
            if days <= 5:
                when = "overdue" if days < 0 else f"in {days} day(s)"
                alerts.append(c5_alerts.make_alert(
                    common.NOTIFY, c5_alerts.CAT_REBALANCE, "Rebalance due",
                    f"Next rebalance {pd.Timestamp(nxt).date()} ({when})."))
        except Exception:
            pass
    return alerts


def run(rebalance_date: str, trade_list_path: str | Path,
        deliver_channels=("local", "email"),
        require_approval: bool = True) -> dict:
    config.ensure_dirs()
    state = common.load_state()
    watch = _holdings_symbols()

    # --- detective controls ---
    c2 = c2_data_source.reconcile()
    c3 = c3_corp_actions.reconcile(watch=watch)
    c4 = c4_broker_recon.reconcile()

    # --- freshness / rebalance-due (category alerts) ---
    fresh_alerts = _freshness_alerts(c2, state)
    fresh_halt = any(a["severity"] == common.HALT for a in fresh_alerts)

    # --- approval gate (last; depends on the trade list under review) ---
    if require_approval:
        c1 = c1_approval.require_approval(rebalance_date, trade_list_path)
    else:
        c1 = common.ControlResult("C1", "Approval Gate", common.NOTIFY,
                                  "Approval check skipped (require_approval=False).", {})

    results = [c2, c3, c4, c1]

    # --- collect & deliver alerts ---
    alerts = c5_alerts.alerts_from_results(results) + fresh_alerts
    c5 = c5_alerts.deliver(alerts, channels=deliver_channels)
    results.append(c5)

    # --- overall verdict (fail-closed) ---
    blocking = [r for r in (c1, c2, c3, c4) if r.status == common.HALT]
    go = (len(blocking) == 0) and not fresh_halt
    verdict = "GO" if go else "HALT"

    summary = {
        "verdict": verdict,
        "rebalance_date": rebalance_date,
        "evaluated_at": common.now_iso(),
        "git_commit": common.git_commit(),
        "config_fingerprint": common.config_fingerprint(),
        "frozen_tag": config.FROZEN_TAG,
        "trade_list": str(trade_list_path),
        "watch_size": len(watch),
        "controls": {r.control: {"name": r.name, "status": r.status,
                                 "summary": r.summary, "report": r.report_path}
                     for r in results},
        "blocking_controls": [r.control for r in blocking] + (["FRESHNESS"] if fresh_halt else []),
        "n_alerts": len(alerts),
    }
    report = config.REPORTS_DIR / f"preflight_{rebalance_date}.json"
    common.write_json(summary, report)
    summary["report_path"] = str(report)
    return summary


def _print(summary: dict) -> None:
    print("=" * 70)
    print(f"  REBALANCE PREFLIGHT — {summary['rebalance_date']}  ->  "
          f"{summary['verdict']}")
    print("=" * 70)
    for cid, c in summary["controls"].items():
        print(f"  [{c['status']:6}] {cid} {c['name']}: {c['summary']}")
    if summary["blocking_controls"]:
        print(f"\n  BLOCKING: {', '.join(summary['blocking_controls'])}")
    print(f"\n  commit {summary['git_commit']} · config {summary['config_fingerprint']}")
    print(f"  report: {summary['report_path']}")


def _cli(argv) -> int:
    if len(argv) < 2:
        print("usage: python -m controls.preflight <rebalance_date> <trade_list> "
              "[--no-approval] [--no-email]")
        return 2
    channels = ["local"] if "--no-email" in argv else ["local", "email"]
    summary = run(argv[0], argv[1],
                  deliver_channels=tuple(channels),
                  require_approval="--no-approval" not in argv)
    _print(summary)
    return 0 if summary["verdict"] == "GO" else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
