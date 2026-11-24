"""Gerichtsfotos: aus Karten herausziehen, zuschneiden, speichern."""
from __future__ import annotations

import io
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps

log = logging.getLogger(__name__)

MAX_SIDE = 1600
THUMB_SIDE = 480


def _run(cmd: list[str], timeout: int = 120) -> str:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False).stdout.decode("utf-8", "replace")


# ------------------------------------------------------------------ Speichern

def save(img: Image.Image, images_dir: Path, rid: str) -> str:
    """Speichert Bild + Vorschaubild als JPEG und gibt den Dateinamen zurück."""
    images_dir.mkdir(parents=True, exist_ok=True)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    big = img.copy()
    big.thumbnail((MAX_SIDE, MAX_SIDE))
    big.save(images_dir / f"{rid}.jpg", "JPEG", quality=85, optimize=True)
    small = img.copy()
    small.thumbnail((THUMB_SIDE, THUMB_SIDE))
    small.save(images_dir / f"{rid}.thumb.jpg", "JPEG", quality=80, optimize=True)
    return f"{rid}.jpg"


def save_bytes(data: bytes, images_dir: Path, rid: str) -> str:
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        return save(im, images_dir, rid)


def remove(images_dir: Path, rid: str) -> None:
    for name in (f"{rid}.jpg", f"{rid}.thumb.jpg"):
        p = images_dir / name
        if p.is_file():
            p.unlink()


# ------------------------------------------------------------------ Herausziehen

def pdf_has_text(path: Path) -> bool:
    return len(_run(["pdftotext", "-l", "2", str(path), "-"]).strip()) > 300


def largest_embedded(path: Path) -> Image.Image | None:
    """Größtes eingebettetes Foto der ersten beiden Seiten (Marley Spoon, Dinnerly …)."""
    best = None
    for line in _run(["pdfimages", "-list", "-f", "1", "-l", "2", str(path)]).splitlines()[2:]:
        c = line.split()
        if len(c) < 5 or c[2] != "image":
            continue
        page, w, h = int(c[0]), int(c[3]), int(c[4])
        if w >= 500 and h >= 300 and (best is None or w * h > best[1]):
            best = (page, w * h)
    if not best:
        return None
    with tempfile.TemporaryDirectory() as td:
        _run(["pdfimages", "-f", str(best[0]), "-l", str(best[0]), "-j", "-png", str(path), str(Path(td) / "i")])
        cands = []
        for f in Path(td).iterdir():
            try:
                with Image.open(f) as im:
                    im.load()
                    if im.mode in ("L", "1"):
                        continue  # Masken
                    cands.append((im.width * im.height, im.copy()))
            except OSError:
                continue
        if not cands:
            return None
        img = max(cands, key=lambda x: x[0])[1]
    if img.mode == "CMYK":
        img = ImageOps.invert(img.convert("RGB")) if _looks_inverted(img) else img.convert("RGB")
    return img.convert("RGB")


def _looks_inverted(img: Image.Image) -> bool:
    # Manche CMYK-JPEGs aus PDFs sind invertiert gespeichert (Adobe-Marker).
    rgb = img.convert("RGB").resize((32, 32))
    mean = sum(sum(p) for p in rgb.getdata()) / (32 * 32 * 3)
    return mean < 60


def render_page(path: Path, page: int = 1, dpi: int = 150) -> Image.Image | None:
    with tempfile.TemporaryDirectory() as td:
        _run(["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", str(path), str(Path(td) / "p")])
        files = sorted(Path(td).glob("p*.png"))
        if not files:
            return None
        with Image.open(files[0]) as im:
            im.load()
            return im.convert("RGB")


def crop_fraction(img: Image.Image, box: dict) -> Image.Image | None:
    try:
        l, t, r, b = (float(box[k]) for k in ("left", "top", "right", "bottom"))
    except (KeyError, TypeError, ValueError):
        return None
    l, t, r, b = max(0, l), max(0, t), min(1, r), min(1, b)
    if r - l < 0.15 or b - t < 0.15:
        return None
    return img.crop((round(l * img.width), round(t * img.height), round(r * img.width), round(b * img.height)))


def find_photo(img: Image.Image) -> Image.Image | None:
    """Sucht die große Fotofläche auf einer hellen Kartenseite (z. B. HelloFresh-Vorderseite).

    Nicht-weiße Pixel werden geglättet; nur dichte Flächen bleiben übrig (Text und Symbole sind
    locker verteilt). Die größte zusammenhängende dichte Fläche ist das Foto.
    """
    scale = 300 / max(img.size)
    small = img.convert("RGB").resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))))
    w, h = small.size
    darkest = _darkest(*small.split())
    mask = darkest.point(lambda v: 255 if v < 243 else 0)
    dense = mask.filter(ImageFilter.BoxBlur(3)).point(lambda v: 255 if v >= 215 else 0)
    px = dense.load()
    seen = bytearray(w * h)
    best = None
    for y0 in range(h):
        for x0 in range(w):
            if px[x0, y0] == 0 or seen[y0 * w + x0]:
                continue
            stack = [(x0, y0)]
            seen[y0 * w + x0] = 1
            n, minx, miny, maxx, maxy = 0, x0, y0, x0, y0
            while stack:
                x, y = stack.pop()
                n += 1
                minx, maxx, miny, maxy = min(minx, x), max(maxx, x), min(miny, y), max(maxy, y)
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and px[nx, ny] and not seen[ny * w + nx]:
                        seen[ny * w + nx] = 1
                        stack.append((nx, ny))
            if best is None or n > best[0]:
                best = (n, minx, miny, maxx + 1, maxy + 1)
    if not best:
        return None
    n, x0, y0, x1, y1 = best
    bw, bh = x1 - x0, y1 - y0
    if bw * bh < 0.2 * w * h or n < 0.75 * bw * bh or not (0.6 <= bw / max(1, bh) <= 2.6):
        return None
    inv = 1 / scale
    return img.crop((round(x0 * inv), round(y0 * inv), round(x1 * inv), round(y1 * inv)))


def _darkest(*bands: Image.Image) -> Image.Image:
    out = bands[0]
    for band in bands[1:]:
        out = ImageChops.darker(out, band)
    return out


def extract(path: Path, filename: str, hint: dict | None = None) -> Image.Image | None:
    """Gerichtsfoto aus einer Karte. hint: optionale Lage vom Claude-Leser
    ({"page": 1, "left": …, "top": …, "right": …, "bottom": …} als Anteile 0–1)."""
    try:
        is_pdf = filename.lower().endswith(".pdf")
        if is_pdf and pdf_has_text(path):
            img = largest_embedded(path)
            if img:
                return img
        if is_pdf:
            page = int((hint or {}).get("page") or 1)
            base = render_page(path, page if page in (1, 2, 3, 4) else 1)
        else:
            with Image.open(path) as im:
                im.load()
                base = ImageOps.exif_transpose(im).convert("RGB")
        if base is None:
            return None
        if hint:
            img = crop_fraction(base, hint)
            if img:
                return img
        return find_photo(base)
    except Exception:  # noqa: BLE001 – ein fehlendes Bild darf den Import nicht abbrechen
        log.exception("Bild konnte nicht gelesen werden")
        return None


SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,90}$")
