#!/usr/bin/env python3
"""
PYRESEC Farcaster Signer Setup

One-time setup to grant PYRESEC permission to post casts from your Farcaster account.

Usage:
    python scripts/farcaster_signer.py             # create signer + print approval URL
    python scripts/farcaster_signer.py --status    # poll approval status

Requires in .env:
    FARCASTER_MNEMONIC  — your Farcaster recovery phrase (12/24 words)
    NEYNAR_API_KEY      — Neynar API key
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import farcaster_api as fa  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="PYRESEC Farcaster Signer Setup")
    parser.add_argument("--status", action="store_true", help="Check approval status")
    parser.add_argument("--poll", action="store_true", help="Poll until approved")
    args = parser.parse_args()

    if args.status or args.poll:
        state = fa.load_state()
        uuid = state.get("signer_uuid", "")
        if not uuid:
            print("No signer found. Run setup first.")
            sys.exit(1)
        signer = fa.get_signer(uuid)
        print(f"Signer: {uuid}")
        print(f"Status: {signer.get('status')}")
        print(f"FID: {signer.get('fid')}")
        if signer.get("status") == "approved" and signer.get("fid"):
            state["fid"] = signer["fid"]
            state["status"] = "approved"
            fa.save_state(state)
            print("\nAPPROVED — ready to post casts.")
        if args.poll and signer.get("status") != "approved":
            print("Polling every 5s (Ctrl+C to stop)...")
            while signer.get("status") != "approved":
                time.sleep(5)
                signer = fa.get_signer(uuid)
                print(f"  status: {signer.get('status')}")
            state["fid"] = signer.get("fid")
            state["status"] = "approved"
            fa.save_state(state)
            print("\nAPPROVED — ready to post casts.")
        return

    # Setup flow
    mnemonic = os.getenv("FARCASTER_MNEMONIC", "").strip()
    if not mnemonic:
        print("ERROR: FARCASTER_MNEMONIC not set in .env")
        print("Add: FARCASTER_MNEMONIC=\"word1 word2 ... word12\"")
        sys.exit(1)

    print("Creating signer...")
    try:
        result = fa.setup_signer(mnemonic, sponsor_neynar=True)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"\nSigner UUID : {result['signer_uuid']}")
    print(f"FID         : {result['fid']}")
    print(f"Custody     : {result['custody_address']}")
    print(f"Status      : {result['status']}")
    print(f"\nApproval URL:\n{result['approval_url']}")
    print("\nOpen this URL in the Warpcast mobile app and approve the request.")
    print("Then run: python scripts/farcaster_signer.py --poll")


if __name__ == "__main__":
    main()
