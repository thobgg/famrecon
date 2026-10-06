# Alle Ziele arbeiten auf einem Projekt: make PROJEKT=name ...   (Ordner daten/<name>/ wie in der Oberflaeche)
PROJEKT ?= kirchenbuchstil
P = daten/$(PROJEKT)
.PHONY: test sprachen bau gedcom gramps plausibilitaet beispiel messung start bundle

test:
	python3 -m unittest discover -s tests -t .
sprachen:
	for po in famrecon/sprachen/*/LC_MESSAGES/famrecon.po; do msgfmt -o $${po%.po}.mo $$po; done
start:
	python3 -m famrecon start
bau:                     # Tabellen in $(P)/ nach $(P)/zuordnung.toml einlesen und verknuepfen
	python3 -m famrecon bau $(P)/zuordnung.toml $$(ls $(P)/*.xlsx $(P)/*.csv 2>/dev/null) -o $(P)/projekt.db && python3 -m famrecon verknuepfen $(P)/projekt.db
gedcom:
	python3 -m famrecon gedcom $(P)/projekt.db -o $(P)/projekt.ged && python3 -m famrecon pruefe $(P)/projekt.db $(P)/projekt.ged
gramps:
	bash werkzeuge/gramps-pruefen.sh $(P)/projekt.ged -voll
plausibilitaet:
	python3 pruefungen/plausibilitaet.py $(P)/projekt.ged --zeigen 3
beispiel:                # das Kirchenbuchstil- Beispiel als Projekt anlegen
	mkdir -p daten/kirchenbuchstil && cp beispiel/kirchenbuchstil.xlsx daten/kirchenbuchstil/ && cp beispiel/kirchenbuchstil.toml daten/kirchenbuchstil/zuordnung.toml && $(MAKE) PROJEKT=kirchenbuchstil bau
messung:                 # Rundlauf an der Falkenrath-GEDCOM, optional RAUSCHEN=0.3
	bash werkzeuge/falkenrath-lauf.sh $(RAUSCHEN) 8
bundle:                  # Git-Bundle in werkzeuge/windows/ legen; den ganzen Ordner auf den Laptop kopieren
	git bundle create werkzeuge/windows/famrecon.bundle main && ls -la werkzeuge/windows/famrecon.bundle
