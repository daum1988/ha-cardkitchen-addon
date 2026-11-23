"""Kleine Text-Helfer."""
from __future__ import annotations

import re
import unicodedata


def title_from_filename(name: str) -> str:
    """'R-138228_-_Gnocchi_in_cremiger_Ka_sesauce-CV.pdf' → 'Gnocchi in cremiger Käsesauce'."""
    n = unicodedata.normalize("NFC", name)
    n = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", n)
    n = re.sub(r"^[0-9a-f]{8}-", "", n)
    n = re.sub(r"^R-\d+_?-?_?", "", n)
    n = re.sub(r"-CV$", "", n)
    for a, b in (("a_", "ä"), ("o_", "ö"), ("u_", "ü"), ("A_", "Ä"), ("O_", "Ö"), ("U_", "Ü")):
        n = n.replace(a, b)
    n = n.replace("_", " ")
    n = re.sub(r"\s+", " ", n).strip(" -")
    return n or "Rezept"
