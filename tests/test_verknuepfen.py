"""Verknuepfung an den Kirchenbuchstil- Beispielzeilen: die von Hand erkannten Familien."""
import unittest
from pathlib import Path

from famrecon import db, kern, lesen, verknuepfen

B = Path(__file__).resolve().parent.parent / "beispiel"


class Kirchenbuchstil(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = db.oeffnen(":memory:")
        lesen.einlesen(cls.con, lesen.zuordnung_laden(B / "kirchenbuchstil.toml"), [B / "kirchenbuchstil.xlsx"])
        kern.personen_bauen(cls.con)
        verknuepfen.verknuepfen(cls.con)

    def familie(self, mann_name, mann_vorname):
        f = self.con.execute("SELECT f.* FROM familie f JOIN identitaet m ON m.id=f.mann WHERE m.name=? AND m.vorname=?",
                             (mann_name, mann_vorname)).fetchall()
        self.assertEqual(len(f), 1, (mann_name, mann_vorname, len(f)))
        return f[0]

    def kinder(self, f):
        return [tuple(r) for r in self.con.execute(
            "SELECT i.name, i.vorname, i.geb_jahr, i.tod_jahr FROM kind k JOIN identitaet i ON i.id=k.ident WHERE k.familie=? ORDER BY i.geb_jahr", (f["id"],))]

    def test_aberle_drei_taufen_und_kindstod(self):
        f = self.familie("Eberle", "Conrad Israel")
        frau = self.con.execute("SELECT name, vorname, unbekannt FROM identitaet WHERE id=?", (f["frau"],)).fetchone()
        self.assertEqual(tuple(frau), ("Leybold", "Maria Clara Jacobina", 0))      # NN-Frau spaeter benannt
        k = self.kinder(f)
        self.assertEqual([x[2] for x in k], [1734, 1735, 1736])
        self.assertEqual(k[2][3], 1737)                                              # Sophia Eleonora Eva † 24 Wochen

    def test_aal_ahl_eine_familie(self):
        f = self.familie("Haag", "Nicolaus")
        k = self.kinder(f)
        self.assertEqual(len(k), 3)
        self.assertIn(("Haag", "Christoph Georg", 1778, 1845), k)                    # Sterbedatum aus Rueckverweis
        self.assertIn(("Haag", "Johann Georg", 1781, 1784), k)                       # Kindstod ueber die Eltern
        self.assertIn(("Hag", "Friederich Ludwig", None, None), k)                   # Braeutigam 1804 ueber die Eltern
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM identitaet WHERE name_schl=?",
                                          (self.con.execute("SELECT name_schl FROM identitaet WHERE id=?", (f["mann"],)).fetchone()[0],)).fetchone()[0], 4)

    def test_ahlinger_sohn_heiratet(self):
        f = self.familie("Ohringer", "Johannes")
        self.assertEqual(f["tr_jahr"], 1768)
        frau = self.con.execute("SELECT name, geburtsname, ehename FROM identitaet WHERE id=?", (f["frau"],)).fetchone()
        self.assertEqual(tuple(frau), ("Bindermann", "Bindermann", "Schleißer"))
        self.assertEqual([x[:2] for x in self.kinder(f)], [("Ohringer", "Johann Jacob Valentin")])

    def test_totgeburt_taufe_und_tod_eine_person(self):
        f = self.familie("Ebel", "Jacob")
        k = self.kinder(f)
        self.assertEqual(k, [("Ebel", None, 1815, 1815)])

    def test_aberlin_martin_witwe(self):
        f = self.familie("Eberlin", "Martin") if self.con.execute("SELECT 1 FROM identitaet WHERE name='Eberlin' AND vorname='Martin'").fetchone() else self.familie("Eberle", "Martin")
        mann = self.con.execute("SELECT geb_jahr, tod_jahr FROM identitaet WHERE id=?", (f["mann"],)).fetchone()
        self.assertEqual(tuple(mann), (1671, 1748))                                  # Sterbeeintrag 1748, 77 J
        frau = self.con.execute("SELECT vorname, tod_jahr FROM identitaet WHERE id=?", (f["frau"],)).fetchone()
        self.assertEqual(tuple(frau), ("Maria Juliana", 1763))

    def test_keine_offenen_faelle(self):
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM zuordnung WHERE stufe='unsicher'").fetchone()[0], 0)

    def test_zaehler(self):
        st = verknuepfen.statistik(self.con)
        self.assertEqual((st["personen"], st["identitaeten"]), (92, 76))


if __name__ == "__main__":
    unittest.main()
