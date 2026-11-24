# Kartenküche

Kartenküche liest deine Rezeptkarten von HelloFresh, Marley Spoon, Dinnerly und anderen Quellen ein,
sortiert sie in einen Katalog und plant daraus eine Woche. Der Planer bevorzugt Gerichte, die sich
Zutaten teilen, damit von angebrochenen Packungen möglichst wenig übrig bleibt. Dazu gibt es einen
Einkaufszettel, sortiert nach Supermarkt-Gängen, den du an eine Home-Assistant-Liste schicken kannst.

## Einrichtung

1. Add-on installieren und starten.
2. „In Seitenleiste anzeigen“ einschalten. Die App erscheint als **Kartenküche** in der Seitenleiste.
3. Optional: einen Anthropic-API-Schlüssel eintragen (siehe unten).

Die App läuft über Home Assistant (Ingress). Es wird kein zusätzlicher Port geöffnet; der Zugriff von
unterwegs funktioniert überall dort, wo du auch Home Assistant erreichst, z. B. über Nabu Casa oder
einen Cloudflare-Tunnel, und in der Home-Assistant-App.

## Karten einlesen

Unter **Karten einlesen** PDFs, Scans oder Fotos ablegen, auch mehrere auf einmal. Rezepte aus anderen
Quellen (Webseiten, Mails, Kochbücher) lassen sich als Text einfügen oder abfotografieren.

Zwei Leser stehen zur Wahl:

| | Kostenlos (lokal) | Claude |
|---|---|---|
| Kosten | keine | wenige Cent pro Karte über deinen API-Schlüssel |
| Läuft | auf deinem Home Assistant | bei Anthropic (Karte wird dorthin gesendet) |
| PDFs mit Textebene (Marley Spoon, Dinnerly) | sehr gut | sehr gut |
| Scans und Fotos | gut bis mittel, je nach Bildqualität | sehr gut |

Jede eingelesene Karte ist zunächst **zu prüfen**. Ein Klick auf „Prüfen“ öffnet das Rezept zum
Korrigieren; die Originalkarte lässt sich daneben öffnen. Ist ein API-Schlüssel hinterlegt, kann jede
Karte später mit „Mit Claude neu einlesen“ noch einmal genauer gelesen werden.

Tipps für Fotos: Karte flach hinlegen, gerade von oben, gutes Licht, Vorder- und Rückseite als
getrennte Fotos oder gemeinsam als PDF-Scan.

## Fotos

Beim Einlesen übernimmt Kartenküche das Foto des fertigen Gerichts aus der Karte: bei PDFs mit
Textebene das eingebettete Foto in voller Qualität, bei Scans und Fotos wird die Fotofläche
ausgeschnitten. Wurde kein Foto erkannt oder passt der Ausschnitt nicht, lässt sich in der
Bearbeitung ein eigenes Foto hochladen oder das vorhandene entfernen.

## Optionen

| Option | Bedeutung |
|---|---|
| `default_reader` | Voreinstellung für neue Karten: `local` (kostenlos) oder `claude`. |
| `anthropic_api_key` | Optionaler Schlüssel von [console.anthropic.com](https://console.anthropic.com). Ein claude.ai-Abo enthält **keinen** API-Zugang; die API wird getrennt nach Verbrauch abgerechnet. |
| `claude_model` | `claude-opus-5-5` (am genauesten), `claude-sonnet-5-5` (günstiger), `claude-haiku-5-5` (am günstigsten). |
| `ocr_language` | Sprache für die Texterkennung des kostenlosen Lesers. |

## Wochenplan

Unter **Wochenplan** stellst du ein:

- Kochtage (ergibt die Anzahl der Gerichte) und Portionen
- maximale Kochzeit, worauf du Lust hast und was diese Woche nicht sein soll
- Hauptzutaten, Allergene und Zutaten, die ausgeschlossen werden
- wie viele Gerichte mindestens vegetarisch sein sollen
- wie stark Reste verwertet werden sollen

Einzelne Tage lassen sich fixieren, tauschen oder als gekocht markieren. Gerichte mit Fisch und
frischen Kräutern plant die App an den Anfang der Woche. Der **Reste-Radar** zeigt, was nach typischen
Supermarkt-Packungsgrößen übrig bleibt und welche Rezepte aus deinem Katalog es verwerten würden.

## Einkaufszettel

Mengen werden auf deine Portionen umgerechnet und nach Gängen sortiert. Was unter „Immer zu Hause“
steht, landet unter „Vorrat prüfen“. Bei HelloFresh-Gewürzmischungen steht dabei, was drin ist.
Mit **Offene Posten senden** gehen alle nicht abgehakten Posten in eine Aufgabenliste von Home
Assistant (z. B. die Einkaufsliste).

## Deine Daten

Rezepte, Plan, Fotos und Originalkarten liegen ausschließlich im privaten Datenordner des Add-ons auf deinem
Home Assistant und sind in dessen Backups enthalten. Sie sind nie Teil dieses Repositorys. Über
**Sicherung mit Fotos (ZIP)** bekommst du zusätzlich alle Rezepte samt Fotos als Datei. Beim
Einlesen sehr großer Sicherungen über einen Tunnel (z. B. Cloudflare, Limit 100 MB pro Anfrage) die
JSON-Datei und den Foto-Ordner getrennt einlesen („Foto-Ordner nachladen“) oder im Heimnetz arbeiten.

Mit dem kostenlosen Leser verlässt nichts dein Netzwerk. Mit Claude wird die jeweilige Karte bzw. der
eingefügte Text an die Anthropic-API gesendet.

## Quellen und Lizenz

Die Zutatenliste der HelloFresh-Gewürzmischungen stammt aus
[Schischu/hello_fresh_gewuerze](https://github.com/Schischu/hello_fresh_gewuerze) (GPL-3.0).
Kartenküche steht ebenfalls unter der GPL-3.0. HelloFresh, Marley Spoon und Dinnerly sind Marken
ihrer Inhaber; dieses Projekt steht in keiner Verbindung zu ihnen.
