"""Paten und Zeugen den Personen zuordnen, aber nur eindeutig.

    nach dem Verknuepfen: verknuepfen() ruft zuordnen(con)
    in der GEDCOM:        ASSO + RELA (Pate, Trauzeuge, Zeuge) beim Taeufling, den Brautleuten, dem Verstorbenen

Paten und Zeugen stehen nur mit Namen da, ohne Eltern und Daten. Darum wird hier
nicht gerechnet wie beim Verknuepfen, sondern nur gesucht. Eine Person passt, wenn

    der Nachname (oder Ehename) hoechstens einen Buchstaben abweicht (zwei bei langen
    Namen mit gleichem Anfang); der Lautschluessel allein reicht nicht (Heß ist nicht Haas),
    die Vornamensform gleich ist,
    sie selbst hoechstens 15 Jahre vor oder nach dem Eintrag in einem Eintrag steht
    (in einer Gemeinde mit viel Zu- und Wegzug ist "einzig im Bestand" sonst zu wenig),
    sie am Tag des Eintrags mindestens 14 Jahre alt ist (wenn das Geburtsjahr bekannt ist)
    und nicht tot,
    sie nicht schon verheiratet war, wenn die Angabe "ledig" oder "Jgfr." sagt,
    sie keine der Hauptpersonen des Eintrags ist (Taeufling, Eltern, Brautleute, Verstorbener),

und genau eine solche Person im ganzen Bestand passt. Gibt es keine oder mehrere,
bleibt der Pate nur Text (NOTE und Tabellenzeile). Eine falsche Verbindung waere
schlimmer als eine fehlende.
"""
import re

from . import lesen, normalform as nf

FELDER = {"taufe": [("paten", "Pate")], "ehe": [("zeugen", "Trauzeuge")], "tod": [("zeugen", "Zeuge")]}
MINDESTALTER = 14
NAEHE = 15                                     # Jahre zwischen Patenamt und einer eigenen Nennung
LEDIG = re.compile(r"\b(ledig|jgfr|jungfer|jungfrau|junggesell)", re.I)


def einzeln(text):
    """'Weiß, Christoph; Bauer | Haag, Anna' -> ['Weiß, Christoph, Bauer', 'Haag, Anna']"""
    return [t.replace(";", ",").strip() for t in (text or "").split(lesen.TRENNER) if t.strip()]


def name_passt(a, b):
    """Nachname gleich genug: hoechstens ein Buchstabe, bei langen Namen mit gleichem Anfang zwei."""
    if not a or not b:
        return False
    a, b = a.lower(), b.lower()
    d = nf.levenshtein(a, b)
    return d <= 1 or (d == 2 and max(len(a), len(b)) >= 7 and a[:3] == b[:3])


def zuordnen(con):
    """Tabelle beteiligt neu fuellen. Gibt (genannt, zugeordnet) zurueck."""
    con.execute("DELETE FROM beteiligt")
    nach_schl = {}
    for i in con.execute("SELECT id, name, name_schl, ehename, vorname_kanon, geb_jahr, tod_jahr FROM identitaet"):
        for s in {i["name_schl"], nf.koelner(i["ehename"]) or None} - {None}:
            nach_schl.setdefault((s, i["vorname_kanon"]), []).append(dict(i))
    haupt, jahre, heirat = {}, {}, {}
    for r in con.execute("SELECT p.eintrag, p.pfad, e.jahr, z.ident FROM person p JOIN zuordnung z ON z.person=p.id "
                         "JOIN eintrag e ON e.id=p.eintrag"):
        haupt.setdefault(r["eintrag"], set()).add(r["ident"])
        if r["jahr"]:
            jahre.setdefault(r["ident"], []).append(r["jahr"])
            if r["pfad"] in ("braeutigam", "braut"):
                heirat[r["ident"]] = min(heirat.get(r["ident"], 9999), r["jahr"])
    zeilen, genannt = [], 0
    for e in con.execute("SELECT e.id, e.register, e.jahr FROM eintrag e"):
        fl = {f["name"]: f["wert"] for f in con.execute("SELECT name, wert FROM feld WHERE eintrag=? AND wert IS NOT NULL", (e["id"],))}
        for feld, art in FELDER.get(e["register"], []):
            for nr, text in enumerate(einzeln(fl.get(feld) or fl.get(feld + "_kb")), start=1):
                genannt += 1
                p = nf.person_zerlegen(text)
                schl, vk = nf.koelner(p["name"]), nf.vorname_kanon(p["vorname"])
                j, ledig = e["jahr"], bool(LEDIG.search(text))
                kand = [] if not schl or not vk or p["unbekannt"] or not j else [
                    i for i in nach_schl.get((schl, vk), [])
                    if (name_passt(p["name"], i["name"]) or name_passt(p["name"], i["ehename"]))
                    and i["id"] not in haupt.get(e["id"], ())
                    and any(abs(j - x) <= NAEHE for x in jahre.get(i["id"], ()))
                    and not (i["geb_jahr"] and j - i["geb_jahr"] < MINDESTALTER)
                    and not (i["tod_jahr"] and i["tod_jahr"] < j)
                    and not (ledig and heirat.get(i["id"], 9999) < j)]
                ident = kand[0]["id"] if len(kand) == 1 else None
                grund = (f"einzige Person {p['vorname']} {p['name']} im Bestand, die passt" if ident else
                         f"{len(kand)} Personen passen" if kand else "keine Person passt")
                zeilen.append((e["id"], art, nr, text, ident, grund))
    con.executemany("INSERT INTO beteiligt(eintrag, art, nr, text, ident, grund) VALUES (?,?,?,?,?,?)", zeilen)
    con.commit()
    return genannt, sum(1 for z in zeilen if z[4])
