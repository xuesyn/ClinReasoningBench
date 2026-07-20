from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import GROUND_TRUTH_DIR


def list_ground_truth_files() -> list[Path]:
    if not GROUND_TRUTH_DIR.exists():
        return []
    return sorted(p for p in GROUND_TRUTH_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".jsonl", ".json"})


def get_ground_truth_file(filename: str) -> Path:
    for path in list_ground_truth_files():
        if path.name == filename:
            return path
    raise KeyError(f"Unknown ground truth file: {filename}")


def parse_auto(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        iv = int(v)
        return iv if iv in (0, 1) else None
    s = str(v).strip()
    return int(s) if s in {"0", "1"} else None


def parse_manual(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        iv = int(v)
        return iv if iv in (0, 1, 2, 3) else None
    s = str(v).strip().lower()
    if s in {"", "none", "null"}:
        return None
    return int(s) if s in {"0", "1", "2", "3"} else None


def get_auto_check(record: dict[str, Any]) -> Any:
    return record.get("parsed_response", {}).get("auto_check_pass", record.get("auto_check_pass"))


def get_manual_check(record: dict[str, Any]) -> Any:
    return record.get("manual_check", record.get("parsed_response", {}).get("manual_check"))


def get_comment(record: dict[str, Any]) -> str:
    return record.get("comment", record.get("parsed_response", {}).get("comment", ""))


def get_thinking(record: dict[str, Any]) -> str:
    return record.get("parsed_response", {}).get("thinking", "")


def get_thinking_tag(record: dict[str, Any]) -> str:
    return record.get("thinking_tag", record.get("parsed_response", {}).get("thinking_tag", ""))


def load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    decoder = json.JSONDecoder()
    pos = 0
    records: list[dict[str, Any]] = []

    while pos < len(text):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            break
        try:
            obj, end_pos = decoder.raw_decode(text, pos)
            records.append(obj)
            pos = end_pos
        except json.JSONDecodeError:
            error_preview = text[pos : pos + 80].replace("\n", "\\n")
            records.append({"__parse_error": True, "__raw": error_preview, "__line": len(records) + 1})
            next_newline = text.find("\n", pos)
            if next_newline == -1:
                break
            pos = next_newline + 1

    return records


@dataclass
class GTSession:
    session_id: str
    reference_id: str
    gt_file: Path
    records: list[dict[str, Any]]
    updated_at: float = field(default_factory=lambda: time.time())
    filter_cache: dict[tuple[str, str], list[int]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len([r for r in self.records if not r.get("__parse_error")])


SESSIONS: dict[str, GTSession] = {}


def create_session(reference_id: str, gt_filename: str) -> GTSession:
    gt_path = get_ground_truth_file(gt_filename)
    session = GTSession(
        session_id=str(uuid.uuid4()),
        reference_id=reference_id,
        gt_file=gt_path,
        records=load_records(gt_path),
    )
    SESSIONS[session.session_id] = session
    return session


def get_session(session_id: str) -> GTSession:
    session = SESSIONS.get(session_id)
    if session is None:
        raise KeyError(f"Unknown session: {session_id}")
    return session


def close_session(session_id: str) -> None:
    session = SESSIONS.pop(session_id, None)
    if session is None:
        raise KeyError(f"Unknown session: {session_id}")
    session.records.clear()
    session.filter_cache.clear()


def filtered_indices(session: GTSession, auto_filter: str, manual_filter: str) -> list[int]:
    cache_key = (auto_filter, manual_filter)
    if cache_key in session.filter_cache:
        return session.filter_cache[cache_key]

    result: list[int] = []
    for i, record in enumerate(session.records):
        if record.get("__parse_error"):
            continue

        auto_value = parse_auto(get_auto_check(record))
        manual_value = parse_manual(get_manual_check(record))

        if auto_filter != "all":
            wanted = int(auto_filter)
            if auto_value is None or auto_value != wanted:
                continue

        if manual_filter != "all":
            if manual_filter == "null":
                if manual_value is not None:
                    continue
            else:
                wanted = int(manual_filter)
                if manual_value is None or manual_value != wanted:
                    continue

        result.append(i)

    session.filter_cache[cache_key] = result
    return result

