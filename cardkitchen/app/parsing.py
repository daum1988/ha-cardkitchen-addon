"""Gemeinsame Helfer: Vokabular, Zutaten-Zeilen parsen, Rezepte bereinigen."""
from __future__ import annotations

import re
import unicodedata

PROTEINS = ["Geflügel", "Rind", "Schwein", "Lamm", "Fisch & Meeresfrüchte", "Vegetarisch", "Vegan"]
CATEGORIES = [
    "Pasta & Gnocchi", "Reis & Getreide", "Kartoffeln", "Suppe & Eintopf", "Curry", "Salat & Bowl",
    "Burger, Wrap & Brot", "Ofengericht", "Pfannengericht", "Auflauf & Gratin", "Family",
    "Comfort Food", "Leicht",
]
CUISINES = ["Deutsch", "Italienisch", "Mediterran", "Orientalisch", "Asiatisch", "Indisch",
            "Mexikanisch", "Amerikanisch", "International"]
ALLERGENS = ["Gluten", "Krebstiere", "Eier", "Fisch", "Erdnüsse", "Soja", "Milch", "Schalenfrüchte",
             "Sellerie", "Senf", "Sesam", "Sulfite", "Lupinen", "Weichtiere"]
UNITS = ["g", "ml", "Stk", "Zehe", "Bund", "Dose", "Pck", "Becher", "EL", "TL", "Prise", "Glas", ""]

UNIT_MAP = {
    "g": "g", "gr": "g", "gramm": "g", "kg": "kg", "ml": "ml", "l": "l", "liter": "l",
    "el": "EL", "tl": "TL", "prise": "Prise", "prisen": "Prise",
    "stk": "Stk", "stück": "Stk", "stueck": "Stk", "stückchen": "Stk", "stange": "Stk", "stangen": "Stk",
    "knolle": "Stk", "kopf": "Stk", "scheibe": "Stk", "scheiben": "Stk",
    "zehe": "Zehe", "zehen": "Zehe", "bund": "Bund", "dose": "Dose", "dosen": "Dose",
    "packung": "Pck", "packungen": "Pck", "päckchen": "Pck", "pck": "Pck", "beutel": "Pck",
    "glas": "Glas", "becher": "Becher", "handvoll": "Handvoll",
}
_UNIT_RE = "|".join(sorted((re.escape(u) for u in UNIT_MAP), key=len, reverse=True))
ING_RE = re.compile(
    r"^(?P<q>[\d.,/½¼¾]+(?:\s*[–-]\s*[\d.,]+)?)?\s*(?P<u>(?:" + _UNIT_RE + r")\.?)?(?=\s|$)\s*(?P<n>.*)$",
    re.IGNORECASE,
)
ALLERGEN_WORDS = [
    ("Gluten", r"gluten|weizen"), ("Krebstiere", r"krebstier"), ("Eier", r"\beier?\b|eierzeug"),
    ("Fisch", r"\bfisch"), ("Erdnüsse", r"erdnuss|erdnüss"), ("Soja", r"\bsoja"),
    ("Milch", r"\bmilch|laktose"), ("Schalenfrüchte", r"schalenfr|\bnüsse"), ("Sellerie", r"sellerie"),
    ("Senf", r"\bsenf"), ("Sesam", r"\bsesam"), ("Sulfite", r"sulfit|sulphit|schwefeldioxid"),
    ("Lupinen", r"lupine"), ("Weichtiere", r"weichtier"),
]


def slug(text: str) -> str:
    t = (text or "rezept").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:60] or "rezept"


def norm_unit(u: str | None) -> str:
    if not u:
        return ""
    k = u.lower().rstrip(".")
    return UNIT_MAP.get(k, u if u in UNITS else "")


def parse_qty(s: str | None) -> float | None:
    if not s:
        return None
    s = s.replace("½", ".5").replace("¼", ".25").replace("¾", ".75").replace(",", ".").strip()
    m = re.match(r"([\d.]+)\s*[–-]\s*([\d.]+)", s)
    if m:
        try:
            return (float(m.group(1)) + float(m.group(2))) / 2
        except ValueError:
            return None
    m = re.match(r"^(\d+)/(\d+)$", s)
    if m and int(m.group(2)):
        return int(m.group(1)) / int(m.group(2))
    try:
        return float(s)
    except ValueError:
        return None


def strip_allergen_marks(name: str) -> str:
    """Entfernt Allergen-Nummern und Herkunftskürzel wie '3,7', '5)', 'ES | NL'."""
    n = re.sub(r"\s+\d+\s*[)}\]]", " ", name)
    n = re.sub(r"\b(?:[A-Z]{2}\s*\|\s*)+[A-Z]{2}\b", " ", n)
    n = re.sub(r"\s+\b(?:ES|NL|DE|NZ|IT|FR|PL|BE|AT|MA|PE|CL|ZA|EG)\b(?=\s|$)", " ", n)
    n = re.sub(r"\s+\d+(?:\s*,\s*\d+)*\s*$", "", n)
    n = re.sub(r"\s+", " ", n).strip(" ,;*")
    return n


def parse_ing_line(line: str, pantry: bool = False) -> dict | None:
    raw = line.strip()
    line = re.sub(r"^[•·\-–*]\s*", "", raw).strip()
    if not line:
        return None
    if line.endswith("*"):
        pantry = True
        line = line.rstrip("*").strip()
    m = ING_RE.match(line)
    qty, unit, name = None, "", line
    if m and (m.group("q") or m.group("u")) and m.group("n"):
        qty = parse_qty(m.group("q"))
        unit = norm_unit(m.group("u")) if m.group("u") else ("Stk" if m.group("q") else "")
        name = m.group("n")
    name = strip_allergen_marks(name.replace("*", ""))
    if not name:
        return None
    ing = {"name": name, "qty": qty, "unit": unit, "raw": raw, "pantry": pantry}
    return fix_garlic(ing)


def fix_garlic(ing: dict) -> dict:
    if re.search(r"knoblauch", ing["name"], re.I) and not re.search(r"knoblauch(öl|pulver|granulat|paste)", ing["name"], re.I):
        ing["name"] = "Knoblauch"
        if ing["unit"] in ("", "Stk"):
            ing["unit"] = "Zehe"
        if ing["qty"] is None:
            ing["qty"] = 1
    return ing


def split_salt_pepper(ings: list[dict]) -> list[dict]:
    out = []
    for i in ings:
        if re.fullmatch(r"salz\s*(und|&|,)\s*pfeffer", i["name"], re.I):
            out.append({**i, "name": "Salz", "qty": None, "unit": ""})
            out.append({**i, "name": "Pfeffer", "qty": None, "unit": ""})
        else:
            out.append(i)
    return out


# Typische Kochbox-Packungen in Gramm/Milliliter (2 Portionen), damit Mengen verschiedener Karten zusammenpassen.
PACK_SIZES = [
    (r"crème fraîche|creme fraiche|schmand|saure sahne", ("Becher",), 150, "g"),
    (r"sahne|kochsahne|schlagsahne", ("Becher",), 200, "ml"),
    (r"joghurt", ("Becher",), 150, "g"),
    (r"frischkäse", ("Becher", "Pck"), 150, "g"),
    (r"hartkäse|parmesan|grana padano", ("Stk",), 25, "g"),
    (r"getrocknete tomaten", ("Pck",), 40, "g"),
]


def convert_packs(ings: list[dict]) -> list[dict]:
    out = []
    for i in ings:
        for rx, units, size, unit in PACK_SIZES:
            if i["unit"] in units and re.search(rx, i["name"], re.I):
                i = {**i, "qty": (i["qty"] or 1) * size, "unit": unit}
                break
        out.append(i)
    return out


def split_slash(ings: list[dict]) -> list[dict]:
    """'Basilikum/Petersilie 10 g' → je 5 g Basilikum und Petersilie."""
    out = []
    for i in ings:
        m = re.fullmatch(r"([A-Za-zÄÖÜäöüß]{4,})\s*/\s*([A-Za-zÄÖÜäöüß]{4,})", i["name"])
        if m:
            q = i["qty"] / 2 if i["qty"] else None
            out.append({**i, "name": m.group(1), "qty": q})
            out.append({**i, "name": m.group(2), "qty": q})
        else:
            out.append(i)
    return out


def find_allergens(text: str) -> list[str]:
    low = text.lower()
    return [a for a, rx in ALLERGEN_WORDS if re.search(rx, low)]


MEAT = [
    ("Fisch & Meeresfrüchte", r"lachs|fisch|garnele|kabeljau|seelachs|thunfisch|forelle|scampi|dorade|zander|tintenfisch|muschel"),
    ("Geflügel", r"hähnchen|huhn|hühn|pute|chicken|ente\b|entenbrust"),
    ("Rind", r"rind|beef|steak|hackfleisch|hack\b|rinderhack"),
    ("Schwein", r"schwein|speck|bacon|schinken|chorizo|salami|bratwurst|krakauer|pancetta|gyros"),
    ("Lamm", r"lamm"),
]
ANIMAL = r"käse|milch|sahne|crème|creme|joghurt|quark|butter|\bei\b|eier|schmand|honig|mozzarella|feta|parmesan|halloumi"

CAT_RULES = [
    ("Suppe & Eintopf", r"suppe|eintopf|chili con|ramen|pho\b|minestrone"),
    ("Pasta & Gnocchi", r"gnocchi|pasta|nudel|spaghetti|penne|tagliatelle|linguine|fusilli|rigatoni|orzo|ravioli|tortellini|lasagne|maultasche"),
    ("Reis & Getreide", r"reis\b|risotto|couscous|bulgur|quinoa|reispfanne|paella|graupen|polenta"),
    ("Kartoffeln", r"kartoffel|püree|pommes|wedges|rösti|kroketten"),
    ("Curry", r"curry|dal\b|tikka|korma"),
    ("Salat & Bowl", r"salat|bowl"),
    ("Burger, Wrap & Brot", r"burger|wrap|taco|tortilla|quesadilla|sandwich|flammkuchen|pizza|baguette|fladenbrot|bao|burrito|fajita|naan"),
    ("Auflauf & Gratin", r"auflauf|gratin|überbacken|lasagne"),
    ("Ofengericht", r"ofen|gebacken|blech"),
    ("Pfannengericht", r"pfanne|gebraten|schnitzel|geschnetzelt|stir.?fry|bratnudel"),
]
CUISINE_RULES = [
    ("Indisch", r"tikka|masala|dal\b|garam|korma|naan|paneer|tandoori"),
    ("Asiatisch", r"soja|teriyaki|reisnudel|mie\b|udon|ramen|sesam|thai|bulgogi|kimchi|hoisin|sriracha|bao|pak choi|wok"),
    ("Mexikanisch", r"taco|tortilla|fajita|quesadilla|burrito|chili con|jalape|enchilada|hello fiesta"),
    ("Orientalisch", r"ras.?el.?hanout|couscous|harissa|za.?atar|bulgur|hummus|falafel|baharat|dukkah|shakshuka|sumach|tahin|mezze"),
    ("Italienisch", r"gnocchi|pasta|risotto|pesto|parmesan|mozzarella|tagliatelle|spaghetti|penne|lasagne|bruschetta|ciabatta|pizza|buon appetito"),
    ("Mediterran", r"feta|oliven|halloumi|souflaki|zucchini|aubergine|griechisch|mediterran"),
    ("Amerikanisch", r"burger|bbq|smokey|coleslaw|wedges|cajun"),
    ("Deutsch", r"schnitzel|spätzle|maultasche|bratwurst|rotkohl|sauerkraut|kartoffelsalat|frikadelle|knödel|rahm"),
]


def guess_protein(title: str, ings: list[dict], hint: str = "") -> str:
    h = hint.lower()
    if "vegan" in h:
        return "Vegan"
    names = " ".join(i["name"] for i in ings if not i.get("pantry")).lower() + " " + title.lower()
    for prot, rx in MEAT:
        if re.search(rx, names):
            return prot
    if "vegetarisch" in h:
        return "Vegetarisch"
    if not re.search(ANIMAL, names):
        return "Vegan"
    return "Vegetarisch"


def guess_categories(title: str, ings: list[dict], hint: str = "") -> list[str]:
    text = (title + " " + " ".join(i["name"] for i in ings)).lower()
    main = re.split(r"\s(?:mit|dazu|und|an|auf)\s", title.lower())[0]
    cats = [c for c, rx in CAT_RULES if re.search(rx, main)]
    if not cats:
        cats = [c for c, rx in CAT_RULES[:4] if re.search(rx, text)][:1]
    if "family" in hint.lower():
        cats.append("Family")
    return list(dict.fromkeys(cats))[:4]


def guess_cuisine(title: str, ings: list[dict]) -> str:
    text = (title + " " + " ".join(i["name"] for i in ings)).lower()
    for c, rx in CUISINE_RULES:
        if re.search(rx, text):
            return c
    return "International"


def detect_provider(text: str) -> str:
    low = text.lower()
    if "hellofresh" in low or re.search(r"hello\s*fresh", low):
        return "HelloFresh"
    if "marleyspoon" in low or "marley spoon" in low:
        return "Marley Spoon"
    if "dinnerly" in low:
        return "Dinnerly"
    if "kochzauber" in low:
        return "Kochzauber"
    return "Sonstige"


def _num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def clean_recipe(x: dict, fallback_title: str = "Rezept") -> dict:
    """Bringt ein Rezept aus beliebiger Quelle in das gespeicherte Format."""
    r: dict = {}
    r["title"] = str(x.get("title") or fallback_title).strip()[:160] or fallback_title
    r["subtitle"] = str(x.get("subtitle") or "").strip()[:200]
    r["provider"] = re.sub(r"\|.*", "", str(x.get("provider") or "Sonstige")).strip()[:40] or "Sonstige"
    r["servings"] = int(_num(x.get("servings")) or 2) or 2
    r["timeMin"] = int(_num(x.get("timeMin")) or 0) or None
    r["timeMax"] = int(_num(x.get("timeMax")) or 0) or r["timeMin"]
    r["kcal"] = int(_num(x.get("kcal")) or 0) or None
    ings = []
    for i in x.get("ingredients") or []:
        if not isinstance(i, dict) or not str(i.get("name") or "").strip():
            continue
        q = _num(i.get("qty"))
        ings.append({
            "name": str(i["name"]).strip()[:80],
            "qty": round(q, 3) if q else None,
            "unit": norm_unit(str(i.get("unit") or "")) or ("" if not i.get("unit") else str(i.get("unit"))[:10]),
            "raw": str(i.get("raw") or "")[:120],
            "pantry": bool(i.get("pantry")),
        })
    r["ingredients"] = ings
    r["protein"] = x.get("protein") if x.get("protein") in PROTEINS else guess_protein(r["title"], ings)
    r["categories"] = [c for c in (x.get("categories") or []) if c in CATEGORIES][:4]
    r["cuisine"] = x.get("cuisine") if x.get("cuisine") in CUISINES else ""
    r["allergens"] = [a for a in (x.get("allergens") or []) if a in ALLERGENS]
    steps = []
    for s in x.get("steps") or []:
        if isinstance(s, dict) and str(s.get("text") or "").strip():
            steps.append({"title": str(s.get("title") or "")[:80], "text": str(s["text"]).strip()[:2000]})
    r["steps"] = steps
    for k in ("rating", "lastCooked", "cookedCount", "review", "card", "source", "importedAt", "updatedAt", "reader"):
        if k in x and x[k] is not None:
            r[k] = x[k]
    return r
