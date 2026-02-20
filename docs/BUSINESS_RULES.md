# Business Rules — Validation et Traitement des données

## Principes généraux

- Les données raw ne sont **jamais modifiées**
- Une ligne invalide n'est **pas supprimée** au stade du quality check — elle est signalée
- Les champs `null` provenant de jointures manquantes sont **acceptés** dans le curated
- Les décisions de traitement des anomalies sont prises **manuellement** après analyse
  du quality report

---

## Dataset moodle_01 — Fact Orders

**Fichier :** `DataSet_moodle_01.csv`
**Séparateur :** virgule
**Header :** oui — première ligne

### Schéma et règles de validation

| Champ | Type attendu | Format / Règle | Exemple valide | Regex |
|---|---|---|---|---|
| `OrderID` | string | Lettre `O` + exactement 7 chiffres | `O0000001` | `^O\d{7}$` |
| `OrderDate` | datetime | `YYYY-MM-DD HH:MM:SS` | `2022-01-01 00:00:00` | parsing datetime |
| `SupplierID` | string | 1 lettre majuscule + 3 chiffres | `S002` | `^[A-Z]\d{3}$` |
| `OrderAmount` | float | Nombre décimal séparé par un point | `400.84` | parsing float |
| `PaymentDate` | datetime | `YYYY-MM-DD HH:MM:SS` | `2022-03-01 23:00:00` | parsing datetime |
| `CustomerSatisfaction` | int | Entier valide (pas de plage définie) | `3` | parsing int |
| `ClientName` | string | Non vide, non null | `Donna Wood` | len > 0 |
| `ProductName` | string | Non vide, non null | `Ok Always` | len > 0 |

### Règles additionnelles

- `OrderID` doit être **unique** dans le dataset
- Une ligne est invalide si **un seul champ** ne respecte pas son format
- `OrderDate` > `PaymentDate` : signalé dans le quality report, corrigé par échange au niveau curated

---

## Dataset moodle_02 — Dimension Client

**Fichier :** `DataSet_moodle_02.csv`
**Séparateur :** virgule
**Header :** non — le format est défini manuellement ci-dessous

### Schéma défini (colonnes dans l'ordre)

| Position | Nom attribué | Type attendu | Format / Règle | Exemple valide |
|---|---|---|---|---|
| 1 | `ClientName` | string | Non vide, non null | `Aaron Acosta` |
| 2 | `ClientAddress` | string | Adresse complète entre guillemets si elle contient des virgules | `"6809 Campbell Rapids, Lake Lesliemouth, DE 31484"` |
| 3 | `ProductName` | string | Non vide, non null | `Certain Arrive` |

### Décomposition de ClientAddress

L'adresse est décomposée en 4 champs dans le niveau curated :

| Champ curated | Extraction | Exemple |
|---|---|---|
| `ClientStreet` | Tout ce qui précède la première virgule | `6809 Campbell Rapids` |
| `ClientCity` | Entre la première et la dernière virgule | `Lake Lesliemouth` |
| `ClientState` | Après la dernière virgule, premier token | `DE` |
| `ClientZip` | Après la dernière virgule, deuxième token | `31484` |

Format attendu de l'adresse : `"Street, City, State ZIP"`
Une adresse invalide est signalée si elle ne peut pas être décomposée en ces 4 parties.

### Anomalies identifiées dans les données

| Anomalie | Observation | Traitement décidé |
|---|---|---|
| Pas de header | Le fichier n'a pas de ligne d'en-tête | Assignation manuelle des noms de colonnes à la lecture |
| Doublons sur `ClientName + ProductName` | Un même couple peut apparaître plusieurs fois (ex. même client ayant commandé plusieurs fois le même produit) | **Non bloquant** — signalé en informatif dans le quality report. Dédoublonnage avant jointure : première occurrence conservée. |

### Clé de jointure vers moodle_01

Jointure sur **`ClientName + ProductName`** (LEFT JOIN depuis moodle_01).

**Logique :**
- Colonne 1 de moodle_02 (`ClientName`) ↔ champ `ClientName` de moodle_01
- Colonne 3 de moodle_02 (`ProductName`) ↔ champ `ProductName` de moodle_01
- Chaque ligne de moodle_01 reçoit l'adresse correspondant au couple client+produit

**Gestion des doublons dans moodle_02 :**
1. Dédoublonnage de moodle_02 sur `ClientName + ProductName` — première occurrence conservée
2. LEFT JOIN depuis moodle_01 sur `ClientName + ProductName`
3. Résultat : **exactement 1 000 000 de lignes** (cardinalité moodle_01 préservée)

Si le couple `ClientName + ProductName` est absent de moodle_02 → champs adresse à `null`.

---

## Dataset moodle_03 — Dimension Supplier

**Fichier :** `DataSet_moodle_03.csv`
**Séparateur :** virgule
**Header :** oui — première ligne

### Schéma et règles de validation

| Champ | Type attendu | Format / Règle | Exemple valide | Regex |
|---|---|---|---|---|
| `SupplierID` | string | 1 lettre majuscule + 3 chiffres | `S002` | `^[A-Z]\d{3}$` |
| `SupplierName` | string | Non vide, non null | `Garcia, Yang and Gardner PLC` | len > 0 |

### Règles additionnelles

- `SupplierID` doit être **unique** dans cette table (c'est une table de référence)
- `SupplierName` peut contenir des virgules (géré par les guillemets CSV)

### Clé de jointure vers moodle_01

Jointure sur `SupplierID` (LEFT JOIN depuis moodle_01).

---

## Schéma final curated (OBT)

Résultat de la jointure des trois datasets.
**Nombre de lignes : exactement 1 000 000** — identique à moodle_01 (la fact table est la base,
les dimensions enrichissent chaque ligne sans en créer ni en supprimer).

| Champ | Source | Type | Valeur si données manquantes |
|---|---|---|---|
| `OrderID` | moodle_01 | string | `"unknown"` (vide non inférable) |
| `OrderDate` | moodle_01 | datetime string | `"unknown"` (les deux dates vides) |
| `SupplierID` | moodle_01 | string | Non applicable |
| `SupplierName` | moodle_03 | string | `"unknown"` (SupplierID absent de moodle_03) |
| `OrderAmount` | moodle_01 | float string | Non applicable |
| `PaymentDate` | moodle_01 | datetime string | `"unknown"` (les deux dates vides) |
| `CustomerSatisfaction` | moodle_01 | int string | Non applicable |
| `ClientName` | moodle_01 | string | `"unknown"` (vide dans la source) |
| `ClientStreet` | moodle_02 | string | `"unknown"` (couple absent de moodle_02) |
| `ClientCity` | moodle_02 | string | `"unknown"` (couple absent de moodle_02) |
| `ClientState` | moodle_02 | string | `"unknown"` (couple absent de moodle_02) |
| `ClientZip` | moodle_02 | string | `"unknown"` (couple absent de moodle_02) |
| `ProductName` | moodle_01 | string | `"unknown"` (vide dans la source) |

---

---

## Transformations curated — Règles appliquées au Job 2

Ces règles s'appliquent **uniquement au niveau curated**. Les données raw restent intactes.

### Normalisation des identifiants

| Champ | Source | Transformation | Exemple |
|---|---|---|---|
| `OrderID` | moodle_01 | Remplacer le préfixe `O` (lettre) par `0` (chiffre) | `O0000001` → `00000001` |
| `SupplierID` | moodle_01 + moodle_03 | Remplacer la lettre préfixe par `0` (chiffre) | `S002` → `0002`, `S016` → `0016` |

> La transformation s'applique à moodle_01 (colonne `SupplierID`) et à moodle_03
> (colonne `SupplierID`), de façon à ce que la jointure reste cohérente des deux côtés.
> moodle_02 ne contient pas de `SupplierID` — non concerné.

### Champs vides → null (moodle_01)

Les lignes concernées sont déjà signalées par le quality check. Au niveau curated,
elles reçoivent explicitement `null` plutôt que d'être rejetées.

| Champ | Condition | Traitement curated |
|---|---|---|
| `ProductName` | Valeur vide ou null | `null` (puis `"unknown"` si toujours null en fin de pipeline) |
| `ClientName` | Valeur vide ou null | `null` (puis `"unknown"` si toujours null en fin de pipeline) |
| `OrderDate` | Valeur vide ou null | `null` (puis règles de cohérence dates ci-dessous) |

### Inférence de l'OrderID manquant ou corrompu (moodle_01)

Deux cas déclenchent l'inférence — les deux reçoivent exactement le même traitement,
car une valeur corrompue ne peut pas être utilisée telle quelle :

| Cas | Exemple | Traitement |
|---|---|---|
| `OrderID` vide / null | _(vide)_ | Inférence par lignes adjacentes |
| `OrderID` format invalide | `O07606X7` | Inférence par lignes adjacentes |

**Algorithme :**
1. Repérer les lignes avec `OrderID` vide OU format invalide (`needs_inference`)
2. Extraire les numéros des lignes voisines **valides** (`prev`, `next`)
3. Si `next_num - prev_num == 2` → l'OrderID est `O` + `str(prev_num + 1).zfill(7)`
4. Appliquer ensuite la normalisation `O` → `0`
5. Si la condition n'est pas satisfaite → `null`

**Exemples :**

| Ligne précédente | Ligne problématique | Ligne suivante | Résultat |
|---|---|---|---|
| `O0209975` | _(vide)_ | `O0209977` | `O0209976` → curated : `00209976` |
| `O0760606` | `O07606X7` | `O0760608` | `O0760607` → curated : `00760607` |
| `O0209975` | `O07606X7` | `O0209980` | non inférable (écart ≠ 2) → `null` |
| _(vide)_ | _(vide)_ | `O0209977` | non inférable (pas de précédent) → `null` |

### Gestion de la cohérence OrderDate / PaymentDate (moodle_01)

Ces règles s'appliquent **après** la nullification des champs vides, dans cet ordre :

| Ordre | Condition | Transformation |
|---|---|---|
| 1 | `OrderDate` vide / null | Remplacer par la valeur de `PaymentDate` (si disponible) |
| 2 | `PaymentDate` vide / null | Remplacer par la valeur de `OrderDate` (après l'étape 1) |
| 3 | `OrderDate` > `PaymentDate` | Échanger les deux valeurs |

> Si les deux dates sont vides, elles restent `null` après les étapes 1 et 2,
> puis reçoivent `"unknown"` via la règle globale de remplacement null.
>
> La comparaison de l'étape 3 est lexicographique sur les chaînes ISO
> (`YYYY-MM-DD HH:MM:SS`), ce qui est équivalent à une comparaison chronologique.

### Remplacement global null → "unknown"

**Après toutes les transformations et jointures**, tout champ encore null dans l'OBT
reçoit la valeur `"unknown"`. Aucun champ null n'est présent dans le fichier final.

| Champs concernés | Cause possible |
|---|---|
| `OrderID` | OrderID non inférable |
| `OrderDate`, `PaymentDate` | Les deux dates étaient vides dans la source |
| `SupplierName` | SupplierID absent de moodle_03 |
| `ClientName`, `ProductName` | Valeur vide dans moodle_01 |
| `ClientStreet`, `ClientCity`, `ClientState`, `ClientZip` | Couple ClientName+ProductName absent de moodle_02 |

---

## Questions ouvertes (à trancher après quality report)

| # | Question | Impact |
|---|---|---|
| 1 | Quels champs de moodle_01 sont les plus souvent invalides ? | Priorisation du nettoyage |
| 2 | Y a-t-il des `SupplierID` dans moodle_01 qui n'existent pas dans moodle_03 ? | Intégrité référentielle |
| 3 | Y a-t-il des `OrderID` en doublon dans moodle_01 ? | Problème de clé primaire |
| 4 | Combien de clients de moodle_01 sont absents de moodle_02 ? | Mesure de la couverture des adresses |
| 5 | Combien d'`OrderID` vides sont inférables vs non inférables ? | Volume de données récupérables |
