"""Messlauf: Falkenrath-GEDCOM (erfunden, CC0) -> drei Register -> Verknuepfung -> Vergleich mit der Wahrheit.

Die Untergrenzen sind Stand 06.10.2026. Wer an Punkten oder Vetos dreht, sieht hier, ob es traegt.
Seit 06.10. gilt: Bei Gleichstand zwischen Namensvettern (Eltern, Brautleute) raet famrecon nicht, sondern
legt eine eigene Person an und gibt die Kandidaten in die Pruefliste. Das kostet hier Vollstaendigkeit
(zwei Petra Meyer, Franz neben Franz Anton), bringt an echten Registern aber Praezision bei den Kindern.
Die uebrigen Fehler liegen in den Demodaten: Kinder, die vor ihrer Geburt sterben.
"""
import tempfile
import unittest
from pathlib import Path

from famrecon import db, kern, lesen, messen, simulation, verknuepfen, zuordnung

GED = Path(__file__).resolve().parent.parent / "beispiel" / "falkenrath.ged"


def lauf(rauschen=0.0):
    with tempfile.TemporaryDirectory() as d:
        xlsx = Path(d) / "register.xlsx"
        simulation.simulieren(GED, xlsx, rauschen)
        blaetter = zuordnung.vorschlagen(xlsx)
        toml = Path(d) / "z.toml"
        toml.write_text(zuordnung.toml_text(str(xlsx), blaetter), encoding="utf-8")
        con = db.oeffnen(":memory:")
        lesen.einlesen(con, lesen.zuordnung_laden(toml), [xlsx])
        kern.personen_bauen(con)
        verknuepfen.verknuepfen(con)
        m = messen.messen(con)
        m["doppelte_paare"] = con.execute("SELECT COUNT(*) FROM (SELECT mann, frau FROM familie WHERE mann IS NOT NULL "
                                          "AND frau IS NOT NULL GROUP BY mann, frau HAVING COUNT(*)>1)").fetchone()[0]
        return m


class Falkenrath(unittest.TestCase):
    def test_sauber(self):
        m = lauf(0.0)
        self.assertEqual(m["refs"], 492)
        self.assertGreaterEqual(m["praezision"], 0.995, m)
        self.assertGreaterEqual(m["vollstaendigkeit"], 0.98, m)
        self.assertEqual(m["doppelte_paare"], 0)                # ein Paar, eine Familie (Meldung "doppelter Eheeintrag" in Desktop-Programmen)

    def test_mit_rauschen(self):
        m = lauf(0.3)
        self.assertGreaterEqual(m["praezision"], 0.99, m)
        self.assertGreaterEqual(m["vollstaendigkeit"], 0.95, m)


if __name__ == "__main__":
    unittest.main()
