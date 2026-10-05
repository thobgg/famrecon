# Die Tests pruefen deutsche Beschriftungen; auf englischen Rechnern (GitHub-Laeufer) wuerde famrecon
# sonst uebersetzen. Muss vor dem ersten Import von famrecon.i18n gesetzt sein.
import os

os.environ.setdefault("FAMRECON_SPRACHE", "de")
