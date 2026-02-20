# Plan — ETL Data Pipeline

## Contexte du projet

Pipeline ETL dont le but est de passer de données brutes (raw) à des données propres
exportées dans une collection MongoDB.

Les données raw ne sont **jamais modifiées**. Toute transformation se fait dans les
niveaux curated et au-delà.

---

## Sources de données (data_raw)

| Fichier | Rôle | Lignes | Colonnes |
|---|---|---|---|
| `DataSet_moodle_01.csv` | Fact table — données de commandes complètes | ~1 000 000 | 8 |
| `DataSet_moodle_02.csv` | Dimension client — infos client liées par ClientName | ~1 000 000 | 3 (défini manuellement, pas de header) |
| `DataSet_moodle_03.csv` | Dimension supplier — table de référence | ~100 | 2 |

Le pipeline doit fonctionner de façon générique : si le nombre de fichiers passe
de 3 à 100, le comportement doit rester identique sans modification du code.

---

## Architecture choisie : One Big Table (OBT)

**Pourquoi OBT et pas Star Schema :**

- MongoDB est une base documentaire — chaque document doit être autonome
- Les jointures (`$lookup`) dans MongoDB sont coûteuses et contre la philosophie du moteur
- Les dimensions sont petites et stables (100 suppliers, adresses clients fixes)
- L'analyse de données est simplifiée avec tout dans un seul document

**Résultat final :** une collection MongoDB où chaque document représente une commande
enrichie avec les informations client et supplier.

---

## Schéma final OBT (cible MongoDB)

**1 000 000 de documents** — un par ligne de moodle_01 (fact table).

```json
{
  "OrderID": "00000001",
  "OrderDate": "2022-01-01 00:00:00",
  "SupplierID": "0002",
  "SupplierName": "Garcia, Yang and Gardner PLC",
  "OrderAmount": 400.84,
  "PaymentDate": "2022-03-01 23:00:00",
  "CustomerSatisfaction": 3,
  "ClientName": "Aaron Acosta",
  "ClientStreet": "6809 Campbell Rapids",
  "ClientCity": "Lake Lesliemouth",
  "ClientState": "DE",
  "ClientZip": "31484",
  "ProductName": "Ok Always"
}
```

Les champs `ClientStreet`, `ClientCity`, `ClientState`, `ClientZip` sont `null`
si le couple `ClientName + ProductName` est absent de moodle_02.

---

## Logique de jointure

### moodle_01 ← moodle_03 (Supplier)
- Clé : `SupplierID`
- Type : LEFT JOIN
- Cardinalité : N-to-1 (plusieurs orders par supplier)
- Résultat si absent : `SupplierName = null`

### moodle_01 ← moodle_02 (Client)
- Clé : `ClientName + ProductName`
- Type : LEFT JOIN
- **Pré-traitement :** dédoublonnage de moodle_02 sur `ClientName + ProductName`
  (première occurrence conservée) pour garantir une jointure 1-to-1
- Résultat si absent : `ClientStreet`, `ClientCity`, `ClientState`, `ClientZip` = `null`
- **Garantie : 1 000 000 lignes en sortie** — la cardinalité de moodle_01 est préservée

---

## Pipeline — Jobs

### Job 1 : Quality Check (à développer en premier)

**Input :** tous les fichiers `.csv` dans `data_raw/`
**Output :** `data_clean/quality_report.csv`

Ce job ne modifie aucune donnée. Il identifie les lignes invalides selon les
business rules de chaque dataset. Le rapport liste pour chaque anomalie :
- Fichier source
- Numéro de ligne
- Valeur brute de la ligne
- Champ(s) en erreur
- Raison de l'erreur

Ce rapport est utilisé manuellement pour comprendre les anomalies et
éventuellement affiner les business rules.

### Job 2 : Curated (à développer après analyse du rapport)

**Input :** `data_raw/` + résultats de l'analyse du rapport qualité
**Output :** `data_clean/curated_orders.csv` (ou format équivalent)

Ce job applique les transformations définies après analyse :

**Normalisation des identifiants**
- `OrderID` : préfixe `O` (lettre) → `0` (chiffre) — ex. `O0000001` → `00000001`
- `SupplierID` : lettre préfixe → `0` — ex. `S002` → `0002`
  (appliqué dans moodle_01 et moodle_03 avant jointure)

**Gestion des champs vides (moodle_01)**
- `ProductName` vide → `null`
- `ClientName` vide → `null`
- `OrderDate` vide → `null`
- `OrderID` vide → inférence par lignes adjacentes si `next_num - prev_num == 2`, sinon `null`

**Anomalie ignorée**
- `OrderDate` > `PaymentDate` : ligne conservée sans modification

**Construction de l'OBT**
- Dédoublonnage de moodle_02 sur `ClientName + ClientAddress`
- Décomposition de chaque adresse en 4 champs (`street`, `city`, `state`, `zip`)
- Groupement par `ClientName` → tableau d'adresses (`ClientAddresses`)
- Jointure OBT (moodle_01 + moodle_02 groupé + moodle_03)

### Job 3 : Export MongoDB (à définir ultérieurement)

**Input :** données curées
**Output :** collection MongoDB

---

## Stack technique

| Composant | Choix | Raison |
|---|---|---|
| Langage | Python | Existant dans le projet |
| Librairie principale | pandas | Simple, efficace jusqu'à ~5M lignes, bien documentée |
| Format intermédiaire | CSV | Lisible et inspectable manuellement |

---

## Structure du projet

```
data-analyse-etl-SI/
├── data_raw/               ← données brutes (lecture seule)
│   ├── DataSet_moodle_01.csv
│   ├── DataSet_moodle_02.csv
│   └── DataSet_moodle_03.csv
├── data_clean/             ← outputs des jobs ETL
│   └── quality_report.csv  ← généré par Job 1
├── docs/
│   ├── PLAN.md             ← ce fichier
│   └── BUSINESS_RULES.md   ← règles de validation et traitement
└── etl/
    └── quality_check.py    ← Job 1 (à développer)
```
