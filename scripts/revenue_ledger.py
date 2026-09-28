"""PYRESEC Revenue Ledger — per-model pipeline and closed-revenue tracking.

Stages:
  proof_sent   a proof-led first contact went out (pipeline, not $ yet)
  proposal     payment link / proposal delivered to the lead
  closed_won   money received (counts toward revenue)
  closed_lost  dead lead

CLI:
  python scripts/revenue_ledger.py summary
  python scripts/revenue_ledger.py record remediation proposal 750 --lead acme-dao
  python scripts/revenue_ledger.py record monitoring closed_won 495 --lead acme-dao
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

LEDGER_FILE = Path(__file__).resolve().parent / ".revenue_ledger.json"
MODELS = ("remediation", "monitoring", "microscan")  # microscan = legacy cents tiers
STAGES = ("proof_sent", "proposal", "closed_won", "closed_lost")


def _load() -> dict:
    if LEDGER_FILE.exists():
        try:
            return json.loads(LEDGER_FILE.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            pass
    return {"events": []}


def _save(data: dict):
    LEDGER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def record(model: str, stage: str, amount: float = 0.0, lead: str = "",
           channel: str = "email", note: str = "") -> dict:
    if model not in MODELS:
        raise ValueError(f"model must be one of {MODELS}")
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    data = _load()
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "stage": stage,
        "amount": float(amount),
        "lead": lead,
        "channel": channel,
        "note": note,
    }
    data["events"].append(event)
    _save(data)
    return event


def summary() -> dict:
    data = _load()
    out = {"revenue_by_model": {}, "pipeline_by_model": {}, "counts_by_stage": {}}
    for m in MODELS:
        out["revenue_by_model"][m] = 0.0
        out["pipeline_by_model"][m] = {"proof_sent": 0, "proposal": 0}
    for ev in data["events"]:
        m, st, amt = ev.get("model"), ev.get("stage"), ev.get("amount", 0.0)
        if m not in MODELS:
            continue
        out["counts_by_stage"][st] = out["counts_by_stage"].get(st, 0) + 1
        if st == "closed_won":
            out["revenue_by_model"][m] += amt
        elif st in out["pipeline_by_model"][m]:
            out["pipeline_by_model"][m][st] += 1
    out["total_revenue"] = round(sum(out["revenue_by_model"].values()), 2)
    out["events"] = len(data["events"])
    return out


def print_summary():
    s = summary()
    print("=" * 54)
    print("  PYRESEC REVENUE LEDGER")
    print("=" * 54)
    print(f"  Total closed revenue : ${s['total_revenue']:.2f}")
    for m in MODELS:
        rev = s["revenue_by_model"][m]
        pipe = s["pipeline_by_model"][m]
        print(f"  {m:<12} closed: ${rev:>8.2f}   "
              f"proofs out: {pipe['proof_sent']:>3}   proposals: {pipe['proposal']:>3}")
    if s["counts_by_stage"]:
        print("-" * 54)
        for st, n in sorted(s["counts_by_stage"].items()):
            print(f"  {st:<14} {n}")
    print("=" * 54)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="PYRESEC Revenue Ledger")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("summary")
    rec = sub.add_parser("record")
    rec.add_argument("model", choices=MODELS)
    rec.add_argument("stage", choices=STAGES)
    rec.add_argument("amount", type=float, nargs="?", default=0.0)
    rec.add_argument("--lead", default="")
    rec.add_argument("--channel", default="email")
    rec.add_argument("--note", default="")
    args = p.parse_args()

    if args.cmd == "record":
        ev = record(args.model, args.stage, args.amount, args.lead, args.channel, args.note)
        print(f"recorded: {ev['model']}/{ev['stage']} ${ev['amount']} ({ev['lead']})")
    else:
        print_summary()
