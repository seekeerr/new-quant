"""Convenience launcher: `py dashboard/run.py` (UTF-8 safe, any CWD).

Equivalent to `py -m streamlit run dashboard/app.py`. Useful on Windows where
the bare ₹ sign can trip cp1252; sets PYTHONUTF8 before handing off to Streamlit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent / "app.py"


def main() -> int:
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        from streamlit.web import cli as stcli
    except Exception:
        sys.stderr.write(
            "Streamlit is not installed. Run: py -m pip install -r requirements.txt\n")
        return 1
    sys.argv = ["streamlit", "run", str(APP)]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
