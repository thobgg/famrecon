"""Spaltenzuordnung vorschlagen: Ueberschriften und Beispielwerte -> TOML.

    famrecon zuordnung datei.xlsx              Vorschlag auf stdout
    famrecon zuordnung datei.xlsx -o zuordnung.toml

Jede Spalte bekommt ein Feld aus dem Katalog, dazu einen Sicherheitsgrad
(sicher, wahrscheinlich, unsicher) und die Beispielwerte als Kommentar.
Was nicht erkannt wird, steht auskommentiert mit "???" da. Der Mensch
sieht die Datei durch, aendert, und `famrecon bau` liest sie.

Erkannt werden: Rollenwoerter (Braeutigam, Braut, Vater, Mutter, Kind …),
Merkmale (Name, Vorname, Beruf, Herkunft, Alter …), die Synonyme des
Katalogs, Zahlenreihen wie "Taufpate 1 … 40" (werden ein Bereich) und bei
rollenlosen Ueberschriften wie "Alter" die zuletzt genannte Rolle.
"""
import re
from collections import Counter
from pathlib import Path

from openpyxl.utils import get_column_letter

from . import katalog, lesen

SICHER, WAHRSCHEINLICH, UNSICHER = "sicher", "wahrscheinlich", "unsicher"
DATUM = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$|^\d{1,2}\.\d{1,2}\.\d{4}$")

REGISTER_WORTE = {
    "taufe": ["tauf", "pate", "baptism", "christ", "täufling", "kind", "geburt", "geb"],
    "ehe":   ["braut", "brätigam", "bräutigam", "braeu", "trau", "heirat", "ehe", "marriage", "groom", "bride", "hochzeit"],
    "tod":   ["sterbe", "beerd", "begr", "verst", "tod", "tote", "grab", "burial", "death", "krankheit", "famstand", "alter"],
}


def normal(text):
    """Ueberschrift vergleichbar machen: klein, ohne Satzzeichen, ss statt ß, 'v. Mann' -> 'vormann'."""
    t = str(text or "").lower().replace("ß", "ss").replace("_", " ")
    t = re.sub(r"[^\wäöü]+", " ", t)
    t = re.sub(r"\bv (mann|ehemann)\b", "vormann", t)
    t = re.sub(r"\bv (frau|ehefrau)\b", "vorfrau", t)
    return re.sub(r"\s+", " ", t).strip()


def ist_snake(text):
    """Technische Ueberschriften wie vn_vater_braeu nennen das Merkmal zuerst, die Rolle zuletzt."""
    return "_" in str(text or "") and " " not in str(text or "").strip()


def register_erkennen(blattname, kopf, datei=""):
    """Welches Register ist das Blatt? Punkte fuer Registerwoerter in Blattname, Dateiname und Ueberschriften; None, wenn nichts passt."""
    tokens = normal(blattname).split() + normal(str(datei)).split()
    tokens += [t for _, k in kopf for t in normal(k).split()]
    punkte = {}
    for r, worte in REGISTER_WORTE.items():
        punkte[r] = sum(1 for t in tokens for w in worte if t == w or (len(w) >= 4 and t.startswith(w)))
        if normal(blattname)[:4] in [w[:4] for w in worte if len(w) >= 4]:
            punkte[r] += 3
    best = max(punkte, key=punkte.get)
    return best if punkte[best] else None


def _rollen_in(tokens):
    """Rollenwoerter in den Tokens, in Reihenfolge; Rest ohne sie. -> ([rolle, ...], rest)"""
    rollen, rest = [], []
    for t in tokens:
        treffer = next((r for r, woerter in katalog.ROLLENWORTE.items()
                        if t in woerter or any(len(w) >= 5 and t.startswith(w) for w in woerter)), None)
        if treffer:
            rollen.append(treffer)
        else:
            rest.append(t)
    return rollen, rest


def rollenpfad(ueberschrift, register, kontextrolle):
    """-> (pfad wie 'braut_vater' oder None, resttokens, nachsilbe, hauptrolle)"""
    tokens = [t for t in normal(ueberschrift).split() if not t.isdigit()]
    suffix = None
    for sfx in katalog.SUFFIXE:
        if sfx in tokens and len(tokens) > 1:
            suffix = sfx
            tokens = [t for t in tokens if t != sfx]
    rollen, rest = _rollen_in(tokens)
    haupt = [r for r in rollen if r in katalog.HAUPTROLLEN[register]]
    unter = [r for r in rollen if r not in haupt]
    if len(haupt) >= 2:                       # Taufe: vater_mutter = Vater der Mutter
        top, sub = (haupt[-1], haupt[0]) if ist_snake(ueberschrift) else (haupt[0], haupt[1])
    elif haupt:
        top, sub = haupt[0], (unter[0] if unter else None)
    elif unter:
        top, sub = (katalog.STANDARDROLLE[register] or kontextrolle), unter[0]
        if not top:
            return None, rest, suffix, None, tokens
    else:
        return None, rest, suffix, None, tokens
    if sub and sub not in katalog.UNTERROLLEN.get(top, []):
        sub = None
    return (f"{top}_{sub}" if sub else top), rest, suffix, top, tokens


def _syn_punkte(rest, syn):
    """Wie gut passt ein Synonym auf die Resttokens der Ueberschrift?"""
    s = normal(syn).split()
    if not s:
        return 0
    if s == rest:
        return 3
    if all(t in rest for t in s):
        return 2 + 0.1 * len(s)
    if len(s) == 1 and len(s[0]) >= 4 and any(t.startswith(s[0]) or s[0].startswith(t) for t in rest if len(t) >= 4):
        return 1.5
    return 0


def feld_raten(ueberschrift, register, kontextrolle, felder):
    """-> (feldname, punkte, hauptrolle) oder (None, 0, hauptrolle)."""
    pfad, rest, suffix, top, alle = rollenpfad(ueberschrift, register, kontextrolle)
    standard = katalog.STANDARDROLLE[register]
    kandidaten = []
    for name, (rang, art, hilfe, syn) in felder.items():
        feldpfad = None
        for r in katalog.HAUPTROLLEN[register]:
            if name == r or name.startswith(r + "_"):
                feldpfad = r
                for u in katalog.UNTERROLLEN[r]:
                    if name == f"{r}_{u}" or name.startswith(f"{r}_{u}_"):
                        feldpfad = f"{r}_{u}"
                break
        if feldpfad and name == feldpfad:                    # kombiniertes Personenfeld
            if pfad == feldpfad and not rest:
                kandidaten.append((name, 4))
            elif pfad == feldpfad:
                kandidaten.append((name, 2))                 # Rolle, aber kein Merkmal erkannt
            continue
        best = max((_syn_punkte(rest, s) for s in syn), default=0)
        if not feldpfad:
            best = max(best, max((_syn_punkte(alle, s) for s in syn), default=0))
        if not best:
            continue
        if feldpfad:
            if pfad and pfad != feldpfad:
                continue
            if pfad == feldpfad:
                best += 1
            elif feldpfad == (standard or kontextrolle):
                best += 0.3
            else:
                best -= 1
        elif pfad and pfad != standard:
            best -= 1.5                                       # Rollenwort, aber rollenloses Feld
        elif best >= 3 and not pfad:
            best += 0.5                                       # rollenlose Ueberschrift, rollenloses Feld, exakt
        kandidaten.append((name, best))
    if not kandidaten:
        return None, 0, top
    kandidaten.sort(key=lambda k: -k[1])
    name, punkte = kandidaten[0]
    if suffix:
        name = f"{name}_{suffix}"
    return name, punkte, top


def beispiele(spalte, n=3):
    """Bis zu n verschiedene Beispielwerte einer Spalte (gekuerzt) und die Zahl der gefuellten Zellen."""
    werte = [str(v).replace("\n", " ") for v in spalte if v not in (None, "")]
    seen, out = set(), []
    for w in werte:
        if w not in seen:
            seen.add(w); out.append(w[:40])
        if len(out) == n:
            break
    return out, len(werte)


def stufe(punkte, art, werte):
    """Sicherheitsgrad eines Vorschlags: unsicher bei Datums-/Zahlfeld mit unpassenden Werten, sonst nach Punkten der Ueberschrift."""
    if art == "datum" and werte and not all(DATUM.match(w) for w in werte):
        return UNSICHER
    if art == "zahl" and werte and not all(re.match(r"^\d+$", w) for w in werte):
        return UNSICHER
    return SICHER if punkte >= 3 else WAHRSCHEINLICH if punkte >= 2 else UNSICHER


def leerwoerter(zeilen):
    """Kurze Platzhalter wie 'k.A.', '—', '?' in den Zellen: Vorschlag fuer `leer`."""
    z = Counter(str(c).strip() for r in zeilen for c in r
                if isinstance(c, str) and 0 < len(c.strip()) <= 5 and not c.strip().isdigit())
    out = set()
    for w, n in z.items():
        if not re.search(r"\w", w) and set(w) <= set("-—–?.[]()…/ "):   # Platzhalter, kein †
            out.add(w)
        elif re.fullmatch(r"k\.?\s?a\.?", w, re.I) or re.fullmatch(r"n\.?n?\.?", w, re.I) and n >= 2:
            out.add(w)
    return sorted(out)


def blatt_zuordnen(blattname, kopf, zeilen, register):
    """-> Liste von Zeilen (schluessel, feld, stufe, ueberschrift, beispiele) in Spaltenreihenfolge."""
    felder = katalog.felder(register)
    spalten = {}
    kontextrolle = None
    for i, (buchstabe, titel) in enumerate(kopf):
        idx = int(__import__("openpyxl").utils.column_index_from_string(buchstabe))
        werte, n = beispiele([r[idx - 1] if idx - 1 < len(r) else None for r in zeilen])
        feld, punkte, rolle = feld_raten(titel, register, kontextrolle, felder)
        if rolle:
            kontextrolle = rolle
        basis, sfx = katalog.basisname(feld) if feld else (None, None)
        art = ("text" if sfx == "praefix" else felder[basis][1]) if feld else None
        reihe = re.search(r"(\d+)\s*$", titel.strip())
        basis = normal(re.sub(r"\d+\s*$", "", titel))
        spalten[buchstabe] = dict(feld=feld, stufe=stufe(punkte, art, werte) if feld else None,
                                  titel=titel, werte=werte, n=n, reihe=int(reihe.group(1)) if reihe else None,
                                  basis=basis, art=art)
    # Zahlenreihen zu Bereichen zusammenfassen
    out, offen = [], list(spalten.items())
    while offen:
        b, s = offen.pop(0)
        if s["reihe"] is not None and s["feld"]:
            ende = b
            while offen and offen[0][1]["basis"] == s["basis"] and offen[0][1]["reihe"] is not None:
                ende, _ = offen.pop(0)
            if ende != b:
                b = f"{b}-{ende}"
                s = dict(s, titel=f"{s['titel'].strip()} … {ende}")
        out.append((b, s))
    # zwei Spalten "lfd. Nr.": die mit den groesseren Zahlen ist die Gesamtnummer
    lfd = [(b, s) for b, s in out if s["feld"] == "lfd_nr"]
    if len(lfd) > 1:
        def maxwert(s):
            """Groesste Zahl in den Beispielwerten (fuer die Unterscheidung lfd_nr / lfd_nr_gesamt)."""
            try: return max(int(w) for w in s["werte"])
            except ValueError: return 0
        b, s = max(lfd, key=lambda bs: maxwert(bs[1]))
        s["feld"] = "lfd_nr_gesamt"
    return out


def toml_text(datei, blaetter, mit_datei=False):
    """blaetter: [(blattname, register, zuordnung, leerwoerter[, datei])] -> TOML-Text."""
    z = [f"# Spaltenzuordnung, vorgeschlagen von famrecon fuer {datei}",
         "# Bitte durchsehen: 'unsicher' pruefen, '???' ersetzen oder loeschen.",
         "", "[allgemein]"]
    leer = sorted({w for _, _, _, lw, *_ in blaetter for w in lw})
    z.append("leer = [" + ", ".join(f'"{w}"' for w in leer) + "]")
    for blatt, register, zuordnung, _, *rest in blaetter:
        z += ["", f"[register.{register}]", f'blatt = "{blatt}"']
        if mit_datei and rest:
            z.append(f'datei = "{rest[0]}"')
        z += [
              "leitdatum = [" + ", ".join(f'"{f}"' for f in katalog.LEITDATUM[register]) + "]",
              "", f"[register.{register}.spalten]"]
        for b, s in zuordnung:
            key = b if "-" not in b else f'"{b}"'
            bsp = " | ".join(s["werte"]) if s["werte"] else "(leer)"
            if s["feld"]:
                z.append(f'{key} = "{s["feld"]}"'.ljust(38) + f'# {s["stufe"]:14} {s["titel"].strip()!r}: {bsp}')
            elif s["n"]:
                z.append(f'# {key} = "???"'.ljust(38) + f'# unbekannt       {s["titel"].strip()!r}: {bsp}')
            else:
                z.append(f'# {key} = "???"'.ljust(38) + f'# leer            {s["titel"].strip()!r}')
    return "\n".join(z) + "\n"


def vorschlagen(datei):
    """Fuer jedes Blatt einer Datei: Register, Spaltenvorschlaege, Leerwoerter. -> [(blatt, register, zuordnung, leerwoerter, datei), ...]"""
    blaetter = []
    for blatt, _, kopf in lesen.blaetter(datei):
        zeilen = [r for _, r in lesen.zeilen_lesen(datei, blatt)][:200]
        register = register_erkennen(blatt, kopf, Path(datei).stem)
        if not register:
            continue
        blaetter.append((blatt, register, blatt_zuordnen(blatt, kopf, zeilen, register), leerwoerter(zeilen), Path(datei).name))
    return blaetter
