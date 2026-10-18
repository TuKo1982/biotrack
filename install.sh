#!/usr/bin/env bash
# BioTrack — installation en une ligne dans un conteneur LXC Debian 12 / Ubuntu 22.04+ (en root).
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/TuKo1982/biotrack/main/install.sh)"
#
# Variables optionnelles (à placer avant la commande) :
#   BIOTRACK_PASSWORD=secret   mot de passe HTTP Basic (recommandé) — vide = pas d'authentification
#   BIOTRACK_PORT=8080         port d'écoute
#   BIOTRACK_TZ=Europe/Zurich  fuseau utilisé pour l'export Oura
#   BIOTRACK_REPO=...          dépôt git à cloner (défaut : TuKo1982/biotrack) — ou, hors ligne :
#   bash install.sh /chemin/biotrack.tar.gz
set -euo pipefail

APP_DIR=/opt/biotrack
DATA_DIR=/var/lib/biotrack
PORT="${BIOTRACK_PORT:-8080}"
TZ_="${BIOTRACK_TZ:-Europe/Zurich}"
REPO="${BIOTRACK_REPO:-https://github.com/TuKo1982/biotrack.git}"
PASS="${BIOTRACK_PASSWORD:-}"
SRC="${1:-}"

[ "$(id -u)" = 0 ] || { echo "À lancer en root (ou via sudo)."; exit 1; }

echo "==> Paquets système"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip poppler-utils tzdata git curl ca-certificates >/dev/null

echo "==> Code de l'application -> $APP_DIR"
if [ -n "$SRC" ] && [ -f "$SRC" ]; then
  rm -rf "$APP_DIR"; mkdir -p "$APP_DIR"
  tar -xzf "$SRC" -C "$APP_DIR" --strip-components=1
elif [ -n "$SRC" ] && [ -d "$SRC" ]; then
  rm -rf "$APP_DIR"; cp -a "$SRC" "$APP_DIR"
elif [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull -q
else
  rm -rf "$APP_DIR"
  git clone -q "$REPO" "$APP_DIR"
fi

echo "==> Environnement Python"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> Données -> $DATA_DIR"
id -u biotrack >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin -d "$DATA_DIR" biotrack
mkdir -p "$DATA_DIR/uploads"
chown -R biotrack:biotrack "$DATA_DIR"
chmod 750 "$DATA_DIR"

ENV_FILE=/etc/biotrack.env
if [ ! -f "$ENV_FILE" ] || [ -n "$PASS" ]; then
  [ -f "$ENV_FILE" ] && [ -z "$PASS" ] && PASS="$(grep -oP '^BIOTRACK_PASSWORD=\K.*' "$ENV_FILE" || true)"
  cat > "$ENV_FILE" <<EOF
BIOTRACK_DATA=$DATA_DIR
BIOTRACK_TZ=$TZ_
BIOTRACK_PORT=$PORT
BIOTRACK_PASSWORD=$PASS
EOF
  chmod 600 "$ENV_FILE"
fi

echo "==> Service systemd"
cat > /etc/systemd/system/biotrack.service <<EOF
[Unit]
Description=BioTrack - suivi analyses sanguines et Oura
After=network.target

[Service]
User=biotrack
Group=biotrack
EnvironmentFile=$ENV_FILE
WorkingDirectory=$APP_DIR/app
ExecStart=$APP_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port \${BIOTRACK_PORT}
Restart=always
RestartSec=3
ProtectSystem=strict
ReadWritePaths=$DATA_DIR
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
if [ -d /run/systemd/system ]; then
  systemctl daemon-reload
  systemctl enable -q biotrack
  systemctl restart biotrack
  sleep 2
else
  echo "systemd absent : lancer manuellement ->"
  echo "  set -a; . $ENV_FILE; set +a; cd $APP_DIR/app && $APP_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port $PORT"
  exit 0
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if systemctl is-active -q biotrack; then
  echo
  echo "BioTrack est en ligne : http://${IP:-<ip-du-conteneur>}:$PORT"
  [ -n "$PASS" ] && echo "Identifiant : n'importe lequel · mot de passe : celui de BIOTRACK_PASSWORD" || echo "Sans mot de passe (définir BIOTRACK_PASSWORD dans $ENV_FILE puis 'systemctl restart biotrack')."
  echo "Données : $DATA_DIR (base SQLite + PDF importés) · logs : journalctl -u biotrack -f"
  echo "Mise à jour : relancer cette même commande."
else
  echo "Le service n'a pas démarré. Voir : journalctl -u biotrack -n 50"; exit 1
fi
