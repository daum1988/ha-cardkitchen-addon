import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CK_OPTIONS", str(tmp_path / "options.json"))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import app.main as m

    importlib.reload(m)
    return TestClient(m.app), m, tmp_path


def test_recipe_crud_and_state(client):
    c, m, _ = client
    assert c.get("/api/info").json()["readers"] == {"local": True, "claude": False}
    r = c.put("/api/recipes/test-rezept", json={"title": "Test", "ingredients": [{"name": "Salz", "qty": None, "unit": ""}]})
    assert r.status_code == 200 and r.json()["title"] == "Test"
    assert [x["id"] for x in c.get("/api/recipes").json()] == ["test-rezept"]
    assert c.put("/api/recipes/../evil", json={"title": "x"}).status_code in (400, 404)
    c.put("/api/state", json={"prefs": {"portions": 3}})
    assert c.get("/api/state").json()["prefs"]["portions"] == 3
    exp = c.get("/api/export").json()
    assert exp["recipes"][0]["id"] == "test-rezept"
    c.delete("/api/recipes/test-rezept")
    assert c.get("/api/recipes").json() == []
    r = c.post("/api/restore", files={"file": ("b.json", json.dumps(exp), "application/json")})
    assert r.json()["imported"] == 1


def test_import_text_local(client):
    c, _, _ = client
    r = c.post("/api/import-text", json={"text": "Tomatensuppe\n\nZutaten\n500 g Tomaten\n1 Zwiebel\n200 ml Sahne\n\nZubereitung\nAlles in einem Topf mit der Sahne kochen und pürieren.", "reader": "local"})
    rec = r.json()["recipe"]
    assert rec["review"] is True and rec["title"] == "Tomatensuppe"


def test_claude_requires_key(client):
    c, _, _ = client
    r = c.post("/api/import-text", json={"text": "x" * 50, "reader": "claude"})
    assert r.status_code == 400


def test_claude_request_shape(client, monkeypatch):
    """Prüft, was an die Claude-API geschickt würde (ohne echten Aufruf)."""
    c, m, tmp = client
    (tmp / "options.json").write_text(json.dumps({"anthropic_api_key": "sk-ant-test", "claude_model": "claude-opus-5-5"}))
    from app import reader_claude

    sent = {}

    class Block:
        type = "text"
        text = json.dumps({"title": "Dal", "subtitle": "", "provider": "Sonstige", "servings": 2, "timeMin": 30, "timeMax": 30,
                           "kcal": 600, "protein": "Vegan", "categories": ["Curry"], "cuisine": "Indisch", "allergens": [],
                           "ingredients": [{"name": "Linsen", "qty": 200, "unit": "g", "raw": "200 g Linsen", "pantry": False}],
                           "steps": [{"title": "", "text": "Kochen."}]})

    class Resp:
        stop_reason = "end_turn"
        content = [Block()]
        model = "claude-opus-5-5"
        usage = None

    class Msgs:
        def create(self, **kw):
            sent.update(kw)
            return Resp()

    class Fake:
        def __init__(self, **kw):
            sent["client"] = kw
            self.messages = Msgs()
            self.beta = type("B", (), {"messages": Msgs()})()

    monkeypatch.setattr(reader_claude.anthropic, "Anthropic", Fake)
    r = c.post("/api/import-text", json={"text": "Dal\n200 g Linsen\nKochen. " * 3, "reader": "claude", "source": "Blog"})
    assert r.status_code == 200, r.text
    assert sent["client"]["api_key"] == "sk-ant-test"
    assert sent["model"] == "claude-opus-5-5"
    assert sent["fallbacks"] == "default" and sent["betas"] == ["server-side-fallback-2026-07-01"]
    assert sent["output_config"]["format"]["type"] == "json_schema"
    rec = r.json()["recipe"]
    assert rec["provider"] == "Blog" and rec["ingredients"][0]["name"] == "Linsen"
