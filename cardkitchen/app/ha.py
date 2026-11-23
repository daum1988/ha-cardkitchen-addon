"""Zugriff auf Home Assistant über die Supervisor-API (nur innerhalb des Add-ons verfügbar)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = "http://supervisor/core/api"


def available() -> bool:
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


def _req(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + os.environ.get("SUPERVISOR_TOKEN", ""), "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def todo_lists() -> list[dict]:
    states = _req("GET", "/states") or []
    return [
        {"entity_id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name") or s["entity_id"]}
        for s in states
        if s.get("entity_id", "").startswith("todo.")
    ]


def add_items(entity_id: str, items: list[str]) -> int:
    if not entity_id.startswith("todo."):
        raise ValueError("Keine Aufgabenliste")
    n = 0
    for it in items:
        _req("POST", "/services/todo/add_item", {"entity_id": entity_id, "item": it[:200]})
        n += 1
    return n
