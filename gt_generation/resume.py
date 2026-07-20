"""
Resume and output merge helpers for GT generation.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, Optional


def load_done_status(path: str) -> Dict[str, Dict[str, Any]]:
    status: Dict[str, Dict[str, Any]] = {}
    if not os.path.exists(path):
        return status

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            uuid = record.get("uuid")
            if not uuid:
                continue
            status[uuid] = record
    return status


def can_skip_by_check(manual_check: Any, auto_check_pass: Any) -> bool:
    return manual_check == 1 or (manual_check is None and int(auto_check_pass or 0) == 1)


def should_skip_record(existing_record: Optional[Dict[str, Any]], policy: str) -> bool:
    if existing_record is None:
        return False
    if policy == "force-rerun":
        return False
    if policy == "uuid-exists":
        return True
    if policy == "qc-pass-only":
        return can_skip_by_check(
            existing_record.get("manual_check"),
            existing_record.get("auto_check_pass"),
        )
    raise ValueError(f"Unsupported resume policy: {policy}")


def merge_records(path: str, updates: Iterable[Dict[str, Any]]) -> None:
    update_map = {}
    update_order = []
    for item in updates:
        uuid = item.get("uuid")
        if not uuid:
            continue
        if uuid not in update_map:
            update_order.append(uuid)
        update_map[uuid] = item

    if not update_map:
        return

    records = []
    index = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                uuid = record.get("uuid")
                if not uuid:
                    continue
                if uuid in index:
                    records[index[uuid]] = record
                else:
                    index[uuid] = len(records)
                    records.append(record)

    for uuid in update_order:
        record = update_map[uuid]
        if uuid in index:
            records[index[uuid]] = record
        else:
            records.append(record)
            index[uuid] = len(records) - 1

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.replace(tmp_path, path)
