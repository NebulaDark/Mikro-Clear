"""Bounded read-only readers for EVE JSON, audit JSONL, and text logs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def tail_lines(path: str | Path, *, limit: int = 100, max_bytes: int = 4 * 1024 * 1024) -> list[str]:
    wanted = max(1, min(int(limit), 1000))
    file_path = Path(path)
    if not file_path.is_file():
        return []

    with file_path.open("rb") as handle:
        handle.seek(0, 2)
        end = handle.tell()
        start = max(0, end - max(4096, int(max_bytes)))
        handle.seek(start)
        data = handle.read(end - start)

    if start:
        newline = data.find(b"\n")
        data = data[newline + 1 :] if newline >= 0 else b""

    return [line.decode("utf-8", errors="replace") for line in data.splitlines()[-wanted:]]


def read_jsonl(path: str | Path, *, limit: int = 100, max_bytes: int = 4 * 1024 * 1024) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in tail_lines(path, limit=limit, max_bytes=max_bytes):
        try:
            value = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def recent_alerts(path: str | Path, *, limit: int = 100, query: str = "", max_bytes: int = 4 * 1024 * 1024) -> list[dict[str, Any]]:
    wanted = max(1, min(int(limit), 500))
    search = query.strip().lower()
    candidates = read_jsonl(path, limit=min(4000, max(wanted * 20, 500)), max_bytes=max_bytes)
    alerts: list[dict[str, Any]] = []

    for event in reversed(candidates):
        if event.get("event_type") != "alert":
            continue
        alert = event.get("alert")
        if not isinstance(alert, dict):
            alert = {}
        row = {
            "timestamp": str(event.get("timestamp", "")),
            "src_ip": str(event.get("src_ip", "")),
            "src_port": event.get("src_port"),
            "dest_ip": str(event.get("dest_ip", "")),
            "dest_port": event.get("dest_port"),
            "proto": str(event.get("proto", "")),
            "in_iface": str(event.get("in_iface", "")),
            "severity": alert.get("severity"),
            "signature_id": alert.get("signature_id"),
            "signature": str(alert.get("signature", "")),
            "category": str(alert.get("category", "")),
        }
        if search and search not in " ".join(str(value) for value in row.values()).lower():
            continue
        alerts.append(row)
        if len(alerts) >= wanted:
            break
    return alerts


def text_log(path: str | Path, *, limit: int = 200, query: str = "", max_bytes: int = 4 * 1024 * 1024) -> list[str]:
    search = query.strip().lower()
    lines = tail_lines(path, limit=min(max(limit * 4, limit), 1000), max_bytes=max_bytes)
    if search:
        lines = [line for line in lines if search in line.lower()]
    return lines[-max(1, min(int(limit), 1000)) :]


__all__ = ["read_jsonl", "recent_alerts", "tail_lines", "text_log"]
