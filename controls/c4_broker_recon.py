"""C4 — Broker Reconciliation.

Compares the system's expected holdings (paper_trading/holdings.csv) against the
broker's holdings statement (paper_trading/broker_statement.csv) and reports any
mismatch. In a paper program the "broker statement" is the operator's recorded
demat/positions export; in live it is the actual broker holdings file.

Mismatch classes:
  - missing_at_broker : expected to hold, broker shows nothing (or less)
  - extra_at_broker   : broker holds a name the system does not expect
  - quantity_mismatch : both hold the name but quantities differ

Any mismatch is a HALT — you do not trade a book you cannot reconcile.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from . import common, config

_EXPECTED_COLS = ["symbol", "quantity"]


def _read_holdings(path: Path, label: str) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        if "symbol" not in df.columns or "quantity" not in df.columns:
            return None
        df = df[["symbol", "quantity"]].copy()
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
        return df.groupby("symbol", as_index=False)["quantity"].sum()
    except Exception:
        return None


def reconcile(expected_path: Path = config.HOLDINGS_FILE,
              broker_path: Path = config.BROKER_STATEMENT) -> common.ControlResult:
    expected = _read_holdings(expected_path, "expected")
    broker = _read_holdings(broker_path, "broker")
    details = {"expected_file": str(expected_path), "broker_file": str(broker_path)}

    if expected is None:
        return common.ControlResult("C4", "Broker Reconciliation", common.HALT,
                                    "Expected holdings (holdings.csv) missing/unreadable.",
                                    details)
    if broker is None:
        return common.ControlResult("C4", "Broker Reconciliation", common.HALT,
                                    "Broker statement missing/unreadable — cannot reconcile.",
                                    details)

    merged = expected.merge(broker, on="symbol", how="outer",
                            suffixes=("_expected", "_broker")).fillna(0)
    merged["quantity_expected"] = merged["quantity_expected"].astype(int)
    merged["quantity_broker"] = merged["quantity_broker"].astype(int)
    merged["delta"] = merged["quantity_broker"] - merged["quantity_expected"]

    def classify(r):
        if r["delta"] == 0:
            return "match"
        if r["quantity_expected"] == 0:
            return "extra_at_broker"
        if r["quantity_broker"] == 0:
            return "missing_at_broker"
        return "quantity_mismatch"

    merged["status"] = merged.apply(classify, axis=1)
    report = common.write_report(
        merged.sort_values(["status", "symbol"]), "c4_broker_reconciliation.csv")

    mismatches = merged[merged["status"] != "match"]
    counts = mismatches["status"].value_counts().to_dict()
    details.update({"n_positions_expected": int((expected["quantity"] != 0).sum()),
                    "n_positions_broker": int((broker["quantity"] != 0).sum()),
                    "n_mismatches": int(len(mismatches)),
                    "mismatch_breakdown": counts})

    if len(mismatches) > 0:
        names = ", ".join(mismatches["symbol"].head(10))
        return common.ControlResult("C4", "Broker Reconciliation", common.HALT,
                                    f"{len(mismatches)} holding mismatch(es): {names}"
                                    + (" ..." if len(mismatches) > 10 else "")
                                    + f"  {counts}", details, report)
    return common.ControlResult("C4", "Broker Reconciliation", common.PASS,
                                f"All {len(expected)} positions reconcile with the broker.",
                                details, report)


def _cli(argv) -> int:
    r = reconcile()
    print(f"[{r.status}] {r.summary}")
    print(f"  report: {r.report_path}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
