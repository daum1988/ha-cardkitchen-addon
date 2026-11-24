"""Claude-Leser: schickt die Karte (PDF, Foto oder Text) mit dem eigenen API-Schlüssel an Claude.

Die Antwort ist per JSON-Schema festgelegt (structured outputs), sodass immer ein gültiges Rezept
zurückkommt. Kosten trägt das Anthropic-Konto des Schlüssels.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
from pathlib import Path

import anthropic

from . import parsing as P

log = logging.getLogger(__name__)

# Modelle, für die serverseitige Ausweichmodelle bei einer Ablehnung verfügbar sind.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}


class ClaudeError(Exception):
    """Fehler, dessen Text dem Nutzer angezeigt werden kann."""


def _nullable(t: str) -> dict:
    return {"anyOf": [{"type": t}, {"type": "null"}]}


SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "provider": {"type": "string"},
        "servings": {"type": "integer"},
        "timeMin": _nullable("integer"),
        "timeMax": _nullable("integer"),
        "kcal": _nullable("integer"),
        "protein": {"type": "string", "enum": P.PROTEINS},
        "categories": {"type": "array", "items": {"type": "string", "enum": P.CATEGORIES}},
        "cuisine": {"type": "string", "enum": P.CUISINES},
        "allergens": {"type": "array", "items": {"type": "string", "enum": P.ALLERGENS}},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "qty": _nullable("number"),
                    "unit": {"type": "string", "enum": P.UNITS},
                    "raw": {"type": "string"},
                    "pantry": {"type": "boolean"},
                },
                "required": ["name", "qty", "unit", "raw", "pantry"],
                "additionalProperties": False,
            },
        },
        "photo": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "properties": {
                        "page": {"type": "integer"},
                        "left": {"type": "number"}, "top": {"type": "number"},
                        "right": {"type": "number"}, "bottom": {"type": "number"},
                    },
                    "required": ["page", "left", "top", "right", "bottom"],
                    "additionalProperties": False,
                },
            ]
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
                "required": ["title", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "subtitle", "provider", "servings", "timeMin", "timeMax", "kcal", "protein",
                 "categories", "cuisine", "allergens", "ingredients", "photo", "steps"],
    "additionalProperties": False,
}

INSTRUCTIONS = """Lies das Rezept vollständig aus. Es kann eine Kochbox-Rezeptkarte (HelloFresh, Marley Spoon, Dinnerly o. ä.), eine Kochbuchseite, ein Foto oder kopierter Text von einer Webseite sein.

Regeln:
- title: nur der Haupttitel; subtitle: die Zeile darunter (z. B. "mit Mais und gebratenen Pilzen"), sonst leer.
- provider: der Anbieter bzw. die Quelle (HelloFresh, Marley Spoon, Dinnerly, Webseitenname, Kochbuchtitel) oder "Sonstige".
- servings: die kleinste Portionsspalte der Karte (meist 2) bzw. die Portionszahl des Rezepts. Alle Mengen gelten für genau diese Portionszahl.
- ingredients: ALLE Zutaten, auch die unter "Was du zu Hause benötigst"/"Gut im Haus zu haben" oder mit * markierten (dann pantry=true). "Salz und Pfeffer" als zwei Einträge. Keine Küchenutensilien.
- name: kurzer, normalisierter deutscher Grundname ohne Menge, Verpackung, Herkunftsland oder Allergen-Nummer, damit dieselbe Zutat auf verschiedenen Karten gleich heißt, z. B. "Lauchzwiebel", "Knoblauch", "Kartoffel", "Zwiebel", "Crème fraîche", "Petersilie", "Hähnchenbrust", "Champignons", "Kirschtomaten", "Gemüsebrühe", "Hartkäse", "getrocknete Tomaten". Gewürzmischungen mit ihrem Namen, z. B. "Hello Muskat", "Ras el Hanout". Kombinierte Kräuter wie "Basilikum/Petersilie 10 g" als zwei Einträge mit je der halben Menge.
- unit: Knoblauch immer "Zehe". Packungsangaben (Becher, Packung, Stückchen) möglichst realistisch in g oder ml umrechnen (z. B. 1 Becher Crème fraîche ≈ 150 g, 1 Packung Hähnchenbrustfilet für 2 Personen ≈ 300 g) und die Originalangabe in raw lassen. Gewürzmischungen in "Pck" oder g.
- qty: Zahl (Brüche dezimal, Spannen als Mittelwert) oder null bei "nach Geschmack".
- categories: 1–4 passende Kategorien. cuisine: die passendste Küche.
- steps: alle Zubereitungsschritte in Reihenfolge, Titel (falls vorhanden) und Text wörtlich, ohne Zeilenumbrüche.
- kcal: pro Portion. Zeiten in Minuten.
- photo: Lage des Fotos vom fertigen Gericht (nur das Foto, ohne Logo, Titel, Zutaten-Symbole oder Rand) als Anteile der Seite von 0 bis 1 (left/top/right/bottom) und die Seitennummer ab 1; null, wenn es kein Gerichtsfoto gibt oder nur Text vorliegt."""


def _content_for_file(path: Path, filename: str) -> list[dict]:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    if filename.lower().endswith(".pdf"):
        return [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}]
    mt = mimetypes.guess_type(filename)[0] or "image/jpeg"
    if mt not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        mt = "image/jpeg"
    return [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}}]


def _shrink_image(path: Path, filename: str) -> tuple[Path, str]:
    """Große Handyfotos verkleinern (Claude skaliert ohnehin auf ~1,2 MP herunter)."""
    if filename.lower().endswith(".pdf") or path.stat().st_size < 3_500_000:
        return path, filename
    from PIL import Image, ImageOps

    out = path.with_suffix(".claude.jpg")
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((2400, 2400))
        im.save(out, "JPEG", quality=88)
    return out, out.name


def _call(api_key: str, model: str, content: list[dict]) -> dict:
    client = anthropic.Anthropic(api_key=api_key, timeout=300.0, max_retries=2)
    params = dict(
        model=model,
        max_tokens=16000,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        if model in FALLBACK_MODELS:
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        else:
            resp = client.messages.create(**params)
    except anthropic.AuthenticationError as e:
        raise ClaudeError("Der API-Schlüssel wurde abgelehnt. Bitte in den Add-on-Einstellungen prüfen.") from e
    except anthropic.PermissionDeniedError as e:
        raise ClaudeError("Der API-Schlüssel hat keine Berechtigung für dieses Modell.") from e
    except anthropic.NotFoundError as e:
        raise ClaudeError(f"Modell „{model}“ nicht gefunden. Bitte ein anderes Modell in den Einstellungen wählen.") from e
    except anthropic.RateLimitError as e:
        raise ClaudeError("Zu viele Anfragen oder Guthaben aufgebraucht. Bitte später erneut versuchen.") from e
    except anthropic.BadRequestError as e:
        msg = getattr(e, "message", str(e))
        if "credit" in msg.lower():
            raise ClaudeError("Kein Guthaben mehr auf dem Anthropic-Konto.") from e
        raise ClaudeError(f"Claude hat die Anfrage abgelehnt: {msg}") from e
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Claude ist gerade nicht erreichbar (Fehler {e.status_code}).") from e
    except anthropic.APIConnectionError as e:
        raise ClaudeError("Keine Verbindung zu api.anthropic.com. Hat Home Assistant Internetzugang?") from e

    if resp.stop_reason == "refusal":
        raise ClaudeError("Claude hat diese Datei nicht verarbeitet. Bitte den kostenlosen Leser verwenden.")
    if resp.stop_reason == "max_tokens":
        raise ClaudeError("Die Antwort wurde abgeschnitten. Bitte die Karte einzeln einlesen.")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ClaudeError("Claude hat kein lesbares Rezept geliefert. Bitte erneut versuchen.") from e
    usage = getattr(resp, "usage", None)
    if usage:
        log.info("Claude %s: %s Eingabe- / %s Ausgabe-Tokens", resp.model, usage.input_tokens, usage.output_tokens)
    return data


def read_file(path: Path, filename: str, api_key: str, model: str, fallback_title: str) -> tuple[dict, dict | None]:
    """Liest die Karte; gibt das Rezept und die von Claude genannte Lage des Gerichtsfotos zurück."""
    p, fn = _shrink_image(path, filename)
    content = _content_for_file(p, fn) + [{"type": "text", "text": INSTRUCTIONS}]
    data = _call(api_key, model, content)
    photo = data.get("photo") if isinstance(data.get("photo"), dict) else None
    return P.clean_recipe(data, fallback_title), photo


def read_text(text: str, source: str, api_key: str, model: str) -> dict:
    prompt = INSTRUCTIONS
    if source:
        prompt += f"\n\nQuelle laut Nutzer: {source} (als provider verwenden)."
    content = [{"type": "text", "text": prompt + "\n\n<rezept>\n" + text[:60000] + "\n</rezept>"}]
    rec = P.clean_recipe(_call(api_key, model, content), "Rezept")
    if source:
        rec["provider"] = source[:40]
    return rec
