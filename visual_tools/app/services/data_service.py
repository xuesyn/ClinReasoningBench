from __future__ import annotations

import ast
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import DATA_DIR
from app.services.gt_service import load_records


def list_data_files() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return sorted(p for p in DATA_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".jsonl", ".json"})


def get_data_file(filename: str) -> Path:
    for path in list_data_files():
        if path.name == filename:
            return path
    raise KeyError(f"Unknown data file: {filename}")


def parse_prediction_payload(text: str) -> dict[str, Any]:
    raw_text = (text or "").strip()
    outer_thinking = _extract_outer_thinking(raw_text)

    for candidate in _prediction_parse_candidates(raw_text):
        for parser in (json.loads, ast.literal_eval):
            try:
                obj = parser(candidate)
                if isinstance(obj, dict):
                    if outer_thinking:
                        obj.setdefault("chain_of_thought", outer_thinking)
                        if not obj.get("thinking"):
                            obj["thinking"] = outer_thinking
                    return obj
            except Exception:
                continue
    return {}


def _extract_outer_thinking(text: str) -> str:
    match = re.search(r"<thinking>\s*(.*?)\s*</thinking>", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    fence_match = re.fullmatch(r"```(?:json|JSON)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    return fence_match.group(1).strip() if fence_match else stripped


def _extract_balanced_json_objects(text: str) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for start in (index for index, ch in enumerate(text) if ch == "{"):
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : index + 1].strip()
                    if candidate and candidate not in seen:
                        seen.add(candidate)
                        results.append(candidate)
                    break

    results.sort(key=len, reverse=True)
    return results


def _prediction_parse_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def push(value: str) -> None:
        candidate = value.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    push(text)
    push(_strip_code_fence(text))

    for block in re.findall(r"```(?:json|JSON)?\s*(.*?)\s*```", text, flags=re.DOTALL):
        push(block)

    for block in re.findall(r"</thinking>\s*(\{.*)", text, flags=re.DOTALL | re.IGNORECASE):
        push(block)

    for candidate in list(candidates):
        for obj in _extract_balanced_json_objects(candidate):
            push(obj)

    return candidates


def normalize_prediction_thinking(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(parts)
    return str(value)


def get_prompt(record: dict[str, Any]) -> str:
    conversations = record.get("conversations", [])
    for item in conversations:
        if isinstance(item, dict) and item.get("role") == "user":
            return item.get("text", "")
    return ""


def get_prediction_text(record: dict[str, Any]) -> str:
    predictions = record.get("predictions", [])
    if isinstance(predictions, list) and predictions:
        return predictions[0] if isinstance(predictions[0], str) else json.dumps(predictions[0], ensure_ascii=False)
    return ""


@dataclass
class DataSession:
    session_id: str
    reference_id: str
    data_file: Path
    records: list[dict[str, Any]]

    @property
    def total(self) -> int:
        return len([r for r in self.records if not r.get("__parse_error")])


SESSIONS: dict[str, DataSession] = {}


def create_session(reference_id: str, data_filename: str) -> DataSession:
    session = DataSession(
        session_id=str(uuid.uuid4()),
        reference_id=reference_id,
        data_file=get_data_file(data_filename),
        records=load_records(get_data_file(data_filename)),
    )
    SESSIONS[session.session_id] = session
    return session


def get_session(session_id: str) -> DataSession:
    session = SESSIONS.get(session_id)
    if session is None:
        raise KeyError(f"Unknown session: {session_id}")
    return session


def close_session(session_id: str) -> None:
    session = SESSIONS.pop(session_id, None)
    if session is None:
        raise KeyError(f"Unknown session: {session_id}")
    session.records.clear()
