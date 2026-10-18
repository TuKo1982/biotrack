#!/usr/bin/env bash
# BioTrack — création du conteneur LXC + installation, en une ligne depuis l'HÔTE Proxmox VE (en root) :
#
#   BIOTRACK_PASSWORD='un-mot-de-passe' bash -c "$(curl -fsSL https://raw.githubusercontent.com/TuKo1982/biotrack/main/pve-create.sh)"
#
# Variables optionnelles :
#   CT_ID=150            VMID (défaut : prochain libre)         CT_HOSTNAME=biotrack
#   CT_STORAGE=local-lvm stockage du disque                     CT_DISK=4        Go
#   CT_MEM=512           Mo                                      CT_CORES=1
#   CT_BRIDGE=vmbr0      CT_IP=dhcp  (ou 192.168.1.50/24)        CT_GW=192.168.1.1 (si IP fixe)
#   CT_TEMPLATE_STORAGE=local   stockage des templates           CT_PASSWORD=...  mot de passe root du CT (défaut : aléatoire)
#   BIOTRACK_PORT / BIOTRACK_TZ / BIOTRACK_REPO : transmis à install.sh
set -euo pipefail

command -v pct >/dev/null || { echo "Ce script s'exécute sur un hôte Proxmox VE (commande pct absente)."; exit 1; }
[ "$(id -u)" = 0 ] || { echo "À lancer en root."; exit 1; }

CT_ID="${CT_ID:-$(pvesh get /cluster/nextid)}"
CT_HOSTNAME="${CT_HOSTNAME:-biotrack}"
CT_STORAGE="${CT_STORAGE:-local-lvm}"
CT_TEMPLATE_STORAGE="${CT_TEMPLATE_STORAGE:-local}"
CT_DISK="${CT_DISK:-4}"
CT_MEM="${CT_MEM:-512}"
CT_CORES="${CT_CORES:-1}"
CT_BRIDGE="${CT_BRIDGE:-vmbr0}"
CT_IP="${CT_IP:-dhcp}"
CT_GW="${CT_GW:-}"
CT_PASSWORD="${CT_PASSWORD:-$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)}"
PASS="${BIOTRACK_PASSWORD:-}"
RAW="https://raw.githubusercontent.com/${BIOTRACK_GH:-TuKo1982/biotrack}/main"

if pct status "$CT_ID" >/dev/null 2>&1; then
  echo "Le conteneur $CT_ID existe déjà. Choisir un autre CT_ID ou lancer install.sh à l'intérieur."; exit 1
fi

echo "==> Template Debian 12"
pveam update >/dev/null
TPL=$(pveam available --section system | awk '/debian-12-standard/ {print $2}' | sort -V | tail -1)
[ -n "$TPL" ] || { echo "Template debian-12-standard introuvable."; exit 1; }
if ! pveam list "$CT_TEMPLATE_STORAGE" | grep -q "$TPL"; then
  pveam download "$CT_TEMPLATE_STORAGE" "$TPL"
fi

NET="name=eth0,bridge=$CT_BRIDGE,ip=$CT_IP"
[ "$CT_IP" != "dhcp" ] && [ -n "$CT_GW" ] && NET="$NET,gw=$CT_GW"

echo "==> Création du conteneur $CT_ID ($CT_HOSTNAME, ${CT_MEM} Mo, ${CT_DISK} Go sur $CT_STORAGE)"
pct create "$CT_ID" "$CT_TEMPLATE_STORAGE:vztmpl/$TPL" \
  --hostname "$CT_HOSTNAME" --password "$CT_PASSWORD" \
  --memory "$CT_MEM" --swap 256 --cores "$CT_CORES" \
  --rootfs "$CT_STORAGE:$CT_DISK" \
  --net0 "$NET" \
  --unprivileged 1 --features nesting=1 \
  --onboot 1 --start 1 \
  --description "BioTrack - suivi analyses sanguines et Oura" >/dev/null

echo "==> Attente du réseau dans le conteneur"
for i in $(seq 1 30); do
  if pct exec "$CT_ID" -- getent hosts deb.debian.org >/dev/null 2>&1; then break; fi
  sleep 2
  [ "$i" = 30 ] && { echo "Pas de réseau dans le conteneur après 60 s (DHCP ? passerelle ?)."; exit 1; }
done

echo "==> Installation de BioTrack dans le conteneur"
pct exec "$CT_ID" -- bash -c "apt-get update -qq >/dev/null && apt-get install -y -qq curl ca-certificates >/dev/null"
pct exec "$CT_ID" -- env BIOTRACK_PASSWORD="$PASS" BIOTRACK_PORT="${BIOTRACK_PORT:-8080}" \
  BIOTRACK_TZ="${BIOTRACK_TZ:-Europe/Zurich}" BIOTRACK_REPO="${BIOTRACK_REPO:-}" \
  bash -c "bash <(curl -fsSL $RAW/install.sh)"

IP=$(pct exec "$CT_ID" -- hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "Conteneur $CT_ID ($CT_HOSTNAME) créé · root du CT : $CT_PASSWORD"
echo "BioTrack : http://${IP:-<ip>}:${BIOTRACK_PORT:-8080}"
echo "Mise à jour ultérieure : pct exec $CT_ID -- bash -c \"bash <(curl -fsSL $RAW/install.sh)\""
