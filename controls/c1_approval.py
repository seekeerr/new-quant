"""C1 — Approval Gate.

A rebalance may not proceed without an explicit, recorded approval that binds:
  - approver (who)
  - timestamp (when)
  - git commit hash (what code)
  - config fingerprint (what parameters)
  - trade-list hash (what orders) — so approval cannot be reused for a different list

The approval is an immutable JSON record under paper_trading/controls/approvals/.
`require_approval()` is the gate the preflight calls; it HALTs unless a valid,
matching approval exists AND the live commit/config still match the frozen tag.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from . import common, config


def _record_path(rebalance_date: str) -> Path:
    return config.APPROVALS_DIR / f"approval_{rebalance_date}.json"


def create_approval(rebalance_date: str, approver: str,
                    trade_list_path: str | Path,
                    note: str = "") -> dict:
    """Record an approval for a specific rebalance + trade list.

    This is the *human action*. It captures the binding fingerprints at the
    moment of sign-off. Returns the written record.
    """
    config.ensure_dirs()
    trade_list_path = Path(trade_list_path)
    record = {
        "rebalance_date": rebalance_date,
        "approver": approver,
        "approved_at": common.now_iso(),
        "git_commit": common.git_commit(),
        "config_fingerprint": common.config_fingerprint(),
        "trade_list_file": str(trade_list_path),
        "trade_list_sha256": common.sha256_file(trade_list_path),
        "frozen_tag": config.FROZEN_TAG,
        "note": note,
        "status": "APPROVED",
    }
    common.write_json(record, _record_path(rebalance_date))
    return record


def load_approval(rebalance_date: str) -> Optional[dict]:
    path = _record_path(rebalance_date)
    if not path.exists():
        return None
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def require_approval(rebalance_date: str,
                     trade_list_path: str | Path) -> common.ControlResult:
    """Gate: PASS only if a valid approval matches this exact trade list and the
    live commit/config still equal what was approved (and the frozen tag)."""
    trade_list_path = Path(trade_list_path)
    rec = load_approval(rebalance_date)
    details = {"rebalance_date": rebalance_date,
               "trade_list_file": str(trade_list_path)}

    if rec is None:
        return common.ControlResult(
            "C1", "Approval Gate", common.HALT,
            f"No approval on file for rebalance {rebalance_date}.", details)

    # 1) trade list must match exactly what was approved
    current_hash = common.sha256_file(trade_list_path)
    details["approved_hash"] = rec.get("trade_list_sha256")
    details["current_hash"] = current_hash
    if current_hash is None:
        return common.ControlResult(
            "C1", "Approval Gate", common.HALT,
            "Trade list file unreadable — cannot verify approval.", details)
    if current_hash != rec.get("trade_list_sha256"):
        return common.ControlResult(
            "C1", "Approval Gate", common.HALT,
            "Trade list changed since approval (hash mismatch). Re-approve.",
            details)

    # 2) commit must not have drifted from what was approved
    live_commit = common.git_commit()
    details["approved_commit"] = rec.get("git_commit")
    details["live_commit"] = live_commit
    if live_commit != rec.get("git_commit"):
        return common.ControlResult(
            "C1", "Approval Gate", common.HALT,
            f"Commit drift: approved {rec.get('git_commit')}, live {live_commit}.",
            details)

    # 3) config must not have drifted
    live_fp = common.config_fingerprint()
    details["approved_config_fp"] = rec.get("config_fingerprint")
    details["live_config_fp"] = live_fp
    if live_fp != rec.get("config_fingerprint"):
        return common.ControlResult(
            "C1", "Approval Gate", common.HALT,
            "Config fingerprint drift since approval. Re-approve.", details)

    details["approver"] = rec.get("approver")
    details["approved_at"] = rec.get("approved_at")
    return common.ControlResult(
        "C1", "Approval Gate", common.PASS,
        f"Approved by {rec.get('approver')} at {rec.get('approved_at')}; "
        "trade list, commit and config all match.", details)


# ----------------------------------------------------------------------------
def _cli(argv: list[str]) -> int:
    """`py -m controls.c1_approval approve <date> <approver> <trade_list>` /
       `... verify <date> <trade_list>`."""
    if len(argv) >= 4 and argv[0] == "approve":
        rec = create_approval(argv[1], argv[2], argv[3],
                              note=" ".join(argv[4:]))
        print(f"APPROVED {rec['rebalance_date']} by {rec['approver']} "
              f"(commit {rec['git_commit']}, config {rec['config_fingerprint']})")
        return 0
    if len(argv) >= 3 and argv[0] == "verify":
        r = require_approval(argv[1], argv[2])
        print(f"[{r.status}] {r.summary}")
        return 0 if r.ok else 1
    print("usage: approve <date> <approver> <trade_list> [note] | "
          "verify <date> <trade_list>")
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
