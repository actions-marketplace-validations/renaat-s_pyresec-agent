#!/usr/bin/env python3
"""
PYRESEC Farcaster API — Neynar signer management + cast publishing.

Flow:
    python scripts/farcaster_signer.py            # create signer, get approval URL
    (approve in Warpcast app, then:)
    python scripts/farcaster_signer.py --status   # check approval status

Environment:
    NEYNAR_API_KEY       — Neynar API key
    FARCASTER_MNEMONIC   — Farcaster custody wallet recovery phrase (12/24 words)
    FARCASTER_SIGNER_UUID — set automatically after signer registration
"""

import os
import json
import time
from typing import Optional
from pathlib import Path

import httpx

NEYNAR_API = "https://api.neynar.com"
STATE_FILE = Path("scripts/.farcaster_state.json")

# EIP-712 domain for SignedKeyRequestValidator (OP Mainnet)
SIGNED_KEY_REQUEST_DOMAIN = {
    "name": "Farcaster SignedKeyRequestValidator",
    "version": "1",
    "chainId": 10,
    "verifyingContract": "0x00000000fc700472606ed4fa22623acf62c60553",
}
SIGNED_KEY_REQUEST_TYPES = {
    "SignedKeyRequest": [
        {"name": "requestFid", "type": "uint256"},
        {"name": "key", "type": "bytes"},
        {"name": "deadline", "type": "uint256"},
    ]
}


def _headers() -> dict:
    key = os.getenv("NEYNAR_API_KEY", "")
    if not key:
        raise RuntimeError("NEYNAR_API_KEY not set")
    return {"x-api-key": key, "Content-Type": "application/json"}


# ==================== STATE ====================

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_signer_uuid() -> str:
    uuid = os.getenv("FARCASTER_SIGNER_UUID", "") or load_state().get("signer_uuid", "")
    if not uuid:
        raise RuntimeError("No signer. Run: python scripts/farcaster_signer.py")
    return uuid


# ==================== SIGNER MANAGEMENT ====================

def create_signer() -> dict:
    """Step 1: create a Neynar-managed signer."""
    resp = httpx.post(f"{NEYNAR_API}/v2/farcaster/signer/", headers=_headers(), json={})
    resp.raise_for_status()
    return resp.json()


def derive_signer_request(mnemonic: str, public_key: str, app_fid: int) -> tuple[int, str]:
    """
    Step 2: EIP-712 sign SignedKeyRequest with the custody wallet.
    Returns (deadline, signature_hex).
    """
    from eth_account import Account
    Account.enable_unaudited_hdwallet_features()

    acct = Account.from_mnemonic(mnemonic)
    deadline = int(time.time()) + 86400  # valid 24h

    signed = Account.sign_typed_data(
        private_key=acct.key,
        domain_data=SIGNED_KEY_REQUEST_DOMAIN,
        message_types=SIGNED_KEY_REQUEST_TYPES,
        message_data={
            "requestFid": app_fid,
            "key": bytes.fromhex(public_key.removeprefix("0x")),
            "deadline": deadline,
        },
    )
    sig_hex = "0x" + bytes(signed.signature).hex()
    return deadline, sig_hex


def register_signed_key(signer_uuid: str, app_fid: int, deadline: int,
                        signature: str, sponsor_neynar: bool = True) -> dict:
    """
    Step 3: register signed key -> returns signer with approval URL.
    """
    body = {
        "signer_uuid": signer_uuid,
        "app_fid": app_fid,
        "deadline": deadline,
        "signature": signature,
    }
    if sponsor_neynar:
        body["sponsor"] = {"sponsored_by_neynar": True}

    resp = httpx.post(f"{NEYNAR_API}/v2/farcaster/signer/signed_key/",
                      headers=_headers(), json=body, timeout=30.0)
    if resp.status_code != 200:
        raise RuntimeError(f"register failed {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def get_signer(signer_uuid: str) -> dict:
    resp = httpx.get(f"{NEYNAR_API}/v2/farcaster/signer/",
                     headers=_headers(), params={"signer_uuid": signer_uuid})
    resp.raise_for_status()
    return resp.json()


def lookup_fid_by_custody(custody_address: str) -> Optional[int]:
    """Find the FID registered to a custody address."""
    resp = httpx.get(f"{NEYNAR_API}/v2/farcaster/user/custody-address/",
                     headers=_headers(), params={"custody_address": custody_address})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    user = resp.json().get("user")
    if isinstance(user, list):
        user = user[0] if user else None
    return user.get("fid") if user else None


def setup_signer(mnemonic: str, sponsor_neynar: bool = True) -> dict:
    """
    Full setup: create signer -> sign request -> register -> approval URL.
    Returns dict with signer_uuid, approval_url, fid, status.
    """
    from eth_account import Account
    Account.enable_unaudited_hdwallet_features()

    acct = Account.from_mnemonic(mnemonic)
    fid = lookup_fid_by_custody(acct.address)
    if not fid:
        raise RuntimeError(
            f"No Farcaster account found for custody address {acct.address}. "
            "Is this the recovery phrase of your Farcaster account?"
        )

    signer = create_signer()
    deadline, sig = derive_signer_request(mnemonic, signer["public_key"], fid)
    registered = register_signed_key(
        signer["signer_uuid"], fid, deadline, sig, sponsor_neynar=sponsor_neynar
    )

    result = {
        "signer_uuid": registered["signer_uuid"],
        "approval_url": registered.get("signer_approval_url", ""),
        "fid": fid,
        "custody_address": acct.address,
        "status": registered.get("status", ""),
    }

    # Persist signer uuid
    state = load_state()
    state.update(result)
    save_state(state)
    return result


# ==================== PUBLISHING ====================

def publish_cast(text: str, parent_hash: Optional[str] = None,
                 parent_fid: Optional[int] = None) -> dict:
    """
    Publish a cast to Farcaster via Neynar.
    If parent_hash/parent_fid given, posts as a reply under that cast.
    Returns dict with success + cast hash.
    """
    body = {"signer_uuid": get_signer_uuid(), "text": text}
    if parent_hash and parent_fid:
        body["parent"] = parent_hash
        body["parent_author_fid"] = parent_fid

    resp = httpx.post(f"{NEYNAR_API}/v2/farcaster/cast", headers=_headers(),
                      json=body, timeout=30.0)
    if resp.status_code != 200:
        raise RuntimeError(f"publish failed {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    cast = data.get("cast", {})
    return {
        "success": data.get("success", False),
        "hash": cast.get("hash", ""),
        "url": _cast_url(cast),
    }


def _cast_url(cast: dict) -> str:
    author = cast.get("author", {}) or {}
    username = author.get("username", "_")
    h = cast.get("hash", "")
    return f"https://farcaster.xyz/{username}/{h[:10]}" if h else ""


def truncate_to_bytes(text: str, max_bytes: int = 1024) -> str:
    """Farcaster cast limit is 1024 UTF-8 bytes."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip() + "…"
