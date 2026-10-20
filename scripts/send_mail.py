#!/usr/bin/env python3
"""Send a one-off email AS info@nanoclonesystems.com via Resend.

Usage:
  python scripts/send_mail.py <to@example.com> "Subject" "Plain-text body"
  python scripts/send_mail.py <to@example.com> "Subject" @reply_draft.txt
  python scripts/send_mail.py <to@example.com> "Subject" @draft.txt --from-name "Renaat Sibanda"

The From address comes from PYRESEC_SENDER (info@nanoclonesystems.com).
Body argument starting with @ is read from that file path.
"""
import argparse
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def main() -> None:
    p = argparse.ArgumentParser(description="Send email as info@nanoclonesystems.com")
    p.add_argument("to", help="recipient email address")
    p.add_argument("subject", help="email subject")
    p.add_argument("body", help="plain-text body, or @path/to/file.txt")
    p.add_argument("--from-name", default=os.getenv("PYRESEC_FROM_NAME", "Renaat Sibanda, NanoClone Systems"),
                   help="From display name")
    p.add_argument("--reply-to", default=None, help="Reply-To address (optional)")
    args = p.parse_args()

    key = os.getenv("RESEND_API_KEY", "")
    sender = os.getenv("PYRESEC_SENDER", "info@nanoclonesystems.com")
    if not key:
        sys.exit("RESEND_API_KEY not set in .env")

    body = args.body
    if body.startswith("@"):
        f = Path(body[1:])
        if not f.exists():
            sys.exit(f"body file not found: {f}")
        body = f.read_text(encoding="utf-8")

    payload = {
        "from": f"{args.from_name} <{sender}>",
        "to": [args.to],
        "subject": args.subject,
        "text": body,
    }
    if args.reply_to:
        payload["reply_to"] = [args.reply_to]

    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {key}", "accept": "application/json"},
        json=payload,
        timeout=30.0,
    )
    if r.status_code in (200, 201):
        print(f"OK sent id={r.json().get('id')} from={sender} to={args.to}")
    else:
        print(f"FAILED {r.status_code}: {r.text[:300]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
