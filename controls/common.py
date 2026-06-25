"""Shared helpers for the operational controls: results, hashing, IO.

Pure stdlib + pandas. No strategy imports.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from . import config

# Severity / status vocabulary (mirrors LIVE_TRADING_ARCHITECTURE HALT/NOTIFY).
PASS = "PASS"
HALT = "HALT"
NOTIFY = "NOTIFY"


@dataclass
class ControlResult:
    """Uniform outcome of any control check."""
    control: str                       # e.g. "C1"
    name: str                          # human label
    status: str                        # PASS | HALT | NOTIFY
    summary: str                       # one-line result
    details: dict = field(default_factory=dict)
    report_path: Optional[str] = None  # CSV/JSON written, if any

    @property
    def ok(self) -> bool:
        return self.status != HALT

    def to_dict(self) -> dict:
        return asdict(self)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=config.PROJECT_ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> Optional[str]:
    try:
        return sha256_bytes(Path(path).read_bytes())
    except Exception:
        return None


def config_fingerprint() -> str:
    """SHA-256 of the *frozen* strategy config file.

    Computed by reading bytes, NOT by importing the module — the control must
    detect config drift without ever executing strategy code.
    """
    fp = sha256_file(config.STRATEGY_CONFIG_FILE)
    return fp[:16] if fp else "unknown"


def write_report(df: pd.DataFrame, filename: str) -> str:
    """Write a report CSV under the controls reports dir; return its path."""
    config.ensure_dirs()
    path = config.REPORTS_DIR / filename
    df.to_csv(path, index=False)
    return str(path)


def write_json(obj: dict, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    return str(path)


def load_parquet(path: Path) -> pd.DataFrame:
    """Read a parquet panel sorted by date; empty frame on any failure."""
    try:
        return pd.read_parquet(path).sort_index()
    except Exception:
        return pd.DataFrame()


def load_state() -> dict:
    try:
        return json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
