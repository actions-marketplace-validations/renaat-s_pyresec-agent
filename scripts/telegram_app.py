#!/usr/bin/env python3
"""
PYRESEC Telegram — approval queue for social replies.

Sends lead reply drafts to your Telegram with Approve/Reject buttons.
On Approve, the reply is posted to Farcaster.

Environment:
    TELEGRAM_BOT_TOKEN  — bot token from @BotFather
    TELEGRAM_CHAT_ID    — your chat ID (auto-detected on first run if empty)
"""

import os
import json
from typing import Optional
from pathlib import Path

import httpx

TELEGRAM_API = "https://api.telegram.org"
CHAT_ID_FILE = Path("scripts/.telegram_chat_id")


def token() -> str:
    t = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not t:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    return t


def configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", ""))


def chat_id() -> str:
    cid = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not cid and CHAT_ID_FILE.exists():
        cid = CHAT_ID_FILE.read_text(encoding="utf-8").strip()
    if not cid:
        cid = detect_chat_id()
    return cid


def detect_chat_id() -> str:
    """Fetch the chat ID from the most recent message sent to the bot."""
    resp = httpx.get(f"{TELEGRAM_API}/bot{token()}/getUpdates", timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    for upd in reversed(data.get("result", [])):
        chat = (upd.get("message") or upd.get("my_chat_member") or {}).get("chat")
        if chat and chat.get("type") == "private":
            cid = str(chat["id"])
            CHAT_ID_FILE.write_text(cid, encoding="utf-8")
            return cid
    raise RuntimeError(
        "No chat found. Send any message to your bot in Telegram first, then retry."
    )


def _post(method: str, payload: dict) -> dict:
    resp = httpx.post(f"{TELEGRAM_API}/bot{token()}/{method}",
                      json=payload, timeout=30.0)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
    return data["result"]


def _get(method: str, params: dict) -> dict:
    resp = httpx.get(f"{TELEGRAM_API}/bot{token()}/{method}",
                     params=params, timeout=60.0)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
    return data["result"]


def approve_keyboard(qid: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"ap:{qid}"},
            {"text": "❌ Reject", "callback_data": f"rj:{qid}"},
        ]]
    }


def send_lead(header: str, body: str, qid: str) -> int:
    """Send a lead reply draft with Approve/Reject buttons. Returns message_id."""
    text = f"{header}\n\n{body}"
    if len(text) > 3900:
        text = text[:3900] + "…"
    msg = _post("sendMessage", {
        "chat_id": chat_id(),
        "text": text,
        "reply_markup": approve_keyboard(qid),
        "disable_web_page_preview": True,
    })
    return msg["message_id"]


def edit_message(message_id: int, text: str, keyboard: Optional[dict] = None):
    payload = {
        "chat_id": chat_id(),
        "message_id": message_id,
        "text": text[:3900],
    }
    if keyboard is not None:
        payload["reply_markup"] = keyboard
    try:
        _post("editMessageText", payload)
    except RuntimeError:
        pass  # message unchanged or too old


def answer_callback(callback_query_id: str, text: str = ""):
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = False
    try:
        _post("answerCallbackQuery", payload)
    except RuntimeError:
        pass


def get_updates(offset: int, timeout: int = 25) -> list[dict]:
    """Long-poll for updates. Returns list of update dicts."""
    try:
        return _get("getUpdates", {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": json.dumps(["callback_query"]),
        })
    except Exception:
        return []


def notify(text: str):
    """Plain notification (no buttons)."""
    try:
        _post("sendMessage", {"chat_id": chat_id(), "text": text[:3900]})
    except RuntimeError:
        pass
