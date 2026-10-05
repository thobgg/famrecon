# PyInstaller: eine Datei, startet die Oberflaeche. Datendateien des Pakets (Schema, Sprachen,
# Seiten) kommen mit; die Module finden sie ueber Path(__file__), das in der EXE auf den
# entpackten Ordner zeigt.
#     python -m PyInstaller werkzeuge/famrecon.spec --noconfirm   -> dist/famrecon[.exe]
from pathlib import Path
wurzel = Path(SPECPATH).parent
daten = [(str(wurzel / "famrecon" / p), f"famrecon/{Path(p).parent}") for p in
         ("schema.sql", "sprachen/famrecon.pot", "sprachen/en/LC_MESSAGES/famrecon.mo",
          "web/static/stil.css", "web/static/symbol.png", "web/vorlagen/rahmen.html", "web/vorlagen/start.html", "web/vorlagen/projekt.html",
          "web/vorlagen/zuordnung.html", "web/vorlagen/personen.html", "web/vorlagen/familien.html",
          "web/vorlagen/pruefliste.html", "web/vorlagen/gedcom.html")]
daten += [(str(wurzel / "beispiel" / p), "beispiel") for p in
          ("falkenrath-taufen.csv", "falkenrath-ehen.csv", "falkenrath-tote.csv")]
a = Analysis([str(wurzel / "werkzeuge" / "start.py")], pathex=[str(wurzel)], datas=daten,
             hiddenimports=["famrecon.web.server", "openpyxl"], noarchive=False)
pyz = PYZ(a.pure)
import sys
symbol = str(wurzel / "werkzeuge" / ("famrecon.ico" if sys.platform.startswith("win") else "famrecon-512.png"))
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="famrecon", console=True, upx=False, icon=symbol)
