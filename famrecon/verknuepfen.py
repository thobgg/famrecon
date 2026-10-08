"""Verknuepfen: aus den Nennungen je Eintrag die realen Personen (Identitaeten) und Familien bilden.

    famrecon verknuepfen daten/projekt.db        Lauf; Ergebnis in identitaet, familie, kind, zuordnung
    famrecon familien daten/projekt.db           Familien mit Kindern zeigen
    famrecon pruefliste daten/projekt.db         offene Faelle zeigen

DAS SCHEMA (so liest man dieses Modul)
======================================

  Eingabe   person: je Eintrag und Rolle eine Nennung in Normalform (kern.py), mit name, vorname,
            name_schl (Koelner Phonetik), vorname_kanon (Einheitsform), geb (Jahr/Monat/Tag, bei
            Toten aus dem Alter gerechnet), stand, ref (Kennung), pfad (kind, vater, braut_vater ...).
  Zustand   Bestand: Identitaeten und Familien im Speicher, indiziert nach Lautschluessel des Nachnamens.
  Ablauf    alle Eintraege CHRONOLOGISCH, die drei Register gemischt, je Eintrag ein Schritt:

    Taufe       1. familie_finden(vater, mutter): gibt es eine Familie, deren Mann zum genannten Vater
                   passt und deren Frau der Mutter nicht widerspricht (und bei der Taufe noch lebte)?
                   Zwei gleich gute -> offen: eigene Familie, die Mutter (oder der Vater) mit den
                   Ehen als Alternativen in die Pruefliste.
                2. sonst Vater und Mutter einzeln suchen (finde) oder neu anlegen, neue Familie "eltern".
                3. Kind: immer neue Identitaet, Geburt = Geburtsdatum, sonst Taufdatum; Sterbedatum aus
                   einem Rueckverweis der Taufzeile gleich mit. Mit Kennung: an die vorgegebene Person.
    Trauung     Braeutigam und Braut je mit finde(...) suchen (Anker: Vorname, Alter, genannte Eltern,
                Heiratsalter); genannte Eltern werden ihre Elternfamilie (eltern_anbinden), ein voriger
                Ehepartner eine Vorehe. Dann Familie "ehe" anlegen oder eine "eltern"-Familie des Paares
                (Kinder vor der Trauung) zur Ehe machen.
    Begraebnis  Verstorbenen suchen (finde; bei Gleichstand offen: eigene Person, Kandidaten in die Pruefliste);
                Anker: Vorname, Geburt aus dem Alter, Vater, Ehepartner, Sterbedatum aus Rueckverweis.
                Dann die Nachpruefungen: Vetos (ledig/verheiratet), Kind ohne Anker -> eigene Person.
                Genannter Ehepartner wird gesucht oder angelegt, genannte Eltern angebunden.

  Bewertung person_punkte(i, p): Punkte fuer "Nennung p ist Identitaet i" oder None (ausgeschlossen).
            Ausschluss: Geschlecht widerspricht; Alter ausserhalb des Fensters der Rolle; Lebenslauf
            (geboren nach dem ersten Auftreten als Erwachsener); Vorname widerspricht (0 Punkte);
            errechnete und belegte Geburt mehr als MAX_GEB_DIFF Jahre auseinander.
            Punkte: siehe die Konstanten unten; die Gruende werden als Klartext mitgefuehrt.
  Entscheidung entscheiden(kandidaten, schwelle) -> Stufe:
            sicher          ein Anker ueber den Namen hinaus und kein Zweiter innerhalb ABSTAND_SICHER
            wahrscheinlich  ueber der Schwelle, kein Zweiter innerhalb ABSTAND_KLAR
            unsicher        ueber der Schwelle, aber ein Zweiter liegt naeher als ABSTAND_KLAR
            neu             kein Kandidat ueber der Schwelle
            vorgabe         eine Kennung (Feld ref) hat entschieden
  Grundsatz Keine Eindeutigkeit -> offen lassen, dokumentiert. Bei Gleichstand wird nie geraten:
            eigene Person bzw. Familie, Stufe "neu" mit den Kandidaten als Alternativen und dem Grund
            "offen, ..."; das erscheint in der Pruefliste, ein Urteil dort gilt beim naechsten Lauf.
            Ebenso ein Veto gegen einen Kandidaten mit Anker. Jeder Ausschluss wird je Regel gezaehlt
            (famrecon ausschluesse). Begraebnis eines Kindes nur mit Anker an eine
            Taufe. Mutter mit widersprechendem Vornamen: Veto fuer diese Familie. Vetos bei einem
            Kandidaten mit Anker machen ihn unsicher statt ihn zu verwerfen.
  Mensch    entscheidung: Urteile aus der Pruefliste, an der Tabellenzeile festgemacht (Datei, Blatt,
            Zeile, Rolle), ueberleben jeden Lauf und gehen der Rechnung vor (von_hand).
            Kennungen (Einstellung kennungen): gleiche Kennung = dieselbe Person, Widerspruch -> Pruefliste.
  Ausgabe   schreiben(): Tabellen identitaet, familie, kind, zuordnung (je Nennung: Identitaet, Stufe,
            Punkte, Grund, Alternativen fuer die Pruefliste). Zuletzt familien_zusammenlegen().

Die Punkte und Vetos stammen aus einer Vorgaenger-Pipeline, die an rund 2.800 echten Eintraegen
eingestellt wurde, und sind seither an zwei handgepruefte Ortsfamilienbuecher gemessen
(Praezision und Vollstaendigkeit ueber 0,9; Kinder zu ueber 98 % bei den richtigen Eltern).
Jede Aenderung an Regeln wird gegen diese Bestaende und gegen beispiel/falkenrath.ged gemessen,
bevor sie bleibt (tests/test_messung.py haelt die Untergrenzen).
"""
import json
from collections import Counter

from . import normalform as nf

# Ausschluesse je Regel, je Lauf neu gezaehlt: alle Faelle, und die, bei denen der Vorname gepasst haette
# (dort entscheidet die Regel wirklich). Ergebnis in einstellung 'ausschluesse', Anzeige: famrecon ausschluesse.
AUSSCHLUSS, AUSSCHLUSS_TREFFER = Counter(), Counter()
_RELEVANT = [False]


def _aus(regel, relevant=None):
    """Ausschluss zaehlen und None liefern (fuer `return _aus(...)` in den Bewertungen)."""
    AUSSCHLUSS[regel] += 1
    if _RELEVANT[0] if relevant is None else relevant:
        AUSSCHLUSS_TREFFER[regel] += 1
    return None

# ---------------------------------------------------------------- Stellschrauben
# Alle Zahlen, an denen die Verknuepfung haengt. Mehr sollen es nicht werden: Was sich damit nicht
# ausdruecken laesst, ist ein Sonderfall und gehoert in die Pruefliste, nicht in eine neue Regel.
P_VORNAME, P_VORNAME_TEIL = 100, 70      # Vorname gleich / teilweise gleich (Details: normalform.vornamen_punkte)
P_GEB_EXAKT, P_GEB_JAHR, P_GEB_NAH = 100, 50, 30   # Geburtsdatum exakt / Jahr gleich / Jahr bis MAX_GEB_DIFF daneben
P_VATER, P_MUTTER, P_PARTNER, P_TOD_RV = 30, 50, 50, 200   # genannter Vater, Mutter, Ehepartner passt; Sterbedatum = Rueckverweis
P_NAME_EXAKT = 20                        # Nachname buchstabengleich (nicht nur lautgleich)
SCHWELLE, SCHWELLE_TOD, SCHWELLE_NIEDRIG = 100, 80, 50   # Mindestpunkte: allgemein / Verstorbene / Partner und Vorehen
ABSTAND_SICHER, ABSTAND_KLAR = 50, 30    # Vorsprung vor dem Zweiten: ab 50 "sicher", unter 30 "unsicher" (Gleichstand)
MAX_GEB_DIFF = 5                         # Jahre zwischen gerechneter (Alter) und belegter Geburt, sonst nicht dieselbe Person
ALTER_VATER = (16, 75)                   # plausibles Alter in der Rolle beim Ereignis; ausserhalb: ausgeschlossen
ALTER_MUTTER = (15, 50)
ALTER_EHE = (14, 80)
MAX_KINDERSPANNE = 22                    # Jahre zwischen erstem und letztem Kind einer Familie


class Bestand:
    """Identitaeten und Familien im Speicher, nach Namensschluessel indiziert."""

    def __init__(self):
        self.idents, self.fams, self.kinder = {}, {}, {}
        self.by_schl = {}
        self.by_anfang = {}           # (erste zwei Buchstaben, Laenge//2) -> [ident]: fuer aehnliche Schreibungen
        self.fams_von = {}            # ident -> [familie] als Mann/Frau
        self.next_i = self.next_f = 1

    def neu_ident(self, p, pfad=None):
        """Neue Identitaet aus einer Nennung: Geburtsname wird Hauptname, der genannte Name dann Ehename; Lautschluessel und Vornamensform gleich mit; in die Namensindizes eintragen."""
        i = dict(id=self.next_i, geschlecht=p.get("geschlecht"), name=p.get("geburtsname") or p.get("name"),
                 vorname=p.get("vorname"), geburtsname=p.get("geburtsname"),
                 ehename=p.get("name") if p.get("geburtsname") else None, unbekannt=int(bool(p.get("unbekannt"))),
                 geb=None, geb_praefix=None, tod=None, famc=None, pfade=[], ref=None, erwachsen_ab=None)
        i["name_schl"] = nf.koelner(i["name"]) or None
        i["vorname_kanon"] = nf.vorname_kanon(i["vorname"]) or None
        self.next_i += 1
        self.idents[i["id"]] = i
        self._index(i)
        return i

    def _index(self, i):
        for s in {i["name_schl"], nf.koelner(i["ehename"]) or None} - {None}:
            self.by_schl.setdefault(s, []).append(i["id"])
        for n in {i["name"], i["ehename"]} - {None}:
            self.by_anfang.setdefault(self._anfang(n), []).append(i["id"])

    @staticmethod
    def _anfang(name):
        n = name.lower()
        return (n[:2], len(n) // 2)

    def name_setzen(self, i, name, geburtsname=None):
        """NN-Frau bekommt spaeter einen Namen: Index nachziehen."""
        i["name"] = geburtsname or name
        i["geburtsname"] = geburtsname or i["geburtsname"]
        i["name_schl"] = nf.koelner(i["name"]) or None
        i["unbekannt"] = 0
        self._index(i)

    def neu_fam(self, mann=None, frau=None, art="ehe", trauung=None, eintrag=None):
        """Neue Familie (art: ehe = Traueintrag, eltern = nur aus Taufen/Toden erschlossen); Mann und Frau in fams_von eintragen."""
        f = dict(id=self.next_f, mann=mann, frau=frau, art=art, tr=trauung, eintrag=eintrag, kinder=[])
        self.next_f += 1
        self.fams[f["id"]] = f
        for p in (mann, frau):
            if p:
                self.fams_von.setdefault(p, []).append(f["id"])
        return f

    def partner_setzen(self, f, rolle, ident):
        """Fehlenden Partner (NN-Frau, spaeter genannter Mann) in eine bestehende Familie setzen."""
        f[rolle] = ident
        self.fams_von.setdefault(ident, []).append(f["id"])

    def kind_setzen(self, f, ident):
        """Kind in die Familie haengen und famc der Identitaet setzen (eine Elternfamilie je Person)."""
        if ident not in f["kinder"]:
            f["kinder"].append(ident)
        self.idents[ident]["famc"] = f["id"]

    def kandidaten_name(self, name, schl, geschlecht=None):
        """Alle Identitaeten mit lautgleichem Nachnamen, dazu kleine Schreibvarianten (gleicher Anfang, aehnliche Laenge); Geschlecht muss passen, wenn beides bekannt."""
        ids = set(self.by_schl.get(schl or nf.koelner(name), []))
        # kleine Schreibdistanz ohne gleichen Schluessel (Bindermann/Bindemann): nur gleicher Anfang, aehnliche Laenge
        if name and len(name) >= 5:
            a, b = self._anfang(name)
            for bucket in ((a, b - 1), (a, b), (a, b + 1)):
                for i in self.by_anfang.get(bucket, []):
                    if i not in ids and (nf.namen_aehnlich(name, self.idents[i]["name"]) or nf.namen_aehnlich(name, self.idents[i]["ehename"])):
                        ids.add(i)
        return [self.idents[i] for i in ids if not geschlecht or not self.idents[i]["geschlecht"] or self.idents[i]["geschlecht"] == geschlecht]

    def zirkel(self, ident, fam):
        """Wuerde `ident` als Kind von `fam` sein eigener Vorfahre?"""
        vorfahren, offen = set(), [p for p in (fam["mann"], fam["frau"]) if p]
        while offen:
            cur = offen.pop()
            if cur in vorfahren:
                continue
            vorfahren.add(cur)
            famc = self.idents[cur]["famc"]
            if famc:
                offen += [p for p in (self.fams[famc]["mann"], self.fams[famc]["frau"]) if p]
        if ident in vorfahren:
            return True
        nach, offen = set(), [ident]
        while offen:
            cur = offen.pop()
            if cur in nach:
                continue
            nach.add(cur)
            for fid in self.fams_von.get(cur, []):
                offen += self.fams[fid]["kinder"]
        return bool({fam["mann"], fam["frau"]} & nach)

    def geb_jahr(self, i):
        """Geburtsjahr der Identitaet oder None."""
        return i["geb"][0] if i["geb"] else None


# ------------------------------------------------------------ Bewertung
def person_punkte(best, i, p, jahr, vater=None, mutter=None, partner=None, tod=None, vorname_pflicht=True, tot_erlaubt=False, alter=None):
    """Punkte fuer: Person p (Normalform) ist Identitaet i. -> (punkte, gruende) oder None bei Ausschluss.
    `alter` = (min, max): erlaubtes Alter der Identitaet beim Ereignisjahr (Vater bei Taufe, Brautleute ...)."""
    punkte, gruende = 0, []
    vp = nf.vornamen_punkte(p.get("vorname_kanon"), i["vorname_kanon"])
    _RELEVANT[0] = bool(vp)                                   # Vorname passt: ein Ausschluss entscheidet hier wirklich
    if alter and jahr and best.geb_jahr(i) and not (alter[0] <= jahr - best.geb_jahr(i) <= alter[1]):
        return _aus("Alter ausserhalb des Fensters der Rolle")
    if p.get("geschlecht") and i["geschlecht"] and p["geschlecht"] != i["geschlecht"]:
        return _aus("Geschlecht widerspricht")
    # Lebenslauf: wer schon als Erwachsener auftrat, kann nicht danach geboren sein (und umgekehrt)
    if p.get("geb") and i.get("erwachsen_ab") and p["geb"][0] > i["erwachsen_ab"] - ALTER_EHE[0]:
        return _aus("geboren nach erstem Auftreten als Erwachsener")
    if jahr and best.geb_jahr(i) and p.get("pfad") not in ("kind", "verstorbener") and jahr - best.geb_jahr(i) < ALTER_EHE[0]:
        return _aus("juenger als 14 in einer Erwachsenenrolle")
    if vp is None:
        if vorname_pflicht and p.get("vorname_kanon") and not i["vorname_kanon"] and not p.get("totgeburt"):
            return _aus("Kandidat ohne Vorname")
    elif vp == 0:
        return _aus("Vorname widerspricht")
    else:
        punkte += vp
        gruende.append("Vorname" if vp == 100 else "Vorname teils")
    if p.get("name") and i["name"] and p["name"].lower() == i["name"].lower():
        punkte += P_NAME_EXAKT
    if alter == ALTER_EHE and jahr and best.geb_jahr(i) and 18 <= jahr - best.geb_jahr(i) <= 32:
        punkte += 10; gruende.append("Heiratsalter")          # Zuenglein bei Namensvettern: der 23-Jaehrige vor dem 39-Jaehrigen
    gj = p.get("geb")[0] if p.get("geb") else None
    ij = best.geb_jahr(i)
    if gj and ij:
        if p["geb"] == i["geb"] and p["geb"][1] and p["geb"][2]:
            punkte += P_GEB_EXAKT; gruende.append("Geburtsdatum")
        elif abs(gj - ij) <= 1:
            punkte += P_GEB_JAHR; gruende.append("Geburtsjahr")
        elif abs(gj - ij) <= MAX_GEB_DIFF:
            punkte += P_GEB_NAH
        else:
            return _aus("Geburt weicht mehr als 5 Jahre ab")
    if jahr and i["tod"] and i["tod"][0] and i["tod"][0] < jahr and not p.get("verstorben") and not tot_erlaubt:
        if not (alter is ALTER_VATER and jahr - i["tod"][0] <= 1):
            return _aus("schon tot")                          # Ausnahme: Vater eines nachgeborenen Kindes
    if jahr and ij and not (0 <= jahr - ij <= 100):
        return _aus("aelter als 100")
    if tod and tod[0] and i["tod"] and i["tod"] == tod:
        punkte += P_TOD_RV; gruende.append("Sterbedatum aus Rueckverweis")
    if vater and i["famc"]:
        v = best.fams[i["famc"]]["mann"]
        if v and vater_passt(best.idents[v], vater):
            punkte += P_VATER; gruende.append("Vater")
        elif v and not nf.namen_aehnlich(best.idents[v]["name"], vater.get("name")):
            return _aus("anderer Vater")
    if mutter and i["famc"]:
        m = best.fams[i["famc"]]["frau"]
        if m and mutter_passt(best.idents[m], mutter) >= P_MUTTER:
            punkte += P_MUTTER; gruende.append("Mutter")
    # Wer mit der genannten Mutter verheiratet ist, ist der Vater, nicht das Kind (Johannes 1768 vs. Sohn Johann 1795)
    eltern_p = mutter if i["geschlecht"] == "M" else vater
    if eltern_p and not partner:
        for fid in best.fams_von.get(i["id"], []):
            f = best.fams[fid]
            pid = f["frau"] if f["mann"] == i["id"] else f["mann"]
            if pid and vater_passt(best.idents[pid], eltern_p):
                return _aus("mit der genannten Mutter verheiratet (ist der Vater)")
    if partner:
        for fid in best.fams_von.get(i["id"], []):
            f = best.fams[fid]
            pid = f["frau"] if f["mann"] == i["id"] else f["mann"]
            if pid and vater_passt(best.idents[pid], partner):
                punkte += P_PARTNER; gruende.append("Ehepartner")
                break
    return punkte, gruende


def vater_passt(i, p):
    """Genannter Vater/Partner p passt auf Identitaet i (Name aehnlich, Vorname nicht widerspruechlich)."""
    if not nf.namen_aehnlich(i["name"], p.get("name"), i["name_schl"]) and not nf.namen_aehnlich(i["ehename"], p.get("name")):
        return False
    vp = nf.vornamen_punkte(p.get("vorname_kanon"), i["vorname_kanon"])
    return vp is None or vp > 0


def widerspruch(i, p):
    """Echter Widerspruch zwischen Identitaet i und Nennung p: Nachname unaehnlich oder kein gemeinsamer Vornamensteil."""
    if p.get("name") and not p.get("unbekannt") and i["name"] and not i["unbekannt"] \
            and not nf.namen_aehnlich(i["name"], p["name"], i["name_schl"]) and not nf.namen_aehnlich(i["ehename"], p["name"]):
        return True
    return nf.vornamen_widerspruch(p.get("vorname_kanon"), i["vorname_kanon"])


def mutter_passt(i, p):
    """-> Punkte: 50 Name+Vorname, 30 NN-Frau mit gleichem Vornamen, 10 Mutter fehlt, -1 Veto bei Widerspruch.
    Ein anderer Vorname der Mutter (Margaretha gegen Anna Maria) ist ein Veto, auch wenn eine Seite NN heisst:
    sonst landen Kinder bei der falschen Frau desselben Mannes."""
    vp = nf.vornamen_punkte(p.get("vorname_kanon"), i["vorname_kanon"])
    if nf.vornamen_widerspruch(p.get("vorname_kanon"), i["vorname_kanon"]):
        return -1
    if p.get("unbekannt") or not p.get("name"):
        return P_MUTTER // 2 if vp and vp > 0 else 10
    if i["unbekannt"] or not i["name"]:
        return 30 if vp and vp > 0 else 10
    if nf.namen_aehnlich(i["name"], p["name"], i["name_schl"]) or nf.namen_aehnlich(i["ehename"], p["name"]):
        return P_MUTTER if (vp is None or vp > 0) else -1
    return -1


def entscheiden(kandidaten, schwelle):
    """kandidaten: [(ident, punkte, gruende)] -> (ident|None, stufe, punkte, grund, alternativen)."""
    kandidaten = sorted((k for k in kandidaten if k[1] >= schwelle), key=lambda k: -k[1])
    if not kandidaten:
        return None, "neu", 0, "", []
    best, punkte, gruende = kandidaten[0]
    zweiter = kandidaten[1][1] if len(kandidaten) > 1 else None
    anker = any(g in ("Geburtsdatum", "Geburtsjahr", "Vater", "Mutter", "Ehepartner", "Sterbedatum aus Rueckverweis") for g in gruende)
    if zweiter is not None and punkte - zweiter < ABSTAND_KLAR:
        stufe = "unsicher"
    elif anker and (zweiter is None or punkte - zweiter >= ABSTAND_SICHER):
        stufe = "sicher"
    else:
        stufe = "wahrscheinlich"
    alternativen = [[k[0]["id"], k[1], ", ".join(k[2])] for k in kandidaten[1:4]]
    return best, stufe, punkte, ", ".join(gruende), alternativen


# ------------------------------------------------------------- Durchlauf
def lade(con):
    """Alle Eintraege mit ihren Feldern und Nennungen aus der Projektdatei, chronologisch sortiert (Jahr, Monat, Tag; bei gleichem Datum Trauung vor Taufe vor Tod). Fehlende Monate/Tage zaehlen als Jahresmitte."""
    eintraege = {}
    for e in con.execute("SELECT id, register, jahr, monat, tag FROM eintrag"):
        eintraege[e["id"]] = dict(e) | {"personen": {}, "felder": {}}
    for f in con.execute("SELECT eintrag, name, wert FROM feld WHERE wert IS NOT NULL"):
        eintraege[f["eintrag"]]["felder"][f["name"]] = f["wert"]
    for p in con.execute("SELECT * FROM person"):
        d = dict(p)
        d["geb"] = (p["geburt_jahr"], p["geburt_monat"], p["geburt_tag"]) if p["geburt_jahr"] else None
        d["jahr"] = eintraege[p["eintrag"]]["jahr"]
        eintraege[p["eintrag"]]["personen"][p["pfad"]] = d
    return sorted(eintraege.values(), key=lambda e: (e["jahr"] or 9999, e["monat"] or 6, e["tag"] or 15,
                                                      {"ehe": 0, "taufe": 1, "tod": 2}[e["register"]]))


def verknuepfen(con, kennungen=None):
    """kennungen: Kennungen (Feld ref) als Vorgabe nutzen; None = Einstellung des Projekts."""
    if kennungen is None:
        r = con.execute("SELECT wert FROM einstellung WHERE name='kennungen'").fetchone()
        kennungen = bool(r and r["wert"] == "1")
    best = Bestand()
    AUSSCHLUSS.clear(); AUSSCHLUSS_TREFFER.clear()
    offen = {}                        # familie_finden legt hier Gleichstaende ab, die Taufe dokumentiert sie
    ident_von_ref = {}                # Kennung -> ident_id (nur mit `kennungen`)
    zuordnungen = []                  # (person_id, ident_id, stufe, punkte, grund, alternativen)
    schluessel = {r["id"]: f"{r['datei']}|{r['blatt']}|{r['zeile']}|{r['pfad']}" for r in con.execute(
        "SELECT p.id, q.datei, q.blatt, e.zeile, p.pfad FROM person p JOIN eintrag e ON e.id=p.eintrag JOIN quelle q ON q.id=e.quelle")}
    person_von_schluessel = {v: k for k, v in schluessel.items()}
    entsch = {}
    for r in con.execute("SELECT schluessel, art, ziel FROM entscheidung"):
        if r["schluessel"] in person_von_schluessel:
            entsch[person_von_schluessel[r["schluessel"]]] = (r["art"], person_von_schluessel.get(r["ziel"]))
    ident_von_person = {}             # fuer Entscheidungen "gleich wie Nennung X"

    def merke(p, i, stufe="neu", punkte=0, grund="", alt=None):
        """Zuordnung festhalten: Nennung p gehoert zu Identitaet i (Stufe, Punkte, Grund, Alternativen); Kennung und erstes Erwachsenenjahr der Identitaet nachziehen."""
        if p and i:
            zuordnungen.append((p["id"], i["id"], stufe, punkte, grund, json.dumps(alt or [], ensure_ascii=False)))
            i["pfade"].append((p["eintrag"], p["pfad"]))
            ident_von_person[p["id"]] = i["id"]
            if p["pfad"] not in ("kind", "verstorbener") and p.get("jahr"):   # Vater, Braut, Partner ...: hier erwachsen
                i["erwachsen_ab"] = min(i["erwachsen_ab"] or 9999, p["jahr"])
            if kennungen and p.get("ref") and not i["ref"]:
                i["ref"] = p["ref"]
                ident_von_ref[p["ref"]] = i["id"]

    def ref_passt(i, p):
        """Mit Kennungen: eine Identitaet mit fremder Kennung kommt fuer p nicht in Frage."""
        return not kennungen or not p or not p.get("ref") or i["ref"] in (None, p["ref"])

    def vorgabe_fuer(p):
        """Die Identitaet, die p laut Kennung sein muss, oder None."""
        if kennungen and p and p.get("ref") and p["ref"] in ident_von_ref:
            return best.idents[ident_von_ref[p["ref"]]]
        return None

    def von_hand(p):
        """Entscheidung aus der Pruefliste: (ident|None, stufe) oder None, wenn keine vorliegt."""
        e = entsch.get(p["id"]) if p else None
        if not e:
            return None
        if e[0] == "neu":
            return (None, "neu", 0, "von Hand: eigene Person", [])
        if e[0] == "gleich" and e[1] in ident_von_person:
            return (best.idents[ident_von_person[e[1]]], "sicher", 999, "von Hand bestaetigt", [])
        return None

    def finde(p, jahr, geschlecht=None, schwelle=SCHWELLE, raten=False, **ctx):
        """raten=False: bei Gleichstand keine Wahl (eigene Person, Kandidaten fuer die Pruefliste);
        raten=True: den Besten nehmen, Stufe unsicher (wird nicht mehr benutzt: offen lassen ist der Grundsatz)."""
        hand = von_hand(p)
        if hand:
            return [], hand
        vorgabe = vorgabe_fuer(p)
        if not p or (not p.get("name") and not p.get("geburtsname")):
            return [], ((vorgabe, "vorgabe", 999, "Kennung " + p["ref"], []) if vorgabe else (None, "neu", 0, "", []))
        kand = []
        for name in {p.get("name"), p.get("geburtsname")} - {None}:
            for i in best.kandidaten_name(name, nf.koelner(name), geschlecht or p.get("geschlecht")):
                if not vorgabe and not ref_passt(i, p):     # mit Vorgabe zaehlen alle: die Rechnung soll widersprechen duerfen
                    continue
                r = person_punkte(best, i, p, jahr, **ctx)
                if r and not any(k[0]["id"] == i["id"] for k in kand):
                    kand.append((i, r[0], r[1]))
        ergebnis = entscheiden(kand, schwelle)
        if ergebnis[1] == "unsicher" and not vorgabe and not raten:
            # Gleichstand (Namensvettern ohne weiteren Anker): nicht raten. Eigene Person, Kandidaten in die
            # Pruefliste; eine Entscheidung dort zieht alle spaeteren Nennungen der Familie mit.
            i, _st, punkte, grund, alt = ergebnis
            _aus("offen: zwei Personen passen gleich gut", True)
            ergebnis = (None, "neu", 0, f"offen, unentschieden zwischen {len(alt) + 1} Kandidaten: {grund}", [[i["id"], punkte, grund]] + alt)
        if vorgabe:                       # Kennung entscheidet; widerspricht die Rechnung deutlich, in die Pruefliste
            i, stufe, punkte, grund, alt = ergebnis
            if i is not None and i["id"] != vorgabe["id"]:
                return kand, (vorgabe, "unsicher", 999, f"Kennung {p['ref']}; Rechnung spricht für [{i['id']}]: {grund}",
                              [[i["id"], punkte, grund]] + alt)
            return kand, (vorgabe, "vorgabe", 999, "Kennung " + p["ref"], [])
        return kand, ergebnis

    def person_oder_neu(p, jahr, geschlecht=None, schwelle=SCHWELLE, raten=False, **ctx):
        """Nennung suchen (finde) oder neue Identitaet anlegen; die Zuordnung wird in jedem Fall gemerkt."""
        if not p:
            return None
        kand, (i, stufe, punkte, grund, alt) = finde(p, jahr, geschlecht, schwelle, raten, **ctx)
        if i is None:
            i = best.neu_ident(p)
            if geschlecht and not i["geschlecht"]:
                i["geschlecht"] = geschlecht               # Ehepartner: Gegenstueck des Verstorbenen
        merke(p, i, stufe, punkte, grund, alt)
        return i

    def eltern_anbinden(kind_i, vater_p, mutter_p, jahr, art="eltern"):
        """Genannte Eltern einer Person: passende Familie suchen oder anlegen, Kind einhaengen.
        `jahr` ist das Ereignisjahr; das Geburtsjahr des Kindes wird daraus geschaetzt, wenn es fehlt."""
        if not vater_p and not mutter_p:
            return None
        kind_jahr = best.geb_jahr(kind_i) or (jahr - 25)
        f = familie_finden(vater_p, mutter_p, kind_jahr, kind_name=kind_i["name"], grob=not best.geb_jahr(kind_i))
        if f is None:
            v = person_oder_neu(vater_p, jahr, "M", schwelle=SCHWELLE) if vater_p else None
            m = person_oder_neu(mutter_p, jahr, "F", schwelle=SCHWELLE) if mutter_p else None
            f = best.neu_fam(v["id"] if v else None, m["id"] if m else None, art=art)
        if not best.zirkel(kind_i["id"], f):
            best.kind_setzen(f, kind_i["id"])
        return f

    def familie_finden(vater_p, mutter_p, jahr, kind_name=None, grob=False):
        """Familie, in der vater_p Mann ist (und mutter_p nicht widerspricht). None, wenn keine passt."""
        if not vater_p or not vater_p.get("name"):
            return None
        if von_hand(vater_p) or von_hand(mutter_p):          # Urteil zu Vater oder Mutter: die Einzelsuche (finde) folgt ihm
            return None
        kand = []
        vorgabe = vorgabe_fuer(vater_p)
        for i in ([vorgabe] if vorgabe else best.kandidaten_name(vater_p["name"], vater_p.get("name_schl"), "M")):
            if not ref_passt(i, vater_p):
                continue
            r = person_punkte(best, i, vater_p, jahr, vorname_pflicht=True, tot_erlaubt=grob, alter=None if grob else ALTER_VATER)
            if vorgabe and not r:
                r = (SCHWELLE, ["Kennung"])
            if not r:
                continue
            ij = best.geb_jahr(i)
            if ij and not grob and not (ALTER_VATER[0] <= jahr - ij <= ALTER_VATER[1]):
                continue
            for fid in best.fams_von.get(i["id"], []):
                f = best.fams[fid]
                if f["mann"] != i["id"]:
                    continue
                punkte = r[0]
                gruende = list(r[1])
                if f["frau"] and jahr and best.idents[f["frau"]]["tod"] and best.idents[f["frau"]]["tod"][0] \
                        and best.idents[f["frau"]]["tod"][0] < jahr - 1:
                    _aus("Ehefrau vor der Taufe gestorben", True)
                    continue
                if mutter_p:
                    mp = mutter_passt(best.idents[f["frau"]], mutter_p) if f["frau"] else 10
                    if mp < 0 or (f["frau"] and not ref_passt(best.idents[f["frau"]], mutter_p)):
                        _aus("Mutter widerspricht", True)
                        continue
                    if f["frau"] and vorgabe_fuer(mutter_p) is not None and vorgabe_fuer(mutter_p)["id"] != f["frau"]:
                        continue
                    punkte += mp
                    if mp >= P_MUTTER:
                        gruende.append("Mutter")
                if f["tr"] and f["tr"][0] and jahr and f["tr"][0] > jahr:
                    _aus("Trauung nach der Taufe", True)
                    continue
                kj = [best.geb_jahr(best.idents[k]) for k in f["kinder"]]
                kj = [k for k in kj if k]
                spanne = MAX_KINDERSPANNE + (15 if grob else 0)
                if kj and (jahr - min(kj) > spanne or min(kj) - jahr > spanne):
                    _aus("Kinderspanne ueberschritten", True)
                    continue
                if kind_name and any(nf.namen_aehnlich(best.idents[k]["name"], kind_name) for k in f["kinder"]):
                    punkte += 20; gruende.append("Geschwister")
                kand.append((f, punkte, gruende))
        # bei gleichen Punkten zuerst die juengere Ehe (ein Witwer lebt mit der zweiten Frau)
        kand.sort(key=lambda k: (-k[1], -((k[0]["tr"] or (0,))[0] or 0), -k[0]["id"]))
        gleichstand = [k for k in kand[1:] if kand[0][1] - k[1] < ABSTAND_KLAR and k[0]["id"] != kand[0][0]["id"]]
        if kand and kand[0][1] >= SCHWELLE and gleichstand:
            # Zwei Familien passen gleich gut: NICHT raten. Die Taufe bekommt eine eigene Elternfamilie, und die
            # Nennung, an der es haengt, geht dokumentiert in die Pruefliste (Stufe neu mit Alternativen).
            # Derselbe Mann mit zwei Frauen -> die Mutter ist offen; verschiedene Maenner -> der Vater (finde).
            alle = [kand[0]] + gleichstand
            offen["grund"] = "offen, zwei Ehen passen gleich gut: " + ", ".join(
                f"F{k[0]['id']}" + (f" (Trauung {k[0]['tr'][0]})" if k[0]["tr"] and k[0]["tr"][0] else "") for k in alle)
            offen["frauen"] = [[k[0]["frau"], k[1], ", ".join(k[2])] for k in alle if k[0]["frau"]]
            offen["gleicher_mann"] = len({k[0]["mann"] for k in alle}) == 1
            _aus("offen: zwei Familien passen gleich gut", True)
            return None
        if kand and kand[0][1] >= SCHWELLE:
            f = kand[0][0]
            merke(vater_p, best.idents[f["mann"]], "sicher" if "Mutter" in kand[0][2] else "wahrscheinlich", kand[0][1], ", ".join(kand[0][2]),
                  [[k[0]["mann"], k[1], ", ".join(k[2])] for k in kand[1:4] if k[0]["mann"] != f["mann"]])
            if mutter_p:
                if f["frau"]:
                    fi = best.idents[f["frau"]]
                    if fi["unbekannt"] and mutter_p.get("name") and not mutter_p.get("unbekannt"):
                        best.name_setzen(fi, mutter_p["name"], mutter_p.get("geburtsname"))
                    merke(mutter_p, fi, "wahrscheinlich", kand[0][1], "ueber den Mann")
                else:
                    m = best.neu_ident(mutter_p)
                    best.partner_setzen(f, "frau", m["id"])
                    merke(mutter_p, m)
            return f
        return None

    # ---- der Durchlauf: ein Eintrag nach dem anderen, chronologisch, alle Register gemischt
    for e in lade(con):
        P, jahr = e["personen"], e["jahr"] or 0
        if e["register"] == "taufe":                      # Taufe: Elternfamilie finden oder anlegen, Kind einhaengen
            vater_p, mutter_p, kind_p = P.get("vater"), P.get("mutter"), P.get("kind")
            offen.clear()
            f = familie_finden(vater_p, mutter_p, jahr)
            if f is None:
                v = person_oder_neu(vater_p, jahr, "M", alter=ALTER_VATER, partner=mutter_p) if vater_p else None
                m = None
                hand_m = von_hand(mutter_p) if mutter_p else None
                if hand_m and hand_m[0]:                       # Urteil: diese Ehefrau, auch bei "N., Catharina"
                    m = hand_m[0]; merke(mutter_p, m, hand_m[1], hand_m[2], hand_m[3])
                elif mutter_p and not mutter_p.get("unbekannt"):
                    m = person_oder_neu(mutter_p, jahr, "F", alter=ALTER_MUTTER, partner=vater_p)
                elif mutter_p:
                    m = best.neu_ident(mutter_p)
                    if offen.get("gleicher_mann") and offen.get("frauen") and not hand_m:
                        merke(mutter_p, m, "neu", 0, offen["grund"], offen["frauen"])   # offen: welche Ehefrau?
                    else:
                        merke(mutter_p, m)
                vorhanden = next((best.fams[x] for x in best.fams_von.get(v["id"], []) if v and m
                                  and best.fams[x]["mann"] == v["id"] and best.fams[x]["frau"] == m["id"]), None) if v and m else None
                f = vorhanden or best.neu_fam(v["id"] if v else None, m["id"] if m else None, art="eltern")
                # Eltern der Mutter (Hollerbach nennt sie): als deren Elternfamilie
                if m and (P.get("mutter_vater") or P.get("mutter_mutter")):
                    eltern_anbinden(m, P.get("mutter_vater"), P.get("mutter_mutter"), jahr)
            if kind_p:
                vorgabe = vorgabe_fuer(kind_p)
                k = vorgabe or best.neu_ident(kind_p)
                rv = nf.datum_zerlegen(e["felder"].get("sterbe_datum_rv"))
                if rv:
                    k["tod"] = rv
                best.kind_setzen(f, k["id"])
                if vorgabe and (k["geb"] or k["famc"] not in (None, f["id"])):   # zweite Taufe auf eine Kennung: Tippfehler?
                    merke(kind_p, k, "unsicher", 999, f"Kennung {kind_p['ref']}; Rechnung spricht für eine neue Person: schon getauft {k['geb'][0] if k['geb'] else ''}", [])
                else:
                    merke(kind_p, k, "vorgabe" if vorgabe else "neu", 999 if vorgabe else 0, "Kennung " + kind_p["ref"] if vorgabe else "")
                # ohne Geburtsdatum gilt das Taufdatum als Geburt (Tage danach): sonst fehlt der Anker fuers Begraebnis
                k["geb"] = k["geb"] or kind_p["geb"] or nf.datum_zerlegen(e["felder"].get("tauf_datum"))
        elif e["register"] == "ehe":                     # Trauung: Brautleute finden, Eltern anbinden, Familie anlegen
            paar = {}
            for rolle, g in (("braeutigam", "M"), ("braut", "F")):
                p = P.get(rolle)
                if not p:
                    continue
                vater_p, mutter_p = P.get(f"{rolle}_vater"), P.get(f"{rolle}_mutter")
                kand, (i, stufe, punkte, grund, alt) = finde(p, jahr, g, vater=vater_p, mutter=mutter_p, alter=ALTER_EHE)
                if i is None:
                    i = best.neu_ident(p)
                    merke(p, i, stufe, punkte, grund, alt)
                    if vater_p or mutter_p:
                        eltern_anbinden(i, vater_p, mutter_p, jahr)
                else:
                    merke(p, i, stufe, punkte, grund, alt)
                if p.get("geburtsname") and not i["geburtsname"]:
                    best.name_setzen(i, p["name"], p["geburtsname"])
                vorehe_p = P.get(f"{rolle}_vorehe")
                if vorehe_p:
                    vi = person_oder_neu(vorehe_p, jahr, "F" if g == "M" else "M", schwelle=SCHWELLE_NIEDRIG, tot_erlaubt=True)
                    best.neu_fam(*( (vi["id"], i["id"]) if g == "F" else (i["id"], vi["id"]) ), art="ehe")
                paar[rolle] = i
            if paar:
                m_id, w_id = paar.get("braeutigam", {}).get("id"), paar.get("braut", {}).get("id")
                tr = (e["jahr"], e["monat"], e["tag"]) if e["jahr"] else None
                vorhanden = next((best.fams[fid] for fid in best.fams_von.get(m_id, []) if m_id and w_id
                                  and best.fams[fid]["frau"] == w_id and best.fams[fid]["eintrag"] is None), None)
                if vorhanden:                                 # Kinder vor der Trauung getauft: dieselbe Familie
                    vorhanden.update(art="ehe", tr=tr, eintrag=e["id"])
                else:
                    best.neu_fam(m_id, w_id, art="ehe", trauung=tr, eintrag=e["id"])
        else:                                             # Begraebnis: Verstorbenen finden, Vetos, Partner, Eltern
            p = P.get("verstorbener")
            if not p:
                continue
            vater_p, mutter_p, partner_p = P.get("verstorbener_vater"), P.get("verstorbener_mutter"), P.get("verstorbener_ehepartner")
            tod = (e["jahr"], e["monat"], e["tag"]) if e["jahr"] else None
            kand, (i, stufe, punkte, grund, alt) = finde(p, jahr, None, SCHWELLE_TOD, vater=vater_p, mutter=mutter_p,
                                                        partner=partner_p, tod=tod, vorname_pflicht=not p.get("totgeburt"))
            # Totgeburt / Kind ohne Vornamen: ueber Eltern und Datum
            if i is None and (p.get("totgeburt") or not p.get("vorname")) and vater_p:
                for fi in best.fams.values():
                    if fi["mann"] and vater_passt(best.idents[fi["mann"]], vater_p):
                        for kid in fi["kinder"]:
                            ki = best.idents[kid]
                            if ki["geb"] and ki["geb"][0] == e["jahr"] and (p.get("totgeburt") or not ki["vorname"]):
                                i, stufe, punkte, grund = ki, "sicher", 150, "Eltern und Jahr, ohne Vornamen"
            anker = any(g in grund for g in ("Geburtsjahr", "Geburtsdatum", "Rueckverweis", "Vater", "Mutter", "Ehepartner"))
            # Vetos nach Hollerbach: ledig -> genannter Vater darf dem Vater der Familie nicht widersprechen;
            # verheiratet/verwitwet -> ein Partner muss passen. Nur echter Widerspruch zaehlt (Johann Philipp
            # gegen Philipp Jakob ist keiner). Mit Anker wird der Fall unsicher und geht in die Pruefliste,
            # statt still eine zweite Person zu erzeugen.
            if i is not None and not (kennungen and p.get("ref") and i["ref"] == p["ref"]):    # eine Kennung schlaegt Vetos
                stand = (p.get("stand") or "").lower()
                veto = None
                if stand == "ledig" and vater_p and i["famc"] and best.fams[i["famc"]]["mann"] \
                        and widerspruch(best.idents[best.fams[i["famc"]]["mann"]], vater_p):
                    veto = "ledig, genannter Vater widerspricht"
                elif stand in ("verheiratet", "verwitwet") and partner_p and best.fams_von.get(i["id"]) and "Ehepartner" not in grund:
                    partner_ids = [best.fams[fid]["frau"] if best.fams[fid]["mann"] == i["id"] else best.fams[fid]["mann"] for fid in best.fams_von[i["id"]]]
                    if all(widerspruch(best.idents[pid], partner_p) for pid in partner_ids if pid):
                        veto = "verheiratet, kein Partner passt"
                if veto:
                    _aus("Begraebnis: " + veto, True)
                    if anker:                                 # offen lassen, dokumentiert: Kandidat als Alternative
                        alt = [[i["id"], punkte, f"{grund}; Veto: {veto}"]] + alt
                        i, stufe, punkte, grund = None, "neu", 0, f"offen, Veto: {veto}"
                    else:
                        i = None
            # Begraebnis eines Kindes: nur mit Anker (Geburt, Vater, Rueckverweis) an eine Taufe; bei zwei gleich guten
            # Taufen (Zwillinge, Namenswiederholung) nie von selbst. Sonst eigene Person, Kandidaten fuer die Pruefliste.
            kind = (p.get("alter_tage") is not None and p["alter_tage"] < 15 * 365) or (p.get("geb") and jahr and jahr - p["geb"][0] < 15)
            if i is not None and kind and (not anker or stufe == "unsicher") and not (kennungen and p.get("ref")):
                _aus("Begraebnis: Kind ohne klaren Anker an eine Taufe", True)
                alt = [[i["id"], punkte, grund]] + alt
                i, stufe, punkte, grund = None, "neu", 0, "Kind ohne klaren Anker; Kandidaten siehe Alternativen"
            if i is None:
                i = best.neu_ident(p)
                merke(p, i, stufe, punkte, grund, alt)
                if vater_p or mutter_p:
                    eltern_anbinden(i, vater_p, mutter_p, (p["geb"][0] if p.get("geb") else jahr))
            else:
                merke(p, i, stufe, punkte, grund, alt)
            if tod:
                i["tod"] = tod
            if not i["geb"] and p.get("geb"):
                i["geb"], i["geb_praefix"] = p["geb"], p.get("geburt_praefix")
            if partner_p:
                pg = "F" if i["geschlecht"] == "M" else "M" if i["geschlecht"] == "F" else None
                vorhanden = None
                for fid in best.fams_von.get(i["id"], []):
                    f = best.fams[fid]
                    pid = f["frau"] if f["mann"] == i["id"] else f["mann"]
                    if pid and vater_passt(best.idents[pid], partner_p) and ref_passt(best.idents[pid], partner_p):
                        vorhanden = best.idents[pid]
                        merke(partner_p, vorhanden, "sicher", P_PARTNER, "Ehepartner des Verstorbenen")
                        break
                if not vorhanden:
                    pi = person_oder_neu(partner_p, jahr, pg, schwelle=SCHWELLE_NIEDRIG, tot_erlaubt=True)
                    if pi:
                        mann, frau = (i["id"], pi["id"]) if i["geschlecht"] == "M" else (pi["id"], i["id"])
                        best.neu_fam(mann, frau, art="ehe")
    familien_zusammenlegen(best)
    con.execute("INSERT OR REPLACE INTO einstellung(name, wert) VALUES ('ausschluesse', ?)",
                (json.dumps({r: [AUSSCHLUSS[r], AUSSCHLUSS_TREFFER[r]] for r in AUSSCHLUSS}, ensure_ascii=False),))
    schreiben(con, best, zuordnungen)
    return best, zuordnungen


def familien_zusammenlegen(best):
    """Zwei Familien mit demselben Mann und derselben Frau sind eine: Kinder zusammenfuehren,
    die mit Traueintrag behalten. Entsteht, wenn Taufen und Trauung sich nicht gefunden haben."""
    nach_paar = {}
    for f in list(best.fams.values()):
        if f["mann"] and f["frau"]:
            nach_paar.setdefault((f["mann"], f["frau"]), []).append(f)
    for paar, liste in nach_paar.items():
        if len(liste) < 2:
            continue
        liste.sort(key=lambda f: (f["eintrag"] is None, f["id"]))
        ziel = liste[0]
        for f in liste[1:]:
            for k in f["kinder"]:
                best.kind_setzen(ziel, k)
            for p in paar:
                best.fams_von[p] = [x for x in best.fams_von.get(p, []) if x != f["id"]]
            del best.fams[f["id"]]


def schreiben(con, best, zuordnungen):
    """Ergebnis in die Projektdatei: identitaet, familie, kind werden ersetzt, zuordnung je Nennung mit Stufe, Punkten, Grund und Alternativen (JSON) fuer die Pruefliste."""
    con.execute("DELETE FROM zuordnung"); con.execute("DELETE FROM kind"); con.execute("DELETE FROM familie"); con.execute("DELETE FROM identitaet")
    for i in best.idents.values():
        g = i["geb"] or (None, None, None)
        t = i["tod"] or (None, None, None)
        con.execute("INSERT INTO identitaet(id, geschlecht, name, vorname, name_schl, vorname_kanon, geburtsname, ehename, unbekannt, "
                    "geb_jahr, geb_monat, geb_tag, geb_praefix, tod_jahr, tod_monat, tod_tag, famc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (i["id"], i["geschlecht"], i["name"], i["vorname"], i["name_schl"], i["vorname_kanon"], i["geburtsname"], i["ehename"],
                     i["unbekannt"], g[0], g[1], g[2], i["geb_praefix"], t[0], t[1], t[2], i["famc"]))
    for f in best.fams.values():
        tr = f["tr"] or (None, None, None)
        con.execute("INSERT INTO familie(id, mann, frau, trauung_eintrag, tr_jahr, tr_monat, tr_tag, art) VALUES (?,?,?,?,?,?,?,?)",
                    (f["id"], f["mann"], f["frau"], f["eintrag"], tr[0], tr[1], tr[2], f["art"]))
        con.executemany("INSERT OR IGNORE INTO kind(familie, ident) VALUES (?,?)", [(f["id"], k) for k in f["kinder"]])
    con.executemany("INSERT OR REPLACE INTO zuordnung(person, ident, stufe, punkte, grund, alternativen) VALUES (?,?,?,?,?,?)", zuordnungen)
    con.commit()


def person_schluessel(con, person_id):
    """Stabiler Schluessel einer Nennung 'datei|blatt|zeile|pfad': ueberlebt jedes Neu-Einlesen, daran haengen die Entscheidungen von Hand."""
    r = con.execute("SELECT q.datei, q.blatt, e.zeile, p.pfad FROM person p JOIN eintrag e ON e.id=p.eintrag JOIN quelle q ON q.id=e.quelle WHERE p.id=?", (person_id,)).fetchone()
    return f"{r['datei']}|{r['blatt']}|{r['zeile']}|{r['pfad']}" if r else None


def entscheiden_von_hand(con, person_id, art, ziel_id=None):
    """Entscheidung aus der Pruefliste speichern (art 'gleich'|'neu') oder loeschen (art None)."""
    import datetime as dt
    k = person_schluessel(con, person_id)
    if art is None:
        con.execute("DELETE FROM entscheidung WHERE schluessel=?", (k,))
    else:
        con.execute("INSERT OR REPLACE INTO entscheidung(schluessel, art, ziel, angelegt) VALUES (?,?,?,?)",
                    (k, art, person_schluessel(con, ziel_id) if ziel_id else None, dt.datetime.now().isoformat(timespec="seconds")))
    con.commit()


def statistik(con):
    """Zahlen fuer die Meldung nach dem Lauf: Nennungen, Identitaeten, Familien, Kinder, Verteilung der Stufen."""
    z = dict(con.execute("SELECT stufe, COUNT(*) FROM zuordnung GROUP BY stufe"))
    n_i = con.execute("SELECT COUNT(*) FROM identitaet").fetchone()[0]
    n_p = con.execute("SELECT COUNT(*) FROM person").fetchone()[0]
    n_f = con.execute("SELECT COUNT(*) FROM familie").fetchone()[0]
    n_fk = con.execute("SELECT COUNT(DISTINCT familie) FROM kind").fetchone()[0]
    n_k = con.execute("SELECT COUNT(*) FROM kind").fetchone()[0]
    return dict(personen=n_p, identitaeten=n_i, familien=n_f, familien_mit_kindern=n_fk, kinder=n_k, stufen=z)


def familien_zeigen(con, limit=200):
    """Familien mit Kindern als Text (Kommandozeile `famrecon familien`)."""
    def wer(i):
        """Kurztext einer Identitaet fuer die Ausgabe."""
        if not i:
            return "—"
        r = con.execute("SELECT * FROM identitaet WHERE id=?", (i,)).fetchone()
        geb = f" *{r['geb_praefix'] or ''}{r['geb_jahr']}" if r["geb_jahr"] else ""
        tod = f" †{r['tod_jahr']}" if r["tod_jahr"] else ""
        name = r["name"] or ("NN" if r["unbekannt"] else "—")
        if r["ehename"]:
            name += f" (verh. {r['ehename']})"
        return f"{name}, {r['vorname'] or '—'}{geb}{tod} [{r['id']}]"
    for f in con.execute("SELECT * FROM familie ORDER BY COALESCE(tr_jahr, (SELECT MIN(geb_jahr) FROM kind k JOIN identitaet i ON i.id=k.ident WHERE k.familie=familie.id), 9999), id LIMIT ?", (limit,)):
        tr = f" oo {f['tr_jahr']}" if f["tr_jahr"] else ""
        print(f"F{f['id']} ({f['art']}){tr}: {wer(f['mann'])}  &  {wer(f['frau'])}")
        for k in con.execute("SELECT i.* FROM kind k JOIN identitaet i ON i.id=k.ident WHERE k.familie=? ORDER BY i.geb_jahr", (f["id"],)):
            print(f"      - {wer(k['id'])}")


def pruefliste_zeigen(con, stufe=None):
    """Offene Faelle als Text (Kommandozeile `famrecon pruefliste`): unsichere Zuordnungen und neue Personen mit Kandidaten, je mit den Alternativen."""
    sql = ("SELECT z.*, p.pfad, p.roh, e.register, e.jahr, i.name iname, i.vorname ivorname, i.geb_jahr, i.id iid "
           "FROM zuordnung z JOIN person p ON p.id=z.person JOIN eintrag e ON e.id=p.eintrag JOIN identitaet i ON i.id=z.ident "
           "WHERE (z.stufe IN ('unsicher'" + (",'wahrscheinlich'" if stufe == "alle" else "") + ") OR (z.stufe='neu' AND z.alternativen<>'[]')) ORDER BY e.jahr")
    n = 0
    for r in con.execute(sql):
        n += 1
        print(f"{r['register']:6} {r['jahr']} {r['pfad']:24} {(r['roh'] or '')[:50]!r}")
        print(f"       -> [{r['iid']}] {r['iname']}, {r['ivorname']} *{r['geb_jahr'] or '?'}  {r['punkte']} Punkte ({r['grund']})  {r['stufe']}")
        for alt in json.loads(r["alternativen"] or "[]"):
            a = con.execute("SELECT name, vorname, geb_jahr FROM identitaet WHERE id=?", (alt[0],)).fetchone()
            print(f"          oder [{alt[0]}] {a['name']}, {a['vorname']} *{a['geb_jahr'] or '?'}  {alt[1]} Punkte ({alt[2]})")
    if not n:
        print("Keine offenen Faelle.")


def ausschluesse(con):
    """Gezaehlte Ausschluesse des letzten Laufs: [(regel, alle, bei passendem Vornamen)], absteigend."""
    r = con.execute("SELECT wert FROM einstellung WHERE name='ausschluesse'").fetchone()
    d = json.loads(r["wert"]) if r else {}
    return sorted(((k, v[0], v[1]) for k, v in d.items()), key=lambda x: -x[2])


def ausschluesse_zeigen(con):
    """Tabelle der Ausschluesse und offenen Faelle fuer die Kommandozeile."""
    zeilen = ausschluesse(con)
    if not zeilen:
        print("Keine Zaehlung vorhanden (erst verknuepfen).")
        return
    print(f"{'Regel':58} {'alle':>8} {'Vorname passt':>14}")
    for regel, alle, treffer in zeilen:
        print(f"{regel:58} {alle:>8} {treffer:>14}")
    offen = con.execute("SELECT COUNT(*) FROM zuordnung WHERE stufe='neu' AND alternativen<>'[]'").fetchone()[0]
    print(f"\nOffen gelassen und dokumentiert (Stufe neu mit Kandidaten): {offen}")
