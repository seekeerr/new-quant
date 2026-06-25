"""
AUTOMATIC DAILY MARKET-DATA MAINTENANCE  (Phase 3L — Part B).

Keeps the bhavcopy cache and the wide panels current WITHOUT manual prompts.
It is a *data-only* job: it never generates portfolios, never rebalances, never
runs paper trading, never executes trades. The frozen quarterly strategy stays
manually initiated.

What it does, every run (idempotent):
  1. Determine the latest expected NSE trading day (IST-aware, holiday-aware).
  2. Download every missing trading day from the cache's last date to that day,
     reusing the repo's existing, validated download primitives.
  3. CLASSIFY each missing day precisely — published / holiday / publication-delay
     / network-failure / NSE-blocking — and retry transient failures with
     exponential backoff. It NEVER silently marks a recent trading day a holiday.
  4. Rebuild the wide RAW panels (build_bhav_panels.py) ONLY when new data exists.
  5. Re-adjust panels for splits/bonuses (adjust_bhav.py) when new data exists.
  6. Validate the cache: freshness gate + C2 consistency (read-only, reuses the
     frozen operational controls — does not modify them).
  7. Update freshness state and emit a health report (JSON + Markdown).

Fail-safe contract:
  * Never silently continues on stale data.
  * Freshness > FRESHNESS_HALT_TRADING_DAYS (5) trading days  ->  status HALT.
  * Any unresolved recent trading day  ->  status WARNING (never auto-holiday).

Run:
  py pipeline/auto_data_update.py                 # normal scheduled run
  py pipeline/auto_data_update.py --dry-run       # classify only, no writes/rebuild
  py pipeline/auto_data_update.py --max-retries 5 --base-delay 60
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import time
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse the repo's existing, validated download primitives (no duplication).
# Importing only binds module-level constants/functions; no network call fires.
from build_bhavcopy_cache import (  # noqa: E402
    _make_opener, _url, fetch_day, CACHE, EMPTY, load_holidays,
)

# ── locations ─────────────────────────────────────────────────────────────
CACHE_BHAV = PROJECT_ROOT / "data" / "cache_bhav"
PANELS = {
    "adj_close":    CACHE_BHAV / "adj_close.parquet",
    "raw_close":    CACHE_BHAV / "raw_close.parquet",
    "raw_volume":   CACHE_BHAV / "raw_volume.parquet",
    "raw_turnover": CACHE_BHAV / "raw_turnover.parquet",
}
HEALTH_DIR = PROJECT_ROOT / "pipeline" / "health"
LOG_DIR = PROJECT_ROOT / "pipeline" / "logs"
FRESHNESS_FILE = HEALTH_DIR / "freshness.json"
# Operator-maintained authoritative holiday calendar (optional). If present, a
# 404 on a date listed here is a CONFIRMED holiday; otherwise recent 404s are
# treated as unconfirmed (WARNING), never auto-written as holidays.
KNOWN_HOLIDAYS_FILE = PROJECT_ROOT / "data" / "nse_holidays_known.txt"

# ── policy thresholds (operational only — no strategy params) ──────────────
FRESHNESS_HALT_TRADING_DAYS = 5      # > this many trading days stale  -> HALT
IST = timezone(timedelta(hours=5, minutes=30))
PUBLISH_CUTOFF_HOUR_IST = 18         # NSE bhavcopy is normally up by ~18:00 IST
RECENT_DAYS_NO_AUTO_HOLIDAY = 10     # never auto-classify a 404 in this window as holiday

# classification constants
PUBLISHED = "published"
HOLIDAY_CONFIRMED = "holiday_confirmed"
PENDING_PUBLICATION = "pending_publication"     # today, before cutoff
PUBLICATION_DELAY = "publication_delay"          # trading day, 404 after cutoff (unconfirmed)
HOLIDAY_UNCONFIRMED = "holiday_or_gap_unconfirmed"
NETWORK_FAILURE = "network_failure"
NSE_BLOCKING = "nse_blocking"


def now_ist() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST)


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


# ── calendar helpers ───────────────────────────────────────────────────────
def known_holidays() -> set[str]:
    """Confirmed non-trading dates: past 404 markers + operator calendar."""
    hol = set(load_holidays())
    if KNOWN_HOLIDAYS_FILE.exists():
        hol |= {ln.strip() for ln in KNOWN_HOLIDAYS_FILE.read_text().split()
                if ln.strip()}
    return hol


def expected_trading_days(start: date, end: date, holidays: set[str]) -> list[date]:
    """Weekdays in [start, end] that are not confirmed holidays."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in holidays:
            out.append(d)
        d += timedelta(days=1)
    return out


def latest_expected_trading_day(today_ist: datetime, holidays: set[str]) -> date:
    """Most recent trading day whose bhavcopy should already be published.

    Today counts only if it is a weekday, not a holiday, AND we are past the
    publication cutoff; otherwise step back to the previous trading day.
    """
    d = today_ist.date()
    before_cutoff = today_ist.hour < PUBLISH_CUTOFF_HOUR_IST
    while True:
        is_trading = d.weekday() < 5 and d.isoformat() not in holidays
        if is_trading and not (d == today_ist.date() and before_cutoff):
            return d
        d -= timedelta(days=1)


def cache_last_date() -> date | None:
    files = sorted(CACHE.glob("*.parquet"))
    return pd.Timestamp(files[-1].stem).date() if files else None


# ── download with classification + exponential backoff ─────────────────────
def attempt_day(op, d: date, max_retries: int, base_delay: float,
                now: datetime) -> tuple[str, int, str]:
    """Try to fetch one day. Returns (classification, retries_used, note).

    On success the day's parquet is written to the cache. 404 / network / block
    are discriminated; transient failures get exponential backoff. A 404 is NEVER
    auto-written to the holiday file here — recent unconfirmed 404s stay WARNINGs.
    """
    is_today = d == now.date()
    before_cutoff = now.hour < PUBLISH_CUTOFF_HOUR_IST
    retries = 0
    last_note = ""
    while True:
        try:
            df = fetch_day(op, d)            # None on 404; raises on other errors
        except urllib.error.HTTPError as e:
            if e.code in (403, 401, 429):
                last_note = f"HTTP {e.code} (NSE blocking/throttle)"
                cls = NSE_BLOCKING
            else:
                last_note = f"HTTP {e.code}"
                cls = NETWORK_FAILURE
        except Exception as e:              # timeout / conn reset / DNS / etc.
            last_note = repr(e)[:100]
            cls = NETWORK_FAILURE
        else:
            if df is not None:
                df.to_parquet(CACHE / f"{d.isoformat()}.parquet")
                return PUBLISHED, retries, f"{len(df)} rows"
            # df is None -> a clean 404 (no file for this date)
            if d.isoformat() in known_holidays():
                return HOLIDAY_CONFIRMED, retries, "404 on confirmed holiday"
            if is_today and before_cutoff:
                return PENDING_PUBLICATION, retries, "today, before publish cutoff"
            # unconfirmed 404 on a weekday -> backoff & retry (publication delay)
            cls = PUBLICATION_DELAY
            last_note = "404 (not yet published / possible holiday)"

        if retries >= max_retries:
            # Exhausted retries. Recent days are never auto-marked holiday.
            if cls == PUBLICATION_DELAY:
                age = (now.date() - d).days
                if age > RECENT_DAYS_NO_AUTO_HOLIDAY:
                    return HOLIDAY_UNCONFIRMED, retries, last_note
                return PUBLICATION_DELAY, retries, last_note
            return cls, retries, last_note

        retries += 1
        delay = base_delay * (2 ** (retries - 1))
        time.sleep(delay)


# ── pipeline stages (subprocess; only on new data) ─────────────────────────
def run_script(script: str, log_lines: list[str]) -> tuple[bool, str]:
    log_lines.append(f"  $ py {script}")
    try:
        p = subprocess.run([sys.executable, str(PROJECT_ROOT / script)],
                           cwd=PROJECT_ROOT, capture_output=True, text=True,
                           timeout=1800)
        tail = "\n".join((p.stdout or "").strip().splitlines()[-6:])
        log_lines.append(tail)
        if p.returncode != 0:
            log_lines.append(f"  !! {script} exit {p.returncode}: "
                             f"{(p.stderr or '')[-300:]}")
            return False, tail
        return True, tail
    except Exception as e:
        log_lines.append(f"  !! {script} raised {repr(e)[:200]}")
        return False, repr(e)[:200]


def panel_status() -> dict:
    out = {}
    for name, path in PANELS.items():
        try:
            idx = pd.read_parquet(path, columns=[]).index
            out[name] = str(pd.Timestamp(idx[-1]).date())
        except Exception:
            try:
                p = pd.read_parquet(path)
                out[name] = str(pd.Timestamp(p.index[-1]).date())
            except Exception:
                out[name] = "MISSING"
    return out


def validate_cache(holidays: set[str], now: datetime) -> dict:
    """Freshness (trading-day) gate + C2 consistency. Read-only."""
    last = None
    try:
        idx = pd.read_parquet(PANELS["adj_close"]).index
        last = pd.Timestamp(idx[-1]).date()
    except Exception:
        return {"ok": False, "error": "adj_close panel unreadable",
                "freshness_trading_days": None}

    latest_expected = latest_expected_trading_day(now, holidays)
    td = expected_trading_days(last + timedelta(days=1), latest_expected, holidays)
    freshness_td = len(td)
    calendar_days = (now.date() - last).days

    c2_status, c2_summary = "SKIPPED", "controls import failed"
    try:
        from controls import c2_data_source
        r = c2_data_source.reconcile()
        c2_status, c2_summary = r.status, r.summary
    except Exception as e:
        c2_summary = repr(e)[:160]

    return {
        "panel_last_date": str(last),
        "latest_expected_trading_day": str(latest_expected),
        "freshness_trading_days": freshness_td,
        "freshness_calendar_days": calendar_days,
        "freshness_ok": freshness_td <= FRESHNESS_HALT_TRADING_DAYS,
        "c2_status": c2_status,
        "c2_summary": c2_summary,
    }


# ── health report ───────────────────────────────────────────────────────────
def write_health(report: dict) -> tuple[Path, Path]:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = report["run_at_ist"][:10].replace("-", "")
    jpath = HEALTH_DIR / f"health_{stamp}.json"
    jpath.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    v = report["validation"]
    cls = report["classification_counts"]
    lines = [
        f"# Market-Data Health Report — {report['run_at_ist']}",
        "",
        f"**Overall status:** `{report['status']}`",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Latest trading date (cache) | {v.get('panel_last_date')} |",
        f"| Latest expected trading day | {v.get('latest_expected_trading_day')} |",
        f"| Freshness (trading days) | {v.get('freshness_trading_days')} "
        f"(limit {FRESHNESS_HALT_TRADING_DAYS}) |",
        f"| Freshness (calendar days) | {v.get('freshness_calendar_days')} |",
        f"| Freshness gate | {'PASS' if v.get('freshness_ok') else 'HALT'} |",
        f"| C2 consistency | {v.get('c2_status')} — {v.get('c2_summary')} |",
        f"| New days downloaded | {report['downloaded_count']} |",
        f"| Holidays in window | {cls.get(HOLIDAY_CONFIRMED, 0)} confirmed |",
        f"| Retries used | {report['total_retries']} |",
        f"| Failures / warnings | {report['warning_count']} |",
        f"| Panels rebuilt | {report['panels_rebuilt']} |",
        f"| git commit | {report['git_commit']} |",
        "",
        "## Downloaded days",
        "",
        ("\n".join(f"- {d} ({n})" for d, n in report["downloaded"]) or "_none_"),
        "",
        "## Classification breakdown",
        "",
        ("\n".join(f"- {k}: {n}" for k, n in cls.items()) or "_none_"),
        "",
        "## Panel end-dates",
        "",
        "\n".join(f"- {k}: {d}" for k, d in report["panel_status"].items()),
        "",
        "## Warnings / failures",
        "",
        ("\n".join(f"- **{w['kind']}** {w['date']}: {w['note']}"
                   for w in report["warnings"]) or "_none_"),
        "",
        "## Recovery",
        "",
        "If status is HALT or WARNING persists, see AUTOMATIC_DATA_PIPELINE.md "
        "(Recovery procedure). Data is never advanced past a failed validation.",
    ]
    mpath = HEALTH_DIR / "latest_health.md"
    mpath.write_text("\n".join(lines), encoding="utf-8")
    return jpath, mpath


# ── orchestrator ─────────────────────────────────────────────────────────────
def run(dry_run: bool = False, max_retries: int = 3, base_delay: float = 30.0) -> dict:
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = now_ist()
    log: list[str] = [f"AUTO DATA UPDATE @ {now.isoformat()} (IST)  dry_run={dry_run}"]
    holidays = known_holidays()

    last = cache_last_date()
    latest_expected = latest_expected_trading_day(now, holidays)
    log.append(f"cache last={last}  latest_expected={latest_expected}")

    downloaded: list[tuple[str, str]] = []
    warnings: list[dict] = []
    cls_counts: dict[str, int] = {}
    total_retries = 0

    if last is None:
        warnings.append({"kind": "EMPTY_CACHE", "date": "", "note":
                         "bhavcopy cache is empty — run a full historical build first"})
    else:
        missing = expected_trading_days(last + timedelta(days=1), latest_expected, holidays)
        log.append(f"missing expected trading days: {len(missing)}")
        if missing and not dry_run:
            op = _make_opener()
            for d in missing:
                cls, retries, note = attempt_day(op, d, max_retries, base_delay, now)
                cls_counts[cls] = cls_counts.get(cls, 0) + 1
                total_retries += retries
                log.append(f"  {d}  {cls}  retries={retries}  {note}")
                if cls == PUBLISHED:
                    downloaded.append((d.isoformat(), note))
                elif cls in (PUBLICATION_DELAY, NETWORK_FAILURE, NSE_BLOCKING,
                             HOLIDAY_UNCONFIRMED, PENDING_PUBLICATION):
                    if cls != PENDING_PUBLICATION:
                        warnings.append({"kind": cls, "date": d.isoformat(), "note": note})
        elif missing and dry_run:
            for d in missing:
                cls_counts["(dry-run-missing)"] = cls_counts.get("(dry-run-missing)", 0) + 1
                log.append(f"  {d}  would-attempt (dry-run)")

    # rebuild panels ONLY when new data landed
    panels_rebuilt = False
    if downloaded and not dry_run:
        log.append("new data -> rebuilding panels")
        ok1, _ = run_script("build_bhav_panels.py", log)
        ok2, _ = run_script("adjust_bhav.py", log)
        panels_rebuilt = ok1 and ok2
        if not panels_rebuilt:
            warnings.append({"kind": "PANEL_REBUILD_FAILED", "date": "",
                             "note": "panel/adjust step returned non-zero"})
    else:
        log.append("no new data -> panels not rebuilt (up to date or dry-run)")

    validation = validate_cache(holidays, now)

    # update freshness state
    if not dry_run:
        FRESHNESS_FILE.write_text(json.dumps({
            "computed_at_ist": now.isoformat(),
            "panel_last_date": validation.get("panel_last_date"),
            "freshness_trading_days": validation.get("freshness_trading_days"),
            "freshness_ok": validation.get("freshness_ok"),
        }, indent=2), encoding="utf-8")

    # overall status (fail-safe)
    if not validation.get("freshness_ok", False) or validation.get("c2_status") == "HALT":
        status = "HALT"
    elif warnings:
        status = "WARNING"
    else:
        status = "OK"

    report = {
        "status": status,
        "run_at_ist": now.isoformat(),
        "git_commit": git_commit(),
        "dry_run": dry_run,
        "cache_last_before": str(last),
        "latest_expected_trading_day": str(latest_expected),
        "downloaded": downloaded,
        "downloaded_count": len(downloaded),
        "classification_counts": cls_counts,
        "total_retries": total_retries,
        "warnings": warnings,
        "warning_count": len(warnings),
        "panels_rebuilt": panels_rebuilt,
        "panel_status": panel_status(),
        "validation": validation,
    }

    log.append(f"STATUS={status}  downloaded={len(downloaded)}  warnings={len(warnings)}")
    (LOG_DIR / f"run_{now.strftime('%Y%m%d')}.log").write_text(
        "\n".join(log), encoding="utf-8")

    if not dry_run:
        jpath, mpath = write_health(report)
        report["health_json"] = str(jpath)
        report["health_md"] = str(mpath)

    return report


def main():
    ap = argparse.ArgumentParser(description="Automatic daily NSE market-data maintenance.")
    ap.add_argument("--dry-run", action="store_true",
                    help="classify the missing window; no downloads, rebuilds, or writes")
    ap.add_argument("--max-retries", type=int, default=3)
    ap.add_argument("--base-delay", type=float, default=30.0,
                    help="seconds; exponential backoff base for transient failures")
    args = ap.parse_args()

    report = run(dry_run=args.dry_run, max_retries=args.max_retries,
                 base_delay=args.base_delay)
    print("=" * 72)
    print(f"  AUTO DATA UPDATE  ->  {report['status']}")
    print("=" * 72)
    v = report["validation"]
    print(f"  cache last date     : {v.get('panel_last_date')}")
    print(f"  latest expected day : {report['latest_expected_trading_day']}")
    print(f"  freshness (td/cal)  : {v.get('freshness_trading_days')} / "
          f"{v.get('freshness_calendar_days')}  (limit {FRESHNESS_HALT_TRADING_DAYS} td)")
    print(f"  downloaded          : {report['downloaded_count']}")
    print(f"  panels rebuilt      : {report['panels_rebuilt']}")
    print(f"  C2 consistency      : {v.get('c2_status')} — {v.get('c2_summary')}")
    print(f"  warnings            : {report['warning_count']}")
    if not report["dry_run"]:
        print(f"  health report       : {report.get('health_md')}")
    # exit code: 0 OK, 1 WARNING, 2 HALT (for the scheduler to act on)
    return {"OK": 0, "WARNING": 1, "HALT": 2}.get(report["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
