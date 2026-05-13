"""Normalize WildChat and ShareGPT-style rows into a shared conversation schema."""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any, Optional


ROLE_ALIASES = {
    "human": "user",
    "user": "user",
    "prompter": "user",
    "gpt": "assistant",
    "assistant": "assistant",
    "chatgpt": "assistant",
    "bot": "assistant",
}


def normalize_role(raw_role: Any) -> Optional[str]:
    if raw_role is None:
        return None
    role = str(raw_role).strip().lower()
    return ROLE_ALIASES.get(role)


def clean_text(text: Any) -> str:
    if text is None:
        return ""
    cleaned = unescape(str(text))
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</p\s*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_turn(raw_turn: Any) -> Optional[dict[str, str]]:
    if isinstance(raw_turn, str):
        try:
            raw_turn = json.loads(raw_turn)
        except json.JSONDecodeError:
            return None

    if not isinstance(raw_turn, dict):
        return None

    role = normalize_role(
        raw_turn.get("role")
        or raw_turn.get("from")
        or raw_turn.get("speaker")
        or raw_turn.get("author")
    )
    content = clean_text(
        raw_turn.get("content")
        or raw_turn.get("value")
        or raw_turn.get("text")
        or raw_turn.get("message")
    )

    if role not in {"user", "assistant"} or not content:
        return None
    return {"role": role, "content": content}


def extract_turns(row: dict[str, Any]) -> list[dict[str, str]]:
    for key in ("conversation", "conversations", "messages", "turns", "chat"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = None
        if isinstance(value, list):
            turns = [turn for item in value if (turn := normalize_turn(item))]
            if turns:
                return merge_adjacent_same_role(turns)

    # Fallback for prompt/response or instruction/output rows.
    user_text = clean_text(row.get("prompt") or row.get("instruction") or row.get("input"))
    assistant_text = clean_text(row.get("response") or row.get("output") or row.get("answer"))
    if user_text and assistant_text:
        return [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ]

    return []


def merge_adjacent_same_role(turns: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    for turn in turns:
        if merged and merged[-1]["role"] == turn["role"]:
            merged[-1]["content"] = f'{merged[-1]["content"]}\n\n{turn["content"]}'
        else:
            merged.append(dict(turn))
    return merged


def get_conversation_id(row: dict[str, Any], source: str, fallback_index: int) -> str:
    for key in ("conversation_id", "id", "conversation_hash", "hash", "uid"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return f"{source.lower()}_{fallback_index:08d}"


def normalize_row(row: dict[str, Any], source: str, fallback_index: int) -> Optional[dict[str, Any]]:
    turns = extract_turns(row)
    if not turns:
        return None
    return {
        "source": source,
        "conversation_id": get_conversation_id(row, source, fallback_index),
        "turns": turns,
    }


def conversation_to_text(conversation: dict[str, Any], max_chars: Optional[int] = None) -> str:
    chunks = []
    for turn in conversation["turns"]:
        chunks.append(f'{turn["role"].upper()}: {turn["content"]}')
    text = "\n\n".join(chunks)
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 30].rstrip() + "\n\n[TRUNCATED]"
    return text
