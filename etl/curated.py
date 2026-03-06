"""
curated.py — Job 2 : transformation et jointure OBT (curated level)

Ce job lit les fichiers raw, applique toutes les business rules de nettoyage
et produit un fichier curated (One Big Table) prêt pour l'export MongoDB.

Transformations appliquées :
  - OrderID vide       → inférence par lignes adjacentes (si next - prev == 2), sinon null
  - OrderID valide     → préfixe O → 0  (ex. O0000001 → 00000001)
  - SupplierID         → correction O/0 dans partie numérique (ex. S02O → S020)
                         puis préfixe lettre → 0 (ex. S020 → 0020) — moodle_01 + moodle_03
  - OrderDate vide     → utilise PaymentDate si disponible, sinon null
  - PaymentDate vide   → utilise OrderDate si disponible, sinon null
  - OrderDate > PaymentDate → échange des deux valeurs
  - ClientName vide    → null
  - ProductName vide   → null
  - Tous les champs null restants dans l'OBT → "unknown"
  - moodle_02 dédoublonné sur ClientName + ProductName avant jointure
  - Adresse décomposée en 4 champs plats : ClientStreet, ClientCity, ClientState, ClientZip

Jointures (LEFT JOIN depuis moodle_01) :
  - moodle_01 ← moodle_03 sur SupplierID
  - moodle_01 ← moodle_02 sur ClientName + ProductName

Garantie : 1 000 000 lignes en sortie (cardinalité moodle_01 préservée).
"""

import pandas as pd
from pathlib import Path

# ─── Chemins ──────────────────────────────────────────────────────────────────

PROJECT_ROOT   = Path(__file__).parent.parent
DATA_RAW_DIR   = PROJECT_ROOT / "data_raw"
DATA_CLEAN_DIR = PROJECT_ROOT / "data_clean"
OUTPUT_FILE    = DATA_CLEAN_DIR / "curated_orders.csv"

# ─── Constantes ───────────────────────────────────────────────────────────────

ORDERS_COLUMNS    = {"OrderID", "OrderDate", "SupplierID", "OrderAmount",
                     "PaymentDate", "CustomerSatisfaction", "ClientName", "ProductName"}
SUPPLIERS_COLUMNS = {"SupplierID", "SupplierName"}
CLIENTS_COLUMNS   = ["ClientName", "ClientAddress", "ProductName"]

OBT_COLUMNS = [
    "OrderID", "OrderDate", "SupplierID", "SupplierName",
    "OrderAmount", "PaymentDate", "CustomerSatisfaction",
    "ClientName", "ClientStreet", "ClientCity", "ClientState", "ClientZip",
    "ProductName",
]

# ─── Détection des fichiers ────────────────────────────────────────────────────

def detect_file_type(filepath: Path) -> str:
    try:
        cols = set(pd.read_csv(filepath, nrows=0).columns)
        if cols == ORDERS_COLUMNS:
            return "orders"
        if cols == SUPPLIERS_COLUMNS:
            return "suppliers"
    except Exception:
        pass
    return "clients"


def find_files() -> dict:
    """Classe tous les CSV de data_raw/ par type."""
    result = {"orders": [], "clients": [], "suppliers": []}
    for f in sorted(DATA_RAW_DIR.glob("*.csv")):
        result[detect_file_type(f)].append(f)
    return result

# ─── Transformations communes ─────────────────────────────────────────────────

def fix_supplier_id_ocr(series: pd.Series) -> pd.Series:
    """
    Corrige la confusion O (lettre) / 0 (chiffre) dans la partie numérique
    du SupplierID (positions 1 à 3, après la lettre préfixe).

    Ex : S02O → S020  (puis normalize_id_prefix le passe en 0020)

    S'applique uniquement aux valeurs de forme [A-Z][A-Z0-9]{3} — les autres
    (vides, trop courtes, etc.) sont laissées telles quelles.
    """
    candidate = series.str.match(r"^[A-Z][A-Z0-9]{3}$", na=False)
    result = series.copy()
    prefix   = series[candidate].str[0]
    digits   = series[candidate].str[1:].str.replace("O", "0", regex=False)
    result[candidate] = prefix + digits
    return result


def normalize_id_prefix(series: pd.Series, pattern: str) -> pd.Series:
    """
    Remplace le premier caractère (lettre préfixe) par '0' pour les valeurs
    correspondant au pattern regex.
      ex. O0000001 → 00000001   (pattern: ^O\\d{7}$)
      ex. S002     → 0002       (pattern: ^[A-Z]\\d{3}$)
    Les valeurs ne correspondant pas au pattern (y compris null) sont inchangées.
    """
    result = series.copy()
    valid  = series.str.match(pattern, na=False)
    result[valid] = "0" + series[valid].str[1:]
    return result


def null_if_blank(series: pd.Series) -> pd.Series:
    """Remplace les valeurs vides ou whitespace-only par None (null)."""
    blank = series.isna() | series.fillna("").str.strip().eq("")
    return series.where(~blank, other=None)


def fix_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Applique les règles de cohérence sur OrderDate et PaymentDate, dans cet ordre :
      1. OrderDate vide        → prend la valeur de PaymentDate (si disponible)
      2. PaymentDate vide      → prend la valeur de OrderDate   (après étape 1)
      3. OrderDate > PaymentDate → échange des deux valeurs
      4. OrderDate antérieure à 2010 → remplace par PaymentDate

    Si les deux dates sont vides, elles restent null après les étapes 1 et 2.
    La comparaison de l'étape 3 est lexicographique sur les chaînes ISO
    (YYYY-MM-DD HH:MM:SS), ce qui est équivalent à une comparaison chronologique.
    L'étape 4 s'applique après l'étape 3 : une date < 2010 issue d'un swap est
    également corrigée.
    """
    df = df.copy()

    od_empty  = df["OrderDate"].isna()
    pmt_empty = df["PaymentDate"].isna()

    # 1. OrderDate vide → PaymentDate
    df.loc[od_empty, "OrderDate"] = df.loc[od_empty, "PaymentDate"]

    # 2. PaymentDate vide → OrderDate (utilise la OrderDate déjà complétée à l'étape 1)
    df.loc[pmt_empty, "PaymentDate"] = df.loc[pmt_empty, "OrderDate"]

    # 3. Swap si OrderDate > PaymentDate
    both_present = df["OrderDate"].notna() & df["PaymentDate"].notna()
    swap = both_present & (df["OrderDate"] > df["PaymentDate"])
    tmp = df.loc[swap, "OrderDate"].copy()
    df.loc[swap, "OrderDate"]    = df.loc[swap, "PaymentDate"]
    df.loc[swap, "PaymentDate"]  = tmp

    # 4. OrderDate antérieure à 2010 → remplace par PaymentDate
    od_year = pd.to_datetime(df["OrderDate"], errors="coerce").dt.year
    too_old = df["OrderDate"].notna() & (od_year < 2010)
    df.loc[too_old, "OrderDate"] = df.loc[too_old, "PaymentDate"]

    print(f"    OrderDate vide → PaymentDate              : {int(od_empty.sum()):,}")
    print(f"    PaymentDate vide → OrderDate              : {int(pmt_empty.sum()):,}")
    print(f"    Échange OD ↔ PD (OD > PD)                : {int(swap.sum()):,}")
    print(f"    OrderDate < 2010 → PaymentDate            : {int(too_old.sum()):,}")

    return df

# ─── moodle_01 — Orders ───────────────────────────────────────────────────────

def infer_order_ids(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pour les OrderID vides/null ET les OrderID au format invalide (ex. O07606X7) :
      - Si le dernier ID valide précédent et le premier ID valide suivant
        diffèrent de 2, l'ID manquant est reconstruit (format O + 7 chiffres).
      - Sinon → null.

    Les deux cas (vide et format invalide) reçoivent le même traitement :
    on ne peut pas faire confiance à une valeur corrompue, donc on l'écrase.
    """
    ids        = df["OrderID"].fillna("")
    is_empty   = df["OrderID"].isna() | ids.str.strip().eq("")
    is_valid   = ids.str.match(r"^O\d{7}$")
    is_invalid = ~is_empty & ~is_valid   # non vide mais format incorrect

    # Les deux cas déclenchent l'inférence
    needs_inference = is_empty | is_invalid

    # Numéros extraits des ID valides uniquement (NaN pour tout le reste)
    valid_nums = pd.to_numeric(ids.where(is_valid).str[1:], errors="coerce")
    prev_nums  = valid_nums.ffill()   # dernier ID valide précédent
    next_nums  = valid_nums.bfill()   # premier ID valide suivant

    inferable = (
        needs_inference
        & prev_nums.notna()
        & next_nums.notna()
        & ((next_nums - prev_nums) == 2)
    )
    inferred_vals = "O" + (prev_nums.fillna(0) + 1).astype(int).astype(str).str.zfill(7)

    df = df.copy()
    df.loc[inferable,                    "OrderID"] = inferred_vals[inferable]
    df.loc[needs_inference & ~inferable, "OrderID"] = None
    return df


def load_orders(filepaths: list) -> pd.DataFrame:
    frames = []

    for fp in filepaths:
        print(f"  Lecture : {fp.name}")
        df = pd.read_csv(fp, dtype=str)

        # 1. Inférence des OrderID vides OU format invalide
        ids_raw    = df["OrderID"].fillna("")
        n_empty    = (df["OrderID"].isna() | ids_raw.str.strip().eq("")).sum()
        n_invalid  = (~(df["OrderID"].isna() | ids_raw.str.strip().eq(""))
                      & ~ids_raw.str.match(r"^O\d{7}$")).sum()
        print(f"    OrderID vides          : {int(n_empty):,}")
        print(f"    OrderID format invalide: {int(n_invalid):,}")

        df = infer_order_ids(df)

        n_inferred = int(n_empty + n_invalid) - int(df["OrderID"].isna().sum())
        print(f"    OrderID inférés        : {n_inferred:,}")
        print(f"    OrderID null restants  : {int(df['OrderID'].isna().sum()):,}")

        # 2. Normalisation OrderID : O → 0
        df["OrderID"] = normalize_id_prefix(null_if_blank(df["OrderID"]), r"^O\d{7}$")

        # 3. Normalisation SupplierID : correction O/0 puis préfixe lettre → 0
        df["SupplierID"] = fix_supplier_id_ocr(df["SupplierID"].fillna(""))
        df["SupplierID"] = normalize_id_prefix(df["SupplierID"], r"^[A-Z]\d{3}$")
        df["SupplierID"] = null_if_blank(df["SupplierID"])

        # 4. Champs vides → null
        for col in ("OrderDate", "ClientName", "ProductName"):
            df[col] = null_if_blank(df[col])

        # 5. Cohérence OrderDate / PaymentDate
        print("    [Cohérence dates]")
        df = fix_dates(df)

        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=list(ORDERS_COLUMNS))

    return pd.concat(frames, ignore_index=True)

# ─── moodle_02 — Clients ──────────────────────────────────────────────────────

def decompose_address(addr: pd.Series) -> pd.DataFrame:
    """
    Décompose une adresse au format 'Street, City, State ZIP' en 4 colonnes.
    Les adresses non décomposables produisent des null pour les 4 champs.

    Algorithme :
      - Séparer Street+City de State+ZIP sur la dernière virgule
      - Séparer Street de City sur la première virgule du côté gauche
      - Séparer State de ZIP sur le premier espace du côté droit
    """
    result = pd.DataFrame(
        {"ClientStreet": None, "ClientCity": None, "ClientState": None, "ClientZip": None},
        index=addr.index,
        dtype=object,
    )

    valid = addr.notna() & (addr.str.count(",") >= 2)
    if not valid.any():
        return result

    a = addr[valid]

    # "Street, City, State ZIP" → left="Street, City", right="State ZIP"
    split_last  = a.str.rsplit(",", n=1)
    left        = split_last.str[0]
    right       = split_last.str[1].str.strip()

    # left → street, city
    split_first = left.str.split(",", n=1)
    street      = split_first.str[0].str.strip()
    city        = split_first.str[1].str.strip()

    # right → state, zip
    split_sz    = right.str.split(" ", n=1)
    state       = split_sz.str[0].str.strip()
    zip_code    = split_sz.str[1].str.strip()

    result.loc[valid, "ClientStreet"] = street.values
    result.loc[valid, "ClientCity"]   = city.values
    result.loc[valid, "ClientState"]  = state.values
    result.loc[valid, "ClientZip"]    = zip_code.values

    return result


def load_clients(filepaths: list) -> pd.DataFrame:
    frames = []

    for fp in filepaths:
        print(f"  Lecture : {fp.name}")
        df = pd.read_csv(fp, header=None, names=CLIENTS_COLUMNS, dtype=str)
        frames.append(df)

    if not frames:
        return pd.DataFrame(
            columns=["ClientName", "ProductName",
                     "ClientStreet", "ClientCity", "ClientState", "ClientZip"]
        )

    df = pd.concat(frames, ignore_index=True)
    before = len(df)

    # Dédoublonnage sur la clé de jointure (première occurrence conservée)
    df = df.drop_duplicates(subset=["ClientName", "ProductName"], keep="first")

    # Décomposition de l'adresse en 4 champs plats
    addr_cols = decompose_address(df["ClientAddress"])
    df = pd.concat([df.drop(columns=["ClientAddress"]), addr_cols], axis=1)

    return df

# ─── moodle_03 — Suppliers ────────────────────────────────────────────────────

def _read_suppliers_csv(fp: Path) -> pd.DataFrame:
    """
    Lecteur robuste pour moodle_03 (SupplierID, SupplierName).

    pandas.read_csv() ne convient pas ici : si un SupplierName contient une
    virgule sans être quoté, pandas voit trop de colonnes et crash.
    On split à la main sur la PREMIÈRE virgule — le SupplierID étant toujours
    au format [A-Z]\\d{3}, il ne peut jamais contenir de virgule.
    Les guillemets CSV du SupplierName sont retirés si présents.

    Cas supportés :
      S003,Johnson-Davis and Sons         → name = Johnson-Davis and Sons
      S004,"Guzman, Hoffman and Baldwin"  → name = Guzman, Hoffman and Baldwin
      S004,Guzman, Hoffman and Baldwin    → name = Guzman, Hoffman and Baldwin
    """
    lines = fp.read_text(encoding="utf-8").splitlines()
    rows = []
    for line in lines[1:]:     # ignorer le header
        if not line.strip():
            continue
        sid, _, rest = line.partition(",")
        name = rest.strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('""', '"')
        rows.append({"SupplierID": sid.strip(), "SupplierName": name or None})
    if not rows:
        return pd.DataFrame(columns=["SupplierID", "SupplierName"])
    return pd.DataFrame(rows, dtype=str)


def load_suppliers(filepaths: list) -> pd.DataFrame:
    frames = []

    for fp in filepaths:
        print(f"  Lecture : {fp.name}")
        df = _read_suppliers_csv(fp)

        # Normalisation SupplierID : correction O/0 puis préfixe lettre → 0
        df["SupplierID"] = fix_supplier_id_ocr(df["SupplierID"].fillna(""))
        df["SupplierID"] = normalize_id_prefix(df["SupplierID"], r"^[A-Z]\d{3}$")
        df["SupplierID"] = null_if_blank(df["SupplierID"])

        # SupplierName vide → null (sera "unknown" après le fillna global de build_obt)
        df["SupplierName"] = null_if_blank(df["SupplierName"])

        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["SupplierID", "SupplierName"])

    return pd.concat(frames, ignore_index=True)

# ─── Jointures OBT ────────────────────────────────────────────────────────────

def build_obt(
    df_orders: pd.DataFrame,
    df_clients: pd.DataFrame,
    df_suppliers: pd.DataFrame,
) -> pd.DataFrame:
    """
    Construit l'OBT par deux LEFT JOINs depuis moodle_01.
    Lève une erreur si le nombre de lignes change (jointure non 1-to-1).
    """
    n_in = len(df_orders)

    # JOIN 1 : orders ← suppliers sur SupplierID
    df = df_orders.merge(
        df_suppliers[["SupplierID", "SupplierName"]],
        on="SupplierID",
        how="left",
    )

    # JOIN 2 : orders ← clients sur ClientName + ProductName
    df = df.merge(
        df_clients[["ClientName", "ProductName",
                    "ClientStreet", "ClientCity", "ClientState", "ClientZip"]],
        on=["ClientName", "ProductName"],
        how="left",
    )

    n_out = len(df)
    if n_out != n_in:
        raise RuntimeError(
            f"La jointure a modifié le nombre de lignes : {n_in:,} → {n_out:,}.\n"
            "Vérifier que moodle_02 est bien dédoublonné sur ClientName+ProductName."
        )

    # Rapport sur la couverture des jointures (avant remplacement des null)
    null_supplier = df["SupplierName"].isna().sum()
    null_address  = df["ClientStreet"].isna().sum()
    print(f"  Lignes sans SupplierName (SupplierID absent de moodle_03) : {null_supplier:,}")
    print(f"  Lignes sans adresse (ClientName+ProductName absent de moodle_02) : {null_address:,}")

    # Remplacement global : tous les null restants → "unknown"
    df = df.fillna("unknown")

    return df[OBT_COLUMNS]

# ─── Export ───────────────────────────────────────────────────────────────────

def export(df: pd.DataFrame, fmt: str) -> Path:
    """
    Exporte le DataFrame dans le format demandé.
      csv  → data_clean/curated_orders.csv
      json → data_clean/curated_orders.json  (NDJSON, 1 document par ligne)
             Format natif pour mongoimport --type json
    """
    DATA_CLEAN_DIR.mkdir(exist_ok=True)

    if fmt == "json":
        output = DATA_CLEAN_DIR / "curated_orders.json"
        df.to_json(output, orient="records", lines=True,
                   force_ascii=False, default_handler=str)
    else:
        output = DATA_CLEAN_DIR / "curated_orders.csv"
        df.to_csv(output, index=False, encoding="utf-8")

    return output

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Job 2 — Curated OBT")
    parser.add_argument(
        "--format", choices=["csv", "json"], default="csv",
        help="Format de sortie : csv (défaut) ou json (NDJSON pour mongoimport)"
    )
    args = parser.parse_args()

    files = find_files()

    if not files["orders"]:
        print("Aucun fichier orders trouvé dans data_raw/")
        return

    print("\n[moodle_01 — Orders]")
    df_orders = load_orders(files["orders"])
    print(f"  Total lignes : {len(df_orders):,}")

    print("\n[moodle_02 — Clients]")
    df_clients = load_clients(files["clients"])
    print(f"  Total lignes après dédup : {len(df_clients):,}")

    print("\n[moodle_03 — Suppliers]")
    df_suppliers = load_suppliers(files["suppliers"])
    print(f"  Total lignes : {len(df_suppliers):,}")

    print("\n[Jointures OBT]")
    df_obt = build_obt(df_orders, df_clients, df_suppliers)

    output = export(df_obt, args.format)

    print(f"\n{'─' * 55}")
    print(f"Format    : {args.format.upper()}")
    print(f"Curated   : {output}")
    print(f"Lignes    : {len(df_obt):,}")
    print(f"Colonnes  : {', '.join(OBT_COLUMNS)}")


if __name__ == "__main__":
    main()
