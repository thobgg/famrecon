#!/bin/bash
# Falkenrath-Messlauf: GEDCOM -> Register -> Zuordnung -> Projekt -> Verknuepfung -> Messung
set -e
cd "$(dirname "$0")/.."
R=${1:-0}
python3 -m famrecon simuliere beispiel/falkenrath.ged -o daten/falkenrath/register.xlsx --rauschen "$R" >/dev/null
python3 -m famrecon zuordnung daten/falkenrath/register.xlsx -o daten/falkenrath/zuordnung.toml >/dev/null
rm -f daten/falkenrath/projekt.db
python3 -m famrecon bau daten/falkenrath/zuordnung.toml daten/falkenrath/register.xlsx -o daten/falkenrath/projekt.db >/dev/null
python3 -m famrecon verknuepfen daten/falkenrath/projekt.db
python3 -m famrecon messen daten/falkenrath/projekt.db --zeigen "${2:-8}"
