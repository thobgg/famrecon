#!/bin/bash
# Das Buch (famrecon buch) als Container auf die NAS bringen: nginx liefert den statischen Ordner aus.
# Dasselbe Muster wie db-blank/deploy.sh: Dateien per ssh kopieren; den Container startet man einmal auf der NAS
# mit sudo (Docker braucht dort Root). Spaetere Staende: nur dieses Skript, nginx liest den Ordner live.
#     bash werkzeuge/buch-deploy.sh daten/<projekt>/deploy.env
# deploy.env (lokal, nicht im Repo):
#     NAS=benutzer@nas            SSH-Ziel
#     DIR=/volume1/docker/<name>   Projektordner auf der NAS
#     NAME=<name>                  Containername
#     PORT=5054                    externer Port; der Reverse Proxy zeigt auf nas:PORT
#     SITE=daten/<projekt>/buch    der erzeugte Ordner
set -euo pipefail
env_datei=${1:?deploy.env}
# shellcheck disable=SC1090
source "$env_datei"
: "${NAS:?}" "${DIR:?}" "${NAME:?}" "${PORT:?}" "${SITE:?}"
[ -f "$SITE/index.html" ] || { echo "!! $SITE/index.html fehlt - erst 'famrecon buch' laufen lassen." >&2; exit 1; }
echo "→ Site nach $NAS:$DIR/site ($(du -sh "$SITE" | cut -f1), $(ls "$SITE" | wc -l) Dateien)"
ssh "$NAS" "mkdir -p '$DIR'"
# Ordner als Ganzes tauschen: erst site.neu fuellen, dann umbenennen, kein halber Stand sichtbar
tar -C "$SITE" -czf - . | ssh "$NAS" "rm -rf '$DIR/site.neu' && mkdir -p '$DIR/site.neu' && tar -C '$DIR/site.neu' -xzf - && rm -rf '$DIR/site.alt' && { [ -d '$DIR/site' ] && mv '$DIR/site' '$DIR/site.alt' || true; } && mv '$DIR/site.neu' '$DIR/site'"
ssh "$NAS" "cat > '$DIR/nginx.conf'" <<'NGINX'
server {
    listen 80;
    charset utf-8;
    root /usr/share/nginx/html;
    index index.html;
    add_header X-Robots-Tag "noindex, nofollow";
    location / { try_files $uri $uri/ =404; }
}
NGINX
ssh "$NAS" "cat > '$DIR/docker-compose.yml'" <<COMPOSE
services:
  buch:
    image: nginx:alpine
    container_name: $NAME
    restart: unless-stopped
    ports:
      - "$PORT:80"
    volumes:
      - ./site:/usr/share/nginx/html:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
COMPOSE
echo "✓ Dateien liegen auf der NAS. Docker braucht dort Root, wie bei db-blank: einmal auf der NAS ausführen"
echo "    sudo docker compose -f $DIR/docker-compose.yml up -d"
echo "  Danach erreichbar unter http://${NAS#*@}:$PORT/ ; der Reverse Proxy zeigt auf diesen Port."
echo "  Bei einem neuen Stand genügt dieses Skript: nginx liest den getauschten Ordner sofort, kein Neustart nötig."
