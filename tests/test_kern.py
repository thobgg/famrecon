"""Personen in Normalform aus beiden Beispielformaten."""
import unittest
from pathlib import Path

from famrecon import db, kern, lesen

B = Path(__file__).resolve().parent.parent / "beispiel"


def bauen(toml, *dateien):
    con = db.oeffnen(":memory:")
    lesen.einlesen(con, lesen.zuordnung_laden(B / toml), [B / d for d in dateien])
    kern.personen_bauen(con)
    return con


class Kirchenbuchstil(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = bauen("kirchenbuchstil.toml", "kirchenbuchstil.xlsx")

    def person(self, register, jahr, pfad, **wo):
        sql = "SELECT p.* FROM person p JOIN eintrag e ON e.id=p.eintrag WHERE e.register=? AND e.jahr=? AND p.pfad=?"
        rows = [r for r in self.con.execute(sql, (register, jahr, pfad)) if all(r[k] == v for k, v in wo.items())]
        self.assertEqual(len(rows), 1, (register, jahr, pfad, wo, len(rows)))
        return rows[0]

    def test_zaehler(self):
        n = dict(self.con.execute("SELECT e.register, COUNT(*) FROM person p JOIN eintrag e ON e.id=p.eintrag GROUP BY 1"))
        self.assertEqual(n, {"taufe": 21, "ehe": 43, "tod": 28})

    def test_taufe_aal(self):
        v = self.person("taufe", 1778, "vater")
        self.assertEqual((v["name"], v["vorname"], v["geschlecht"], v["beruf"]), ("Haag", "Nicolaus", "M", "Kutscher bei Obervogt von Schmidtberg"))
        k = self.person("taufe", 1778, "kind")
        self.assertEqual((k["geburt_jahr"], k["geburt_monat"], k["geburt_tag"], k["geschlecht"]), (1778, 8, 31, "M"))

    def test_mutter_unbekannt(self):
        m = self.person("taufe", 1750, "mutter")
        self.assertEqual((m["name"], m["vorname"], m["unbekannt"]), (None, "Eberhardina Sophia", 1))

    def test_totgeburt(self):
        k = self.person("taufe", 1815, "kind")
        self.assertEqual((k["vorname"], k["totgeburt"], k["geschlecht"]), (None, 1, "F"))
        self.assertEqual(self.person("taufe", 1815, "mutter")["unsicher"], 1)

    def test_ehe_marker(self):
        b = self.person("ehe", 1734, "braeutigam")
        self.assertEqual((b["name"], b["stand"], b["beruf"]), ("Adam", "verwitwet", "fürstl. Bauknecht"))
        self.assertEqual(self.person("ehe", 1733, "braut")["name"], "Lötz")
        b = self.person("ehe", 1768, "braut")
        self.assertEqual((b["name"], b["geburtsname"], b["stand"]), ("Schleißer", "Bindermann", "verwitwet"))
        v = self.person("ehe", 1804, "braeutigam_vater")
        self.assertEqual((v["name"], v["vorname"], v["verstorben"]), ("Hag", "Nikolaus", 1))

    def test_adel(self):
        self.assertEqual(self.person("ehe", 1770, "braeutigam")["name"], "von Rosenfeld")
        m = self.person("ehe", 1770, "braut_mutter")
        self.assertEqual((m["name"], m["vorname"]), ("von Rebenfels", "Maria Magdalena"))

    def test_tod_alter(self):
        v = self.person("tod", 1798, "verstorbener")
        self.assertEqual((v["name"], v["geburtsname"], v["alter_tage"], v["geburt_jahr"], v["geburt_praefix"]), ("Lutz", "Kugel", 21839, 1739, "CAL"))
        v = self.person("tod", 1731, "verstorbener")
        self.assertEqual((v["geburt_jahr"], v["geburt_monat"], v["geburt_tag"]), (1731, 1, 29))   # 10 Tage vor dem 8.2.
        self.assertEqual(self.person("tod", 1798, "verstorbener_ehepartner")["beruf"], "fürstl. Hof-Bedienter")

    def test_schluessel(self):
        a = self.person("taufe", 1778, "vater")["name_schl"]
        b = self.person("ehe", 1804, "braeutigam_vater")["name_schl"]
        self.assertEqual(a, b)                                    # Haag = Hag
        self.assertEqual(self.person("taufe", 1778, "mutter")["name_schl"],
                         self.person("ehe", 1804, "braeutigam_mutter")["name_schl"])   # Kriehmann


class Hollerbach(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = bauen("technisch.toml", "technisch-taufen.xlsx", "technisch-trauungen.xlsx", "technisch-begraebnisse.xlsx")

    def test_kb_form_und_unterrolle(self):
        r = self.con.execute("SELECT name, name_kb, vorname, geschlecht FROM person WHERE pfad='braut_vorehe'").fetchone()
        self.assertEqual(tuple(r), ("Fänner", "Faenner", "Wilhelm Ludwig", "M"))

    def test_nn_als_leerwort(self):
        r = self.con.execute("SELECT name, unbekannt FROM person p JOIN eintrag e ON e.id=p.eintrag WHERE e.register='ehe' AND e.jahr=1738 AND pfad='braut'").fetchone()
        self.assertEqual(tuple(r), (None, 1))

    def test_anonymus(self):
        r = self.con.execute("SELECT vorname, totgeburt FROM person WHERE name='Rehm' AND pfad='verstorbener'").fetchone()
        self.assertEqual(tuple(r), (None, 0))

    def test_stand_verstorben(self):
        r = self.con.execute("SELECT verstorben, stand FROM person WHERE pfad='braeutigam_vater' AND name='Jung'").fetchone()
        self.assertEqual(tuple(r), (1, "verstorben"))


if __name__ == "__main__":
    unittest.main()
