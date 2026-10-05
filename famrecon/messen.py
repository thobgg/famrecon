"""Messen: wie gut hat das Verknuepfen die Wahrheit getroffen?

    famrecon messen daten/projekt.db

Voraussetzung: Personen tragen eine Ref (Kennung aus der Quelle), etwa aus
`famrecon simuliere`. Gemessen wird paarweise ueber Personenzeilen mit Ref:

    sollten zusammen    zwei Zeilen mit derselben Ref
    sind zusammen       zwei Zeilen in derselben Identitaet
    Treffer             beides; Verpasst: sollten, sind nicht; Falsch: sind, sollten nicht

    Praezision = Treffer / sind zusammen        (wie oft ist ein Zusammenlegen richtig)
    Vollstaendigkeit = Treffer / sollten        (wie viel vom Moeglichen wurde gefunden)

Dazu je Identitaet: rein (eine Ref), gemischt (mehrere Refs = falsch
zusammengelegt), und je Ref: zersplittert (mehrere Identitaeten = verpasst).
"""
from collections import defaultdict
from itertools import combinations


def messen(con):
    zeilen = con.execute("SELECT p.id, p.ref, z.ident, p.pfad, e.register FROM person p "
                         "JOIN zuordnung z ON z.person=p.id JOIN eintrag e ON e.id=p.eintrag WHERE p.ref IS NOT NULL").fetchall()
    nach_ref, nach_ident = defaultdict(list), defaultdict(list)
    for r in zeilen:
        nach_ref[r["ref"]].append(r["id"])
        nach_ident[r["ident"]].append(r["id"])
    ident_von = {r["id"]: r["ident"] for r in zeilen}
    ref_von = {r["id"]: r["ref"] for r in zeilen}
    sollten = sum(len(v) * (len(v) - 1) // 2 for v in nach_ref.values())
    sind = sum(len(v) * (len(v) - 1) // 2 for v in nach_ident.values())
    treffer = sum(1 for v in nach_ref.values() for a, b in combinations(v, 2) if ident_von[a] == ident_von[b])
    gemischt = [(i, sorted({ref_von[p] for p in ps})) for i, ps in nach_ident.items() if len({ref_von[p] for p in ps}) > 1]
    zersplittert = [(r, sorted({ident_von[p] for p in ps})) for r, ps in nach_ref.items() if len({ident_von[p] for p in ps}) > 1]
    return dict(zeilen=len(zeilen), refs=len(nach_ref), identitaeten=len(nach_ident),
                sollten=sollten, sind=sind, treffer=treffer, verpasst=sollten - treffer, falsch=sind - treffer,
                praezision=(treffer / sind) if sind else 1.0, vollstaendigkeit=(treffer / sollten) if sollten else 1.0,
                gemischt=gemischt, zersplittert=zersplittert)


def familien_messen(con):
    """Familien gegen die Wahrheit: Paare (Ref Mann, Ref Frau) und Kinder (Ref) je Paar.

    Wahrheit aus den Eintraegen: Taufzeilen nennen Vater-Ref, Mutter-Ref, Kind-Ref; Ehezeilen Braeutigam-Ref,
    Braut-Ref. famrecon: Familien mit den Refs ihrer Identitaeten. Verglichen werden die Mengen.
    """
    ref_von_ident = {}
    for r in con.execute("SELECT z.ident, p.ref FROM zuordnung z JOIN person p ON p.id=z.person WHERE p.ref IS NOT NULL"):
        ref_von_ident.setdefault(r["ident"], set()).add(r["ref"])

    def ref(i):
        refs = ref_von_ident.get(i, set())
        return min(refs) if refs else None

    soll_paare, soll_kinder = set(), set()
    for e in con.execute("SELECT id FROM eintrag"):
        f = {r["name"]: r["wert"] for r in con.execute("SELECT name, wert FROM feld WHERE eintrag=? AND name LIKE '%_ref'", (e["id"],))}
        if f.get("vater_ref") and f.get("mutter_ref"):
            soll_paare.add((f["vater_ref"], f["mutter_ref"]))
            if f.get("kind_ref"):
                soll_kinder.add((f["vater_ref"], f["mutter_ref"], f["kind_ref"]))
        if f.get("braeutigam_ref") and f.get("braut_ref"):
            soll_paare.add((f["braeutigam_ref"], f["braut_ref"]))
    ist_paare, ist_kinder = set(), set()
    for fam in con.execute("SELECT id, mann, frau FROM familie"):
        m, w = ref(fam["mann"]), ref(fam["frau"])
        if m and w:
            ist_paare.add((m, w))
            for k in con.execute("SELECT ident FROM kind WHERE familie=?", (fam["id"],)):
                kr = ref(k["ident"])
                if kr:
                    ist_kinder.add((m, w, kr))
    return dict(paare_soll=len(soll_paare), paare_ist=len(ist_paare), paare_treffer=len(soll_paare & ist_paare),
                paare_fehlen=sorted(soll_paare - ist_paare), paare_zuviel=sorted(ist_paare - soll_paare),
                kinder_soll=len(soll_kinder), kinder_ist=len(ist_kinder), kinder_treffer=len(soll_kinder & ist_kinder),
                kinder_fehlen=sorted(soll_kinder - ist_kinder), kinder_zuviel=sorted(ist_kinder - soll_kinder))


def bericht(con, zeigen=10):
    m = messen(con)
    print(f"Personenzeilen mit Ref {m['zeilen']}, davon {m['refs']} verschiedene Personen, {m['identitaeten']} Identitaeten gebildet")
    print(f"Paare: sollten zusammen {m['sollten']}, sind zusammen {m['sind']}, Treffer {m['treffer']}, verpasst {m['verpasst']}, falsch {m['falsch']}")
    print(f"Praezision {m['praezision']:.3f}   Vollstaendigkeit {m['vollstaendigkeit']:.3f}")
    print(f"Identitaeten mit mehreren Personen (falsch zusammengelegt): {len(m['gemischt'])}")
    for i, refs in m["gemischt"][:zeigen]:
        r = con.execute("SELECT name, vorname, geb_jahr FROM identitaet WHERE id=?", (i,)).fetchone()
        print(f"   [{i}] {r['name']}, {r['vorname']} *{r['geb_jahr'] or '?'}: {', '.join(refs)}")
    print(f"Personen auf mehrere Identitaeten verteilt (verpasst): {len(m['zersplittert'])}")
    for ref, idents in m["zersplittert"][:zeigen]:
        teile = []
        for i in idents:
            r = con.execute("SELECT name, vorname, geb_jahr, tod_jahr FROM identitaet WHERE id=?", (i,)).fetchone()
            pf = [x[0] for x in con.execute("SELECT e.register||'/'||p.pfad FROM person p JOIN zuordnung z ON z.person=p.id JOIN eintrag e ON e.id=p.eintrag WHERE z.ident=? AND p.ref=?", (i, ref))]
            teile.append(f"[{i}] {r['name']}, {r['vorname']} *{r['geb_jahr'] or '?'} †{r['tod_jahr'] or '?'} ({', '.join(pf)})")
        print(f"   {ref}: " + "  |  ".join(teile))
    fm = familien_messen(con)
    print(f"Paare (Mann & Frau): soll {fm['paare_soll']}, ist {fm['paare_ist']}, Treffer {fm['paare_treffer']}; fehlen {len(fm['paare_fehlen'])}, zu viel {len(fm['paare_zuviel'])}")
    print(f"Kinder in Familien: soll {fm['kinder_soll']}, ist {fm['kinder_ist']}, Treffer {fm['kinder_treffer']}; fehlen {len(fm['kinder_fehlen'])}, zu viel {len(fm['kinder_zuviel'])}")
    for titel, liste in (("fehlendes Paar", fm["paare_fehlen"]), ("Paar zu viel", fm["paare_zuviel"]), ("fehlendes Kind", fm["kinder_fehlen"])):
        for x in liste[:zeigen]:
            print(f"   {titel}: {' & '.join(x[:2])}" + (f" -> {x[2]}" if len(x) > 2 else ""))
    m.update(fm)
    return m
