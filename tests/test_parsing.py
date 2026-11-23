"""Tests mit selbst geschriebenen Beispielzeilen (keine echten Karteninhalte)."""
from app import parsing as P
from app.reader_local import _ocr_qty, _parse_ocr_table, read_text
from app.text_utils import title_from_filename


def test_ingredient_lines():
    assert P.parse_ing_line("• 250g Champignons") == {"name": "Champignons", "qty": 250.0, "unit": "g", "raw": "• 250g Champignons", "pantry": False}
    i = P.parse_ing_line("1 Becher Crème fraîche 7")
    assert (i["qty"], i["unit"], i["name"]) == (1.0, "Becher", "Crème fraîche")
    i = P.parse_ing_line("1 Stückchen Hartkäse 3,7")
    assert (i["unit"], i["name"]) == ("Stk", "Hartkäse")
    i = P.parse_ing_line("1–2 EL Olivenöl", pantry=True)
    assert (i["qty"], i["unit"], i["pantry"]) == (1.5, "EL", True)
    i = P.parse_ing_line("2 Knoblauchzehen")
    assert (i["name"], i["unit"], i["qty"]) == ("Knoblauch", "Zehe", 2.0)


def test_salt_pepper_and_slash():
    ings = P.split_salt_pepper([{"name": "Salz und Pfeffer", "qty": None, "unit": "", "raw": "", "pantry": True}])
    assert [i["name"] for i in ings] == ["Salz", "Pfeffer"]
    ings = P.split_slash([{"name": "Basilikum/Petersilie", "qty": 10.0, "unit": "g", "raw": "", "pantry": False}])
    assert [(i["name"], i["qty"]) for i in ings] == [("Basilikum", 5.0), ("Petersilie", 5.0)]


def test_pack_conversion():
    ings = P.convert_packs([{"name": "Crème fraîche", "qty": 1.0, "unit": "Becher", "raw": "", "pantry": False}])
    assert (ings[0]["qty"], ings[0]["unit"]) == (150.0, "g")


def test_ocr_quantity_fixes():
    assert _ocr_qty("1508", "Crème fraîche") == (150.0, "g")
    assert _ocr_qty("108g", "Petersilie") == (10.0, "g")
    assert _ocr_qty("Sg", "Gemüsebrühe") == (8.0, "g")
    assert _ocr_qty("2,5g**", "Gewürz") == (2.5, "g")
    assert _ocr_qty("18", "Knoblauchzehe") == (1.0, "")
    assert _ocr_qty("2", "mehligk. Kartoffeln") == (2.0, "")


def test_ocr_table():
    rows = [
        "2P",
        "Paprika ES|NL 1",
        "Joghurt 5) 1508",
        "Gewürzmischung „Hello 5g**",
        "Paprika“ x",
        "Ber Bergkäse 508",
        "Öl*, Salz*",
    ]
    out = _parse_ocr_table(rows)
    got = [(i["name"], i["qty"], i["unit"], i["pantry"]) for i in out]
    assert got == [
        ("Paprika", 1.0, "Stk", False),
        ("Joghurt", 150.0, "g", False),
        ("Hello Paprika", 5.0, "g", False),
        ("Bergkäse", 50.0, "g", False),
        ("Öl", None, "", True),
        ("Salz", None, "", True),
    ]


def test_guessers():
    ings = [{"name": "Hähnchenbrust", "pantry": False}, {"name": "Couscous", "pantry": False}]
    assert P.guess_protein("Hähnchen mit Couscous", ings) == "Geflügel"
    assert P.guess_protein("Linsen-Dal", [{"name": "Linsen", "pantry": False}]) == "Vegan"
    assert "Suppe & Eintopf" in P.guess_categories("Kürbissuppe mit Brot", [])
    assert "Burger, Wrap & Brot" not in P.guess_categories("Kürbissuppe mit Baguette", [])


def test_filename_title():
    assert title_from_filename("cc237002-R-138228_-_Gnocchi_in_cremiger_Ka_sesauce-CV.pdf") == "Gnocchi in cremiger Käsesauce"


def test_read_text():
    rec, warn = read_text("Linsen-Dal\n\nZutaten\n200 g rote Linsen\n1 Zwiebel\n400 ml Kokosmilch\n\nZubereitung\nAlles in einem Topf mit dem Curry köcheln lassen, bis die Linsen weich sind.", "Testquelle")
    assert rec["title"] == "Linsen-Dal"
    assert [i["name"] for i in rec["ingredients"]] == ["rote Linsen", "Zwiebel", "Kokosmilch"]
    assert rec["provider"] == "Testquelle"
    assert rec["steps"]
