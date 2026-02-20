# data-analyse-etl-SI

Pipeline ETL de nettoyage et transformation de données vers MongoDB.

---

## Structure du projet

```
data-analyse-etl-SI/
├── data_raw/                  ← Déposer les fichiers CSV ici (lecture seule)
├── data_clean/                ← Fichiers générés par les jobs (créé automatiquement)
├── docs/
│   ├── PLAN.md                ← Architecture, choix techniques, schéma OBT
│   └── BUSINESS_RULES.md      ← Règles de validation et de transformation
└── etl/
    ├── fetch_holidays.py      ← Téléchargement des jours fériés (nager.at)
    ├── quality_check.py       ← Job 1 — détection des anomalies
    ├── curated.py             ← Job 2 — nettoyage et production du fichier final
    └── diagnostic.py          ← Outil de diagnostic (écarts de lignes, etc.)
```

---

## Prérequis

```bash
pip install pandas
```

---

## 1. Déposer les fichiers sources

Copier les trois fichiers CSV dans `data_raw/` :

```
data_raw/
├── DataSet_moodle_01.csv   ← Données de commandes (fact table, ~1 000 000 lignes)
├── DataSet_moodle_02.csv   ← Informations clients (pas de header)
└── DataSet_moodle_03.csv   ← Table de référence suppliers
```

> Les fichiers dans `data_raw/` ne sont **jamais modifiés**.

---

## 2. Télécharger les données externes

Deux sources sont disponibles, téléchargeables ensemble ou séparément.

```bash
# Les deux sources, années par défaut 2022 2023 (défaut)
python etl/fetch_holidays.py

# Années personnalisées
python etl/fetch_holidays.py --years 2022 2023 2024

# nager.at uniquement (jours fériés US)
python etl/fetch_holidays.py --source nager

# Autre pays pour nager.at
python etl/fetch_holidays.py --source nager --country FR --years 2022 2023

# jiejiariapi.com uniquement (week-ends CN)
python etl/fetch_holidays.py --source jiejiariapi
```

### Source 1 — nager.at (jours fériés par pays)

**Output :** `data_raw/{country}_public_holidays_{year}.json`

```json
{
  "date": "2022-07-04",
  "name": "Independence Day",
  "global": true,
  "counties": null,
  "types": ["Public"]
}
```

> `global: true` = fête nationale / `global: false` + `counties` = fête d'état(s) spécifique(s)

### Source 2 — jiejiariapi.com (week-ends et jours ajustés CN)

**Output :** `data_raw/cn_weekends_{year}.json`

```json
{
  "date": "2022-01-01",
  "name": "周六",
  "isOffDay": false
}
```

> `isOffDay: false` = jour travaillé malgré le week-end (ajustement de calendrier CN)

---

## 3. Job 1 — Quality Check

Analyse les données brutes et produit un rapport des anomalies.

```bash
python etl/quality_check.py
```

**Output :** `data_clean/quality_report.csv`

Chaque ligne du rapport correspond à une anomalie :

| Colonne | Description |
|---|---|
| `source_file` | Fichier source concerné |
| `line_number` | Numéro de ligne dans le fichier raw |
| `raw_data` | Contenu brut de la ligne |
| `field` | Champ en erreur |
| `error` | Description de l'anomalie |

> Lire `docs/BUSINESS_RULES.md` pour le détail des règles de validation appliquées.

---

## 4. Job 2 — Curated

Nettoie les données, applique les transformations et produit le fichier final (One Big Table).

**Export CSV** (pour PostgreSQL, Excel, etc.) :
```bash
python etl/curated.py --format csv
```
Output : `data_clean/curated_orders.csv`

**Export JSON** (pour MongoDB via `mongoimport`) :
```bash
python etl/curated.py --format json
```
Output : `data_clean/curated_orders.json`

> Sans `--format`, le CSV est produit par défaut.

### Import dans MongoDB

```bash
mongoimport --db <base> --collection orders \
            --type json \
            --file data_clean/curated_orders.json
```

### Schéma du fichier produit

| Champ | Source | Type |
|---|---|---|
| `OrderID` | moodle_01 | string (`00000001`) |
| `OrderDate` | moodle_01 | datetime string |
| `SupplierID` | moodle_01 | string (`0002`) |
| `SupplierName` | moodle_03 | string |
| `OrderAmount` | moodle_01 | float |
| `PaymentDate` | moodle_01 | datetime string |
| `CustomerSatisfaction` | moodle_01 | int |
| `ClientName` | moodle_01 | string |
| `ClientStreet` | moodle_02 | string |
| `ClientCity` | moodle_02 | string |
| `ClientState` | moodle_02 | string |
| `ClientZip` | moodle_02 | string |
| `ProductName` | moodle_01 | string |

---

## 5. Job 3 — Calendrier curated

Génère une table calendrier avec une ligne par date pour 2022 et 2023.

```bash
# Export CSV (défaut)
python etl/curated_calendar.py

# Export JSON (NDJSON pour mongoimport)
python etl/curated_calendar.py --format json

# Années personnalisées
python etl/curated_calendar.py --years 2022 2023 --format json
```

**Import dans MongoDB :**
```bash
mongoimport --db <base> --collection calendar \
            --type json \
            --file data_clean/curated_calendar.json
```

**Prérequis :** avoir exécuté `fetch_holidays.py` au préalable (fichiers nager.at nécessaires).

**Output :** `data_clean/curated_calendar.csv`

| Colonne | Type | Description |
|---|---|---|
| `date` | string (`YYYY-MM-DD`) | Date |
| `isWeekend` | bool | `True` si samedi ou dimanche |
| `isUSHoliday` | bool | `True` si jour férié US national (nager.at, `global=true`, type `Public`) |

> 730 lignes pour 2022 + 2023 (365 + 365).

---

## 7. Docker — MongoDB + import automatique

Lance MongoDB et importe les deux tables curées en une seule commande.

### Prérequis

Les deux fichiers JSON doivent exister avant de lancer Docker :

```bash
python etl/curated.py --format json          # → data_clean/curated_orders.json
python etl/curated_calendar.py --format json # → data_clean/curated_calendar.json
```

### Démarrage

```bash
docker compose up
```

Le service `importer` attend que MongoDB soit prêt (healthcheck), puis importe
les deux collections dans la base `etl_db` :

| Collection | Fichier source | Lignes |
|---|---|---|
| `orders` | `data_clean/curated_orders.json` | ~1 000 000 |
| `calendar` | `data_clean/curated_calendar.json` | 730 |

> Chaque relance de `docker compose up` **écrase** les collections existantes (`--drop`).

### Connexion

```
mongodb://localhost:27017/etl_db
```

### Arrêt

```bash
docker compose down          # arrête les conteneurs, conserve les données
docker compose down -v       # arrête et supprime le volume (données effacées)
```

---

## 9. Diagnostic (optionnel)

En cas d'écart de lignes entre le fichier produit et la base de données cible :

```bash
python etl/diagnostic.py
```

Vérifie les lignes physiques vs logiques, les caractères problématiques et peut
comparer les OrderIDs avec un export PostgreSQL.

---

## Documentation

| Fichier | Contenu |
|---|---|
| `docs/PLAN.md` | Architecture du projet, choix OBT vs Star Schema, logique de jointure |
| `docs/BUSINESS_RULES.md` | Règles de validation champ par champ, transformations curated, anomalies ignorées |
