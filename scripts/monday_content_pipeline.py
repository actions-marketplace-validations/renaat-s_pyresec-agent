#!/usr/bin/env python3
"""PYRESEC Monday Content Pipeline.

Runs every Monday at 11:00 UTC and populates the Social Deck / Telegram
approval queue with two fresh cards:

  1. A Zero-Day Breakdown case study from the Shadow Audit engine.
  2. A Build-in-Public Code Drop from the live operational stats.

This is the scheduled content construct referenced in the build-in-public
materials; it keeps the Social Deck fed without manual intervention.

Usage:
    python scripts/monday_content_pipeline.py
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def run(cmd: list[str], label: str) -> bool:
    print(f"\n[monday] {'=' * 60}")
    print(f"[monday] {label}")
    print(f"[monday] {'=' * 60}")
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            check=False,
            stdout=sys.stdout,
            stderr=subprocess.STDOUT,
        )
        ok = result.returncode == 0
        if not ok:
            print(f"[monday] WARNING: {label} exited with code {result.returncode}")
        return ok
    except Exception as exc:
        print(f"[monday] ERROR running {label}: {exc}")
        return False


def main():
    print(f"[monday] PYRESEC Monday Content Pipeline — {datetime.now(timezone.utc).isoformat()} UTC")

    ok1 = run([PYTHON, "scripts/shadow_audit.py", "--limit", "1"], "Shadow Audit — case study generation")
    ok2 = run([PYTHON, "scripts/social_pipeline.py"], "Social Pipeline — queue case-study card")
    ok3 = run([PYTHON, "scripts/buildinpublic_engine.py"], "Build in Public — queue code-drop card")

    print(f"\n[monday] {'=' * 60}")
    print(f"[monday] Summary")
    print(f"[monday] {'=' * 60}")
    print(f"[monday] Shadow Audit:        {'OK' if ok1 else 'FAIL'}")
    print(f"[monday] Social Pipeline:     {'OK' if ok2 else 'FAIL'}")
    print(f"[monday] Build in Public:     {'OK' if ok3 else 'FAIL'}")
    sys.exit(0 if (ok1 and ok2 and ok3) else 1)


if __name__ == "__main__":
    main()
