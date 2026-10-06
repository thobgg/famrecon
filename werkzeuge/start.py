"""Einstieg fuer das Paket: ohne Argumente die Oberflaeche, sonst die Kommandozeile.

Das Paket ist ohne Konsolenfenster gebaut. Wer die Windows-EXE trotzdem in einer
Eingabeaufforderung mit Argumenten aufruft, bekommt die Ausgabe dort: wir haengen
uns an die Konsole des aufrufenden Prozesses."""
import sys


def konsole_anhaengen():
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import ctypes
    if ctypes.windll.kernel32.AttachConsole(-1):              # -1: die Konsole des Elternprozesses
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
        sys.stdin = open("CONIN$", "r", encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:]:
        konsole_anhaengen()
    from famrecon.cli import main
    main(sys.argv[1:] or ["start"])
