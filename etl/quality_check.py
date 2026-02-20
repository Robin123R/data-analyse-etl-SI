"""
quality_check.py — Job 1 : détection des anomalies dans les données raw.

Ce script lit tous les fichiers CSV de data_raw/, applique les business rules
de chaque dataset et génère un rapport des lignes invalides dans data_clean/.

Il ne modifie aucune donnée source.
"""

import pandas as pd
from pathlib import Path

# ─── Chemins ──────────────────────────────────────────────────────────────────

PROJECT_ROOT  = Path(__file__).parent.parent
DATA_RAW_DIR  = PROJECT_ROOT / "data_raw"
DATA_CLEAN_DIR = PROJECT_ROOT / "data_clean"
OUTPUT_FILE   = DATA_CLEAN_DIR / "quality_report.csv"

# ─── Constantes ───────────────────────────────────────────────────────────────

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

ORDERS_COLUMNS    = {"OrderID", "OrderDate", "SupplierID", "OrderAmount",
                     "PaymentDate", "CustomerSatisfaction", "ClientName", "ProductName"}
SUPPLIERS_COLUMNS = {"SupplierID", "SupplierName"}
CLIENTS_COLUMNS   = ["ClientName", "ClientAddress", "ProductName"]

EMPTY_REPORT = pd.DataFrame(
    columns=["source_file", "line_number", "raw_data", "field", "error"]
)

# ─── Détection et chargement ──────────────────────────────────────────────────

def detect_file_type(filepath: Path) -> str:
    """Détecte le type de dataset en lisant les colonnes du header."""
    try:
        cols = set(pd.read_csv(filepath, nrows=0).columns)
        if cols == ORDERS_COLUMNS:
            return "orders"
        if cols == SUPPLIERS_COLUMNS:
            return "suppliers"
    except Exception:
        pass
    return "clients"


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


def load_file(filepath: Path, file_type: str) -> pd.DataFrame:
    """
    Charge le CSV en string brut et ajoute deux colonnes internes :
      _line : numéro de ligne dans le fichier source (commence à 1)
      _raw  : contenu brut de la ligne (pour le rapport)

    Note : suppose que les champs multi-lignes (newline dans un champ quoté)
    sont absents du dataset. Si présents, l'alignement _raw/_line serait faux.
    """
    raw_lines = filepath.read_text(encoding="utf-8").splitlines()

    if file_type == "clients":
        # Pas de header — assignation manuelle des noms de colonnes
        df = pd.read_csv(filepath, header=None, names=CLIENTS_COLUMNS, dtype=str)
        df["_line"] = range(1, len(df) + 1)
        df["_raw"]  = raw_lines[: len(df)]
    elif file_type == "suppliers":
        # Lecteur robuste : split sur la première virgule (voir _read_suppliers_csv)
        df = _read_suppliers_csv(filepath)
        df["_line"] = range(2, len(df) + 2)
        df["_raw"]  = raw_lines[1 : len(df) + 1]
    else:
        df = pd.read_csv(filepath, dtype=str)
        df["_line"] = range(2, len(df) + 2)          # +2 : index 0-based + header
        df["_raw"]  = raw_lines[1 : len(df) + 1]    # skip header line

    return df

# ─── Helper rapport ───────────────────────────────────────────────────────────

def make_errors(df: pd.DataFrame, mask: pd.Series,
                filename: str, field: str, reason) -> pd.DataFrame:
    """
    Construit un DataFrame d'erreurs standardisé pour les lignes où mask=True.

    reason : str (message constant) ou pd.Series (message par ligne, même index que df)
    """
    subset = df.loc[mask, ["_line", "_raw"]].copy()
    subset["source_file"] = filename
    subset["field"]        = field
    subset["error"]        = reason[mask].values if isinstance(reason, pd.Series) else reason

    return (
        subset
        .rename(columns={"_line": "line_number", "_raw": "raw_data"})
        [["source_file", "line_number", "raw_data", "field", "error"]]
    )

# ─── Validateurs ──────────────────────────────────────────────────────────────

def _check_orderid(df: pd.DataFrame, filename: str) -> list:
    """
    Vérifie OrderID avec trois cas distincts :
      1. Vide/null  → tente l'inférence par lignes adjacentes
      2. Format invalide (non vide, mauvais format)
      3. Duplicat   (sur les IDs au bon format uniquement)
    """
    errors = []
    ids      = df["OrderID"].fillna("")
    is_empty = df["OrderID"].isna() | ids.str.strip().eq("")
    is_valid = ids.str.match(r"^O\d{7}$")

    # ── Cas 1 : vide ──
    if is_empty.any():
        # Extraire les numéros des IDs valides (ex. "O0209975" → 209975.0, sinon NaN)
        valid_nums = pd.to_numeric(
            ids.where(is_valid).str[1:], errors="coerce"
        )
        prev_nums = valid_nums.ffill()   # dernier ID valide précédent
        next_nums = valid_nums.bfill()   # premier ID valide suivant

        # Inférable ssi écart = 2 et les deux voisins existent
        inferable = (
            is_empty
            & prev_nums.notna()
            & next_nums.notna()
            & ((next_nums - prev_nums) == 2)
        )
        not_inferable = is_empty & ~inferable

        if inferable.any():
            # Reconstruire l'ID inféré : O + numéro zfill 7
            inferred = "O" + (prev_nums.fillna(0) + 1).astype(int).astype(str).str.zfill(7)
            errors.append(make_errors(df, inferable, filename, "OrderID",
                "Vide — inférable, valeur curated: '" + inferred + "'"))

        if not_inferable.any():
            errors.append(make_errors(df, not_inferable, filename, "OrderID",
                "Vide — non inférable, sera null au niveau curated"))

    # ── Cas 2 : format invalide (non vide) ──
    # Même traitement que les vides au curated : inférence par lignes adjacentes.
    invalid_fmt = ~is_empty & ~is_valid
    if invalid_fmt.any():
        errors.append(make_errors(df, invalid_fmt, filename, "OrderID",
            "Format invalide (attendu: O + 7 chiffres), valeur: '" + ids + "'"
            " — inférence par lignes adjacentes tentée au curated, sinon null"))

    # ── Cas 3 : duplicats ──
    dup_mask = df["OrderID"].duplicated(keep=False) & is_valid
    if dup_mask.any():
        errors.append(make_errors(df, dup_mask, filename, "OrderID",
            "OrderID dupliqué: '" + ids + "'"))

    return errors


def check_orders(df: pd.DataFrame, filename: str) -> pd.DataFrame:
    errors = []

    # OrderID — logique complète (vide / format invalide / duplicat)
    errors.extend(_check_orderid(df, filename))

    # OrderDate — distinguer vide (→ null curated) de format invalide
    order_dates     = pd.to_datetime(df["OrderDate"], format=DATETIME_FORMAT, errors="coerce")
    is_empty_odate  = df["OrderDate"].isna() | df["OrderDate"].str.strip().eq("")
    is_invalid_odate = ~is_empty_odate & order_dates.isna()

    if is_empty_odate.any():
        errors.append(make_errors(df, is_empty_odate, filename, "OrderDate",
            "Vide — sera remplacée par PaymentDate au niveau curated"))
    if is_invalid_odate.any():
        errors.append(make_errors(df, is_invalid_odate, filename, "OrderDate",
            "Format invalide (attendu: YYYY-MM-DD HH:MM:SS), valeur: '" + df["OrderDate"].fillna("") + "'"))

    # OrderDate — année < 2010 (aberrante) → sera remplacée par PaymentDate au curated
    is_old_odate = ~is_empty_odate & ~is_invalid_odate & (order_dates.dt.year < 2010)
    if is_old_odate.any():
        errors.append(make_errors(df, is_old_odate, filename, "OrderDate",
            "Année antérieure à 2010 — sera remplacée par PaymentDate au niveau curated, "
            "valeur: '" + df["OrderDate"].fillna("") + "'"))

    # SupplierID — format : 1 lettre majuscule + 3 chiffres
    mask = ~df["SupplierID"].str.match(r"^[A-Z]\d{3}$", na=False)
    if mask.any():
        errors.append(make_errors(df, mask, filename, "SupplierID",
            "Format invalide (attendu: lettre majuscule + 3 chiffres), valeur: '" + df["SupplierID"].fillna("") + "'"))

    # OrderAmount — float valide
    mask = pd.to_numeric(df["OrderAmount"], errors="coerce").isna()
    if mask.any():
        errors.append(make_errors(df, mask, filename, "OrderAmount",
            "Float invalide, valeur: '" + df["OrderAmount"].fillna("") + "'"))

    # PaymentDate — format datetime
    mask = pd.to_datetime(df["PaymentDate"], format=DATETIME_FORMAT, errors="coerce").isna()
    if mask.any():
        errors.append(make_errors(df, mask, filename, "PaymentDate",
            "Format invalide (attendu: YYYY-MM-DD HH:MM:SS), valeur: '" + df["PaymentDate"].fillna("") + "'"))

    # CustomerSatisfaction — entier valide (pas de décimale)
    mask = ~df["CustomerSatisfaction"].str.strip().str.match(r"^-?\d+$", na=False)
    if mask.any():
        errors.append(make_errors(df, mask, filename, "CustomerSatisfaction",
            "Entier invalide, valeur: '" + df["CustomerSatisfaction"].fillna("") + "'"))

    # ClientName — vide → sera null au curated
    mask = df["ClientName"].isna() | df["ClientName"].str.strip().eq("")
    if mask.any():
        errors.append(make_errors(df, mask, filename, "ClientName",
            "Vide — sera null au niveau curated"))

    # ProductName — vide → sera null au curated
    mask = df["ProductName"].isna() | df["ProductName"].str.strip().eq("")
    if mask.any():
        errors.append(make_errors(df, mask, filename, "ProductName",
            "Vide — sera null au niveau curated"))

    # Cross-field OrderDate <= PaymentDate : IGNORÉ (décision métier)
    # Cas identifié mais non actionnable. Voir BUSINESS_RULES.md "Anomalies ignorées".

    return pd.concat(errors, ignore_index=True) if errors else EMPTY_REPORT.copy()


def check_clients(df: pd.DataFrame, filename: str) -> pd.DataFrame:
    errors = []

    # ClientName — non vide
    mask = df["ClientName"].isna() | df["ClientName"].str.strip().eq("")
    if mask.any():
        errors.append(make_errors(df, mask, filename, "ClientName", "Valeur vide ou null"))

    # ClientAddress — décomposable en "Street, City, State ZIP"
    #   Règles : au moins 2 virgules, et la dernière partie contient au moins 2 tokens
    addr          = df["ClientAddress"].fillna("")
    has_commas    = addr.str.count(",") >= 2
    last_part     = addr.str.rsplit(",", n=1).str[-1].str.strip()
    has_state_zip = last_part.str.split().str.len() >= 2
    mask = df["ClientAddress"].isna() | ~(has_commas & has_state_zip)
    if mask.any():
        errors.append(make_errors(df, mask, filename, "ClientAddress",
            "Adresse non décomposable en (Street, City, State ZIP), valeur: '" + addr + "'"))

    # ProductName — non vide
    mask = df["ProductName"].isna() | df["ProductName"].str.strip().eq("")
    if mask.any():
        errors.append(make_errors(df, mask, filename, "ProductName", "Valeur vide ou null"))

    # ClientName + ProductName — doublons (informatif, non bloquant)
    # La clé de jointure vers moodle_01 est ClientName + ProductName.
    # Les doublons sont dédoublonnés au curated (première occurrence conservée).
    dup_key  = df["ClientName"].fillna("") + "|||" + df["ProductName"].fillna("")
    dup_mask = dup_key.duplicated(keep="first")   # première occurrence non flaggée
    if dup_mask.any():
        errors.append(make_errors(df, dup_mask, filename, "ClientName+ProductName",
            "INFO — Dupliqué sur clé de jointure (ClientName+ProductName), "
            "sera dédoublonné au curated (première occurrence conservée)"))

    return pd.concat(errors, ignore_index=True) if errors else EMPTY_REPORT.copy()


def check_suppliers(df: pd.DataFrame, filename: str) -> pd.DataFrame:
    errors = []

    # SupplierID — format : 1 lettre majuscule + 3 chiffres
    mask = ~df["SupplierID"].str.match(r"^[A-Z]\d{3}$", na=False)
    if mask.any():
        errors.append(make_errors(df, mask, filename, "SupplierID",
            "Format invalide (attendu: lettre majuscule + 3 chiffres), valeur: '" + df["SupplierID"].fillna("") + "'"))

    # SupplierID — unicité (table de référence, pas de doublons attendus)
    dup_mask = df["SupplierID"].duplicated(keep=False)
    if dup_mask.any():
        errors.append(make_errors(df, dup_mask, filename, "SupplierID",
            "SupplierID dupliqué: '" + df["SupplierID"].fillna("") + "'"))

    # SupplierName — non vide
    mask = df["SupplierName"].isna() | df["SupplierName"].str.strip().eq("")
    if mask.any():
        errors.append(make_errors(df, mask, filename, "SupplierName", "Valeur vide ou null"))

    return pd.concat(errors, ignore_index=True) if errors else EMPTY_REPORT.copy()


# ─── Dispatch ─────────────────────────────────────────────────────────────────

VALIDATORS = {
    "orders":    check_orders,
    "clients":   check_clients,
    "suppliers": check_suppliers,
}

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    DATA_CLEAN_DIR.mkdir(exist_ok=True)

    csv_files = sorted(DATA_RAW_DIR.glob("*.csv"))
    if not csv_files:
        print("Aucun fichier CSV trouvé dans data_raw/")
        return

    all_errors = []

    for filepath in csv_files:
        print(f"\n[{filepath.name}]")

        file_type = detect_file_type(filepath)
        print(f"  Type    : {file_type}")

        df = load_file(filepath, file_type)
        print(f"  Lignes  : {len(df):,}")

        report = VALIDATORS[file_type](df, filepath.name)
        print(f"  Erreurs : {len(report):,}")

        if not report.empty:
            all_errors.append(report)

    # Assemblage du rapport final
    final = (
        pd.concat(all_errors, ignore_index=True)
        .sort_values(["source_file", "line_number"])
        if all_errors
        else EMPTY_REPORT.copy()
    )

    final.to_csv(OUTPUT_FILE, index=False, encoding="utf-8")

    # Résumé console
    print(f"\n{'─' * 55}")
    print(f"Rapport   : {OUTPUT_FILE}")
    print(f"Total     : {len(final):,} anomalie(s)\n")

    if not final.empty:
        print("Détail par fichier et champ :")
        for source_file, grp_file in final.groupby("source_file"):
            print(f"\n  {source_file} — {len(grp_file):,} anomalie(s)")
            for field, grp_field in grp_file.groupby("field"):
                print(f"    {field:<30} {len(grp_field):,}")


if __name__ == "__main__":
    main()
