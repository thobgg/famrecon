"""Verknuepfen: aus Personen je Eintrag die realen Personen und Familien bilden.

    famrecon verknuepfen daten/projekt.db
    famrecon familien daten/projekt.db
    famrecon pruefliste daten/projekt.db

Die Eintraege laufen chronologisch durch, alle drei Register gemischt, weil
jeder Eintrag die spaeteren ankert: Die Trauung von 1768 traegt die Taufe von
1770 und die Trauung des Sohnes von 1795.

    Taufe   Vater+Mutter -> Elternfamilie suchen (Vater: Name+Vorname, Mutter
            bestaetigt oder widerspricht), sonst neu. Kind immer neu.
    Trauung Braeutigam und Braut suchen (Name, Vorname, Alter, genannte Eltern),
            sonst neu; genannte Eltern als Elternfamilie, voriger Mann als Vorehe.
    Tod     Verstorbenen suchen (Name, Vorname, Geburt aus Alter, Vater, Ehepartner,
            Sterbedatum aus einem Rueckverweis), mit Vetos bei ledig/verheiratet.

Punkte und Vetos stammen aus der Hollerbach-Pipeline (v47) von Thomas; dort an
2.800 Eintraegen eingestellt. Jede Entscheidung bekommt eine Stufe:

    sicher          ein Anker ueber den Namen hinaus (Datum, Eltern, Partner) und kein naher Zweiter
    wahrscheinlich  Punkte ueber der Schwelle, kein naher Zweiter
    unsicher        Punkte ueber der Schwelle, aber ein Zweiter liegt nah -> Pruefliste
    neu             kein Kandidat

Nichts hier ist endgueltig: Die Pruefliste legt die unsicheren Faelle vor,
und eine Entscheidung von Hand ueberschreibt die Rechnung beim naechsten Lauf.
"""
import json

from . import normalform as nf

P_VORNAME, P_VORNAME_TEIL = 100, 70
P_GEB_EXAKT, P_GEB_JAHR, P_GEB_NAH = 100, 50, 30
P_VATER, P_MUTTER, P_PARTNER, P_TOD_RV = 30, 50, 50, 200
P_NAME_EXAKT = 20
SCHWELLE, SCHWELLE_TOD, SCHWELLE_NIEDRIG = 100, 80, 50
ABSTAND_SICHER, ABSTAND_KLAR = 50, 30
MAX_GEB_DIFF = 5            # Jahre zwischen gerechneter und belegter Geburt
ALTER_VATER = (16, 75)
ALTER_MUTTER = (15, 50)
ALTER_EHE = (14, 80)
MAX_KINDERSPANNE = 22


class Bestand:
    """Identitaeten und Familien im Speicher, nach Namensschluessel indiziert."""

    def __init__(self):
        self.idents, self.fams, self.kinder = {}, {}, {}
        self.by_schl = {}
        self.by_anfang = {}           # (erste zwei Buchstaben, Laenge//2) -> [ident]: fuer aehnliche Schreibungen
        self.fams_von = {}            # ident -> [familie] als Mann/Frau
        self.next_i = self.next_f = 1

    def neu_ident(self, p, pfad=None):
        i = dict(id=self.next_i, geschlecht=p.get("geschlecht"), name=p.get("geburtsname") or p.get("name"),
                 vorname=p.get("vorname"), geburtsname=p.get("geburtsname"),
                 ehename=p.get("name") if p.get("geburtsname") else None, unbekannt=int(bool(p.get("unbekannt"))),
                 geb=None, geb_praefix=None, tod=None, famc=None, pfade=[])
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
        f = dict(id=self.next_f, mann=mann, frau=frau, art=art, tr=trauung, eintrag=eintrag, kinder=[])
        self.next_f += 1
        self.fams[f["id"]] = f
        for p in (mann, frau):
            if p:
                self.fams_von.setdefault(p, []).append(f["id"])
        return f

    def partner_setzen(self, f, rolle, ident):
        f[rolle] = ident
        self.fams_von.setdefault(ident, []).append(f["id"])

    def kind_setzen(self, f, ident):
        if ident not in f["kinder"]:
            f["kinder"].append(ident)
        self.idents[ident]["famc"] = f["id"]

    def kandidaten_name(self, name, schl, geschlecht=None):
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
        return i["geb"][0] if i["geb"] else None


# ------------------------------------------------------------ Bewertung
def person_punkte(best, i, p, jahr, vater=None, mutter=None, partner=None, tod=None, vorname_pflicht=True, tot_erlaubt=False, alter=None):
    """Punkte fuer: Person p (Normalform) ist Identitaet i. -> (punkte, gruende) oder None bei Ausschluss.
    `alter` = (min, max): erlaubtes Alter der Identitaet beim Ereignisjahr (Vater bei Taufe, Brautleute ...)."""
    punkte, gruende = 0, []
    if alter and jahr and best.geb_jahr(i) and not (alter[0] <= jahr - best.geb_jahr(i) <= alter[1]):
        return None
    if p.get("geschlecht") and i["geschlecht"] and p["geschlecht"] != i["geschlecht"]:
        return None
    vp = nf.vornamen_punkte(p.get("vorname_kanon"), i["vorname_kanon"])
    if vp is None:
        if vorname_pflicht and p.get("vorname_kanon") and not i["vorname_kanon"] and not p.get("totgeburt"):
            return None
    elif vp == 0:
        return None
    else:
        punkte += vp
        gruende.append("Vorname" if vp == 100 else "Vorname teils")
    if p.get("name") and i["name"] and p["name"].lower() == i["name"].lower():
        punkte += P_NAME_EXAKT
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
            return None
    if jahr and i["tod"] and i["tod"][0] and i["tod"][0] < jahr and not p.get("verstorben") and not tot_erlaubt:
        if not (alter is ALTER_VATER and jahr - i["tod"][0] <= 1):
            return None                                       # schon tot; Ausnahme: Vater eines nachgeborenen Kindes
    if jahr and ij and not (0 <= jahr - ij <= 100):
        return None
    if tod and tod[0] and i["tod"] and i["tod"] == tod:
        punkte += P_TOD_RV; gruende.append("Sterbedatum aus Rueckverweis")
    if vater and i["famc"]:
        v = best.fams[i["famc"]]["mann"]
        if v and vater_passt(best.idents[v], vater):
            punkte += P_VATER; gruende.append("Vater")
        elif v and not nf.namen_aehnlich(best.idents[v]["name"], vater.get("name")):
            return None                                       # anderer Vater
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
                return None
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


def mutter_passt(i, p):
    """-> Punkte: 50 Name+Vorname, 30 NN-Frau mit gleichem Vornamen, 10 Mutter fehlt, 0 widerspruechlich, -1 Veto."""
    vp = nf.vornamen_punkte(p.get("vorname_kanon"), i["vorname_kanon"])
    if p.get("unbekannt") or not p.get("name"):
        return P_MUTTER // 2 if vp and vp > 0 else (10 if vp is None else 0)
    if i["unbekannt"] or not i["name"]:
        return 30 if vp and vp > 0 else (10 if vp is None else -1)
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
    eintraege = {}
    for e in con.execute("SELECT id, register, jahr, monat, tag FROM eintrag"):
        eintraege[e["id"]] = dict(e) | {"personen": {}, "felder": {}}
    for f in con.execute("SELECT eintrag, name, wert FROM feld WHERE wert IS NOT NULL"):
        eintraege[f["eintrag"]]["felder"][f["name"]] = f["wert"]
    for p in con.execute("SELECT * FROM person"):
        d = dict(p)
        d["geb"] = (p["geburt_jahr"], p["geburt_monat"], p["geburt_tag"]) if p["geburt_jahr"] else None
        eintraege[p["eintrag"]]["personen"][p["pfad"]] = d
    return sorted(eintraege.values(), key=lambda e: (e["jahr"] or 9999, e["monat"] or 6, e["tag"] or 15,
                                                      {"ehe": 0, "taufe": 1, "tod": 2}[e["register"]]))


def verknuepfen(con):
    best = Bestand()
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
        if p and i:
            zuordnungen.append((p["id"], i["id"], stufe, punkte, grund, json.dumps(alt or [], ensure_ascii=False)))
            i["pfade"].append((p["eintrag"], p["pfad"]))
            ident_von_person[p["id"]] = i["id"]

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

    def finde(p, jahr, geschlecht=None, schwelle=SCHWELLE, **ctx):
        hand = von_hand(p)
        if hand:
            return [], hand
        if not p or (not p.get("name") and not p.get("geburtsname")):
            return [], (None, "neu", 0, "", [])
        kand = []
        for name in {p.get("name"), p.get("geburtsname")} - {None}:
            for i in best.kandidaten_name(name, nf.koelner(name), geschlecht or p.get("geschlecht")):
                r = person_punkte(best, i, p, jahr, **ctx)
                if r and not any(k[0]["id"] == i["id"] for k in kand):
                    kand.append((i, r[0], r[1]))
        return kand, entscheiden(kand, schwelle)

    def person_oder_neu(p, jahr, geschlecht=None, schwelle=SCHWELLE, **ctx):
        if not p:
            return None
        kand, (i, stufe, punkte, grund, alt) = finde(p, jahr, geschlecht, schwelle, **ctx)
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
        kand = []
        for i in best.kandidaten_name(vater_p["name"], vater_p.get("name_schl"), "M"):
            r = person_punkte(best, i, vater_p, jahr, vorname_pflicht=True, tot_erlaubt=grob, alter=None if grob else ALTER_VATER)
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
                if mutter_p:
                    mp = mutter_passt(best.idents[f["frau"]], mutter_p) if f["frau"] else 10
                    if mp < 0:
                        continue
                    punkte += mp
                    if mp >= P_MUTTER:
                        gruende.append("Mutter")
                if f["tr"] and f["tr"][0] and jahr and f["tr"][0] > jahr:
                    continue
                kj = [best.geb_jahr(best.idents[k]) for k in f["kinder"]]
                kj = [k for k in kj if k]
                spanne = MAX_KINDERSPANNE + (15 if grob else 0)
                if kj and (jahr - min(kj) > spanne or min(kj) - jahr > spanne):
                    continue
                if kind_name and any(nf.namen_aehnlich(best.idents[k]["name"], kind_name) for k in f["kinder"]):
                    punkte += 20; gruende.append("Geschwister")
                kand.append((f, punkte, gruende))
        kand.sort(key=lambda k: -k[1])
        if kand and kand[0][1] >= SCHWELLE:
            f = kand[0][0]
            merke(vater_p, best.idents[f["mann"]], "sicher" if "Mutter" in kand[0][2] else "wahrscheinlich", kand[0][1], ", ".join(kand[0][2]),
                  [[k[0]["mann"], k[1], ", ".join(k[2])] for k in kand[1:4]])
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

    for e in lade(con):
        P, jahr = e["personen"], e["jahr"] or 0
        if e["register"] == "taufe":
            vater_p, mutter_p, kind_p = P.get("vater"), P.get("mutter"), P.get("kind")
            f = familie_finden(vater_p, mutter_p, jahr)
            if f is None:
                v = person_oder_neu(vater_p, jahr, "M", alter=ALTER_VATER, partner=mutter_p) if vater_p else None
                m = None
                if mutter_p and not mutter_p.get("unbekannt"):
                    m = person_oder_neu(mutter_p, jahr, "F", alter=ALTER_MUTTER, partner=vater_p)
                elif mutter_p:
                    m = best.neu_ident(mutter_p); merke(mutter_p, m)
                f = best.neu_fam(v["id"] if v else None, m["id"] if m else None, art="eltern")
                # Eltern der Mutter (Hollerbach nennt sie): als deren Elternfamilie
                if m and (P.get("mutter_vater") or P.get("mutter_mutter")):
                    eltern_anbinden(m, P.get("mutter_vater"), P.get("mutter_mutter"), jahr)
            if kind_p:
                k = best.neu_ident(kind_p)
                k["geb"] = kind_p["geb"]
                rv = nf.datum_zerlegen(e["felder"].get("sterbe_datum_rv"))
                if rv:
                    k["tod"] = rv
                best.kind_setzen(f, k["id"])
                merke(kind_p, k)
        elif e["register"] == "ehe":
            paar = {}
            for rolle, g in (("braeutigam", "M"), ("braut", "F")):
                p = P.get(rolle)
                if not p:
                    continue
                vater_p, mutter_p = P.get(f"{rolle}_vater"), P.get(f"{rolle}_mutter")
                kand, (i, stufe, punkte, grund, alt) = finde(p, jahr, g, vater=vater_p, mutter=mutter_p, alter=ALTER_EHE)
                if i is None:
                    i = best.neu_ident(p)
                    merke(p, i)
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
        else:  # tod
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
            # Vetos nach Hollerbach: ledig -> Vater muss passen, wenn Familie da; verheiratet -> ein Partner muss passen
            if i is not None:
                stand = (p.get("stand") or "").lower()
                if stand == "ledig" and vater_p and i["famc"] and best.fams[i["famc"]]["mann"] \
                        and not vater_passt(best.idents[best.fams[i["famc"]]["mann"]], vater_p):
                    i = None
                elif stand in ("verheiratet", "verwitwet") and partner_p and best.fams_von.get(i["id"]) and "Ehepartner" not in grund:
                    i = None
            if i is None:
                i = best.neu_ident(p)
                merke(p, i)
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
                    if pid and vater_passt(best.idents[pid], partner_p):
                        vorhanden = best.idents[pid]
                        merke(partner_p, vorhanden, "sicher", P_PARTNER, "Ehepartner des Verstorbenen")
                        break
                if not vorhanden:
                    pi = person_oder_neu(partner_p, jahr, pg, schwelle=SCHWELLE_NIEDRIG, tot_erlaubt=True)
                    if pi:
                        mann, frau = (i["id"], pi["id"]) if i["geschlecht"] == "M" else (pi["id"], i["id"])
                        best.neu_fam(mann, frau, art="ehe")
    familien_zusammenlegen(best)
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
    z = dict(con.execute("SELECT stufe, COUNT(*) FROM zuordnung GROUP BY stufe"))
    n_i = con.execute("SELECT COUNT(*) FROM identitaet").fetchone()[0]
    n_p = con.execute("SELECT COUNT(*) FROM person").fetchone()[0]
    n_f = con.execute("SELECT COUNT(*) FROM familie").fetchone()[0]
    n_fk = con.execute("SELECT COUNT(DISTINCT familie) FROM kind").fetchone()[0]
    n_k = con.execute("SELECT COUNT(*) FROM kind").fetchone()[0]
    return dict(personen=n_p, identitaeten=n_i, familien=n_f, familien_mit_kindern=n_fk, kinder=n_k, stufen=z)


def familien_zeigen(con, limit=200):
    def wer(i):
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
    sql = ("SELECT z.*, p.pfad, p.roh, e.register, e.jahr, i.name iname, i.vorname ivorname, i.geb_jahr, i.id iid "
           "FROM zuordnung z JOIN person p ON p.id=z.person JOIN eintrag e ON e.id=p.eintrag JOIN identitaet i ON i.id=z.ident "
           "WHERE z.stufe IN ('unsicher'" + (",'wahrscheinlich'" if stufe == "alle" else "") + ") ORDER BY e.jahr")
    n = 0
    for r in con.execute(sql):
        n += 1
        print(f"{r['register']:6} {r['jahr']} {r['pfad']:24} {r['roh'][:50]!r}")
        print(f"       -> [{r['iid']}] {r['iname']}, {r['ivorname']} *{r['geb_jahr'] or '?'}  {r['punkte']} Punkte ({r['grund']})  {r['stufe']}")
        for alt in json.loads(r["alternativen"] or "[]"):
            a = con.execute("SELECT name, vorname, geb_jahr FROM identitaet WHERE id=?", (alt[0],)).fetchone()
            print(f"          oder [{alt[0]}] {a['name']}, {a['vorname']} *{a['geb_jahr'] or '?'}  {alt[1]} Punkte ({alt[2]})")
    if not n:
        print("Keine offenen Faelle.")
