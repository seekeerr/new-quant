#!/usr/bin/env python3
"""
Driver / smoke harness for the systematic quant backtest system.

This is a CLI app (no GUI, no server). The "interaction" is running the
backtest entry points from a clean shell, checking exit codes + key output
strings, and confirming the report PNGs were regenerated.

Run from the project root (the dir containing main.py):

    py .claude/skills/run-quant/driver.py smoke      # fast, cache-only, no network (~30s)
    py .claude/skills/run-quant/driver.py backtest   # flagship 12-1 momentum, makes PNGs (~2-4 min)
    py .claude/skills/run-quant/driver.py all         # smoke + backtest

Why a driver and not "just run main.py": main.py prints the Rupee sign (U+20B9)
and CRASHES under Windows' default cp1252 console encoding. This driver forces
UTF-8 in the child process (PYTHONUTF8=1) so every command actually completes.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

# This driver echoes child output that contains the Rupee sign (U+20B9).
# Force our OWN stdout to UTF-8 so we don't crash on Windows' cp1252 console.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[3]   # .../new quant/.claude/skills/run-quant/driver.py -> new quant
PY = sys.executable                            # whatever python launched this driver


def run(args, *, must_contain=(), timeout=600):
    """Run `python <args...>` from ROOT with UTF-8 forced. Returns (ok, stdout)."""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    label = " ".join(args)
    print(f"\n>>> {PY} {label}")
    t0 = time.time()
    p = subprocess.run(
        [PY, *args],
        cwd=str(ROOT), env=env, timeout=timeout,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    dt = time.time() - t0
    tail = "\n".join(p.stdout.splitlines()[-15:])
    print(tail)
    ok = p.returncode == 0
    for needle in must_contain:
        if needle not in p.stdout:
            print(f"!!! MISSING expected output: {needle!r}")
            ok = False
    print(f"--- exit={p.returncode} time={dt:.0f}s {'OK' if ok else 'FAIL'}")
    if p.returncode != 0:
        print("STDERR tail:\n" + "\n".join(p.stderr.splitlines()[-10:]))
    return ok, p.stdout


def smoke():
    """Fast, cache-only checks. No network."""
    ok = True
    ok &= run(["main.py", "costs"], must_contain=["TRANSACTION COST ESTIMATES", "Large-cap"])[0]
    ok &= run(["main.py", "validate-data"], must_contain=["usable"], timeout=180)[0]
    return ok


def backtest():
    """Run the flagship pure 12-1 momentum backtest and confirm PNGs regenerated."""
    out_dir = ROOT / "results" / "pure_momentum"
    expected = [
        "factor_report_5stocks_quarterly.png",
        "factor_report_10stocks_monthly.png",
        "factor_comparison.png",
    ]
    before = {f: (out_dir / f).stat().st_mtime if (out_dir / f).exists() else 0 for f in expected}

    ok, _ = run(
        ["run_pure_momentum.py"],
        must_contain=["FACTOR ISOLATION SUMMARY", "DIAGNOSIS", "CAGR"],
        timeout=600,
    )

    for f in expected:
        path = out_dir / f
        if not path.exists():
            print(f"!!! report not produced: {path}")
            ok = False
        elif path.stat().st_mtime <= before[f]:
            print(f"!!! report not refreshed (stale): {path}")
            ok = False
        else:
            print(f"    fresh report: {path} ({path.stat().st_size//1024} KB)")
    return ok


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    print(f"ROOT = {ROOT}")
    if mode == "smoke":
        ok = smoke()
    elif mode == "backtest":
        ok = backtest()
    elif mode == "all":
        ok = smoke() and backtest()
    else:
        print(f"unknown mode {mode!r}; use: smoke | backtest | all")
        sys.exit(2)
    print("\n==== DRIVER", "PASS" if ok else "FAIL", "====")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
