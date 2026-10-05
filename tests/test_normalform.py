"""Zerleger der Normalform an Werten aus Kirchenbuchstil und Hollerbach."""
import unittest

from famrecon import normalform as nf


class Personenzeile(unittest.TestCase):
    def z(self, text):
        return nf.person_zerlegen(text)

    def test_kirchenbuchstil(self):
        p = self.z("Haag, Nicolaus, weyl., gewesener adelicher Kutscher")
        self.assertEqual((p["name"], p["vorname"], p["beruf"], p["verstorben"]),
                         ("Haag", "Nicolaus", "gewesener adelicher Kutscher", True))

    def test_marker(self):
        self.assertEqual(self.z("Lötz(in)")["geschlecht"], "F")
        self.assertEqual(self.z("Adam (W)")["stand"], "verwitwet")
        p = self.z("Schleißer(in) geb. Bindermann (W)")
        self.assertEqual((p["name"], p["geburtsname"], p["stand"]), ("Schleißer", "Bindermann", "verwitwet"))
        p = self.z("Nüb (??) = HÜB")
        self.assertEqual((p["name"], p["alternative"]), ("Nüb", "HÜB"))
        self.assertEqual(self.z("Lutz geb. Kugel(in)")["geburtsname"], "Kugel")
        self.assertEqual(self.z("Eberlin (Witwe)")["stand"], "verwitwet")
        p = self.z("N., Eberhardina Sophia")
        self.assertEqual((p["name"], p["vorname"], p["unbekannt"]), (None, "Eberhardina Sophia", True))
        self.assertTrue(self.z("Hauber ?, Barbara")["unsicher"])
        self.assertTrue(self.z("Kriemann (?), Elisabeth Dorothea")["unsicher"])
        self.assertTrue(self.z("Hag, Nikolaus, weil., ")["verstorben"])

    def test_adel(self):
        self.assertEqual(self.z("Rosenfeld von")["name"], "von Rosenfeld")
        p = self.z("Rebenfels, Maria Magdalena von")
        self.assertEqual((p["name"], p["vorname"]), ("von Rebenfels", "Maria Magdalena"))
        p = self.z("Temmingen zu Buttenberg, Reinhard von, hochfürstl. Geheimer Rat")
        self.assertEqual((p["name"], p["vorname"]), ("von Temmingen zu Buttenberg", "Reinhard"))

    def test_totgeburt(self):
        p = self.z("Mädchen - totgeboren")
        self.assertEqual((p["name"], p["vorname"], p["totgeburt"], p["geschlecht"]), (None, None, True, "F"))
        p = self.z("Rehm, Anonymus")
        self.assertEqual((p["name"], p["vorname"], p["totgeburt"]), ("Rehm", None, False))


class Alter(unittest.TestCase):
    def test_formen(self):
        for text, tage in [("59 J 10 M 4 T", 21839), ("3 J., 7 M., 14 T", 1319), ("26 Jahre 6 Mo., 8 Tage", 9678),
                           ("24 Wochen", 168), ("2 J 12 Wo", 814), ("10 T", 10), ("77 J", 28105), ("0", 0),
                           ("1 Monat", 30), ("27 Tage", 27), ("40 Jahre", 14600), (None, None), ("", None)]:
            with self.subTest(text=text):
                self.assertEqual(nf.alter_tage(text), tage)


class Datum(unittest.TestCase):
    def test_formen(self):
        self.assertEqual(nf.datum_zerlegen("1778-08-31"), (1778, 8, 31))
        self.assertEqual(nf.datum_zerlegen("1699-08-00"), (1699, 8, None))
        self.assertEqual(nf.datum_zerlegen("12.03.1778"), (1778, 3, 12))
        self.assertEqual(nf.datum_zerlegen("um 1750"), (1750, None, None))
        self.assertEqual(nf.datum_praefix("um 1750"), "ABT")
        self.assertIsNone(nf.datum_zerlegen("k.A."))

    def test_rechnen(self):
        d = nf.datum_minus_tage((1798, 11, 24), nf.alter_tage("59 J 10 M 4 T"))
        self.assertEqual(d.year, 1739)


class Schluessel(unittest.TestCase):
    def test_koelner(self):
        self.assertEqual(nf.koelner("Haag"), nf.koelner("Hag"))
        self.assertEqual(nf.koelner("Kriehmann"), nf.koelner("Kriemann"))
        self.assertEqual(nf.koelner("Eberlein"), nf.koelner("Eberlin"))
        self.assertEqual(nf.koelner("Müller"), nf.koelner("Miller"))
        self.assertNotEqual(nf.koelner("Nüb"), nf.koelner("Rüb"))

    def test_vornamen(self):
        self.assertEqual(nf.vorname_kanon("Nicolaus"), nf.vorname_kanon("Nikolaus"))
        self.assertEqual(nf.vorname_kanon("Catharina Dorothea"), nf.vorname_kanon("Katharina Dorothee"))
        self.assertEqual(nf.vorname_kanon("Hanß Georg"), nf.vorname_kanon("Johann Georg"))
        self.assertEqual(nf.vorname_kanon("Friderica"), nf.vorname_kanon("Friedrika"))
        self.assertEqual(nf.vorname_kanon("Jacob"), nf.vorname_kanon("Jakob"))
        self.assertNotEqual(nf.vorname_kanon("Johann Georg"), nf.vorname_kanon("Johann Jacob"))

    def test_geschlecht(self):
        self.assertEqual(nf.geschlecht_aus_vorname("Luisa Elisabetha Kunigunda"), "F")
        self.assertEqual(nf.geschlecht_aus_vorname("Conrad Israel"), "M")
        self.assertIsNone(nf.geschlecht_aus_vorname("Xyz Abc"))


if __name__ == "__main__":
    unittest.main()
