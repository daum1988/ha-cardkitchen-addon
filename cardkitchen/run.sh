#!/usr/bin/with-contenv sh
# Startet Kartenküche mit den Umgebungsvariablen des Add-ons (u. a. SUPERVISOR_TOKEN).
cd /opt/cardkitchen
exec python3 -m app.main
