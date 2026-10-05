"""Zuordnungsvorschlag fuer die Kirchenbuchstil- Beispieldatei: von Hand geprueft."""
import unittest
from pathlib import Path

from famrecon import zuordnung

XLSX = Path(__file__).resolve().parent.parent / "beispiel" / "kirchenbuchstil.xlsx"

ERWARTET = {
    "taufe": {"A": "lfd_nr_gesamt", "B": "ort", "F": "lfd_nr", "G": "geburt_ort", "H": "geburt_datum",
              "I": "tauf_datum", "J": "sterbe_datum_rv", "M": "kind_name", "N": "kind_vorname",
              "O": "vater", "P": "vater_beruf", "Q": "mutter", "R": "bemerkung", "S-BF": "paten"},
    "ehe":   {"A": "ort", "G": "trauung_datum", "H": "trauung_ort", "I": "braeutigam_name",
              "J": "braeutigam_vorname", "K": "braeutigam_beruf", "L": "braeutigam_alter",
              "M": "braut_name", "O": "braut_herkunft", "P": "braut_alter", "Q": "braeutigam_vater",
              "T": "braut_mutter", "U": "bemerkung", "V": "pfarrer", "W-Z": "zeugen", "AA": "bemerkung"},
    "tod":   {"A": "ort", "G": "geburt_datum_rv", "H": "tauf_datum_rv", "I": "sterbe_datum",
              "J": "begraebnis_datum", "K": "verstorbener_name", "L": "verstorbener_vorname",
              "M": "verstorbener_alter", "N": "todesursache", "O": "verstorbener_beruf",
              "P": "verstorbener_herkunft", "Q": "verstorbener_vater", "R": "verstorbener_mutter",
              "S": "verstorbener_ehepartner",
              "T": "bemerkung", "U-X": "zeugen"},
}


class Zuordnung(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blaetter = {register: dict((b, s["feld"]) for b, s in zu)
                        for _, register, zu, *_ in zuordnung.vorschlagen(XLSX)}

    def test_register_erkannt(self):
        self.assertEqual(set(self.blaetter), {"taufe", "ehe", "tod"})

    def test_spalten(self):
        for register, erwartet in ERWARTET.items():
            for spalte, feld in erwartet.items():
                with self.subTest(register=register, spalte=spalte):
                    self.assertEqual(self.blaetter[register].get(spalte), feld)

    def test_nichts_unerkannt(self):
        for register, zu in self.blaetter.items():
            offen = [b for b, f in zu.items() if f is None]
            self.assertEqual(offen, [], f"{register}: {offen}")


TECHNISCH = {
    "technisch-taufen.xlsx": ("taufe", {
        "A": "geburt_datum", "C": "tauf_datum", "D": "tauf_ort", "E": "kind_vorname_kb", "F": "kind_vorname",
        "G": "kind_name_kb", "H": "kind_name", "I": "kind_geschlecht", "J": "unehelich", "K": "sterbe_datum_rv",
        "M": "kind_totgeburt", "N": "todesursache_rv", "O": "kind_verzogen", "P": "kind_bemerkung_kb",
        "Q": "vater_vorname_kb", "T": "vater_name", "U": "vater_beruf_kb", "V": "vater_beruf", "W": "vater_beruf_ort",
        "X": "vater_herkunft", "Y": "vater_konfession", "Z": "vater_bemerkung_kb", "AD": "mutter_name",
        "AE": "mutter_herkunft", "AG": "mutter_bemerkung", "AI": "mutter_vater_vorname", "AK": "mutter_vater_name",
        "AO": "mutter_mutter_name", "AP": "paten_kb", "AQ": "kb", "AR": "zitat"}),
    "technisch-trauungen.xlsx": ("ehe", {
        "A": "trauung_datum", "B": "trauung_ort", "C": "braeutigam_vorname_kb", "F": "braeutigam_name",
        "H": "braeutigam_beruf", "I": "braeutigam_beruf_ort", "J": "braeutigam_herkunft", "K": "braeutigam_stand",
        "L": "braeutigam_bemerkung", "N": "braeutigam_vater_vorname", "P": "braeutigam_vater_name",
        "R": "braeutigam_vater_beruf", "S": "braeutigam_vater_beruf_ort", "T": "braeutigam_vater_herkunft",
        "U": "braeutigam_vater_stand", "X": "braut_vorname", "Z": "braut_name", "AA": "braut_herkunft",
        "AB": "braut_stand", "AG": "braut_vater_name", "AI": "braut_vater_beruf", "AO": "braut_vorehe_vorname",
        "AQ": "braut_vorehe_name", "AS": "braut_vorehe_beruf", "AT": "braut_vorehe_beruf_ort", "AV": "kb", "AW": "zitat"}),
    "technisch-begraebnisse.xlsx": ("tod", {
        "A": "sterbe_datum", "B": "begraebnis_datum", "C": "begraebnis_ort", "E": "verstorbener_vorname",
        "G": "verstorbener_name", "H": "verstorbener_geschlecht", "I": "verstorbener_stand", "K": "verstorbener_beruf",
        "L": "verstorbener_beruf_ort", "N": "verstorbener_vater_vorname", "P": "verstorbener_vater_name",
        "R": "verstorbener_vater_beruf", "V": "verstorbener_ehepartner_vorname", "X": "verstorbener_ehepartner_name",
        "Y": "verstorbener_ehepartner_geschlecht", "AA": "verstorbener_ehepartner_beruf", "AD": "todesursache",
        "AE": "verstorbener_alter_kb", "AF": "geburt_datum_rv_praefix", "AG": "geburt_datum_rv",
        "AH": "verstorbener_bemerkung_kb", "AI": "kb", "AJ": "zitat"}),
}


class ZuordnungTechnisch(unittest.TestCase):
    """Zweites Format: technische Ueberschriften (vn_vater_braeu), _kb-Spalten, Unterrollen."""

    def test_technisch(self):
        for datei, (register, erwartet) in TECHNISCH.items():
            blaetter = zuordnung.vorschlagen(XLSX.parent / datei)
            self.assertEqual(len(blaetter), 1, datei)
            _, erkannt, zu, *_ = blaetter[0]
            self.assertEqual(erkannt, register, datei)
            felder = dict((b, s["feld"]) for b, s in zu)
            for spalte, feld in erwartet.items():
                with self.subTest(datei=datei, spalte=spalte):
                    self.assertEqual(felder.get(spalte), feld)


if __name__ == "__main__":
    unittest.main()
