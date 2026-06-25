"""Single source of truth for every on-disk location the dashboard reads.

Nothing else in the dashboard hard-codes a path. All locations are resolved
relative to the project root so the app works from any working directory.
"""
from __future__ import annotations

from pathlib import Path

# dashboard/utils/paths.py -> dashboard/utils -> dashboard -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# --- New, operator-owned operational state (the data contract) -------------
PAPER_DIR = PROJECT_ROOT / "paper_trading"
STATE_FILE = PAPER_DIR / "state.json"
HOLDINGS_FILE = PAPER_DIR / "holdings.csv"
TARGET_FILE = PAPER_DIR / "target_portfolio.csv"
REBALANCE_FILE = PAPER_DIR / "rebalance_history.csv"
TRADE_LOG_FILE = PAPER_DIR / "trade_log.csv"
EQUITY_FILE = PAPER_DIR / "equity_curve.csv"
AUDIT_DIR = PAPER_DIR / "audit"

# --- Existing artifacts reused read-only -----------------------------------
DATA_DIR = PROJECT_ROOT / "data"
PRICE_CACHE = DATA_DIR / "cache_bhav" / "adj_close.parquet"
BENCHMARK_FILE = DATA_DIR / "nifty500_tri.csv"
RESULTS_DIR = PROJECT_ROOT / "results"
CHAMPION_RESULTS_DIR = RESULTS_DIR / "momentum_lowvol"
LOGS_DIR = PROJECT_ROOT / "logs"

# Root-level audit / governance documents surfaced by the Audit page.
AUDIT_DOCS = [
    "PRODUCTION_READINESS_AUDIT.md",
    "LIVE_TRADING_ARCHITECTURE.md",
    "PAPER_TRADING_PROTOCOL.md",
    "CAPACITY_ANALYSIS.md",
    "PRICE_ONLY_FINAL_CONCLUSION.md",
]


def mtime(path: Path) -> float:
    """Modification time, or 0.0 if the file is absent. Used as a cache key."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
