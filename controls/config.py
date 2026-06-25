"""Control thresholds and locations. Operational only — no strategy parameters.

Anything tunable about *how the controls behave* lives here. Strategy
parameters live in the (frozen) project-root config.py and are never touched.
"""
from __future__ import annotations

import os
from pathlib import Path

# controls/config.py -> controls -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parents[1]

# --- inputs the controls read (read-only) ----------------------------------
PAPER_DIR = PROJECT_ROOT / "paper_trading"
HOLDINGS_FILE = PAPER_DIR / "holdings.csv"
STATE_FILE = PAPER_DIR / "state.json"
BROKER_STATEMENT = PAPER_DIR / "broker_statement.csv"

CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
PRIMARY_CLOSE = CACHE_BHAV / "adj_close.parquet"      # the cache the system uses
RAW_CLOSE = CACHE_BHAV / "raw_close.parquet"          # unadjusted, for CA detection
SYMBOL_ISIN = CACHE_BHAV / "symbol_isin.csv"
DELISTED_FILE = CACHE_BHAV / "symbols_delisted.txt"
ACTIVE_FILE = CACHE_BHAV / "symbols_active.txt"

STRATEGY_CONFIG_FILE = PROJECT_ROOT / "config.py"     # fingerprinted, never imported

# --- outputs the controls write --------------------------------------------
CONTROLS_DIR = PAPER_DIR / "controls"                 # reports + approvals + outbox
APPROVALS_DIR = CONTROLS_DIR / "approvals"
REPORTS_DIR = CONTROLS_DIR / "reports"
ALERT_OUTBOX = CONTROLS_DIR / "alert_outbox"

# --- governance --------------------------------------------------------------
FROZEN_COMMIT = "8f0482f"
FROZEN_TAG = "price-only-final"

# --- C2 data-consistency thresholds -----------------------------------------
PRICE_DIVERGENCE_TOL = 0.005          # 0.5% per-name primary-vs-secondary tolerance
FRESHNESS_MAX_TRADING_DAYS = 5        # cache must be <= 5 trading days old (live)
MIN_SYMBOL_COVERAGE = 0.98            # secondary must cover >=98% of primary symbols

# --- C3 corporate-action detection thresholds -------------------------------
ADJ_FACTOR_STEP_TOL = 0.01            # >1% step in adj/raw factor = an adjustment event
UNEXPLAINED_MOVE_TOL = 0.20           # >20% single-day move flagged for review
RECENT_INACTIVITY_DAYS = 20           # no recent print + delisted => delisting

# --- C5 alert delivery -------------------------------------------------------
# Email is OFF unless all SMTP env vars are present; otherwise dry-run to outbox.
SMTP_HOST = os.environ.get("CONTROLS_SMTP_HOST")
SMTP_PORT = int(os.environ.get("CONTROLS_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("CONTROLS_SMTP_USER")
SMTP_PASS = os.environ.get("CONTROLS_SMTP_PASS")
ALERT_FROM = os.environ.get("CONTROLS_ALERT_FROM", "controls@localhost")
ALERT_TO = [a for a in os.environ.get("CONTROLS_ALERT_TO", "").split(",") if a]


def email_configured() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASS and ALERT_TO)


def ensure_dirs() -> None:
    for d in (CONTROLS_DIR, APPROVALS_DIR, REPORTS_DIR, ALERT_OUTBOX):
        d.mkdir(parents=True, exist_ok=True)
