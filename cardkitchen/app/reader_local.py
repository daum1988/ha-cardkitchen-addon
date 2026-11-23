"""Kostenloser Leser: pdftotext für PDFs mit Textebene, Tesseract für Scans und Fotos.

Läuft komplett lokal. Ergebnisse sind Entwürfe und werden in der App als „zu prüfen“ markiert.
"""
from __future__ import annotations

import html
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from . import parsing as P

log = logging.getLogger(__name__)

UTENSILS = re.compile(
    r"topf|pfanne|backofen|^ofen$|sieb|messbecher|reibe|auflaufform|schüssel|backblech|deckel|schneidebrett|"
    r"pürierstab|knoblauchpresse|küchenpapier|küchenkrepp|backpapier|wasserkocher|nudelholz|schneebesen",
    re.I,
)
TIME_RE = re.compile(r"(\d{1,3})\s*[–—-]\s*(\d{1,3})\s*min", re.I)
SERV_RE = re.compile(r"(\d)\s*(?:Personen|Portionen|P\b)", re.I)


def _run(cmd: list[str], timeout: int = 180) -> str:
    res = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    return res.stdout.decode("utf-8", "replace")


def kcal_from(text: str) -> int | None:
    vals = [int(v) for v in re.findall(r"(\d{3,4})\s*kcal", text, re.I)]
    vals = [v for v in vals if 150 <= v <= 2500]
    return max(vals) if vals else None


def time_from(text: str) -> tuple[int | None, int | None]:
    t = re.sub(r"(?<=\d)[Oo]|[Oo](?=\d)", "0", text)
    m = TIME_RE.search(t)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d{1,3})\s*(?:min|Minuten)", t, re.I)
    return (int(m.group(1)), int(m.group(1))) if m else (None, None)


def finish(r: dict, all_text: str, fallback_title: str, hint: str = "") -> dict:
    r.setdefault("title", fallback_title)
    r["provider"] = r.get("provider") or P.detect_provider(all_text)
    tmin, tmax = time_from(all_text)
    r.setdefault("timeMin", tmin)
    r.setdefault("timeMax", tmax)
    r.setdefault("kcal", kcal_from(all_text))
    m = re.search(r"(\d)\s*[–—-]\s*\d\s*(?:Personen|Portionen)", all_text) or SERV_RE.search(all_text)
    r.setdefault("servings", int(m.group(1)) if m else 2)
    ings = P.convert_packs(P.split_slash(P.split_salt_pepper(r.get("ingredients") or [])))
    r["ingredients"] = ings
    r["protein"] = P.guess_protein(r["title"], ings, hint + " " + all_text[:400])
    r["categories"] = P.guess_categories(r["title"] + " " + r.get("subtitle", ""), ings, hint + " " + all_text[:400])
    r["cuisine"] = P.guess_cuisine(r["title"] + " " + r.get("subtitle", ""), ings)
    if not r.get("allergens"):
        m = re.search(r"Allergene[:\s]+(.{0,400}?)(?:Kann Spuren|Bitte beachte|\(Bitte|$)", all_text, re.S | re.I)
        r["allergens"] = P.find_allergens(m.group(1)) if m else []
    return P.clean_recipe(r, fallback_title)


# ---------------------------------------------------------------- PDF mit Textebene

def pdf_blocks(path: Path) -> list[dict]:
    raw = _run(["pdftotext", "-bbox-layout", "-l", "4", str(path), "-"])
    blocks = []
    for page_i, page in enumerate(re.findall(r"<page[^>]*>(.*?)</page>", raw, re.S)):
        for b in re.finditer(r'<block xMin="([\d.]+)" yMin="([\d.]+)"[^>]*>(.*?)</block>', page, re.S):
            lines = []
            for ln in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)"[^>]*>(.*?)</line>', b.group(3), re.S):
                words = [html.unescape(w) for w in re.findall(r"<word[^>]*>(.*?)</word>", ln.group(3))]
                lines.append({"x": float(ln.group(1)), "y": float(ln.group(2)), "text": " ".join(words).strip()})
            text = "\n".join(l["text"] for l in lines)
            blocks.append({"page": page_i, "x": float(b.group(1)), "y": float(b.group(2)), "lines": lines, "text": text})
    return blocks


def _ingredients_from_block(block: dict, bullets: list[dict], pantry: bool) -> list[dict]:
    items: list[str] = []
    for ln in block["lines"]:
        t = ln["text"]
        starts = t.startswith("•") or any(
            b["page"] == block["page"] and abs(b["y"] - ln["y"]) < 6 and b["x"] <= ln["x"] for b in bullets
        )
        t = t.lstrip("• ").strip()
        if not t:
            continue
        if starts or not items:
            items.append(t)
        else:
            sep = "" if items[-1].endswith("-") else " "
            items[-1] = items[-1] + sep + t
    out = []
    for it in items:
        if UTENSILS.search(it):
            continue
        ing = P.parse_ing_line(it, pantry)
        if ing:
            out.append(ing)
    return out


def parse_text_pdf(blocks: list[dict], fallback_title: str) -> dict | None:
    all_text = "\n".join(b["text"] for b in blocks)
    bullets = [b for b in blocks if b["text"].strip() == "•"]
    content = [b for b in blocks if b["text"].strip() and b["text"].strip() != "•"]
    r: dict = {"ingredients": [], "steps": []}

    def after(rx: str) -> dict | None:
        for i, b in enumerate(content):
            if re.fullmatch(rx, b["text"].strip(), re.I):
                return content[i + 1] if i + 1 < len(content) else None
        return None

    box = after(r"was du von uns bekommst|zutaten.*")
    home = after(r"was du zu hause benötigst|gut im haus zu haben|aus deinem vorrat.*")
    if box:
        r["ingredients"] += _ingredients_from_block(box, bullets, False)
    if home:
        r["ingredients"] += _ingredients_from_block(home, bullets, True)
    if not r["ingredients"]:
        return None

    # Titel: kurze Blöcke direkt vor der Zeitangabe
    t_idx = next((i for i, b in enumerate(content) if TIME_RE.search(b["text"]) and len(b["text"]) < 20), None)
    if t_idx:
        head = []
        for b in reversed(content[:t_idx]):
            if len(b["text"]) > 90:
                break
            head.insert(0, re.sub(r"-\n", "-", b["text"]).replace("\n", " "))
        title_parts, subtitle = [], ""
        for h in head:
            if title_parts and re.match(r"^(mit|dazu|und|an|auf|in|aus)\b", h):
                subtitle = (subtitle + " " + h).strip()
            elif subtitle:
                subtitle += " " + h
            else:
                title_parts.append(h)
        title = ""
        for part in title_parts:
            title += part if title.endswith("-") else (" " + part if title else part)
        if title:
            r["title"] = title.strip()
            r["subtitle"] = subtitle.strip()

    # Schritte: "1. Überschrift" + Textblock darunter
    steps = []
    for b in content:
        m = re.fullmatch(r"(\d{1,2})\.\s*(.+)", b["text"].replace("\n", " ").strip())
        if not m or len(m.group(2)) > 60:
            continue
        below = [c for c in content if c["page"] == b["page"] and 0 < c["y"] - b["y"] < 90 and abs(c["x"] - b["x"]) < 25 and c is not b]
        if not below:
            continue
        body = min(below, key=lambda c: c["y"] - b["y"])
        steps.append((int(m.group(1)), m.group(2), body["text"].replace("\n", " ")))
    r["steps"] = [{"title": t, "text": re.sub(r"\s+", " ", x)} for _, t, x in sorted(steps)]

    alg = after(r"allergene")
    if alg:
        r["allergens"] = P.find_allergens(alg["text"])
    return finish(r, all_text, fallback_title)


# ---------------------------------------------------------------- OCR

def _prepare_image(src: Path, dst: Path) -> None:
    from PIL import Image, ImageOps

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("L")
        longest = max(im.size)
        if longest > 4200:
            im = im.resize((round(im.width * 4200 / longest), round(im.height * 4200 / longest)))
        elif longest < 2200:
            f = 2200 / longest
            im = im.resize((round(im.width * f), round(im.height * f)))
        im.save(dst)


def ocr_pages(path: Path, is_pdf: bool, lang: str) -> list[dict]:
    pages = []
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        imgs: list[Path] = []
        if is_pdf:
            _run(["pdftoppm", "-r", "300", "-l", "4", "-png", str(path), str(tdp / "p")], timeout=300)
            imgs = sorted(tdp.glob("p*.png"))
        else:
            dst = tdp / "img.png"
            _prepare_image(path, dst)
            imgs = [dst]
        for img in imgs:
            tsv = _run(["tesseract", str(img), "stdout", "-l", lang, "--psm", "3", "tsv"], timeout=300)
            pages.append(_tsv_to_page(tsv))
    return pages


def _tsv_to_page(tsv: str) -> dict:
    lines: dict[tuple, dict] = {}
    page_h = 1
    for row in tsv.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12:
            continue
        level = c[0]
        if level == "1":
            page_h = int(c[9]) or 1
        if level != "5" or not c[11].strip():
            continue
        key = (int(c[2]), int(c[3]), int(c[4]))
        left, top, w, h = int(c[6]), int(c[7]), int(c[8]), int(c[9])
        ln = lines.setdefault(key, {"words": [], "left": left, "top": top, "bottom": top + h})
        ln["words"].append(c[11])
        ln["left"] = min(ln["left"], left)
        ln["top"] = min(ln["top"], top)
        ln["bottom"] = max(ln["bottom"], top + h)
    out = []
    for key in sorted(lines):
        ln = lines[key]
        out.append({"block": key[0], "par": key[1], "text": " ".join(ln["words"]), "left": ln["left"], "top": ln["top"]})
    return {"height": page_h, "lines": out}


QTY_TOKEN = re.compile(r"^(\d+(?:[.,]\d+)?)([a-zA-Z]*)(\**)$")
COUNTRY = re.compile(r"^\|?[A-Z]{2}(?:\|[A-Z]{2})*\|?$|^\|$")


def _ocr_qty(tok: str, name: str) -> tuple[float | None, str] | None:
    """Liest eine Mengenangabe aus einer OCR-Zelle, korrigiert '1508' → 150 g usw."""
    tok = tok.replace("O", "0").strip("*")
    if tok in ("x", "X", "-", "—"):
        return None
    if tok.lower() in ("sg", "8g"):
        return 8.0, "g"  # "8g" als "Sg" gelesen
    m = QTY_TOKEN.match(tok)
    if not m:
        m2 = re.match(r"^(\d+(?:[.,]\d+)?)(g|ml|EL|TL)", tok)
        if not m2:
            return None
        return P.parse_qty(m2.group(1)), P.norm_unit(m2.group(2))
    num, unit = m.group(1), m.group(2)
    countable = re.search(r"zehe|zwiebel|kartoffel|zucchini|baguette|brötchen|ei\b|eier|paprika|karotte|möhre|tomate\b|lauch|gurke|aubergine|limette|zitrone|stück|stange|chili", name, re.I)
    if unit.lower() == "g" and num.endswith("8") and len(num) >= 3 and "," not in num:
        return P.parse_qty(num[:-1]), "g"  # "108g" = "10g" mit doppelt gelesenem g
    if unit.lower() in ("g", "ml", "el", "tl"):
        return P.parse_qty(num), P.norm_unit(unit)
    if unit.lower() in ("8g", "s", "sg"):
        unit = ""
    # "g" als "8" gelesen
    if not unit and num.endswith("8") and "," not in num and not countable:
        base = num[:-1]
        if base and (len(num) >= 3 or base in ("5",)):
            return P.parse_qty(base), "g"
    if not unit and countable and len(num) == 2 and num.endswith("8"):
        return P.parse_qty(num[0]), ""
    if re.fullmatch(r"\d+,\d+8", num):
        return P.parse_qty(num[:-1]), "g"
    if unit.lower() in ("sg",):
        return 8.0, "g"
    return P.parse_qty(num), ""


def _check_columns(q: tuple, rest: list[str], name: str) -> tuple:
    """Prüft die 2-Personen-Menge gegen die 4-Personen-Spalte (≈ doppelt so viel)."""
    qty, unit = q
    if qty is None or len(rest) < 2:
        return q
    q4 = _ocr_qty(rest[1], name)
    if not q4 or not q4[0]:
        return q
    expected = q4[0] / 2
    if expected and qty >= 4 * expected and abs(qty / 10 - expected) <= expected * 0.35:
        return qty / 10, unit or q4[1]  # Komma nicht erkannt: "25g" statt "2,5g"
    return q


def _parse_ocr_table(lines: list[str]) -> list[dict]:
    """HelloFresh-Tabelle: Name [Herkunft] [Allergen] 2P-Menge …"""
    out: list[dict] = []
    for raw in lines:
        t = re.sub(r"\s*(?:Angaben im Text|nach Geschmack)\s*$", "", raw.strip(), flags=re.I)
        if not t or re.fullmatch(r"\d\s*[Pp]\b.*", t) or re.match(r"(\d[Pp]\s*)+$", t):
            continue
        if "*" in t and "," in t and not re.search(r"\d", t.split("*")[0][-3:] if "*" in t else ""):
            for part in t.split(","):
                n = part.replace("*", "").replace("”", "").strip()
                if n and not re.search(r"\d", n):
                    out.append({"name": n, "qty": None, "unit": "", "raw": t, "pantry": True})
            continue
        t = re.sub(r"(?<=[a-zäöüß])(?:ES|NL|DE|NZ|IT|FR|PL|BE|AT)(?=\s*\||\s|$)", " ", t)
        t = re.sub(r"\s*(?:Angaben im Text|nach Geschmack)\s*$", "", t, flags=re.I)
        toks = [tok for tok in t.split() if not re.search(r"[;:{}<>\\]", tok) or tok[0].isdigit()]
        if len(toks) > 2 and len(toks[0]) <= 4 and toks[1].lower().startswith(toks[0].lower()[:2]) and toks[0] != toks[1]:
            toks = toks[1:]  # OCR-Störwort vor dem Namen ("Ber Bergjausenkäse")
        q = None
        q_idx = None
        for i, tok in enumerate(toks):
            if i == 0:
                continue
            if re.fullmatch(r"\d+[)}\]]", tok) or COUNTRY.match(tok):
                continue
            if tok[0].isdigit() or tok.lower() in ("sg",):
                q = _ocr_qty(tok, " ".join(toks[:i]))
                if q:
                    q_idx = i
                    q = _check_columns(q, toks[i + 1:i + 3], " ".join(toks[:i]))
                    break
        name_toks = toks[:q_idx] if q_idx else toks
        name = P.strip_allergen_marks(" ".join(t for t in name_toks if not COUNTRY.match(t)))
        name = re.sub(r"\s+\b(?:ES|NL|DE|NZ)\b", "", name).strip(" |")
        if not name:
            continue
        if q is None:
            if out and out[-1]["name"].count("„") > out[-1]["name"].count("“"):
                out[-1]["name"] = (out[-1]["name"] + " " + name.split(" ")[0]).strip()
                continue
            if re.search(r"angaben|geschmack|text|beachte", name, re.I):
                continue
            out.append({"name": name, "qty": None, "unit": "", "raw": t, "pantry": False})
            continue
        qty, unit = q
        ing = {"name": name, "qty": qty, "unit": unit or ("" if qty is None else "Stk"), "raw": t, "pantry": False}
        out.append(P.fix_garlic(ing))
    for i in out:
        i["name"] = i["name"].replace("„", "").replace("“", "").replace('"', "").strip()
        i["name"] = re.sub(r"^(Gewürzmischung|Gewürz)\s+(?=Hello)", "", i["name"])
        i["name"] = re.sub(r"(?i)^cr.{1,2}me\s*fra[iî]che$", "Crème fraîche", i["name"])
    return out


STEP_STOP = re.compile(
    r"was du benötigst|zutaten|guten appetit|gurten appetit|allergene|durchschnittliche|nährwert|brennwert|"
    r"für mehr|ursprungsl|bitte beachte|küchenutensilien|vergiss nicht|lade deine|hellofresh\.de|"
    r"angaben im text|nach geschmack|beachte die",
    re.I,
)


def _steps_from_pages(pages: list[dict], skip_until_ing: bool = True) -> list[dict]:
    steps = []
    for p_i, page in enumerate(pages):
        pars: dict[tuple, list[dict]] = {}
        for ln in page["lines"]:
            pars.setdefault((ln["block"], ln["par"]), []).append(ln)
        par_list = list(pars.values())
        band = max(1, page["height"] * 0.08)
        cur = None
        for par in par_list:
            first = par[0]["text"].strip()
            rest = " ".join(l["text"] for l in par[1:]).strip()
            is_title = (
                len(first) <= 34 and len(first.split()) <= 4 and first[:1].isupper()
                and not first.endswith((".", ",", ":")) and not re.search(r"\d{2}", first)
                and not first.replace(" ", "").isupper()
            )
            if is_title and not STEP_STOP.search(first):
                cur = {"title": first, "text": rest, "page": p_i, "top": par[0]["top"], "left": par[0]["left"]}
                steps.append(cur)
            elif is_title:
                cur = None
            elif cur is not None:
                body = " ".join(l["text"] for l in par)
                if STEP_STOP.search(body[:40]):
                    cur = None
                    continue
                cur["text"] = (cur["text"] + " " + body).strip()
        steps_page = [s for s in steps if s["page"] == p_i]
        for s in steps_page:
            s["key"] = (p_i, round(s["top"] / band), s["left"])
    def prose(t: str) -> bool:
        fillers = re.findall(r"\b(?:und|die|der|den|das|dem|mit|in|im|auf|bei|zu|ca|von|bis|ein|eine|einer)\b", t, re.I)
        return len(fillers) >= 2

    steps = [s for s in steps if len(s["text"]) > 25 and prose(s["text"])]
    steps.sort(key=lambda s: s["key"])
    return [{"title": s["title"], "text": re.sub(r"\s+", " ", s["text"])} for s in steps]


def parse_ocr(pages: list[dict], fallback_title: str) -> dict:
    all_lines = [ln["text"] for pg in pages for ln in pg["lines"]]
    all_text = "\n".join(all_lines)
    r: dict = {}
    # Titel: erste aussagekräftige Zeile (Logo-Wörter entfernen)
    hint = ""
    for idx, ln in enumerate(all_lines[:15]):
        t = re.sub(r"^(?:[A-ZÄÖÜ]{2,8}\s+)+(?=[A-ZÄÖÜ][a-zäöüß])", "", ln).strip()
        if re.fullmatch(r"(HELLO|FRESH|\W)+", ln.strip()) or len(t) < 8 or not re.search(r"[a-zäöü]{3}", t):
            continue
        if re.search(r"minuten|kcal|personen", t, re.I):
            continue
        r["title"] = t
        for nxt in all_lines[idx + 1: idx + 3]:
            n = re.sub(r"^(?:[A-ZÄÖÜ]{2,8}\s+)+", "", nxt).strip()
            if re.match(r"^(mit|dazu|und|an|auf)\b", n):
                r["subtitle"] = n
            if re.search(r"minuten|kcal", n, re.I):
                hint = n
        break
    # Zutaten
    lines = all_lines
    start = next((i for i, l in enumerate(lines) if re.match(r"\s*Zutaten\b", l)), None)
    ings: list[dict] = []
    if start is not None:
        end = next((i for i in range(start + 1, len(lines)) if re.search(r"gut,?\s*im haus|durchschnittliche|nährwerte|^\s*\*\*?beachte", lines[i], re.I)), len(lines))
        ings = _parse_ocr_table(lines[start + 1:end])
        for l in lines[end:end + 4]:
            if "*" in l and "," in l and not re.search(r"im haus|beachte", l, re.I):
                ings += _parse_ocr_table([l])
    if not ings:
        sec = None
        for l in lines:
            if re.search(r"von uns bekommst|^zutaten", l, re.I):
                sec = False
                continue
            if re.search(r"zu hause benötigst|im haus", l, re.I):
                sec = True
                continue
            if re.search(r"utensilien|zubereitung|allergene", l, re.I):
                sec = None
                continue
            if sec is not None and re.match(r"^\s*[•\-*]?\s*\d", l):
                ing = P.parse_ing_line(l, sec)
                if ing and not UTENSILS.search(ing["name"]):
                    ings.append(ing)
    for i in ings:
        if re.fullmatch(r"(?:Gewürzmischung\s+)?Hello", i["name"]):
            m = re.search(r"Hello\s+([A-ZÄÖÜ][a-zäöüß]+(?:\s+[A-ZÄÖÜ][a-zäöüß]+)?)", all_text)
            if m:
                i["name"] = "Hello " + m.group(1)
    r["ingredients"] = ings
    r["steps"] = _steps_from_pages(pages)
    return finish(r, all_text, fallback_title, hint)


# ---------------------------------------------------------------- Einstieg

def read_file(path: Path, filename: str, lang: str = "deu") -> tuple[dict, list[str]]:
    from .text_utils import title_from_filename

    fallback = title_from_filename(filename)
    warnings: list[str] = []
    is_pdf = filename.lower().endswith(".pdf")
    if is_pdf:
        blocks = pdf_blocks(path)
        text_len = sum(len(b["text"]) for b in blocks)
        if text_len > 300:
            rec = parse_text_pdf(blocks, fallback)
            if rec and len(rec["ingredients"]) >= 3:
                return rec, warnings
            warnings.append("Textebene gefunden, aber Aufbau nicht erkannt – Texterkennung verwendet.")
    pages = ocr_pages(path, is_pdf, lang)
    rec = parse_ocr(pages, fallback)
    if len(rec["ingredients"]) < 3:
        warnings.append("Nur wenige Zutaten erkannt – bitte prüfen und ergänzen.")
    return rec, warnings


def read_text(text: str, source: str = "") -> tuple[dict, list[str]]:
    lines = [l.strip() for l in text.splitlines()]
    title = next((l for l in lines if l), "Rezept")[:120]
    ings, steps, sec = [], [], "ing"
    for l in lines[1:]:
        if not l:
            continue
        if re.search(r"^(zutaten|einkaufsliste)", l, re.I):
            sec = "ing"
            continue
        if re.search(r"^(zubereitung|anleitung|so geht|schritte)", l, re.I):
            sec = "steps"
            continue
        if sec == "ing" and re.match(r"^[•\-*]?\s*([\d½¼¾]|eine?\b|etwas|prise)", l, re.I):
            ing = P.parse_ing_line(l)
            if ing:
                ings.append(ing)
        elif sec == "steps" or len(l) > 60:
            sec = "steps"
            steps.append({"title": "", "text": re.sub(r"^\d+[.)]\s*", "", l)})
    r = {"title": title, "ingredients": ings, "steps": steps, "provider": source or "Sonstige"}
    rec = finish(r, text, title)
    if source:
        rec["provider"] = source[:40]
    warn = [] if len(ings) >= 3 else ["Wenige Zutaten erkannt – Zeilen sollten mit einer Menge beginnen."]
    return rec, warn
