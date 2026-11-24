import io
import json
import zipfile

from PIL import Image, ImageDraw

from app import images


def _photo(w=600, h=400):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(0, h, 20):  # bunte, dichte Fläche wie ein Foto
        d.rectangle([0, y, w, y + 20], fill=(180 + y % 60, 120, 60 + y % 90))
    d.ellipse([w * 0.2, h * 0.15, w * 0.8, h * 0.85], fill=(235, 230, 200))
    return img


def test_find_photo_on_card_page():
    page = Image.new("RGB", (1400, 1000), "white")
    d = ImageDraw.Draw(page)
    d.text((60, 30), "Testgericht mit Beilage", fill="black")
    for i in range(8):  # kleine Zutaten-Symbole rechts
        d.ellipse([1200, 150 + i * 90, 1260, 210 + i * 90], fill=(120, 160, 90))
    page.paste(_photo(1000, 700), (60, 200))
    found = images.find_photo(page)
    assert found is not None
    assert abs(found.width - 1000) < 40 and abs(found.height - 700) < 40


def test_crop_fraction():
    img = Image.new("RGB", (1000, 500), "white")
    out = images.crop_fraction(img, {"left": 0.1, "top": 0.2, "right": 0.6, "bottom": 0.9})
    assert out.size == (500, 350)
    assert images.crop_fraction(img, {"left": 0.1, "top": 0.1, "right": 0.12, "bottom": 0.9}) is None


def _jpg():
    b = io.BytesIO()
    _photo().save(b, "JPEG")
    return b.getvalue()


def test_image_api_and_zip_roundtrip(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("CK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CK_OPTIONS", str(tmp_path / "options.json"))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    import app.main as m

    importlib.reload(m)
    from fastapi.testclient import TestClient

    c = TestClient(m.app)
    c.put("/api/recipes/suppe", json={"title": "Suppe"})
    r = c.put("/api/recipes/suppe/image", files={"file": ("x.jpg", _jpg(), "image/jpeg")})
    assert r.status_code == 200 and r.json()["image"] == "suppe.jpg" and r.json()["imageSource"] == "manual"
    assert c.get("/api/recipes/suppe/image?thumb=1").headers["content-type"] == "image/jpeg"
    assert c.put("/api/recipes/suppe/image", files={"file": ("x.jpg", b"kein bild", "image/jpeg")}).status_code == 415

    # Die Oberfläche darf keine Dateipfade setzen
    r = c.put("/api/recipes/suppe", json={"title": "Suppe", "card": "../../options.json", "image": "../x.jpg"})
    assert r.json().get("card") is None and r.json()["image"] == "suppe.jpg"

    z = c.get("/api/export.zip")
    assert z.status_code == 200
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        data = json.loads(zf.read("kartenkueche-rezepte.json"))
        assert data["recipes"][0]["image"] == "bilder/suppe.jpg"
        assert "bilder/suppe.jpg" in zf.namelist()

    c.delete("/api/recipes/suppe")
    assert c.get("/api/recipes/suppe/image").status_code == 404
    r = c.post("/api/restore", files={"file": ("s.zip", z.content, "application/zip")})
    assert r.json() == {"imported": 1, "images": 1}
    assert c.get("/api/recipes/suppe/image").status_code == 200

    # Sicherung im Format der lokalen Sitzung: JSON + bilder/ in einem Unterordner
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Rezepte/kartenkueche-rezepte.json", json.dumps({"recipes": [{"id": "dal", "title": "Dal", "image": "bilder/dal.jpg"}]}))
        zf.writestr("Rezepte/bilder/dal.jpg", _jpg())
    r = c.post("/api/restore", files={"file": ("k.zip", buf.getvalue(), "application/zip")})
    assert r.json() == {"imported": 1, "images": 1}

    r = c.delete("/api/recipes/dal/image")
    assert "image" not in r.json() and r.json()["imageSource"] == "none"


def test_chunked_restore(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("CK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CK_OPTIONS", str(tmp_path / "options.json"))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    import app.main as m

    importlib.reload(m)
    from fastapi.testclient import TestClient

    c = TestClient(m.app)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("kartenkueche-rezepte.json", json.dumps({"recipes": [{"id": "dal", "title": "Dal", "image": "bilder/dal.jpg"}]}))
        zf.writestr("bilder/dal.jpg", _jpg())
    data = buf.getvalue()
    uid = "ab" * 16
    step = max(1, len(data) // 3)
    for i, start in enumerate(range(0, len(data), step)):
        assert c.put(f"/api/upload/{uid}/{i}", content=data[start:start + step]).status_code == 200
    r = c.post(f"/api/upload/{uid}/restore")
    assert r.json() == {"imported": 1, "images": 1}
    assert not list((tmp_path / "uploads").glob("*.part"))
    assert c.put("/api/upload/../1", content=b"x").status_code in (400, 404)
    assert c.post(f"/api/upload/{uid}/restore").status_code == 404
