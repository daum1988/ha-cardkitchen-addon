# Kartenküche – Home Assistant add-on

Turn your meal-kit recipe cards (HelloFresh, Marley Spoon, Dinnerly, …) and any other recipes into a
weekly meal plan with a shopping list. The planner prefers dishes that share ingredients so fewer
opened packs go to waste. The UI is in German.

Rezeptkarten von HelloFresh, Marley Spoon, Dinnerly und anderen Quellen einlesen, katalogisieren und
daraus einen Wochenplan mit Einkaufszettel erstellen – mit Resteverwertung zwischen den Gerichten.

![Kartenküche](cardkitchen/logo.png)

## Funktionen

- **Karten einlesen**: PDFs, Scans und Fotos; Rezepte von Webseiten als Text einfügen
  - kostenlos und lokal per Texterkennung (Tesseract)
  - oder genauer mit Claude über deinen eigenen Anthropic-API-Schlüssel
- **Katalog** mit Kategorien, Hauptzutat, Küche, Allergenen, Bewertung und Prüfansicht
- **Wochenplan** nach Vorlieben, mit Optimierung auf gemeinsame Zutaten und einem Reste-Radar
- **Einkaufszettel** nach Supermarkt-Gängen, Übergabe an Home-Assistant-Aufgabenlisten
- Zutaten der **HelloFresh-Gewürzmischungen** auf dem Zettel

## Installation

[![Repository hinzufügen](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fdaum1988%2Fha-cardkitchen-addon)

1. In Home Assistant: **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories** und
   `https://github.com/daum1988/ha-cardkitchen-addon` hinzufügen.
2. **Kartenküche** installieren, starten und „In Seitenleiste anzeigen“ aktivieren.

Unterstützt: `amd64`, `aarch64`. Details stehen in der [Dokumentation](cardkitchen/DOCS.md).

## Datenschutz

Deine Rezepte und Karten liegen nur im Datenordner des Add-ons auf deinem Home Assistant. Dieses
Repository enthält keine Rezepte. Mit dem kostenlosen Leser verlässt nichts dein Netzwerk.

## Entwicklung

```bash
cd cardkitchen
pip install -r requirements.txt pytest
CK_DATA_DIR=./devdata python3 -m app.main   # http://localhost:8099
```

Für den kostenlosen Leser werden `tesseract` (mit deutschen Sprachdaten) und `poppler-utils`
benötigt. Tests: `pytest` im Repo-Hauptordner.

## Lizenz

GPL-3.0. Die Gewürzmischungs-Daten stammen aus
[Schischu/hello_fresh_gewuerze](https://github.com/Schischu/hello_fresh_gewuerze) (GPL-3.0).
HelloFresh, Marley Spoon und Dinnerly sind Marken ihrer Inhaber; dieses Projekt steht in keiner
Verbindung zu ihnen.
