#!/bin/bash
# Debian-Paket aus der PyInstaller-Einzeldatei: Befehl famrecon, Menueeintrag mit Symbol, keine Abhaengigkeiten
# (alles steckt in der Einzeldatei). Daten landen beim ersten Start in ~/.local/share/famrecon/daten,
# Meldungen in ~/.local/share/famrecon/famrecon.log; beendet wird ueber den Knopf in der Oberflaeche.
#     bash werkzeuge/deb-bauen.sh dist/famrecon out            -> out/famrecon_<version>_amd64.deb
set -euo pipefail
bin=${1:?Einzeldatei}; ziel=${2:-out}
hier=$(cd "$(dirname "$0")" && pwd); wurzel=$(dirname "$hier")
version=$(python3 -c "import tomllib,sys;print(tomllib.load(open(sys.argv[1],'rb'))['project']['version'])" "$wurzel/pyproject.toml")
arch=$(dpkg --print-architecture 2>/dev/null || echo amd64)
paket=$ziel/deb/famrecon_${version}_$arch
rm -rf "$paket"; mkdir -p "$paket/DEBIAN" "$paket/usr/bin" "$paket/usr/share/applications" \
  "$paket/usr/share/icons/hicolor/512x512/apps" "$paket/usr/share/doc/famrecon"
install -m 755 "$bin" "$paket/usr/bin/famrecon"
install -m 644 "$wurzel/werkzeuge/famrecon-512.png" "$paket/usr/share/icons/hicolor/512x512/apps/famrecon.png"
install -m 644 "$wurzel/LICENSE" "$paket/usr/share/doc/famrecon/copyright"
cat > "$paket/usr/share/applications/famrecon.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=famrecon
Comment=Familien aus Tauf-, Ehe- und Sterberegistern in Tabellenform, Ausgabe GEDCOM
Comment[en]=Families from baptism, marriage and burial registers in table form, GEDCOM output
Exec=famrecon
Icon=famrecon
Terminal=false
Categories=Office;
Keywords=Genealogie;GEDCOM;Kirchenbuch;Ortsfamilienbuch;
Keywords[en]=genealogy;GEDCOM;parish register;
DESKTOP
cat > "$paket/DEBIAN/control" <<CONTROL
Package: famrecon
Version: $version
Section: misc
Priority: optional
Architecture: $arch
Maintainer: thobgg <thomas@bgg-mail.de>
Homepage: https://github.com/thobgg/famrecon
Installed-Size: $(du -sk "$paket/usr" | cut -f1)
Description: Familien aus Tauf-, Ehe- und Sterberegistern, Ausgabe GEDCOM
 Liest Tauf-, Ehe- und Sterberegister als Excel- oder CSV-Tabelle, verknuepft
 Personen zu Familien und schreibt GEDCOM 5.5.1. Startet eine Oberflaeche im
 Browser; Daten liegen in ~/.local/share/famrecon.
CONTROL
mkdir -p "$ziel"
chmod -R go-w "$paket"; chmod 644 "$paket/usr/share/applications/famrecon.desktop"
dpkg-deb --build --root-owner-group "$paket" "$ziel/famrecon_${version}_$arch.deb"
rm -rf "$ziel/deb"
ls -la "$ziel"/*.deb
