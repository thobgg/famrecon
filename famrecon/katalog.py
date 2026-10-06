"""Der Feldkatalog: welche Felder famrecon innen kennt, je Register.

Drei Raenge:
    pflicht       ohne das Feld laesst sich der Eintrag nicht verwenden
    verknuepfung  hilft, Personen ueber Register hinweg zu verbinden
    ergaenzend    wird mitgenommen und ausgegeben, entscheidet aber nichts

Felder haengen an Rollen. Jedes Register hat Hauptrollen (Taufe: kind,
vater, mutter; Ehe: braeutigam, braut; Tod: verstorbener), und eine Rolle
kann Unterrollen haben (die Braut ihren Vater, ihre Mutter, ihren vorigen
Mann). Der Feldname ist der Pfad: `braut_vater_name`. Jede Person darf als
EIN Feld kommen ("Haag, Nicolaus, Kutscher": `vater`) oder aufgeteilt
(`vater_name`, `vater_vorname`, `vater_beruf`); das Normalisieren fuehrt es
zusammen. Zwei Nachsilben sind ueberall erlaubt: `_kb` fuer die woertliche
Kirchenbuchform neben der normalisierten, `_praefix` fuer einen
Datumszusatz (CAL, ABT, BEF).

Die Synonyme dienen der Zuordnung: bekannte Ueberschriften aus Tabellen im
Kirchenbuchstil, aus technischen Erfassungstabellen (vn_vater_braeu), aus
verbreiteten Erfassungsvorlagen, aus ofb-werkstatt und aus englischen Tabellen.

    python3 -m famrecon.katalog            Katalog als Tabelle
"""

PFLICHT, VERKN, ERG = "pflicht", "verknuepfung", "ergaenzend"
SUFFIXE = ("kb", "praefix")

# Hauptrollen je Register, in der Reihenfolge der Tabelle.
HAUPTROLLEN = {"taufe": ["kind", "vater", "mutter"],
               "ehe": ["braeutigam", "braut"],
               "tod": ["verstorbener"]}
# Welche Rolle eine Ueberschrift ohne Rollenwort meint ("Vorname" in der Taufe = Kind).
STANDARDROLLE = {"taufe": "kind", "ehe": None, "tod": "verstorbener"}
# Unterrollen je Hauptrolle.
UNTERROLLEN = {"kind": [], "vater": [], "mutter": ["vater", "mutter"],
               "braeutigam": ["vater", "mutter", "vorehe"], "braut": ["vater", "mutter", "vorehe"],
               "verstorbener": ["vater", "mutter", "ehepartner"]}
# Erkennungswoerter je Rolle (klein, ohne Satzzeichen; "v mann" wird vorher zu "vormann").
ROLLENWORTE = {
    "kind": ["kind", "täufling", "taeufling", "child"],
    "vater": ["vater", "father"],
    "mutter": ["mutter", "mother"],
    "braeutigam": ["bräutigam", "brätigam", "braeutigam", "braeu", "groom", "husband"],
    "braut": ["braut", "bride", "wife"],
    "verstorbener": ["verstorbener", "verstorbene", "verst", "deceased"],
    "ehepartner": ["ehepartner", "ehemann", "ehefrau", "gatte", "gattin", "ehepart", "spouse"],
    "vorehe": ["vormann", "vorfrau", "voriger", "vorige", "erster", "erste", "previous"],
}

# Merkmale einer Person: (nachsilbe, rang, art, hilfe, synonyme)
MERKMALE = [
    ("",          VERKN, "person", "Nachname, Vorname und Zusatz in einem Feld", []),
    ("name",      VERKN, "text",   "Nachname", ["name", "nachname", "familienname", "fn", "surname", "last name"]),
    ("vorname",   VERKN, "text",   "Vorname(n)", ["vorname", "vornamen", "vn", "given", "given name", "first name", "rufname"]),
    ("geschlecht", VERKN, "geschlecht", "m/w", ["geschlecht", "geschl", "sex", "gender"]),
    ("beruf",     VERKN, "text",   "Beruf, Stand", ["beruf", "stand", "beruf u herkunft", "beruf herkunft", "occupation", "profession"]),
    ("beruf_ort", ERG,   "ort",    "Ort, an dem der Beruf ausgeuebt wird", ["ort beruf", "beruf ort", "wirkungsort"]),
    ("herkunft",  VERKN, "ort",    "Herkunft, Wohnort", ["herkunft", "wohnort", "ort", "aus", "von", "ort herkunft", "origin", "residence"]),
    ("alter",     VERKN, "alter",  "Alter", ["alter", "age"]),
    ("geburt_datum", VERKN, "datum", "Geburtsdatum", ["geb datum", "geburtsdatum", "geboren", "geb", "dat geburt", "birth", "born"]),
    ("geburt_ort", VERKN, "ort",   "Geburtsort", ["geb ort", "geburtsort", "ort geburt", "birthplace"]),
    ("stand",     ERG,   "text",   "Familienstand (ledig, verwitwet, verstorben …)", ["familienstand", "famstand", "status", "marital"]),
    ("konfession", ERG,  "text",   "Konfession", ["konfession", "religion", "rel"]),
    ("verzogen",  ERG,   "ort",    "wohin verzogen", ["verzogen", "weggezogen", "moved"]),
    ("totgeburt", ERG,   "text",   "Vermerk Totgeburt", ["art tod", "totgeburt", "todgeburt", "stillborn"]),
    ("bemerkung", ERG,   "text",   "Bemerkung zu dieser Person", ["notiz", "bemerkung", "anmerkung", "note", "notes"]),
    ("ref",       ERG,   "text",   "Kennung der Person in einer Quelle (Messung gegen eine Wahrheit)", ["ref", "referenz", "xref", "kennung", "id"]),
]
MERKMALE_JE_ROLLE = {
    "kind":         ["", "name", "vorname", "geschlecht", "verzogen", "totgeburt", "bemerkung", "ref"],
    "vater":        ["", "name", "vorname", "beruf", "beruf_ort", "herkunft", "stand", "konfession", "bemerkung", "ref"],
    "mutter":       ["", "name", "vorname", "beruf", "herkunft", "stand", "konfession", "bemerkung", "ref"],
    "braeutigam":   ["", "name", "vorname", "beruf", "beruf_ort", "herkunft", "alter", "geburt_datum", "geburt_ort", "stand", "konfession", "bemerkung", "ref"],
    "braut":        ["", "name", "vorname", "beruf", "beruf_ort", "herkunft", "alter", "geburt_datum", "geburt_ort", "stand", "konfession", "bemerkung", "ref"],
    "verstorbener": ["", "name", "vorname", "geschlecht", "beruf", "beruf_ort", "herkunft", "alter", "stand", "konfession", "bemerkung", "ref"],
    "ehepartner":   ["", "name", "vorname", "geschlecht", "beruf", "beruf_ort", "bemerkung", "ref"],
    "vorehe":       ["", "name", "vorname", "beruf", "beruf_ort", "herkunft", "bemerkung", "ref"],
}
UNTERROLLE_MERKMALE = ["", "name", "vorname", "beruf", "beruf_ort", "herkunft", "stand", "bemerkung", "ref"]
PFLICHTFELDER = {"taufe": ["kind_vorname"], "ehe": ["braeutigam_name", "braut_name"], "tod": ["verstorbener_name"]}

# Felder ausserhalb der Rollen: (name, rang, art, hilfe, synonyme)
ALLGEMEIN = [
    ("ort",        ERG, "ort",   "Pfarrort, Kirche", ["ort", "pfarrei", "parochie", "gemeinde", "kirche", "church", "parish"]),
    ("konfession", ERG, "text",  "Konfession des Registers", ["konfession", "religion", "rel"]),
    ("kb",         ERG, "text",  "Kirchenbuch, Band", ["kb", "kirchenbuch", "buch", "band", "quelle", "source", "register"]),
    ("seite",      ERG, "zahl",  "Seite", ["seite", "s", "page", "blatt", "bild"]),
    ("lfd_nr",     ERG, "zahl",  "Nummer des Eintrags auf der Seite", ["lfd nr", "lfdnr", "nr", "nummer", "no", "lfd"]),
    ("lfd_nr_gesamt", ERG, "zahl", "Fortlaufende Nummer des Autors", ["lfd nr gesamt", "id", "nr gesamt", "zähler"]),
    ("zitat",      ERG, "text",  "Fundstelle als Zitat", ["zitat", "fundstelle", "citation"]),
    ("jahr",       ERG, "zahl",  "Jahr (hilft, wenn das Datum unvollstaendig ist)", ["jahr", "year"]),
    ("pfarrer",    ERG, "text",  "Amtshandelnder", ["pfarrer", "taufender", "trauender", "geistlicher", "minister", "priest"]),
    ("bemerkung",  ERG, "text",  "Bemerkungen, Randvermerke zum Eintrag", ["bemerkung", "bemerkungen", "bem", "anmerkung", "notiz", "randvermerk", "note", "notes", "remarks"]),
]
REGISTER = {
    "taufe": [
        ("geburt_datum", PFLICHT, "datum", "Geburtsdatum (eines von Geburts-/Taufdatum ist Pflicht)",
         ["geb datum", "geburtsdatum", "geboren", "geb", "dat geburt", "birth", "born"]),
        ("tauf_datum", PFLICHT, "datum", "Taufdatum", ["tauf datum", "taufdatum", "taufe", "getauft", "dat taufe", "baptism", "christening"]),
        ("geburt_ort", VERKN, "ort", "Geburtsort", ["geb ort", "geburtsort", "ort geburt", "birthplace"]),
        ("tauf_ort",   ERG, "ort", "Taufort", ["tauf ort", "taufort", "ort taufe"]),
        ("unehelich",  VERKN, "text", "Vermerk unehelich (e/u)", ["unehelich", "status kind", "ehelich", "illegitimate"]),
        ("paten",      ERG, "liste", "Taufpaten und -zeugen, mehrere mit ; getrennt",
         ["pate", "paten", "taufpate", "taufpaten", "taufzeuge", "taufzeugen", "godparent", "godparents", "sponsor"]),
        ("sterbe_datum_rv", ERG, "datum", "Sterbedatum des Kindes als Rueckverweis",
         ["sterbe dat", "sterbedatum", "gestorben", "gest", "dat tod", "tod", "death"]),
        ("sterbe_ort_rv", ERG, "ort", "Sterbeort des Kindes als Rueckverweis", ["ort tod", "sterbeort"]),
        ("todesursache_rv", ERG, "text", "Todesursache des Kindes als Rueckverweis", ["ursache tod", "todesursache", "krankheit"]),
    ],
    "ehe": [
        ("trauung_datum", PFLICHT, "datum", "Trauungsdatum", ["datum", "trauung", "trauungsdatum", "heirat", "heiratsdatum", "getraut", "kopuliert", "dat trauung", "marriage", "date"]),
        ("trauung_ort", ERG, "ort", "Ort der Trauung", ["ort der trauung", "trauungsort", "ort trauung", "place"]),
        ("proklamation", ERG, "text", "Aufgebot", ["proklamation", "aufgebot", "banns"]),
        ("zeugen",     ERG, "liste", "Trauzeugen, mehrere mit ; getrennt", ["zeuge", "zeugen", "trauzeuge", "trauzeugen", "witness", "witnesses"]),
    ],
    "tod": [
        ("sterbe_datum", PFLICHT, "datum", "Sterbedatum (eines von Sterbe-/Begraebnisdatum ist Pflicht)",
         ["sterbe dat", "sterbedatum", "gestorben", "todesdatum", "tod", "dat tod", "death", "died"]),
        ("begraebnis_datum", PFLICHT, "datum", "Begraebnisdatum", ["beerd datum", "beerdigung", "begräbnis", "begraebnis", "begraben", "dat grab", "grab", "burial", "buried"]),
        ("sterbe_ort", ERG, "ort", "Sterbeort", ["sterbeort", "ort tod"]),
        ("begraebnis_ort", ERG, "ort", "Begraebnisort", ["begräbnisort", "ort grab", "friedhof"]),
        ("geburt_datum_rv", VERKN, "datum", "Geburtsdatum als Rueckverweis", ["geb datum", "geburtsdatum", "geboren", "dat geburt", "birth"]),
        ("tauf_datum_rv", ERG, "datum", "Taufdatum als Rueckverweis", ["tauf dat", "taufdatum", "baptism"]),
        ("todesursache", ERG, "text", "Krankheit, Todesursache", ["krankheit", "todesursache", "ursache", "ursache tod", "cause"]),
        ("zeugen",     ERG, "liste", "Zeugen", ["zeuge", "zeugen", "witness"]),
    ],
}
PFLICHT_GRUPPEN = {
    "taufe": [["kind_vorname"], ["geburt_datum", "tauf_datum"], ["vater", "vater_name", "mutter", "mutter_name"]],
    "ehe":   [["trauung_datum"], ["braeutigam", "braeutigam_name"], ["braut", "braut_name"]],
    "tod":   [["verstorbener", "verstorbener_name"], ["sterbe_datum", "begraebnis_datum"]],
}
LEITDATUM = {"taufe": ["geburt_datum", "tauf_datum"], "ehe": ["trauung_datum"], "tod": ["sterbe_datum", "begraebnis_datum"]}

_MERKMAL = {m[0]: m for m in MERKMALE}


def _rollenfelder(pfad, rolle, merkmale, register):
    out = {}
    for suffix in merkmale:
        _, rang, art, hilfe, syn = _MERKMAL[suffix]
        name = f"{pfad}_{suffix}" if suffix else pfad
        if name in PFLICHTFELDER.get(register, []):
            rang = PFLICHT
        out[name] = (rang, art, f"{pfad.replace('_', ' > ')}: {hilfe}", syn)
    return out


def felder(register):
    """Alle Felder eines Registers: {name: (rang, art, hilfe, synonyme)}."""
    out = {}
    for rolle in HAUPTROLLEN[register]:
        out.update(_rollenfelder(rolle, rolle, MERKMALE_JE_ROLLE[rolle], register))
        for unter in UNTERROLLEN[rolle]:
            merkmale = MERKMALE_JE_ROLLE[unter] if unter in ("ehepartner", "vorehe") else UNTERROLLE_MERKMALE
            out.update(_rollenfelder(f"{rolle}_{unter}", unter, merkmale, register))
    for name, rang, art, hilfe, syn in REGISTER[register] + ALLGEMEIN:
        out[name] = (rang, art, hilfe, syn)
    return out


def basisname(name):
    """'kind_vorname_kb' -> ('kind_vorname', 'kb'); ohne Nachsilbe -> (name, None)."""
    for s in SUFFIXE:
        if name.endswith("_" + s):
            return name[: -len(s) - 1], s
    return name, None


def bekannt(register, name):
    """Ist `name` (auch mit Nachsilbe _kb/_praefix) ein Feld dieses Registers?"""
    return basisname(name)[0] in felder(register)


def main():
    for register in REGISTER:
        print(f"\n== {register}")
        for name, (rang, art, hilfe, _) in felder(register).items():
            print(f"  {name:34} {rang:12} {art:10} {hilfe}")


if __name__ == "__main__":
    main()
