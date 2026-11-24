# Changelog

## 0.2.1

- Große Sicherungen (ZIP mit Fotos) werden in Teilen zu 4 MB hochgeladen. Damit klappt das Einlesen
  auch über Home Assistant und Tunnel wie Cloudflare, die die Größe einzelner Uploads begrenzen.

## 0.2.0

- Fotos der fertigen Gerichte: werden beim Einlesen automatisch aus der Karte übernommen
  (eingebettetes Foto bei PDFs mit Text, ausgeschnitten bei Scans und Fotos, mit Claude über die
  von Claude erkannte Lage) und im Katalog, in der Detailansicht und im Wochenplan angezeigt.
- Foto pro Rezept ersetzen oder entfernen.
- Sicherung als ZIP mit Fotos; Einlesen von ZIP- und JSON-Sicherungen; Foto-Ordner nachladen.
- Datei-Verweise (Originalkarte, Foto) setzt nur noch der Server.

## 0.1.0

- Erste Version: Rezeptkarten einlesen (kostenlos per Texterkennung oder mit Claude), Katalog mit
  Prüfansicht, Wochenplan mit Resteverwertung, Einkaufszettel mit Übergabe an Home-Assistant-Listen.
