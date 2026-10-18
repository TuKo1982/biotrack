# BioTrack

Suivi personnel, auto-hébergé, des analyses sanguines (rapports PDF Polyanalytic) et des données
Oura Ring (export `data.zip`). À chaque import, l'application fusionne les nouvelles données avec
l'existant et recalcule :

- l'évolution de chaque paramètre sanguin avec la norme du laboratoire (les valeurs d'« antériorité »
  figurant dans les PDF comblent les bilans dont on n'a pas le rapport) ;
- le contexte Oura de chaque prélèvement : 14 et 3 nuits précédentes, nuits « lourdes »,
  tags (maladie, alcool, fête), sport le matin même, prélèvement l'après-midi, nuit manquante ;
- les tendances Oura (FC de repos, VFC, température, sommeil) avec les prélèvements marqués ;
- une analyse du sommeil (efficacité, endormissement, régularité, effet week-end, perturbations
  respiratoires) ;
- des corrélations exploratoires (Spearman) entre paramètres sanguins et état Oura pré-prélèvement ;
- des constats rédigés en français, à discuter avec le médecin traitant.

Tout reste sur la machine : SQLite + les PDF importés dans `/var/lib/biotrack`. Aucun appel externe.
`rawlocation.csv` et les séries brutes de l'export Oura ne sont pas lus.

## Installation en une ligne

### Depuis l'hôte Proxmox VE (crée le LXC et installe tout), en root

```bash
BIOTRACK_PASSWORD='un-mot-de-passe' bash -c "$(curl -fsSL https://raw.githubusercontent.com/TuKo1982/biotrack/main/pve-create.sh)"
```

Télécharge le template Debian 12 si besoin, crée un conteneur non privilégié (512 Mo, 4 Go, DHCP,
prochain VMID libre), y installe BioTrack et affiche l'URL. Options : `CT_ID`, `CT_HOSTNAME`,
`CT_STORAGE` (local-lvm), `CT_DISK`, `CT_MEM`, `CT_CORES`, `CT_BRIDGE`, `CT_IP` (dhcp ou
`192.168.1.50/24` avec `CT_GW`), `CT_PASSWORD` (root du conteneur, sinon aléatoire et affiché).

### Dans un conteneur ou une VM existante (Debian 12 / Ubuntu 22.04+), en root

```bash
BIOTRACK_PASSWORD='un-mot-de-passe' bash -c "$(curl -fsSL https://raw.githubusercontent.com/TuKo1982/biotrack/main/install.sh)"
```

Puis ouvrir `http://<ip>:8080` (identifiant quelconque, mot de passe = celui choisi). Relancer la
même commande pour mettre à jour. Variables : `BIOTRACK_PORT` (8080), `BIOTRACK_TZ` (Europe/Zurich),
`BIOTRACK_REPO` (dépôt à cloner). Hors ligne : `bash install.sh biotrack.tar.gz`.

## Utilisation

1. Oura : app → Compte → *Exporter mes données* → importer le `data.zip` reçu (tout l'historique à
   chaque fois : les jours existants sont simplement mis à jour).
2. Laboratoire : importer chaque PDF « Rapport Complet ». Un rapport réimporté remplace le précédent
   (clé = numéro de demande).
3. Le tableau de bord se recalcule à chaque affichage ; `/api/data` renvoie la même chose en JSON.

## Développement

```bash
python3 -m venv venv && venv/bin/pip install -r requirements.txt
BIOTRACK_DATA=./data venv/bin/uvicorn --app-dir app main:app --reload
```

Structure : `app/ingest_lab.py` (parseur PDF, table `CANON` des paramètres reconnus),
`app/ingest_oura.py` (export Oura), `app/analysis.py` (règles et statistiques, seuils en tête de
fichier), `app/main.py` (FastAPI), `app/static/app.js` (graphiques SVG sans dépendance).

Pour ajouter un paramètre sanguin : une ligne dans `CANON` (clé, libellé, noms possibles dans le
PDF) et, si on veut un panneau dédié, une entrée dans `PANELS`.

BioTrack ne remplace pas une interprétation médicale.
