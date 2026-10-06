# PyInstaller: eine Datei, startet die Oberflaeche. Datendateien des Pakets (Schema, Sprachen,
# Seiten) kommen mit; die Module finden sie ueber Path(__file__), das in der EXE auf den
# entpackten Ordner zeigt.
#     python -m PyInstaller werkzeuge/famrecon.spec --noconfirm   -> dist/famrecon[.exe], auf dem Mac dist/famrecon.app
# Symbol: werkzeuge/famrecon.ico (Windows), werkzeuge/famrecon-512.png (Mac, PyInstaller wandelt mit Pillow
# nach .icns). Unter Linux traegt die Einzeldatei kein Symbol; das liefert die .deb (werkzeuge/deb-bauen.sh).
import sys
import tomllib
from pathlib import Path
wurzel = Path(SPECPATH).parent
version = tomllib.loads((wurzel / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
daten = [(str(wurzel / "famrecon" / p), f"famrecon/{Path(p).parent}") for p in
         ("schema.sql", "sprachen/famrecon.pot", "sprachen/en/LC_MESSAGES/famrecon.mo",
          "web/static/stil.css", "web/static/symbol.png", "web/vorlagen/rahmen.html", "web/vorlagen/start.html", "web/vorlagen/projekt.html",
          "web/vorlagen/zuordnung.html", "web/vorlagen/personen.html", "web/vorlagen/familien.html",
          "web/vorlagen/pruefliste.html", "web/vorlagen/gedcom.html", "web/vorlagen/hilfe.html", "web/vorlagen/beendet.html",
          "web/hilfe/de.html", "web/hilfe/en.html")]
daten += [(str(wurzel / "beispiel" / p), "beispiel") for p in
          ("falkenrath-taufen.csv", "falkenrath-ehen.csv", "falkenrath-tote.csv")]
a = Analysis([str(wurzel / "werkzeuge" / "start.py")], pathex=[str(wurzel)], datas=daten,
             hiddenimports=["famrecon.web.server", "openpyxl"], noarchive=False,
             excludes=["PIL"])  # Pillow dient nur dem Symbol beim Bau; openpyxl kommt ohne aus (sonst +6 MB)
pyz = PYZ(a.pure)
mac = sys.platform == "darwin"
symbol = str(wurzel / "werkzeuge" / ("famrecon.ico" if sys.platform.startswith("win") else "famrecon-512.png"))
# Ohne Konsolenfenster: Beenden ueber den Knopf in der Oberflaeche, Meldungen in famrecon.log im Datenordner.
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="famrecon", console=False, upx=False, icon=symbol)
if mac:
    app = BUNDLE(exe, name="famrecon.app", icon=symbol, bundle_identifier="de.bgg-home.famrecon",
                 info_plist={"CFBundleShortVersionString": version, "CFBundleVersion": version,
                             "NSHighResolutionCapable": True, "LSApplicationCategoryType": "public.app-category.productivity"})
