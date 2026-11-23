"""Kartenküche – Home-Assistant-Add-on: Server und API."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from . import ha
from . import parsing as P
from . import reader_claude, reader_local
from .db import Store
from .text_utils import title_from_filename

VERSION = "0.1.0"
APP_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("CK_DATA_DIR", "/data"))
OPTIONS_FILE = Path(os.environ.get("CK_OPTIONS", str(DATA_DIR / "options.json")))
INGRESS_IP = "172.30.32.2"
MAX_UPLOAD = 30 * 1024 * 1024
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,90}$")
CARD_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cardkitchen")

store = Store(DATA_DIR)
ocr_slots = threading.Semaphore(2)
app = FastAPI(title="Kartenküche", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)


def options() -> dict:
    opts = {"default_reader": "local", "anthropic_api_key": "", "claude_model": "claude-opus-5-5", "ocr_language": "deu"}
    try:
        opts.update(json.loads(OPTIONS_FILE.read_text()))
    except (OSError, ValueError):
        pass
    if os.environ.get("ANTHROPIC_API_KEY") and not opts.get("anthropic_api_key"):
        opts["anthropic_api_key"] = os.environ["ANTHROPIC_API_KEY"]
    return opts


def claude_ready() -> bool:
    return bool(options().get("anthropic_api_key", "").strip())


@app.middleware("http")
async def only_ingress(request: Request, call_next):
    # Im Add-on nur Anfragen über Home Assistant (Ingress) zulassen.
    if ha.available() and request.client and request.client.host not in (INGRESS_IP, "127.0.0.1"):
        return JSONResponse({"detail": "Nur über Home Assistant erreichbar."}, status_code=403)
    return await call_next(request)


# ------------------------------------------------------------------ Oberfläche

@app.get("/")
def index():
    return FileResponse(APP_DIR / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/info")
def info():
    o = options()
    return {
        "version": VERSION,
        "readers": {"local": True, "claude": claude_ready()},
        "defaultReader": o.get("default_reader") if claude_ready() else "local",
        "claudeModel": o.get("claude_model"),
        "homeAssistant": ha.available(),
        "vocab": {"proteins": P.PROTEINS, "categories": P.CATEGORIES, "cuisines": P.CUISINES, "allergens": P.ALLERGENS},
    }


@app.get("/api/spices")
def spices():
    return json.loads((APP_DIR / "spices.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ Rezepte

def _check_id(rid: str) -> None:
    if not ID_RE.match(rid):
        raise HTTPException(400, "Ungültige Rezept-ID")


@app.get("/api/recipes")
def list_recipes():
    return store.recipes()


@app.put("/api/recipes/{rid}")
def put_recipe(rid: str, body: dict = Body(...)):
    _check_id(rid)
    old = store.get(rid) or {}
    rec = P.clean_recipe(body, body.get("title") or "Rezept")
    if old.get("card") and "card" not in body:
        rec["card"] = old["card"]
    return store.put(rid, rec)


@app.delete("/api/recipes/{rid}")
def delete_recipe(rid: str):
    _check_id(rid)
    store.delete(rid)
    return {"ok": True}


@app.get("/api/recipes/{rid}/card")
def get_card(rid: str):
    _check_id(rid)
    rec = store.get(rid)
    if not rec or not rec.get("card"):
        raise HTTPException(404, "Keine Originalkarte gespeichert")
    f = store.cards / rec["card"]
    if not f.is_file():
        raise HTTPException(404, "Originalkarte fehlt")
    return FileResponse(f, filename=rec["card"])


def _unique_id(title: str) -> str:
    base, ids = P.slug(title), store.ids()
    rid, n = base, 2
    while rid in ids:
        rid, n = f"{base}-{n}", n + 1
    return rid


def _find_duplicate(title: str) -> dict | None:
    s = P.slug(title)
    return next((r for r in store.recipes() if P.slug(r.get("title", "")) == s), None)


def _run_reader(path: Path, filename: str, reader: str) -> tuple[dict, list[str]]:
    o = options()
    if reader == "claude":
        if not claude_ready():
            raise HTTPException(400, "Für Claude fehlt der API-Schlüssel in den Add-on-Einstellungen.")
        try:
            rec = reader_claude.read_file(path, filename, o["anthropic_api_key"].strip(), o["claude_model"], title_from_filename(filename))
        except reader_claude.ClaudeError as e:
            raise HTTPException(502, str(e)) from e
        return rec, []
    with ocr_slots:
        try:
            return reader_local.read_file(path, filename, o.get("ocr_language") or "deu")
        except Exception as e:  # noqa: BLE001 – Lesefehler dem Nutzer melden statt abstürzen
            log.exception("Lokaler Leser fehlgeschlagen")
            raise HTTPException(422, f"Datei konnte nicht gelesen werden: {e}") from e


async def _save_upload(file: UploadFile, dst_dir: Path) -> tuple[Path, str]:
    name = Path(file.filename or "karte").name
    ext = Path(name).suffix.lower()
    if ext not in CARD_EXT:
        raise HTTPException(415, "Bitte PDF, JPG, PNG oder WebP hochladen.")
    dst = dst_dir / ("upload" + ext)
    size = 0
    with dst.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                raise HTTPException(413, "Datei ist größer als 30 MB.")
            out.write(chunk)
    return dst, name


@app.post("/api/import")
async def import_card(file: UploadFile = File(...), reader: str = Form("local"), replace: bool = Form(False)):
    with tempfile.TemporaryDirectory() as td:
        path, name = await _save_upload(file, Path(td))
        from starlette.concurrency import run_in_threadpool

        rec, warnings = await run_in_threadpool(_run_reader, path, name, reader)
        dup = _find_duplicate(rec["title"])
        if dup and not replace:
            return JSONResponse({"duplicate": True, "id": dup["id"], "title": dup["title"]}, status_code=409)
        rid = dup["id"] if dup else _unique_id(rec["title"])
        if dup:
            for k in ("rating", "lastCooked", "cookedCount"):
                if dup.get(k) is not None:
                    rec[k] = dup[k]
        card = rid + path.suffix
        shutil.copyfile(path, store.cards / card)
        rec.update(review=True, reader=reader, source=name, importedAt=int(time.time() * 1000), card=card)
        saved = store.put(rid, rec)
    return {"recipe": saved, "warnings": warnings}


@app.post("/api/recipes/{rid}/reread")
async def reread(rid: str, reader: str = Form("claude")):
    _check_id(rid)
    old = store.get(rid)
    if not old or not old.get("card") or not (store.cards / old["card"]).is_file():
        raise HTTPException(404, "Keine Originalkarte gespeichert")
    from starlette.concurrency import run_in_threadpool

    rec, warnings = await run_in_threadpool(_run_reader, store.cards / old["card"], old["card"], reader)
    for k in ("rating", "lastCooked", "cookedCount", "card", "source", "importedAt"):
        if old.get(k) is not None:
            rec[k] = old[k]
    rec.update(review=True, reader=reader)
    return {"recipe": store.put(rid, rec), "warnings": warnings}


@app.post("/api/import-text")
def import_text(body: dict = Body(...)):
    text = str(body.get("text") or "").strip()
    source = str(body.get("source") or "").strip()[:40]
    reader = body.get("reader") or "local"
    if len(text) < 40:
        raise HTTPException(400, "Bitte den Rezepttext einfügen.")
    if reader == "claude":
        if not claude_ready():
            raise HTTPException(400, "Für Claude fehlt der API-Schlüssel in den Add-on-Einstellungen.")
        o = options()
        try:
            rec, warnings = reader_claude.read_text(text, source, o["anthropic_api_key"].strip(), o["claude_model"]), []
        except reader_claude.ClaudeError as e:
            raise HTTPException(502, str(e)) from e
    else:
        rec, warnings = reader_local.read_text(text, source)
    dup = _find_duplicate(rec["title"])
    rid = _unique_id(rec["title"]) if not dup else _unique_id(rec["title"] + " 2")
    rec.update(review=True, reader=reader, source="Eingefügter Text", importedAt=int(time.time() * 1000))
    return {"recipe": store.put(rid, rec), "warnings": warnings}


# ------------------------------------------------------------------ Plan & Einstellungen

@app.get("/api/state")
def get_state():
    return store.kv_get("state", {})


@app.put("/api/state")
def put_state(body: dict = Body(...)):
    if len(json.dumps(body)) > 500_000:
        raise HTTPException(413, "Zu groß")
    store.kv_put("state", body)
    return {"ok": True}


# ------------------------------------------------------------------ Sicherung

@app.get("/api/export")
def export():
    data = {"app": "cardkitchen", "version": VERSION, "exportedAt": int(time.time() * 1000),
            "recipes": store.recipes(), "pantry": store.kv_get("state", {}).get("pantry")}
    return Response(json.dumps(data, ensure_ascii=False, indent=1), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="kartenkueche-rezepte.json"'})


@app.post("/api/restore")
async def restore(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise HTTPException(400, "Keine gültige Sicherungsdatei.") from e
    items = data if isinstance(data, list) else data.get("recipes") or []
    n = 0
    for x in items:
        if not isinstance(x, dict) or not x.get("title"):
            continue
        rid = x.get("id") if isinstance(x.get("id"), str) and ID_RE.match(x["id"]) else _unique_id(x["title"])
        rec = P.clean_recipe(x, x["title"])
        if rec.get("card") and not (store.cards / str(rec["card"])).is_file():
            rec.pop("card")
        store.put(rid, rec)
        n += 1
    if isinstance(data, dict) and isinstance(data.get("pantry"), list):
        st = store.kv_get("state", {})
        st["pantry"] = [str(p)[:60] for p in data["pantry"]][:300]
        store.kv_put("state", st)
    return {"imported": n}


# ------------------------------------------------------------------ Home Assistant

@app.get("/api/ha/todo")
def ha_todo():
    if not ha.available():
        return []
    try:
        return ha.todo_lists()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Home Assistant nicht erreichbar: {e}") from e


@app.post("/api/ha/todo")
def ha_add(body: dict = Body(...)):
    if not ha.available():
        raise HTTPException(400, "Nur im Home-Assistant-Add-on verfügbar.")
    items = [str(i) for i in body.get("items") or [] if str(i).strip()][:200]
    try:
        n = ha.add_items(str(body.get("entity_id") or ""), items)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Home Assistant nicht erreichbar: {e}") from e
    return {"added": n}


def run() -> None:
    import uvicorn

    port = int(os.environ.get("CK_PORT", "8099"))
    log.info("Kartenküche %s startet auf Port %s (Daten: %s)", VERSION, port, DATA_DIR)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning", proxy_headers=False)


if __name__ == "__main__":
    run()
