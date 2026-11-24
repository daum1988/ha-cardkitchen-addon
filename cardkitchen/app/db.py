"""SQLite-Speicher im privaten Datenordner des Add-ons (/data, Teil der HA-Backups)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


class Store:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.cards = data_dir / "cards"
        self.cards.mkdir(parents=True, exist_ok=True)
        self.images = data_dir / "images"
        self.images.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(data_dir / "cardkitchen.db", check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS recipes (id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at INTEGER NOT NULL)")
        self._db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self._db.commit()

    # Rezepte
    def recipes(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, data FROM recipes").fetchall()
        return [dict(json.loads(d), id=i) for i, d in rows]

    def get(self, rid: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM recipes WHERE id=?", (rid,)).fetchone()
        return dict(json.loads(row[0]), id=rid) if row else None

    def put(self, rid: str, data: dict) -> dict:
        data = dict(data, id=rid, updatedAt=int(time.time() * 1000))
        with self._lock:
            self._db.execute(
                "INSERT INTO recipes (id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                (rid, json.dumps(data, ensure_ascii=False), data["updatedAt"]),
            )
            self._db.commit()
        return data

    def delete(self, rid: str) -> None:
        rec = self.get(rid)
        with self._lock:
            self._db.execute("DELETE FROM recipes WHERE id=?", (rid,))
            self._db.commit()
        if rec and rec.get("card"):
            f = self.cards / rec["card"]
            if f.is_file() and f.parent == self.cards:
                f.unlink()
        for name in (f"{rid}.jpg", f"{rid}.thumb.jpg"):
            f = self.images / name
            if f.is_file():
                f.unlink()

    def ids(self) -> set[str]:
        with self._lock:
            return {r[0] for r in self._db.execute("SELECT id FROM recipes")}

    # Einstellungen / Plan
    def kv_get(self, key: str, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def kv_put(self, key: str, value) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self._db.commit()
