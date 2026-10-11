"""Paten und Zeugen den Personen zuordnen, aber nur eindeutig.

    nach dem Verknuepfen: verknuepfen() ruft zuordnen(con)
    in der GEDCOM:        ASSO + RELA (Pate, Trauzeuge, Zeuge) beim Taeufling, den Brautleuten, dem Verstorbenen

Paten und Zeugen stehen nur mit Namen da, ohne Eltern und Daten. Darum wird hier
nicht gerechnet wie beim Verknuepfen, sondern nur gesucht:

    gleicher Lautschluessel des Nachnamens (oder Ehenamens) und gleiche Vornamensform,
    am Tag des Eintrags mindestens 14 Jahre alt (wenn das Geburtsjahr bekannt ist) und nicht tot,
    keine der Hauptpersonen des Eintrags (Taeufling, Eltern, Brautleute, Verstorbener),
    und genau eine solche Person im ganzen Bestand.

Gibt es keine oder mehrere, bleibt der Pate nur Text (NOTE und Tabellenzeile). Eine
falsche Verbindung waere schlimmer als eine fehlende.
"""
from . import lesen, normalform as nf

FELDER = {"taufe": [("paten", "Pate")], "ehe": [("zeugen", "Trauzeuge")], "tod": [("zeugen", "Zeuge")]}
MINDESTALTER = 14


def einzeln(text):
    """'Weiß, Christoph; Bauer | Haag, Anna' -> ['Weiß, Christoph, Bauer', 'Haag, Anna']"""
    return [t.replace(";", ",").strip() for t in (text or "").split(lesen.TRENNER) if t.strip()]


def zuordnen(con):
    """Tabelle beteiligt neu fuellen. Gibt (genannt, zugeordnet) zurueck."""
    con.execute("DELETE FROM beteiligt")
    nach_schl = {}
    for i in con.execute("SELECT id, name_schl, ehename, vorname_kanon, geb_jahr, tod_jahr FROM identitaet"):
        for s in {i["name_schl"], nf.koelner(i["ehename"]) or None} - {None}:
            nach_schl.setdefault((s, i["vorname_kanon"]), []).append(dict(i))
    haupt = {}
    for r in con.execute("SELECT p.eintrag, z.ident FROM person p JOIN zuordnung z ON z.person=p.id"):
        haupt.setdefault(r["eintrag"], set()).add(r["ident"])
    zeilen, genannt = [], 0
    for e in con.execute("SELECT e.id, e.register, e.jahr FROM eintrag e"):
        fl = {f["name"]: f["wert"] for f in con.execute("SELECT name, wert FROM feld WHERE eintrag=? AND wert IS NOT NULL", (e["id"],))}
        for feld, art in FELDER.get(e["register"], []):
            for nr, text in enumerate(einzeln(fl.get(feld) or fl.get(feld + "_kb")), start=1):
                genannt += 1
                p = nf.person_zerlegen(text)
                schl, vk = nf.koelner(p["name"]), nf.vorname_kanon(p["vorname"])
                kand = [] if not schl or not vk or p["unbekannt"] else [
                    i for i in nach_schl.get((schl, vk), [])
                    if i["id"] not in haupt.get(e["id"], ())
                    and not (e["jahr"] and i["geb_jahr"] and e["jahr"] - i["geb_jahr"] < MINDESTALTER)
                    and not (e["jahr"] and i["tod_jahr"] and i["tod_jahr"] < e["jahr"])]
                ident = kand[0]["id"] if len(kand) == 1 else None
                grund = (f"einzige Person {p['vorname']} {p['name']} im Bestand, die passt" if ident else
                         f"{len(kand)} Personen passen" if kand else "keine Person passt")
                zeilen.append((e["id"], art, nr, text, ident, grund))
    con.executemany("INSERT INTO beteiligt(eintrag, art, nr, text, ident, grund) VALUES (?,?,?,?,?,?)", zeilen)
    con.commit()
    return genannt, sum(1 for z in zeilen if z[4])
