"""Das Buch: aus der Projektdatei eine Website im Stil eines Ortsfamilienbuchs, als Ordner mit HTML-Seiten.

    famrecon buch daten/projekt.db -o daten/x/buch [--konfig daten/x/buch.toml] [--ged daten/x/projekt.ged]

Statisch: kein Programm laeuft auf dem Server, ein Webserver liefert den Ordner aus. Jeder Stand ist ein
neuer Ordner. Was die Site zeigt, stammt vollstaendig aus der Rekonstitution, deshalb traegt sie an jeder
Stelle die Herkunft:

    Artikel     je Familie: Mann, Frau, Trauung, Kinder; jede Angabe mit Fundstelle (Register, Jahr, Zitat)
    Belege      je Person aufklappbar: alle Nennungen in den Eintraegen mit Wortlaut und Stufe
    Stufen      sicher ohne Zeichen, wahrscheinlich kursiv, unsicher mit ?, unentschieden mit ??, vorgabe mit Haken;
                Familien ohne Traueintrag "Ehe erschlossen"
    Register    Personen A-Z, Orte, Berufe, Quellen; Pruefaelle und Stufen als eigene Seiten fuer die Durchsicht
    Statistik   ehrlich: Stufen, Nennungen je Person, Zeitraeume
    Verfahren   wie famrecon dieses Buch gerechnet hat: Schema, Schritte mit den Zahlen dieses Bestands,
                Ausschlussregeln, Grundsatz "offen lassen", Kontrolle, Grenzen

Konfiguration (TOML, optional): titel, untertitel, einleitung, erfasser, bearbeiter, impressum, datenschutz,
noindex (Standard: true). Alles andere kommt aus den Daten. Die Seiten sind gekennzeichnet als Arbeitsfassung
mit Stand (Datum), weil eine Rekonstitution ohne Durchsicht kein fertiges Buch ist.
"""
import datetime as dt
import html
import json
import re
import shutil
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

from . import __version__, pruefe, urteile, verknuepfen
from . import normalform as nf

h = html.escape
ZEICHEN = {"sicher": "", "wahrscheinlich": "", "unsicher": "?", "neu": "", "vorgabe": "✓"}
KLASSE = {"sicher": "s", "wahrscheinlich": "w", "unsicher": "u", "neu": "n", "vorgabe": "v"}


def konfig_laden(pfad, projekt):
    """buch.toml lesen; fehlende Werte aus dem Projektnamen."""
    k = {}
    if pfad and Path(pfad).exists():
        with open(pfad, "rb") as f:
            k = tomllib.load(f)
    k.setdefault("titel", f"Ortsfamilienbuch {projekt}")
    k.setdefault("untertitel", "Familien aus Tauf-, Ehe- und Sterberegistern, Arbeitsfassung")
    k.setdefault("einleitung", "")
    k.setdefault("erfasser", "")
    k.setdefault("bearbeiter", "")
    k.setdefault("impressum", "")
    k.setdefault("datenschutz", "Diese Seiten sind statische Dateien. Es werden keine Daten erhoben, keine Cookies gesetzt und keine Zugriffe ausgewertet.")
    k.setdefault("noindex", True)
    return k


def _datum(j, m=None, t=None, praefix=None):
    if not j:
        return ""
    s = f"{t:02d}.{m:02d}.{j}" if (m and t) else (f"{m:02d}.{j}" if m else str(j))
    return (praefix + " " if praefix else "") + s


def _feld_datum(wert):
    d = nf.datum_zerlegen(wert)
    return _datum(*d) if d else ""


class Daten:
    """Alles aus der Projektdatei im Speicher, nach Identitaet und Familie geordnet."""

    def __init__(self, con):
        self.quellen = {q["id"]: dict(q) for q in con.execute("SELECT * FROM quelle")}
        self.eintraege = {e["id"]: dict(e) for e in con.execute("SELECT * FROM eintrag")}
        self.felder = defaultdict(dict)
        for f in con.execute("SELECT eintrag, name, wert FROM feld WHERE wert IS NOT NULL"):
            self.felder[f["eintrag"]][f["name"]] = f["wert"]
        self.personen = {p["id"]: dict(p) for p in con.execute("SELECT * FROM person")}
        self.rollen = defaultdict(list)                      # ident -> [zuordnung mit person, eintrag]
        for r in con.execute("SELECT z.*, p.eintrag, p.pfad FROM zuordnung z JOIN person p ON p.id=z.person"):
            self.rollen[r["ident"]].append(dict(r))
        self.idents = {i["id"]: dict(i) for i in con.execute("SELECT * FROM identitaet")}
        self.fams = {f["id"]: dict(f) for f in con.execute("SELECT * FROM familie")}
        self.kinder = defaultdict(list)
        for k in con.execute("SELECT k.familie, k.ident, i.geb_jahr, i.geb_monat, i.geb_tag FROM kind k JOIN identitaet i ON i.id=k.ident"):
            self.kinder[k["familie"]].append((k["geb_jahr"] or 9999, k["geb_monat"] or 0, k["geb_tag"] or 0, k["ident"]))
        self.fams_von = defaultdict(list)
        for f in self.fams.values():
            for p in (f["mann"], f["frau"]):
                if p:
                    self.fams_von[p].append(f["id"])
        self.entschieden = {r["schluessel"]: r["art"] for r in con.execute("SELECT schluessel, art FROM entscheidung")}
        self.con = con

    def fund(self, eid):
        fl = self.felder.get(eid, {})
        e = self.eintraege[eid]
        return fl.get("zitat") or " ".join(x for x in (fl.get("kb"), f"S. {fl['seite']}" if fl.get("seite") else None,
                                                        f"Nr. {fl['lfd_nr']}" if fl.get("lfd_nr") else None) if x) or f"Zeile {e['zeile']}"

    def register_name(self, eid):
        return {"taufe": "Taufe", "ehe": "Trauung", "tod": "Begräbnis"}[self.eintraege[eid]["register"]]

    def name(self, i):
        if not i:
            return "—"
        n = i["name"] or ("NN" if i["unbekannt"] else "—")
        return f"{n}, {i['vorname'] or '—'}"

    def buchstabe(self, i):
        n = (i["name"] or "") if i else ""
        b = n[:1].upper() if n else "_"
        return b if b.isalpha() else "_"          # "_" statt "?": Fragezeichen ist unter Windows im Dateinamen verboten

    def familien_buchstabe(self, f):
        i = self.idents.get(f["mann"]) or self.idents.get(f["frau"])
        return self.buchstabe(i)

    def stufe_zeichen(self, r):
        if r["stufe"] == "neu" and r["alternativen"] not in (None, "[]"):
            return "??", "n"
        return ZEICHEN.get(r["stufe"], ""), KLASSE.get(r["stufe"], "")

    def lebensdaten(self, i):
        geb = _datum(i["geb_jahr"], i["geb_monat"], i["geb_tag"], i["geb_praefix"]) if i and i["geb_jahr"] else ""
        tod = _datum(i["tod_jahr"], i["tod_monat"], i["tod_tag"]) if i and i["tod_jahr"] else ""
        return (f" *{geb}" if geb else "") + (f" †{tod}" if tod else "")

    def berufe(self, iid):
        out = []
        for r in sorted(self.rollen.get(iid, []), key=lambda r: self.eintraege[r["eintrag"]]["jahr"] or 0):
            b = self.personen[r["person"]]["beruf"]
            if b and b not in out:
                out.append(b)
        return out

    def belege(self, iid):
        """HTML-Liste aller Nennungen einer Identitaet mit Stufe und Fundstelle."""
        zeilen = []
        for r in sorted(self.rollen.get(iid, []), key=lambda r: (self.eintraege[r["eintrag"]]["jahr"] or 0, r["eintrag"])):
            e, p = self.eintraege[r["eintrag"]], self.personen[r["person"]]
            z, kl = self.stufe_zeichen(r)
            grund = r["grund"] or ""
            zeilen.append(f'<li class="{kl}"><span class="beleg">{self.register_name(e["id"])} {e["jahr"] or "?"}, {h(self.fund(e["id"]))}, {h(r["pfad"])}</span>: '
                          f'{h(p["roh"] or "")} <span class="stufe">{z}</span>' + (f'<small class="grund">{h(grund)}</small>' if grund else "") + "</li>")
        return "<ul class='belege'>" + "".join(zeilen) + "</ul>" if zeilen else ""


def seite(konfig, titel, inhalt, stand, aktiv=""):
    noindex = '<meta name="robots" content="noindex, nofollow">' if konfig.get("noindex", True) else ""
    nav = "".join(f'<a href="{href}"{" class=aktiv" if aktiv == href else ""}>{t}</a>' for href, t in (
        ("index.html", "Start"), ("familien.html", "Familien"), ("personen.html", "Personen"), ("orte.html", "Orte"),
        ("berufe.html", "Berufe"), ("quellen.html", "Quellen"), ("prueffaelle.html", "Prüffälle"), ("stufen.html", "Stufen"),
        ("statistik.html", "Statistik"), ("verfahren.html", "Verfahren")))
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">{noindex}
<title>{h(titel)} · {h(konfig["titel"])}</title><link rel="stylesheet" href="stil.css"></head>
<body><header><a class="marke" href="index.html">{h(konfig["titel"])}</a><nav>{nav}</nav></header>
<main>{inhalt}</main>
<footer>{h(konfig["titel"])} · Arbeitsfassung, Stand {stand} · erzeugt mit famrecon {__version__} · <a href="impressum.html">Impressum</a> · <a href="datenschutz.html">Datenschutz</a></footer>
</body></html>"""


STIL = """
:root { --tinte:#222; --grau:#666; --linie:#ddd; --papier:#fbfaf6; --akzent:#2a5d8f; --warn:#fff4d6; --rot:#fde8e8; --ok:#e6f4ea; }
* { box-sizing: border-box; } body { margin:0; font: 15px/1.5 Georgia, 'DejaVu Serif', serif; color:var(--tinte); background:var(--papier); }
header { display:flex; flex-wrap:wrap; gap:1rem 1.5rem; align-items:baseline; padding:.7rem 1.2rem; background:#fff; border-bottom:1px solid var(--linie); }
.marke { font-weight:700; color:var(--akzent); text-decoration:none; font-size:1.15rem; }
nav a { margin-right:.9rem; color:var(--grau); text-decoration:none; font-family: system-ui, sans-serif; font-size:.92rem; } nav a.aktiv { color:var(--akzent); font-weight:600; }
main { max-width: 980px; margin:0 auto; padding:1rem 1.2rem 3rem; } footer { color:var(--grau); font-size:.85rem; text-align:center; padding:1rem; font-family: system-ui, sans-serif; }
h1 { font-size:1.6rem; margin:.4rem 0 .6rem; } h2 { font-size:1.2rem; margin:1.6rem 0 .5rem; } a { color:var(--akzent); }
.hinweis { background:var(--warn); border-radius:6px; padding:.5rem .8rem; font-family: system-ui, sans-serif; font-size:.92rem; }
.artikel { background:#fff; border:1px solid var(--linie); border-radius:8px; padding:.8rem 1rem; margin:.8rem 0; }
.artikel h3 { margin:0 0 .4rem; font-size:1.05rem; } .artikel h3 small { color:var(--grau); font-weight:normal; }
.paar p { margin:.2rem 0; } .kinder { margin:.4rem 0 0 1.2rem; } .kinder li { margin:.15rem 0; }
.w { font-style: italic; } .u .stufe, .n .stufe { color:#b45309; font-weight:700; } .stufe { margin-left:.2rem; } .v .stufe { color:#2b7a3d; }
.beleg { color:var(--grau); font-family: system-ui, sans-serif; font-size:.85rem; } .grund { color:var(--grau); margin-left:.4rem; }
details { margin:.3rem 0; } summary { cursor:pointer; color:var(--akzent); font-family: system-ui, sans-serif; font-size:.88rem; }
ul.belege { margin:.3rem 0 .5rem 1rem; padding:0; font-size:.92rem; }
table { border-collapse: collapse; width:100%; font-family: system-ui, sans-serif; font-size:.92rem; } th, td { text-align:left; padding:.3rem .5rem; border-bottom:1px solid var(--linie); vertical-align:top; }
.abc a { display:inline-block; margin:.1rem .3rem; } .klein { color:var(--grau); font-size:.88rem; font-family: system-ui, sans-serif; }
.legende span { display:inline-block; margin-right:1rem; }
ol.schema { list-style:none; padding:0; margin:1rem 0 1.5rem; display:flex; flex-wrap:wrap; gap:.4rem; align-items:stretch; counter-reset: s; }
ol.schema li { counter-increment: s; flex:1 1 9.5rem; background:#fff; border:1px solid var(--linie); border-top:4px solid var(--akzent);
  border-radius:6px; padding:.5rem .6rem; font-family: system-ui, sans-serif; font-size:.85rem; position:relative; }
ol.schema li::before { content: counter(s); position:absolute; top:.3rem; right:.5rem; color:var(--grau); font-size:.75rem; }
ol.schema li b { display:block; font-size:.92rem; margin-bottom:.2rem; color:var(--akzent); }
ol.schema li .zahl { display:block; font-size:1.15rem; font-weight:700; color:var(--tinte); }
ol.schema li.offen { border-top-color:#b45309; } ol.schema li.mensch { border-top-color:#2b7a3d; }
.schritt { border-left:3px solid var(--linie); padding-left:.9rem; margin:1.2rem 0; }
@media print { header, footer, details > summary { display:none; } .artikel { break-inside: avoid; border:0; } }
"""


def artikel(D, f):
    """Ein Familienartikel als HTML."""
    mann, frau = D.idents.get(f["mann"]), D.idents.get(f["frau"])
    tr = ""
    if f["trauung_eintrag"]:
        e = D.eintraege[f["trauung_eintrag"]]; fl = D.felder.get(e["id"], {})
        teile = [_datum(f["tr_jahr"], f["tr_monat"], f["tr_tag"])]
        if fl.get("trauung_ort") or fl.get("ort"):
            teile.append(h(fl.get("trauung_ort") or fl.get("ort")))
        tr = " ⚭ " + " ".join(t for t in teile if t) + f' <span class="beleg">({h(D.fund(e["id"]))})</span>'
        extra = []
        if fl.get("zeugen"):
            extra.append("Zeugen: " + h(fl["zeugen"].replace(" | ", "; ")))
        if fl.get("pfarrer"):
            extra.append("Pfarrer: " + h(fl["pfarrer"]))
        if fl.get("bemerkung"):
            extra.append(h(fl["bemerkung"]))
        if extra:
            tr += '<br><span class="klein">' + " · ".join(extra) + "</span>"
    elif f["art"] == "eltern":
        tr = ' <span class="klein">(Ehe erschlossen, kein Traueintrag)</span>'

    def person(i, rolle):
        if not i:
            return f"<p><b>{rolle}:</b> —</p>"
        berufe = D.berufe(i["id"])
        herkunft = next((D.personen[r["person"]]["herkunft"] for r in D.rollen.get(i["id"], []) if D.personen[r["person"]]["herkunft"]), None)
        weitere = [fid for fid in D.fams_von.get(i["id"], []) if fid != f["id"]]
        txt = f"<p><b>{rolle}:</b> {h(D.name(i))}{h(D.lebensdaten(i))}"
        if i["geburtsname"] and i["ehename"]:
            txt += f' <span class="klein">(verh. {h(i["ehename"])})</span>'
        if berufe:
            txt += f' <span class="klein">· {h("; ".join(berufe))}</span>'
        if herkunft:
            txt += f' <span class="klein">· aus {h(herkunft)}</span>'
        if i["famc"] and i["famc"] in D.fams:
            txt += f' <a class="klein" href="familien-{D.familien_buchstabe(D.fams[i["famc"]])}.html#F{i["famc"]}">← Eltern F{i["famc"]}</a>'
        for fid in weitere:
            txt += f' <a class="klein" href="familien-{D.familien_buchstabe(D.fams[fid])}.html#F{fid}">⚭ weitere Ehe F{fid}</a>'
        txt += "</p>"
        b = D.belege(i["id"])
        if b:
            txt += f"<details><summary>Belege ({len(D.rollen.get(i['id'], []))})</summary>{b}</details>"
        return txt

    kinder = []
    for _, _, _, kid in sorted(D.kinder.get(f["id"], [])):
        k = D.idents[kid]
        eigene = D.fams_von.get(kid, [])
        zeile = f"{h(D.name(k))}{h(D.lebensdaten(k))}"
        # Taufe des Kindes: Paten, Rueckverweise
        for r in D.rollen.get(kid, []):
            e = D.eintraege[r["eintrag"]]
            if e["register"] == "taufe" and r["pfad"] == "kind":
                fl = D.felder.get(e["id"], {})
                if fl.get("tauf_datum"):
                    zeile += f' <span class="klein">~{_feld_datum(fl["tauf_datum"])}</span>'
                if fl.get("unehelich") and str(fl["unehelich"]).lower() in ("u", "unehelich", "ja", "x", "1"):
                    zeile += ' <span class="klein">unehelich</span>'
                zeile += f' <span class="beleg">({h(D.fund(e["id"]))})</span>'
                if fl.get("paten"):
                    zeile += f'<details><summary>Paten</summary><span class="klein">{h(fl["paten"].replace(" | ", "; "))}</span></details>'
        for fid in eigene:
            zeile += f' <a class="klein" href="familien-{D.familien_buchstabe(D.fams[fid])}.html#F{fid}">⚭ F{fid}</a>'
        b = D.belege(kid)
        if b and len(D.rollen.get(kid, [])) > 1:
            zeile += f"<details><summary>Belege ({len(D.rollen.get(kid, []))})</summary>{b}</details>"
        kinder.append(f"<li>{zeile}</li>")
    kopf_name = h(D.name(mann) if mann else D.name(frau))
    return (f'<article class="artikel" id="F{f["id"]}"><h3>{kopf_name}{tr} <small>F{f["id"]}</small></h3>'
            f'<div class="paar">{person(mann, "Mann")}{person(frau, "Frau")}</div>'
            + (f'<ol class="kinder">{"".join(kinder)}</ol>' if kinder else '<p class="klein">keine Kinder in den Registern</p>') + "</article>")


def zeig(b):
    """Buchstabe fuer die Anzeige: Namen ohne Anfangsbuchstaben stehen unter "?" (Datei: _)."""
    return "?" if b == "_" else b


def bauen(con, ziel, konfig=None, ged=None, projekt="projekt"):
    """Die ganze Site in den Ordner `ziel` schreiben. -> dict mit Zahlen."""
    ziel = Path(ziel); ziel.mkdir(parents=True, exist_ok=True)
    K = konfig_laden(konfig, projekt) if not isinstance(konfig, dict) else konfig
    D = Daten(con)
    stand = dt.date.today().strftime("%d.%m.%Y")
    (ziel / "stil.css").write_text(STIL, encoding="utf-8")

    def schreibe(name, titel, inhalt, aktiv=None):
        (ziel / name).write_text(seite(K, titel, inhalt, stand, aktiv or name), encoding="utf-8")

    legende = ('<p class="legende klein"><span><b>Zeichen:</b></span><span>sicher: ohne Zeichen</span><span class="w">wahrscheinlich: kursiv</span>'
               '<span class="u">unsicher: <span class="stufe">?</span></span><span class="n">unentschieden: <span class="stufe">??</span></span>'
               '<span class="v">Kennung: <span class="stufe">✓</span></span><span>Ehe erschlossen: kein Traueintrag</span></p>')
    hinweis = (f'<p class="hinweis">Arbeitsfassung, Stand {stand}. Die Familien sind aus den Registern gerechnet, nicht von Hand geprüft. '
               f'Jede Angabe trägt ihre Fundstelle; jede Verbindung zwischen Einträgen ihre Stufe. Zweifel stehen unter <a href="prueffaelle.html">Prüffälle</a>.</p>')

    # ---- Familien je Buchstabe
    nach_b = defaultdict(list)
    for f in D.fams.values():
        nach_b[D.familien_buchstabe(f)].append(f)
    buchstaben = sorted(nach_b)
    abc = '<p class="abc">' + " ".join(f'<a href="familien-{b}.html">{zeig(b)}</a>' for b in buchstaben) + "</p>"
    for b, fl in nach_b.items():
        fl.sort(key=lambda f: (D.name(D.idents.get(f["mann"]) or D.idents.get(f["frau"])).lower(), f["tr_jahr"] or 0, f["id"]))
        inhalt = f"<h1>Familien {zeig(b)}</h1>{abc}{legende}" + "".join(artikel(D, f) for f in fl) + abc
        schreibe(f"familien-{b}.html", f"Familien {zeig(b)}", inhalt, "familien.html")
    schreibe("familien.html", "Familien", f"<h1>Familien</h1>{hinweis}{abc}<p>{len(D.fams)} Familien, nach dem Nachnamen des Mannes geordnet. {legende}</p>")

    # ---- Personen A-Z
    nach_bp = defaultdict(list)
    for i in D.idents.values():
        nach_bp[D.buchstabe(i)].append(i)
    abcp = '<p class="abc">' + " ".join(f'<a href="personen-{b}.html">{zeig(b)}</a>' for b in sorted(nach_bp)) + "</p>"
    for b, il in nach_bp.items():
        il.sort(key=lambda i: (D.name(i).lower(), i["geb_jahr"] or 0))
        zeilen = []
        for i in il:
            links = []
            if i["famc"] and i["famc"] in D.fams:
                links.append(f'<a href="familien-{D.familien_buchstabe(D.fams[i["famc"]])}.html#F{i["famc"]}">Kind in F{i["famc"]}</a>')
            for fid in D.fams_von.get(i["id"], []):
                links.append(f'<a href="familien-{D.familien_buchstabe(D.fams[fid])}.html#F{fid}">F{fid}</a>')
            zeilen.append(f"<tr><td>{h(D.name(i))}</td><td>{h(D.lebensdaten(i))}</td><td>{h('; '.join(D.berufe(i['id'])))}</td><td>{len(D.rollen.get(i['id'], []))}</td><td>{' · '.join(links)}</td></tr>")
        schreibe(f"personen-{b}.html", f"Personen {zeig(b)}", f"<h1>Personen {zeig(b)}</h1>{abcp}<table><tr><th>Name</th><th>Lebensdaten</th><th>Berufe</th><th>Nennungen</th><th>Familien</th></tr>{''.join(zeilen)}</table>{abcp}", "personen.html")
    schreibe("personen.html", "Personen", f"<h1>Personen</h1>{abcp}<p>{len(D.idents)} Personen, wie die Rekonstitution sie aus {len(D.personen)} Nennungen gebildet hat.</p>")

    # ---- Orte, Berufe, Quellen
    orte, berufe = Counter(), Counter()
    for eid, fl in D.felder.items():
        for k in ("ort", "geburt_ort", "tauf_ort", "trauung_ort", "sterbe_ort", "begraebnis_ort"):
            if fl.get(k):
                orte[fl[k]] += 1
    for p in D.personen.values():
        if p["herkunft"]:
            orte[p["herkunft"]] += 1
        if p["beruf"]:
            berufe[p["beruf"]] += 1
    tab = lambda c: "<table><tr><th>Bezeichnung</th><th>Nennungen</th></tr>" + "".join(f"<tr><td>{h(k)}</td><td>{n}</td></tr>" for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))) + "</table>"
    schreibe("orte.html", "Orte", f"<h1>Orte</h1><p class='klein'>{len(orte)} verschiedene Ortsangaben, wie sie in den Einträgen stehen (Pfarrort, Geburts-, Trau-, Sterbeorte, Herkunft).</p>{tab(orte)}")
    schreibe("berufe.html", "Berufe", f"<h1>Berufe und Stände</h1><p class='klein'>{len(berufe)} verschiedene Angaben, wörtlich aus den Einträgen.</p>{tab(berufe)}")
    q = "<table><tr><th>Datei</th><th>Blatt</th><th>Register</th><th>Einträge</th></tr>" + "".join(
        f"<tr><td>{h(x['datei'])}</td><td>{h(x['blatt'] or '')}</td><td>{h(x['register'])}</td><td>{x['zeilen']}</td></tr>" for x in D.quellen.values()) + "</table>"
    schreibe("quellen.html", "Quellen", f"<h1>Quellen</h1><p>Grundlage sind die Registerabschriften in Tabellenform{(' von ' + h(K['erfasser'])) if K['erfasser'] else ''}. "
             f"Jede Angabe im Buch nennt in Klammern ihre Fundstelle, so wie sie in der Tabelle steht (Register, Jahr, Buch, Seite, Nummer).</p>{q}")

    # ---- Prueffaelle und Stufen
    faelle = urteile.faelle(con)
    zeilen = []
    for r in faelle:
        kand = [(r["ident"], r["punkte"], r["grund"])] + [tuple(a) for a in json.loads(r["alternativen"] or "[]")]
        if r["stufe"] == "neu":
            kand = kand[1:]
        ktxt = "<br>".join(f'[{k[0]}] {h(D.name(D.idents.get(k[0])))}{h(D.lebensdaten(D.idents.get(k[0])))} <span class="klein">({k[1]} P.: {h(k[2] or "")})</span>' for k in kand)
        fam = D.fams.get(D.idents[r["ident"]]["famc"]) if r["ident"] in D.idents else None
        link = f'<a href="familien-{D.familien_buchstabe(fam)}.html#F{fam["id"]}">F{fam["id"]}</a>' if fam else ""
        zeilen.append(f"<tr><td>{D.register_name(r['eintrag_id'])} {r['jahr'] or '?'}<br><span class='klein'>{h(D.fund(r['eintrag_id']))} · {h(r['pfad'])}</span></td>"
                      f"<td>{h(r['roh'] or '')}</td><td>{'eigene Person (unentschieden)' if r['stufe']=='neu' else h(D.name(D.idents.get(r['ident'])))}<br><span class='klein'>{h(r['grund'] or '')}</span></td><td>{ktxt}</td><td>{link}</td></tr>")
    schreibe("prueffaelle.html", "Prüffälle", f"<h1>Prüffälle</h1><p>{len(faelle)} Nennungen, bei denen die Rekonstitution nicht sicher war: mehrere Personen passen ähnlich gut, oder ein Veto spricht gegen die Wahl. "
             f"Die Spalte Kandidaten zeigt, was in Frage kam. Diese Fälle sind der Arbeitsvorrat für die Durchsicht.</p>"
             f"<table><tr><th>Fall</th><th>Nennung</th><th>Wahl</th><th>Kandidaten</th><th>Familie</th></tr>{''.join(zeilen)}</table>")
    stufen = Counter(r["stufe"] for rl in D.rollen.values() for r in rl)
    erschlossen = [f for f in D.fams.values() if f["art"] == "eltern" and D.kinder.get(f["id"])]
    ohne_vater = [f for f in D.fams.values() if not f["mann"] and D.kinder.get(f["id"])]
    inh = f"<h1>Stufen</h1><p>Jede Verbindung einer Nennung mit einer Person trägt eine Stufe. Verteilung: " + ", ".join(f"{k} {v}" for k, v in sorted(stufen.items())) + ".</p>"
    inh += f"<h2>Familien ohne Traueintrag ({len(erschlossen)})</h2><p class='klein'>Aus Taufen oder Begräbnissen erschlossen: dieselben Eltern, keine Trauung im Bestand.</p><ul>" + "".join(
        f'<li><a href="familien-{D.familien_buchstabe(f)}.html#F{f["id"]}">F{f["id"]}</a> {h(D.name(D.idents.get(f["mann"])))} &amp; {h(D.name(D.idents.get(f["frau"])))}, {len(D.kinder[f["id"]])} Kinder</li>' for f in sorted(erschlossen, key=lambda f: D.name(D.idents.get(f["mann"]) or D.idents.get(f["frau"])))) + "</ul>"
    inh += f"<h2>Kinder ohne genannten Vater ({len(ohne_vater)} Familien)</h2><ul>" + "".join(
        f'<li><a href="familien-{D.familien_buchstabe(f)}.html#F{f["id"]}">F{f["id"]}</a> Mutter {h(D.name(D.idents.get(f["frau"])))}, {len(D.kinder[f["id"]])} Kinder</li>' for f in ohne_vater) + "</ul>"
    schreibe("stufen.html", "Stufen", inh)

    # ---- Statistik
    n_nenn = Counter(len(rl) for rl in D.rollen.values())
    jahre = {}
    for e in D.eintraege.values():
        if e["jahr"]:
            a = jahre.setdefault(e["register"], [e["jahr"], e["jahr"], 0]); a[0] = min(a[0], e["jahr"]); a[1] = max(a[1], e["jahr"]); a[2] += 1
    kinderzahl = Counter(len(v) for v in D.kinder.values())
    st = f"<h1>Statistik</h1><h2>Register</h2><table><tr><th>Register</th><th>von</th><th>bis</th><th>Einträge</th></tr>" + "".join(
        f"<tr><td>{h(r)}</td><td>{a[0]}</td><td>{a[1]}</td><td>{a[2]}</td></tr>" for r, a in jahre.items()) + "</table>"
    st += f"<h2>Rekonstitution</h2><p>{len(D.personen)} Nennungen wurden zu {len(D.idents)} Personen und {len(D.fams)} Familien. Stufen: " + ", ".join(f"{k} {v}" for k, v in sorted(stufen.items())) + ".</p>"
    st += "<table><tr><th>Nennungen je Person</th><th>Personen</th></tr>" + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in sorted(n_nenn.items())) + "</table>"
    st += "<h2>Kinder je Familie</h2><table><tr><th>Kinder</th><th>Familien</th></tr>" + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in sorted(kinderzahl.items())) + "</table>"
    schreibe("statistik.html", "Statistik", st)

    # ---- Verfahren
    schreibe("verfahren.html", "Verfahren", verfahren(con, D, faelle, ged))

    # ---- GEDCOM, Impressum, Datenschutz, Start
    ged_link = ""
    if ged and Path(ged).exists():
        name = f"{projekt}-{dt.date.today().isoformat()}.ged"
        shutil.copy(ged, ziel / name)
        ged_link = f'<p><a href="{name}">GEDCOM herunterladen</a> <span class="klein">({name}, zum Einlesen in Gramps, Ahnenblatt, webtrees oder für das Online-OFB)</span></p>'
    einl = "".join(f"<p>{h(a)}</p>" for a in K["einleitung"].split("\n\n") if a.strip())
    personen_ = ("".join(f"<p class='klein'>{t}: {h(v)}</p>" for t, v in (("Erfassung der Register", K["erfasser"]), ("Bearbeitung", K["bearbeiter"])) if v))
    start = (f"<h1>{h(K['titel'])}</h1><p class='klein'>{h(K['untertitel'])}</p>{hinweis}{einl}{personen_}"
             f"<h2>Inhalt</h2><ul><li><a href='familien.html'>Familien A–Z</a>: {len(D.fams)} Familien</li><li><a href='personen.html'>Personen</a>: {len(D.idents)}</li>"
             f"<li><a href='orte.html'>Orte</a>, <a href='berufe.html'>Berufe</a>, <a href='quellen.html'>Quellen</a></li><li><a href='prueffaelle.html'>Prüffälle</a>: {len(faelle)} offene Fragen</li>"
             f"<li><a href='stufen.html'>Stufen</a>, <a href='statistik.html'>Statistik</a></li>"
             f"<li><a href='verfahren.html'>Verfahren</a>: wie dieses Buch aus den Registern gerechnet wurde</li></ul>{legende}{ged_link}")
    schreibe("index.html", "Start", start)
    schreibe("impressum.html", "Impressum", "<h1>Impressum</h1>" + ("".join(f"<p>{h(a)}</p>" for a in K["impressum"].split("\n\n")) if K["impressum"] else "<p class='klein'>Noch nicht eingetragen (buch.toml, Schlüssel impressum).</p>"))
    schreibe("datenschutz.html", "Datenschutz", "<h1>Datenschutz</h1>" + "".join(f"<p>{h(a)}</p>" for a in K["datenschutz"].split("\n\n")))
    return dict(familien=len(D.fams), personen=len(D.idents), seiten=len(list(ziel.glob("*.html"))), prueffaelle=len(faelle), ordner=str(ziel))


ROLLE_TEXT = {"kind": "Täuflinge", "vater": "Väter", "mutter": "Mütter", "verstorbener": "Verstorbene",
              "verstorbener_vater": "Väter von Verstorbenen", "verstorbener_mutter": "Mütter von Verstorbenen",
              "verstorbener_ehepartner": "Ehepartner von Verstorbenen", "braeutigam": "Bräutigame", "braut": "Bräute",
              "braeutigam_vater": "Väter von Bräutigamen", "braeutigam_mutter": "Mütter von Bräutigamen",
              "braut_vater": "Väter von Bräuten", "braut_mutter": "Mütter von Bräuten"}
REGEL_NAME = {"Alter ausserhalb des Fensters der Rolle": "Alter außerhalb des Fensters der Rolle",
              "juenger als 14 in einer Erwachsenenrolle": "jünger als 14 in einer Erwachsenenrolle",
              "Kinderspanne ueberschritten": "Kinderspanne überschritten", "aelter als 100": "älter als 100",
              "Begraebnis: ledig, genannter Vater widerspricht": "Begräbnis: ledig, genannter Vater widerspricht",
              "Begraebnis: verheiratet, kein Partner passt": "Begräbnis: verheiratet, kein Partner passt",
              "Begraebnis: Kind ohne klaren Anker an eine Taufe": "Begräbnis: Kind ohne klaren Anker an eine Taufe"}

# Erklaerung der Ausschlussregeln fuer Leser (Schluessel = Name in verknuepfen._aus)
REGEL_TEXT = {
    "Mutter widerspricht": "Die genannte Mutter passt nicht zur Ehefrau dieser Familie (anderer Name oder Vorname).",
    "Alter ausserhalb des Fensters der Rolle": "Zu jung oder zu alt für die Rolle: Vater 16 bis 75, Mutter 15 bis 50, Brautleute 14 bis 80 Jahre.",
    "schon tot": "Die Person war zum Zeitpunkt des Eintrags schon begraben (Ausnahme: Vater eines nachgeborenen Kindes).",
    "Geburt weicht mehr als 5 Jahre ab": "Die aus der Altersangabe errechnete Geburt liegt mehr als fünf Jahre neben der belegten Taufe.",
    "geboren nach erstem Auftreten als Erwachsener": "Die Person trat schon als Erwachsene auf, bevor sie geboren sein könnte.",
    "juenger als 14 in einer Erwachsenenrolle": "Als Vater, Mutter oder Brautleute unter 14 Jahren.",
    "Ehefrau vor der Taufe gestorben": "Die Ehefrau dieser Familie war bei der Taufe schon tot, kann also nicht die Mutter sein.",
    "Trauung nach der Taufe": "Die Trauung dieser Familie liegt nach der Taufe.",
    "Kinderspanne ueberschritten": "Zwischen erstem und letztem Kind lägen mehr als 22 Jahre.",
    "anderer Vater": "Die Person hat bereits Eltern, und der genannte Vater hat einen anderen Nachnamen.",
    "Geschlecht widerspricht": "Mann und Frau passen nicht zusammen.",
    "mit der genannten Mutter verheiratet (ist der Vater)": "Der Kandidat ist mit der genannten Mutter verheiratet; er ist der Vater, nicht der Sohn.",
    "Vorname widerspricht": "Kein gemeinsamer Vorname (Johann Friedrich und Friedrich gelten als passend).",
    "Kandidat ohne Vorname": "Die Nennung hat einen Vornamen, der Kandidat keinen.",
    "aelter als 100": "Über hundert Jahre alt.",
    "offen: zwei Personen passen gleich gut": "Nicht geraten: eigene Person, beide Kandidaten in die Prüffälle.",
    "offen: zwei Familien passen gleich gut": "Nicht geraten: eigene Elternfamilie, die Ehen als Kandidaten in die Prüffälle.",
    "Begraebnis: ledig, genannter Vater widerspricht": "Begräbnis eines Ledigen, dessen genannter Vater nicht zur gefundenen Familie passt.",
    "Begraebnis: verheiratet, kein Partner passt": "Begräbnis einer verheirateten Person, deren genannter Ehepartner zu keiner Ehe passt.",
    "Begraebnis: Kind ohne klaren Anker an eine Taufe": "Kindsbegräbnis ohne Datum oder Eltern, die es sicher an eine Taufe binden.",
}


def verfahren(con, D, faelle, ged=None):
    """Seite "Verfahren": wie famrecon diesen Bestand gerechnet hat, mit den Zahlen der Projektdatei."""
    reg = Counter(e["register"] for e in D.eintraege.values())
    jahre = [e["jahr"] for e in D.eintraege.values() if e["jahr"]]
    rollen = Counter(p["pfad"] for p in D.personen.values())
    marker = {k: sum(1 for p in D.personen.values() if p.get(k)) for k in ("unbekannt", "unsicher", "verstorben", "totgeburt")}
    cal = sum(1 for p in D.personen.values() if p.get("geburt_praefix") == "CAL")
    stufen = Counter(r["stufe"] for rl in D.rollen.values() for r in rl)
    offen = sum(1 for rl in D.rollen.values() for r in rl if r["stufe"] == "neu" and r["alternativen"] not in (None, "", "[]"))
    n_nenn = Counter(len(rl) for rl in D.rollen.values())
    mehrfach = sum(v for k, v in n_nenn.items() if k >= 2)
    pfade = defaultdict(set)
    for iid, rl in D.rollen.items():
        for r in rl:
            pfade[iid].add(r["pfad"])
    taufe_tod = sum(1 for s in pfade.values() if "kind" in s and "verstorbener" in s)
    braut_eltern = sum(1 for s in pfade.values() if s & {"braeutigam", "braut"} and s & {"vater", "mutter"})
    mit_tr = sum(1 for f in D.fams.values() if f["trauung_eintrag"])
    erschl = sum(1 for f in D.fams.values() if not f["trauung_eintrag"] and D.kinder.get(f["id"]))
    entsch = con.execute("SELECT COUNT(*) FROM entscheidung").fetchone()[0]
    aus = verknuepfen.ausschluesse(con)
    REG = {"taufe": "Taufen", "ehe": "Trauungen", "tod": "Begräbnisse"}
    fmt = lambda n: f"{n:,}".replace(",", ".")

    schema = (
        '<ol class="schema">'
        f'<li><b>Register</b><span class="zahl">{fmt(len(D.eintraege))}</span>Einträge in {len(D.quellen)} Tabellen</li>'
        f'<li><b>Normalform</b><span class="zahl">{fmt(len(D.personen))}</span>Nennungen von Personen</li>'
        f'<li><b>Verknüpfen</b><span class="zahl">{fmt(sum(a[2] for a in aus if not a[0].startswith("offen")))}</span>Kandidaten nach Regeln ausgeschlossen</li>'
        f'<li><b>Ergebnis</b><span class="zahl">{fmt(len(D.idents))}</span>Personen, {fmt(len(D.fams))} Familien</li>'
        f'<li class="offen"><b>Offen</b><span class="zahl">{fmt(offen)}</span>Prüffälle, nicht geraten</li>'
        f'<li class="mensch"><b>Durchsicht</b><span class="zahl">{fmt(entsch)}</span>Entscheidungen von Hand</li>'
        f'<li><b>Ausgabe</b><span class="zahl">GEDCOM</span>und dieses Buch</li></ol>')

    t = ["<h1>Verfahren</h1>",
         "<p>Dieses Buch ist nicht von Hand zusammengestellt, sondern aus den Registerabschriften gerechnet. "
         "Ein Kirchenbuch kennt keine Personen, nur Einträge: eine Taufe, eine Trauung, ein Begräbnis. Dass der Vater einer "
         "Taufe derselbe Mann ist wie der Bräutigam einer Trauung und der Verstorbene eines Begräbnisses, steht nirgends. "
         "Diese Verbindungen herzustellen heißt <i>Familienrekonstitution</i>; das Programm famrecon tut es nach festen, "
         "hier beschriebenen Regeln. Jede Zahl auf dieser Seite stammt aus diesem Bestand.</p>",
         schema]

    t.append('<div class="schritt"><h2>1. Register</h2><p>Grundlage: ' + ", ".join(f"{fmt(reg[r])} {REG.get(r, r)}" for r in ("taufe", "ehe", "tod") if reg[r])
             + (f", {min(jahre)} bis {max(jahre)}" if jahre else "") + ". Jede Tabellenzeile ist ein Eintrag; Spalten wurden einmal "
             "den Feldern des Programms zugeordnet (Vater, Mutter, Pate, Datum …). Nichts wurde vorher umgeschrieben.</p></div>")

    t.append('<div class="schritt"><h2>2. Normalform</h2><p>Aus jedem Eintrag werden die genannten Personen gelesen: '
             f"{fmt(len(D.personen))} Nennungen, darunter " + ", ".join(f"{fmt(v)} {ROLLE_TEXT.get(k, k.replace('_', ' '))}" for k, v in rollen.most_common(6)) + ". "
             "Schreibweisen wie „Nachname, Vorname, Beruf“ werden zerlegt, Vermerke gedeutet: "
             f"{fmt(marker['unbekannt'])} Namen unbekannt (N., NN), {fmt(marker['unsicher'])} unsicher gelesen (?), "
             f"{fmt(marker['verstorben'])} als verstorben genannt (weyl., +), {fmt(marker['totgeburt'])} Totgeburten. "
             f"Bei {fmt(cal)} Verstorbenen wurde das Geburtsjahr aus der Altersangabe errechnet. "
             "Nachnamen bekommen einen Lautschlüssel (Kölner Phonetik), damit „Kiefer“ und „Kieffer“ sich finden; "
             "Vornamen eine Einheitsform (Nicolaus = Nikolaus). Der Wortlaut der Quelle bleibt daneben erhalten.</p></div>")

    t.append('<div class="schritt"><h2>3. Verknüpfen</h2><p>Alle Einträge laufen in zeitlicher Folge durch, die drei Register gemischt. '
             "Jeder Eintrag sucht unter dem, was vorher war:</p><ul>"
             "<li><b>Taufe:</b> eine Familie, deren Mann zum genannten Vater passt und deren Frau der genannten Mutter nicht widerspricht. "
             "Gibt es keine, entsteht eine Familie „Ehe erschlossen“. Das Kind ist immer eine neue Person.</li>"
             "<li><b>Trauung:</b> Bräutigam und Braut unter den bekannten Personen (Name, Vorname, Alter, genannte Eltern). "
             "Wurden Kinder des Paares schon vorher getauft, wird deren Familie zur Ehe.</li>"
             "<li><b>Begräbnis:</b> der Verstorbene über Name, Vorname, Geburt aus dem Alter, Eltern oder Ehepartner.</li></ul>"
             "<p>Für jede Möglichkeit gibt es Punkte (Vorname, Geburtsjahr, Mutter, Ehepartner …). Gewählt wird nur, wer genug Punkte hat "
             "und deutlich vor dem Nächsten liegt. Vorher scheiden Kandidaten aus, die nach festen Regeln unmöglich sind:</p>")
    if aus:
        t.append("<table><tr><th>Regel</th><th>Bedeutung</th><th>griff</th></tr>" + "".join(
            f"<tr><td>{h(REGEL_NAME.get(r, r))}</td><td class='klein'>{h(REGEL_TEXT.get(r, ''))}</td><td>{fmt(tr)}</td></tr>" for r, alle, tr in aus if tr)
            + "</table><p class='klein'>Gezählt sind Prüfungen, bei denen Nach- und Vorname gepasst hätten; ein Kandidat kann mehrfach geprüft werden.</p>")
    t.append("</div>")

    t.append('<div class="schritt"><h2>4. Ergebnis</h2>'
             f"<p>{fmt(len(D.personen))} Nennungen ergaben {fmt(len(D.idents))} Personen und {fmt(len(D.fams))} Familien, "
             f"davon {fmt(mit_tr)} mit Traueintrag und {fmt(erschl)} aus Taufen erschlossen. "
             f"{fmt(mehrfach)} Personen kommen in mehr als einem Eintrag vor; {fmt(taufe_tod)} sind über Taufe und Begräbnis verbunden, "
             f"{fmt(braut_eltern)} Brautleute treten später als Eltern auf.</p>"
             "<table><tr><th>Stufe</th><th>Nennungen</th><th>Bedeutung</th></tr>"
             f"<tr><td>sicher</td><td>{fmt(stufen.get('sicher', 0))}</td><td class='klein'>außer dem Namen passt ein weiterer Anker (Mutter, Ehepartner, Datum)</td></tr>"
             f"<tr><td><i>wahrscheinlich</i></td><td>{fmt(stufen.get('wahrscheinlich', 0))}</td><td class='klein'>Name und Vorname passen, kein Gegenkandidat</td></tr>"
             f"<tr><td>neu</td><td>{fmt(stufen.get('neu', 0))}</td><td class='klein'>erste Nennung einer Person, oder offen gelassen (siehe 5)</td></tr>"
             + (f"<tr><td>Kennung ✓</td><td>{fmt(stufen.get('vorgabe', 0))}</td><td class='klein'>durch eine Kennung in der Tabelle vorgegeben</td></tr>" if stufen.get("vorgabe") else "")
             + (f"<tr><td>unsicher ?</td><td>{fmt(stufen.get('unsicher', 0))}</td><td class='klein'>Kennung und Rechnung widersprechen sich</td></tr>" if stufen.get("unsicher") else "")
             + "</table></div>")

    t.append('<div class="schritt"><h2>5. Offen lassen statt raten</h2>'
             "<p>Wo es keine Eindeutigkeit gibt, rät das Programm nicht. Passen zwei Personen oder zwei Ehen gleich gut, oder spricht eine Regel "
             "gegen einen sonst passenden Kandidaten, wird eine eigene Person angelegt und der Fall mit allen Kandidaten und dem Grund festgehalten. "
             f"Das sind in diesem Bestand <b>{fmt(offen)}</b> Fälle; sie stehen unter <a href='prueffaelle.html'>Prüffälle</a>. "
             "Eine falsche Verbindung ist schwerer zu finden als eine fehlende; darum bleibt lieber eine Person doppelt, als dass zwei Menschen "
             "zu einem werden.</p></div>")

    t.append('<div class="schritt"><h2>6. Durchsicht</h2>'
             f"<p>Bisher {fmt(entsch)} Entscheidungen von Hand. Prüffälle lassen sich als Tabelle durchgehen: je Fall die Kandidaten mit ihren "
             "Belegen, das Urteil in eine Spalte. Ein Urteil hängt an der Tabellenzeile und gilt bei jedem neuen Lauf; es geht der Rechnung vor.</p></div>")

    kontrolle = ""
    if ged and Path(ged).exists():
        n, fehler = pruefe.pruefen(con, ged)
        kontrolle = (f"<p>Die GEDCOM-Datei wurde gegen die Einträge abgeglichen: von {fmt(sum(n.values()))} Einträgen sind "
                     f"{fmt(sum(n.values()) - len(fehler))} über ihre Fundstelle wiederzufinden"
                     + (f"; {len(fehler)} nicht (meist gestrichene Zeilen ohne Person)." if fehler else ".") + "</p>")
    t.append('<div class="schritt"><h2>7. Kontrolle und Ausgabe</h2>' + kontrolle +
             "<p>Jede Angabe im Buch nennt ihre Fundstelle. Unter jeder Person lassen sich die Registerzeilen aufklappen, aus denen sie "
             "zusammengesetzt wurde. Die GEDCOM-Datei (Version 5.5.1) enthält dieselben Angaben mit Quellen und lässt sich in Gramps, "
             "Ahnenblatt, webtrees oder ein Online-OFB einlesen.</p></div>")

    t.append('<div class="schritt"><h2>Grenzen</h2><ul>'
             "<li>Gleichnamige Personen ohne weiteren Anker (gleicher Name, gleiche Zeit, Mutter ohne Familiennamen) bleiben offen.</li>"
             "<li>Paten und Zeugen sind als Text übernommen, nicht als Personen verknüpft.</li>"
             "<li>Wer nur einmal genannt ist, bleibt eine einzelne Nennung; das sagt nichts über Fehler, sondern über Zu- und Wegzug.</li>"
             "<li>Altersangaben und Schreibweisen der Vorlage werden nicht korrigiert. Fehler der Abschrift setzen sich fort.</li>"
             "<li>Solange die Durchsicht nicht abgeschlossen ist, ist dies eine Arbeitsfassung.</li></ul></div>")
    return "".join(t)
