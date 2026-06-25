"""C5 — Alert Delivery.

A *delivery* mechanism (not a detector): takes alerts produced by the other
controls / freshness checks and dispatches them over the configured channels.

Channels:
  - local : always on. Appends to a dated JSONL outbox + an alert log, prints to
            console, and (best-effort) raises a desktop notification on Windows.
  - email : on only when SMTP env vars are configured (see controls/config.py);
            otherwise email is a logged dry-run so the pipeline never blocks on it.

Categories handled (per the brief): HALT, data freshness, validation, rebalance.
Severity routing: HALT alerts are delivered on every channel and marked urgent;
NOTIFY alerts are delivered locally and batched in email.

`alerts_from_results()` converts ControlResult objects into deliverable alerts so
the preflight can hand its findings straight to `deliver()`.
"""
from __future__ import annotations

import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from typing import Iterable

from . import common, config

# alert categories (free-form but standardized for filtering)
CAT_HALT = "HALT"
CAT_FRESHNESS = "DATA_FRESHNESS"
CAT_VALIDATION = "VALIDATION"
CAT_REBALANCE = "REBALANCE"


def make_alert(severity: str, category: str, title: str, detail: str) -> dict:
    return {"severity": severity, "category": category, "title": title,
            "detail": detail, "ts": common.now_iso()}


def alerts_from_results(results: Iterable[common.ControlResult]) -> list[dict]:
    """Map control outcomes to deliverable alerts (PASS produces none)."""
    out = []
    cat_by_control = {"C1": CAT_VALIDATION, "C2": CAT_FRESHNESS,
                      "C3": CAT_VALIDATION, "C4": CAT_VALIDATION}
    for r in results:
        if r.status == common.PASS:
            continue
        category = CAT_HALT if r.status == common.HALT else \
            cat_by_control.get(r.control, CAT_VALIDATION)
        out.append(make_alert(r.status, category,
                              f"{r.control} {r.name}", r.summary))
    return out


# --- channels ---------------------------------------------------------------

def _deliver_local(alerts: list[dict]) -> dict:
    config.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d")
    outbox = config.ALERT_OUTBOX / f"alerts_{stamp}.jsonl"
    with outbox.open("a", encoding="utf-8") as f:
        for a in alerts:
            f.write(json.dumps(a) + "\n")
    for a in alerts:
        icon = "[HALT]" if a["severity"] == common.HALT else "[notify]"
        print(f"{icon} {a['category']}: {a['title']} — {a['detail']}")
    _try_desktop_notification(alerts)
    return {"channel": "local", "delivered": len(alerts), "outbox": str(outbox)}


def _try_desktop_notification(alerts: list[dict]) -> None:
    """Best-effort Windows toast/balloon. Never raises if unavailable."""
    halts = [a for a in alerts if a["severity"] == common.HALT]
    if not halts:
        return
    try:  # optional dependency; silently skip if absent
        from win10toast import ToastNotifier  # type: ignore
        ToastNotifier().show_toast("Rebalance HALT",
                                   f"{len(halts)} HALT alert(s) — check controls.",
                                   duration=5, threaded=True)
    except Exception:
        pass


def _deliver_email(alerts: list[dict]) -> dict:
    if not alerts:
        return {"channel": "email", "delivered": 0, "mode": "skip-empty"}
    subject = _subject(alerts)
    body = _body(alerts)
    if not config.email_configured():
        # dry-run: persist what *would* be sent so it's testable offline.
        config.ensure_dirs()
        path = config.ALERT_OUTBOX / \
            f"email_dryrun_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path.write_text(f"To: {config.ALERT_TO}\nSubject: {subject}\n\n{body}",
                        encoding="utf-8")
        return {"channel": "email", "delivered": 0, "mode": "dry-run",
                "dryrun_file": str(path)}
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = config.ALERT_FROM
        msg["To"] = ", ".join(config.ALERT_TO)
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASS)
            s.sendmail(config.ALERT_FROM, config.ALERT_TO, msg.as_string())
        return {"channel": "email", "delivered": len(alerts), "mode": "sent"}
    except Exception as e:
        return {"channel": "email", "delivered": 0, "mode": "error", "error": str(e)}


def _subject(alerts: list[dict]) -> str:
    halt = sum(1 for a in alerts if a["severity"] == common.HALT)
    tag = f"[HALT x{halt}] " if halt else "[NOTIFY] "
    return f"{tag}Rebalance controls — {len(alerts)} alert(s)"


def _body(alerts: list[dict]) -> str:
    lines = ["Operational control alerts (frozen champion):", ""]
    for a in sorted(alerts, key=lambda x: 0 if x["severity"] == common.HALT else 1):
        lines.append(f"[{a['severity']}] {a['category']}: {a['title']}")
        lines.append(f"    {a['detail']}  ({a['ts']})")
    return "\n".join(lines)


# --- public API -------------------------------------------------------------

def deliver(alerts: list[dict], channels=("local", "email")) -> common.ControlResult:
    """Dispatch alerts on the chosen channels. Returns a ControlResult whose
    status reflects the *most severe* alert delivered (delivery itself never
    HALTs the pipeline; it reports)."""
    receipts = []
    if "local" in channels:
        receipts.append(_deliver_local(alerts))
    if "email" in channels:
        receipts.append(_deliver_email(alerts))

    halt = sum(1 for a in alerts if a["severity"] == common.HALT)
    notify = sum(1 for a in alerts if a["severity"] == common.NOTIFY)
    details = {"n_alerts": len(alerts), "halt": halt, "notify": notify,
               "receipts": receipts, "email_configured": config.email_configured()}
    if not alerts:
        summary = "No alerts to deliver (all controls clear)."
    else:
        summary = (f"Delivered {len(alerts)} alert(s) [{halt} HALT / {notify} NOTIFY] "
                   f"over {', '.join(channels)}.")
    # C5 reports NOTIFY if it carried HALTs (so the run log shows it), else PASS.
    status = common.NOTIFY if halt else common.PASS
    return common.ControlResult("C5", "Alert Delivery", status, summary, details)


def _cli(argv) -> int:
    demo = [make_alert(common.HALT, CAT_HALT, "C5 self-test",
                       "demo HALT alert from CLI")]
    r = deliver(demo, channels=("local", "email"))
    print(f"[{r.status}] {r.summary}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
