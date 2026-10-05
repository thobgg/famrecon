"""Einstieg fuer das Paket: ohne Argumente die Oberflaeche, sonst die Kommandozeile."""
import sys

from famrecon.cli import main

if __name__ == "__main__":
    main(sys.argv[1:] or ["start"])
