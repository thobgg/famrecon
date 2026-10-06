"""Experten-Schalter: Kennungen (Feld ref) als Vorgabe. An den Falkenrath-Registern, die ihre Kennungen tragen."""
import unittest
from pathlib import Path

from famrecon import db, kern, lesen, messen, verknuepfen, zuordnung

B = Path(__file__).resolve().parent.parent / "beispiel"
DATEIEN = [B / "falkenrath-taufen.csv", B / "falkenrath-ehen.csv", B / "falkenrath-tote.csv"]


def projekt(kennungen):
    blaetter = [b for d in DATEIEN for b in zuordnung.vorschlagen(d)]
    toml = zuordnung.toml_text(", ".join(d.name for d in DATEIEN), blaetter, mit_datei=True)
    toml = toml.replace("[allgemein]", "[allgemein]\nkennungen = " + ("true" if kennungen else "false"), 1)
    con = db.oeffnen(":memory:")
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as f:
        f.write(toml)
    lesen.einlesen(con, lesen.zuordnung_laden(f.name), DATEIEN)
    kern.personen_bauen(con)
    return con


class Kennungen(unittest.TestCase):
    def test_vorgabe_trifft_die_wahrheit(self):
        con = projekt(True)
        self.assertEqual(con.execute("SELECT wert FROM einstellung WHERE name='kennungen'").fetchone()[0], "1")
        verknuepfen.verknuepfen(con)                       # liest die Einstellung
        m = messen.messen(con)
        self.assertEqual(m["praezision"], 1.0, m["gemischt"][:3])
        self.assertEqual(m["vollstaendigkeit"], 1.0, m["zersplittert"][:3])
        self.assertEqual(m["identitaeten"], m["refs"])    # genau eine Person je Kennung
        stufen = dict(con.execute("SELECT stufe, COUNT(*) FROM zuordnung GROUP BY stufe"))
        self.assertIn("vorgabe", stufen)
        # unsicher bleibt nur, wo die Nennung keine Kennung traegt (Mutter im Sterbeeintrag hat keine Ref-Spalte)
        mit_ref = con.execute("SELECT COUNT(*) FROM zuordnung z JOIN person p ON p.id=z.person WHERE z.stufe='unsicher' AND p.ref IS NOT NULL").fetchone()[0]
        self.assertEqual(mit_ref, 0)

    def test_ohne_schalter_wie_bisher(self):
        con = projekt(False)
        verknuepfen.verknuepfen(con)
        stufen = dict(con.execute("SELECT stufe, COUNT(*) FROM zuordnung GROUP BY stufe"))
        self.assertNotIn("vorgabe", stufen)
        self.assertGreater(con.execute("SELECT COUNT(*) FROM identitaet").fetchone()[0], 492)   # 499: Zwillingsnamen

    def test_widerspruch_landet_in_der_pruefliste(self):
        con = projekt(True)
        # Ein Sterbeeintrag bekommt die Kennung einer fremden Person mit anderem Namen (Tippfehler in der Nummer):
        # die Kennung zwingt, die Rechnung findet die richtige Person ueber den Namen und widerspricht.
        tot = con.execute("SELECT p.id, p.ref, p.name FROM person p JOIN eintrag e ON e.id=p.eintrag WHERE e.register='tod' AND p.pfad='verstorbener' AND p.ref IS NOT NULL ORDER BY e.jahr DESC LIMIT 1").fetchone()
        fremd = con.execute("SELECT ref FROM person WHERE ref IS NOT NULL AND pfad='kind' AND name<>? LIMIT 1", (tot["name"],)).fetchone()[0]
        con.execute("UPDATE person SET ref=? WHERE id=?", (fremd, tot["id"]))
        con.commit()
        verknuepfen.verknuepfen(con)
        faelle = con.execute("SELECT grund FROM zuordnung WHERE person=? AND stufe='unsicher'", (tot["id"],)).fetchall()
        self.assertTrue(faelle, "ein Widerspruch zwischen Kennung und Rechnung muss in die Pruefliste")
        self.assertIn("Rechnung spricht für", faelle[0]["grund"])
        # zweite Taufe auf dieselbe Kennung: ebenfalls Pruefliste
        con = projekt(True)
        kinder = con.execute("SELECT p.id, p.ref FROM person p JOIN eintrag e ON e.id=p.eintrag WHERE e.register='taufe' AND p.pfad='kind' ORDER BY e.jahr LIMIT 2").fetchall()
        con.execute("UPDATE person SET ref=? WHERE id=?", (kinder[0]["ref"], kinder[1]["id"]))
        con.commit()
        verknuepfen.verknuepfen(con)
        grund = con.execute("SELECT stufe, grund FROM zuordnung WHERE person=?", (kinder[1]["id"],)).fetchone()
        self.assertEqual(grund["stufe"], "unsicher")
        self.assertIn("schon getauft", grund["grund"])


if __name__ == "__main__":
    unittest.main()
