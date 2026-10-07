"""Abgleich gegen einen Referenzstand: Wie nah ist die Rekonstitution an einem gepruefen Familienbuch?

    famrecon vergleiche daten/projekt.db referenz.ged [--ab 1747] [--inhalt] [--xlsx abweichungen.xlsx]

Die Referenz ist eine GEDCOM, zum Beispiel das von Hand nachgearbeitete Ortsfamilienbuch desselben Orts.
Gekoppelt wird je Eintrag der Register:

    Fundstelle   (Standard) ueber die Zitate: die Referenz traegt an ihren Ereignissen PAGE "Taufe 1647/01",
                 famrecon kennt dieselbe Fundstelle aus der Tabelle. Exakt, aber nur wenn die Referenz die
                 Fundstellen fuehrt und die Nummerierung nicht verrutscht ist.
    Inhalt       (--inhalt) ueber Registerart, Jahr, Lautschluessel des Nachnamens und ersten Vornamen der
                 Hauptperson. Robust gegen Nummern, aber Namensvettern im selben Jahr fallen heraus.

Gezaehlt werden Paare von Eintraegen, die dieselbe Person betreffen (Taufe und Begraebnis desselben
Menschen): sollten zusammen (laut Referenz), sind zusammen (laut famrecon), Treffer -> Praezision und
Vollstaendigkeit; dazu je Taufe, ob Vater und Mutter dieselben sind wie in der Referenz, und wie oft
famrecons Stufen "sicher"/"wahrscheinlich" mit der Referenz uebereinstimmen. --ab begrenzt auf Eintraege
ab einem Jahr (wenn die Tabellen spaeter beginnen als die Referenz).

Die Abweichungen (zu viel verbunden, verpasst) kommen als Liste mit beiden Lesarten und famrecons
Begruendung heraus, auf Wunsch als xlsx zum Durchsehen. Eine Referenz ist selbst nicht fehlerfrei:
Abweichungen sind Fragen an beide Seiten.
"""
import json
import re
from collections import Counter, defaultdict
from itertools import combinations

from . import simulation
from . import normalform as nf

REG_KURZ = {"taufe": "Tau", "ehe": "Tra", "tod": "Beg"}


def _sub(k, tag):
    return [c for c in k["kinder"] if c["tag"] == tag]


def _wert(k, *pfad):
    for t in pfad:
        n = _sub(k, t)
        if not n:
            return None
        k = n[0]
    return k["wert"]


def _jahr(d):
    m = re.search(r"(\d{4})", d or "")
    return int(m.group(1)) if m else None


def _norm_fund(pg):
    """'Taufe 1647/01' und 'Taufe 1647/1' sollen zusammenfinden: Art-Kuerzel, Jahr, Nummer ohne fuehrende Nullen."""
    m = re.match(r"\s*(Tauf|Trau|Begr|Heirat|Ehe|Tod|Sterb|Beerd)\w*\s+(\d{4})\s*/\s*0*(\d+)", pg or "", re.I)
    if not m:
        return re.sub(r"\s+", " ", (pg or "").strip())
    art = {"Tauf": "Tau", "Trau": "Tra", "Heirat": "Tra", "Ehe": "Tra", "Begr": "Beg", "Tod": "Beg", "Sterb": "Beg", "Beerd": "Beg"}[m.group(1).capitalize()[:len(m.group(1))].title() if False else m.group(1).title()]
    return f"{art} {m.group(2)}/{m.group(3)}"


def _inhalt_key(art, jahr, nn, vn):
    v = nf.vorname_kanon(vn or "").split()
    return f"{art} {jahr or '?'} {nf.koelner(nn or '') or (nn or '').lower()} {v[0] if v else '-'}"


def referenz_laden(pfad, kopplung="fundstelle"):
    """GEDCOM -> Personen mit Schluesseln (Fundstellen oder Inhaltsschluessel), Familien."""
    indis, fams = simulation.lesen(pfad)
    P, F = {}, {}
    alle = Counter()
    for x, i in indis.items():
        name = _wert(i, "NAME") or ""
        m = re.match(r"(.*?)/(.*?)/", name)
        vn, nn = (m.group(1).strip(), m.group(2).strip()) if m else (name, "")
        d = dict(x=x, vn=vn, nn=nn, geb=None, tod=None, keys=set(), famc=[w["wert"] for w in _sub(i, "FAMC")])
        for ev in i["kinder"]:
            if ev["tag"] in ("BIRT", "CHR", "DEAT", "BURI"):
                j = _jahr(_wert(ev, "DATE"))
                if ev["tag"] in ("BIRT", "CHR") and j and not d["geb"]:
                    d["geb"] = j
                if ev["tag"] in ("DEAT", "BURI") and j and not d["tod"]:
                    d["tod"] = j
                if kopplung == "inhalt":
                    if j:
                        d["keys"].add(_inhalt_key("Tau" if ev["tag"] in ("BIRT", "CHR") else "Beg", j, nn, vn))
                else:
                    for s in _sub(ev, "SOUR"):
                        pg = _wert(s, "PAGE")
                        if pg:
                            d["keys"].add(_norm_fund(pg))
        for k in d["keys"]:
            alle[k] += 1
        P[x] = d
    if kopplung == "inhalt":                                  # mehrdeutige Schluessel (Namensvettern im Jahr) weglassen
        for d in P.values():
            d["keys"] = {k for k in d["keys"] if alle[k] == 1}
    for x, f in fams.items():
        F[x] = dict(x=x, husb=_wert(f, "HUSB"), wife=_wert(f, "WIFE"), chil=[c["wert"] for c in _sub(f, "CHIL")])
    return P, F


def eigene_laden(con, kopplung="fundstelle"):
    """famrecon-Stand aus der Projektdatei: je Hauptnennung (Kind, Verstorbener) Schluessel -> Identitaet, dazu Stufe/Grund."""
    felder = defaultdict(dict)
    for f in con.execute("SELECT eintrag, name, wert FROM feld WHERE name IN ('zitat','kb','seite','lfd_nr') AND wert IS NOT NULL"):
        felder[f["eintrag"]][f["name"]] = f["wert"]
    rows = con.execute("SELECT z.ident, z.stufe, z.grund, z.alternativen, p.id person, p.pfad, p.name, p.vorname, p.roh, e.id eid, e.register, e.jahr, e.zeile "
                       "FROM zuordnung z JOIN person p ON p.id=z.person JOIN eintrag e ON e.id=p.eintrag "
                       "WHERE (e.register='taufe' AND p.pfad='kind') OR (e.register='tod' AND p.pfad='verstorbener')").fetchall()
    alle = Counter()
    key_von = {}
    for r in rows:
        fl = felder.get(r["eid"], {})
        if kopplung == "inhalt":
            k = _inhalt_key(REG_KURZ[r["register"]], r["jahr"], r["name"], r["vorname"])
        else:
            fund = fl.get("zitat") or " ".join(x for x in (fl.get("kb"), f"S. {fl['seite']}" if fl.get("seite") else None,
                                                            f"Nr. {fl['lfd_nr']}" if fl.get("lfd_nr") else None) if x) or f"Zeile {r['zeile']}"
            k = _norm_fund(fund)
        alle[k] += 1
        key_von[r["person"]] = (k, r)
    idents = {i["id"]: dict(i) for i in con.execute("SELECT * FROM identitaet")}
    fams = {f["id"]: dict(f) for f in con.execute("SELECT * FROM familie")}
    out = {}
    for person, (k, r) in key_von.items():
        if kopplung == "inhalt" and alle[k] > 1:
            continue
        out[k] = dict(ident=r["ident"], stufe=r["stufe"], grund=r["grund"] or "", alternativen=r["alternativen"], roh=r["roh"], register=r["register"], jahr=r["jahr"], person=person)
    return out, idents, fams


def _wer_ref(p):
    return f"{p['nn']}, {p['vn']} *{p['geb'] or '?'} †{p['tod'] or '?'}" if p else "—"


def _wer_eigen(i):
    return f"{i['name'] or 'NN'}, {i['vorname'] or '—'} *{i['geb_jahr'] or '?'} †{i['tod_jahr'] or '?'}" if i else "—"


def vergleichen(con, referenz, ab=0, kopplung="fundstelle", zeigen=15):
    """-> dict mit Kennzahlen und Listen (falsch, verpasst, eltern) fuer Text, Seite und Tabelle."""
    R, RF = referenz_laden(referenz, kopplung)
    E, idents, fams = eigene_laden(con, kopplung)
    ref_von_key = {}
    for x, p in R.items():
        for k in p["keys"]:
            ref_von_key.setdefault(k, x)
    gemeinsam = sorted(k for k in set(E) & set(ref_von_key) if (_jahr(k) or 0) >= ab)
    nach_ref, nach_eigen = defaultdict(list), defaultdict(list)
    for k in gemeinsam:
        nach_ref[ref_von_key[k]].append(k)
        nach_eigen[E[k]["ident"]].append(k)
    soll = {frozenset(c) for v in nach_ref.values() for c in combinations(v, 2)}
    ist = {frozenset(c) for v in nach_eigen.values() for c in combinations(v, 2)}
    treffer = soll & ist
    prae = len(treffer) / len(ist) if ist else 1.0
    voll = len(treffer) / len(soll) if soll else 1.0

    def fall(paar, art):
        a, b = sorted(paar)
        beg = a if a.startswith("Beg") else b
        tau = b if beg == a else a
        e = E[beg] if beg in E else E[tau]
        ref_beg, ref_tau = R[ref_von_key[beg]], R[ref_von_key[tau]]
        eigen = idents.get(E[beg]["ident"]) if beg in E else None
        return dict(art=art, taufe=tau, begraebnis=beg, nennung=E[beg]["roh"] if beg in E else "", stufe=e["stufe"], grund=e["grund"],
                    eigen=_wer_eigen(eigen), referenz_beg=_wer_ref(ref_beg), referenz_tau=_wer_ref(ref_tau),
                    eigen_tau=_wer_eigen(idents.get(E[tau]["ident"])) if tau in E else "")
    falsch = sorted((fall(p, "zu viel") for p in ist - soll), key=lambda f: f["begraebnis"])
    verpasst = sorted((fall(p, "verpasst") for p in soll - ist), key=lambda f: f["begraebnis"])
    # Stufen: stimmt, was famrecon sicher nennt?
    stufen = defaultdict(lambda: [0, 0])
    for ident, keys in nach_eigen.items():
        beg = [k for k in keys if k.startswith("Beg")]
        tau = [k for k in keys if k.startswith("Tau")]
        if beg and tau:
            richtig = ref_von_key[beg[0]] == ref_von_key[tau[0]]
            stufen[E[beg[0]]["stufe"]][0] += 1
            stufen[E[beg[0]]["stufe"]][1] += richtig
    # Eltern je Taufe
    def eltern_ref(x):
        for fx in R[x]["famc"]:
            f = RF.get(fx)
            if f:
                return f["husb"], f["wife"]
        return None, None
    def gleich(ei, rx):
        """Eigene Identitaet und Referenzperson: dieselben Schluessel, sonst Name aehnlich und Vorname nicht widerspruechlich."""
        if ei is None or rx is None:
            return ei is None and rx is None
        i, rp = idents.get(ei), R.get(rx)
        if not i or not rp:
            return False
        meine = {k for k, e in E.items() if e["ident"] == ei}
        if meine & rp["keys"]:
            return True
        if {k[:3] for k in meine} & {k[:3] for k in rp["keys"]}:
            return False
        vp = nf.vornamen_punkte(nf.vorname_kanon(i["vorname"] or ""), nf.vorname_kanon(rp["vn"]))
        unbekannt_i = bool(i["unbekannt"]) or not i["name"]
        unbekannt_r = rp["nn"].upper().strip(". ") in ("NN", "N", "")
        name_ok = (unbekannt_i and unbekannt_r) or nf.namen_aehnlich(i["name"], rp["nn"]) or nf.namen_aehnlich(i["ehename"], rp["nn"])
        return name_ok and (vp is None or vp > 0)
    eltern = Counter()
    for k in gemeinsam:
        if not k.startswith("Tau"):
            continue
        i = idents.get(E[k]["ident"])
        f = fams.get(i["famc"]) if i and i["famc"] else None
        hb, wb = eltern_ref(ref_von_key[k])
        if not f and not hb and not wb:
            eltern["ohne Eltern"] += 1; continue
        if not f:
            eltern["nur Referenz hat Eltern"] += 1; continue
        if not hb and not wb:
            eltern["nur famrecon hat Eltern"] += 1; continue
        v_ok, m_ok = gleich(f["mann"], hb), gleich(f["frau"], wb)
        eltern["gleich" if v_ok and m_ok else "anderer Vater" if not v_ok and m_ok else "andere Mutter" if v_ok else "beide anders"] += 1
    return dict(kopplung=kopplung, ab=ab, referenz_personen=len(R), eigene_personen=len(idents), gemeinsam=len(gemeinsam),
                soll=len(soll), ist=len(ist), treffer=len(treffer), praezision=prae, vollstaendigkeit=voll,
                falsch=falsch, verpasst=verpasst, stufen={k: (n, ok) for k, (n, ok) in stufen.items()}, eltern=dict(eltern))


def bericht(v, zeigen=10):
    """Text fuer die Kommandozeile."""
    z = [f"Kopplung über {v['kopplung']}" + (f", Einträge ab {v['ab']}" if v["ab"] else "") + f": {v['gemeinsam']} gemeinsame Einträge "
         f"(Referenz {v['referenz_personen']} Personen, famrecon {v['eigene_personen']})",
         f"Personenpaare: sollen {v['soll']}, sind {v['ist']}, Treffer {v['treffer']} -> Präzision {v['praezision']:.3f}, Vollständigkeit {v['vollstaendigkeit']:.3f}",
         f"  zu viel verbunden {len(v['falsch'])}, verpasst {len(v['verpasst'])}",
         "Stufen (Begräbnis->Taufe stimmt mit Referenz überein): " + ", ".join(f"{k} {ok}/{n}" for k, (n, ok) in sorted(v["stufen"].items())),
         "Eltern je Taufe: " + ", ".join(f"{k} {n}" for k, n in sorted(v["eltern"].items()))]
    for titel, liste in (("ZU VIEL", v["falsch"]), ("VERPASST", v["verpasst"])):
        for f in liste[:zeigen]:
            z.append(f"  {titel:8} {f['begraebnis']} + {f['taufe']}: famrecon {f['eigen']} [{f['stufe']}: {f['grund'][:40]}] | Referenz: {f['referenz_beg']} / {f['referenz_tau']}")
    return "\n".join(z)


def tabelle(v, pfad):
    """Abweichungen als xlsx zum Durchsehen (Spalte URTEIL: famrecon | Referenz | offen)."""
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Abweichungen"
    ws.append(["ART", "BEGRAEBNIS", "TAUFE", "NENNUNG", "FAMRECON", "STUFE", "BEGRUENDUNG", "REFERENZ BEGRAEBNIS", "REFERENZ TAUFE", "URTEIL", "BEMERKUNG"])
    for f in v["falsch"] + v["verpasst"]:
        ws.append([f["art"], f["begraebnis"], f["taufe"], f["nennung"], f["eigen"], f["stufe"], f["grund"], f["referenz_beg"], f["referenz_tau"], "", ""])
    for col, b in zip("ABCDEFGHIJK", (9, 14, 14, 36, 36, 12, 30, 36, 36, 10, 30)):
        ws.column_dimensions[col].width = b
    ws.freeze_panes = "A2"
    wb.save(pfad)
    return len(v["falsch"]) + len(v["verpasst"])
