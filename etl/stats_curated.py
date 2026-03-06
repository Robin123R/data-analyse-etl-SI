"""
stats_curated.py — Statistiques descriptives sur les données curées (OBT).

Lit data_clean/curated_orders.json (NDJSON produit par curated.py) et
écrit le rapport dans data_clean/stats_curated_report.txt.
"""

import pandas as pd
from pathlib import Path
from io import StringIO

PROJECT_ROOT   = Path(__file__).parent.parent
DATA_CLEAN_DIR = PROJECT_ROOT / "data_clean"
INPUT_FILE     = DATA_CLEAN_DIR / "curated_orders.json"
OUTPUT_FILE    = DATA_CLEAN_DIR / "stats_curated_report.txt"

# ─── Helpers ──────────────────────────────────────────────────────────────────

def sep(char="─", width=72):
    return char * width

def h1(title):
    bar = "=" * 72
    return f"\n{bar}\n  {title}\n{bar}\n"

def h2(title):
    return f"\n── {title}\n{sep()}\n"

def pct(n, total):
    return f"{n:>12,}  ({n / total * 100:5.1f} %)"

def fmt(v, decimals=2):
    if pd.isna(v):
        return "N/A"
    return f"{v:,.{decimals}f}" if decimals else f"{int(v):,}"

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not INPUT_FILE.exists():
        print(f"Fichier introuvable : {INPUT_FILE}")
        print("Lance d'abord : python etl/curated.py --format json")
        return

    print(f"Lecture : {INPUT_FILE}")
    df = pd.read_json(INPUT_FILE, lines=True, dtype=str)

    df["OrderAmount"]          = pd.to_numeric(df["OrderAmount"], errors="coerce")
    df["CustomerSatisfaction"] = pd.to_numeric(df["CustomerSatisfaction"], errors="coerce")
    df["OrderDate"]            = pd.to_datetime(df["OrderDate"],  errors="coerce")
    df["PaymentDate"]          = pd.to_datetime(df["PaymentDate"], errors="coerce")
    df["delay_days"]           = (df["PaymentDate"] - df["OrderDate"]).dt.days

    total = len(df)
    out   = StringIO()
    w     = lambda s="": print(s, file=out)

    # ── En-tête ──────────────────────────────────────────────────────────────
    w("=" * 72)
    w("  STATISTIQUES DESCRIPTIVES — DONNÉES CURÉES (OBT)")
    w(f"  Source : {INPUT_FILE.name}")
    w("=" * 72)

    # ═══════════════════════════════════════════════════════════════════════
    # STRUCTURE GÉNÉRALE
    # ═══════════════════════════════════════════════════════════════════════
    w(h1("STRUCTURE GÉNÉRALE"))

    w(h2("Dimensions"))
    w(f"  Lignes totales          : {total:>12,}")
    w(f"  Colonnes                : {len(df.columns):>12,}")
    w(f"  Colonnes : {', '.join(df.columns)}")

    w(h2("Valeurs 'unknown'  (champs non résolus après curated)"))
    for col in df.columns:
        n_unk = (df[col] == "unknown").sum()
        if n_unk > 0:
            w(f"  {col:<28}: {pct(n_unk, total)}")

    od_valid = df["OrderDate"].dropna()
    pmt_valid = df["PaymentDate"].dropna()
    w(h2("Période couverte"))
    w(f"  OrderDate min / max     :  {od_valid.min().date()}  →  {od_valid.max().date()}")
    w(f"  PaymentDate min / max   :  {pmt_valid.min().date()}  →  {pmt_valid.max().date()}")

    # ═══════════════════════════════════════════════════════════════════════
    # ORDER AMOUNT
    # ═══════════════════════════════════════════════════════════════════════
    w(h1("ORDER AMOUNT"))

    amt = df["OrderAmount"].dropna()
    w(h2("Statistiques"))
    w(f"  Nombre de valeurs       : {len(amt):>12,}")
    w(f"  Minimum                 : {fmt(amt.min()):>15}")
    w(f"  Maximum                 : {fmt(amt.max()):>15}")
    w(f"  Moyenne                 : {fmt(amt.mean()):>15}")
    w(f"  Écart-type              : {fmt(amt.std()):>15}")
    w(f"  1er quartile  (Q1/P25)  : {fmt(amt.quantile(0.25)):>15}")
    w(f"  Médiane       (Q2/P50)  : {fmt(amt.quantile(0.50)):>15}")
    w(f"  3e  quartile  (Q3/P75)  : {fmt(amt.quantile(0.75)):>15}")
    w(f"  90e percentile (P90)    : {fmt(amt.quantile(0.90)):>15}")
    w(f"  95e percentile (P95)    : {fmt(amt.quantile(0.95)):>15}")
    w(f"  IQR (Q3 − Q1)           : {fmt(amt.quantile(0.75) - amt.quantile(0.25)):>15}")

    # ═══════════════════════════════════════════════════════════════════════
    # CUSTOMER SATISFACTION
    # ═══════════════════════════════════════════════════════════════════════
    w(h1("CUSTOMER SATISFACTION  (scores 1–5)"))

    csat = df["CustomerSatisfaction"].dropna()
    w(h2("Statistiques"))
    w(f"  Nombre de valeurs       : {len(csat):>12,}")
    w(f"  Moyenne                 : {fmt(csat.mean()):>15}")
    w(f"  Écart-type              : {fmt(csat.std()):>15}")
    w(f"  Médiane                 : {fmt(csat.median(), 0):>15}")

    w(h2("Distribution"))
    for score in sorted(csat.dropna().unique()):
        n   = int((csat == score).sum())
        bar = "█" * int(n / total * 200)
        w(f"  Score {int(score)}  →  {pct(n, total)}   {bar}")

    # ═══════════════════════════════════════════════════════════════════════
    # DÉLAI DE PAIEMENT
    # ═══════════════════════════════════════════════════════════════════════
    w(h1("DÉLAI DE PAIEMENT  (PaymentDate − OrderDate, en jours)"))

    delay = df["delay_days"].dropna()
    w(h2("Statistiques"))
    w(f"  Nombre de valeurs       : {len(delay):>12,}")
    w(f"  Minimum                 : {fmt(delay.min(), 0):>15}")
    w(f"  Maximum                 : {fmt(delay.max(), 0):>15}")
    w(f"  Moyenne                 : {fmt(delay.mean()):>15}")
    w(f"  Écart-type              : {fmt(delay.std()):>15}")
    w(f"  1er quartile  (Q1)      : {fmt(delay.quantile(0.25), 0):>15}")
    w(f"  Médiane       (Q2)      : {fmt(delay.median(), 0):>15}")
    w(f"  3e  quartile  (Q3)      : {fmt(delay.quantile(0.75), 0):>15}")
    n_neg = int((delay < 0).sum())
    w(f"  Délais négatifs         : {n_neg:>12,}  (anomalies résiduelles)")

    # ═══════════════════════════════════════════════════════════════════════
    # RÉPARTITION TEMPORELLE
    # ═══════════════════════════════════════════════════════════════════════
    w(h1("RÉPARTITION TEMPORELLE"))

    w(h2("Commandes par année"))
    for yr, n in df["OrderDate"].dt.year.value_counts().sort_index().items():
        w(f"  {int(yr)}  →  {pct(n, total)}")

    w(h2("Commandes par mois  (toutes années confondues)"))
    month_names = {1:"Janvier",2:"Février",3:"Mars",4:"Avril",5:"Mai",6:"Juin",
                   7:"Juillet",8:"Août",9:"Septembre",10:"Octobre",11:"Novembre",12:"Décembre"}
    for m, n in df["OrderDate"].dt.month.value_counts().sort_index().items():
        w(f"  {month_names[int(m)]:<12}  →  {pct(n, total)}")

    # ═══════════════════════════════════════════════════════════════════════
    # FOURNISSEURS
    # ═══════════════════════════════════════════════════════════════════════
    w(h1("FOURNISSEURS"))

    w(h2("Cardinalité"))
    valid_sup = df[df["SupplierName"] != "unknown"]
    w(f"  SupplierID distincts    : {df['SupplierID'].nunique():>12,}")
    w(f"  SupplierName distincts  : {df['SupplierName'].nunique():>12,}")
    w(f"  Commandes avec fournisseur résolu   : {pct(len(valid_sup), total)}")
    w(f"  Commandes avec fournisseur inconnu  : {pct(total - len(valid_sup), total)}")

    w(h2("Top 10 fournisseurs  (par nombre de commandes)"))
    for rank, (name, n) in enumerate(df["SupplierName"].value_counts().head(10).items(), 1):
        w(f"  {rank:>2}. {name:<40}  →  {pct(n, total)}")

    # ═══════════════════════════════════════════════════════════════════════
    # PRODUITS & CLIENTS
    # ═══════════════════════════════════════════════════════════════════════
    w(h1("PRODUITS & CLIENTS"))

    w(h2("Cardinalité"))
    w(f"  Produits distincts      : {df['ProductName'].nunique():>12,}")
    w(f"  Clients distincts       : {df['ClientName'].nunique():>12,}")

    w(h2("Top 10 produits  (par nombre de commandes)"))
    for rank, (prod, n) in enumerate(df["ProductName"].value_counts().head(10).items(), 1):
        w(f"  {rank:>2}. {prod:<35}  →  {pct(n, total)}")

    w(h2("Top 10 clients  (par nombre de commandes)"))
    for rank, (client, n) in enumerate(df["ClientName"].value_counts().head(10).items(), 1):
        w(f"  {rank:>2}. {client:<35}  →  {n:,} commandes")

    # ═══════════════════════════════════════════════════════════════════════
    # GÉOGRAPHIE CLIENT
    # ═══════════════════════════════════════════════════════════════════════
    w(h1("GÉOGRAPHIE CLIENT"))

    valid_geo = df[df["ClientState"] != "unknown"]
    w(h2("Couverture"))
    w(f"  Commandes avec adresse résolue  : {pct(len(valid_geo), total)}")
    w(f"  Commandes sans adresse (unknown): {pct(total - len(valid_geo), total)}")
    w(f"  États distincts                 : {valid_geo['ClientState'].nunique():>12,}")
    w(f"  Villes distinctes               : {valid_geo['ClientCity'].nunique():>12,}")

    w(h2("Top 10 états  (par nombre de commandes)"))
    state_counts = valid_geo["ClientState"].value_counts()
    for rank, (state, n) in enumerate(state_counts.head(10).items(), 1):
        w(f"  {rank:>2}. {state:<6}  →  {pct(n, total)}")
    w(f"\n  État le moins fréquent  : {state_counts.index[-1]}  →  {state_counts.iloc[-1]:,} commandes")

    w(h2("Top 10 villes  (par nombre de commandes)"))
    for rank, (city, n) in enumerate(valid_geo["ClientCity"].value_counts().head(10).items(), 1):
        w(f"  {rank:>2}. {city:<35}  →  {n:,} commandes")

    # ── Pied de page ─────────────────────────────────────────────────────
    w("\n" + "=" * 72 + "\n")

    # ── Export ───────────────────────────────────────────────────────────
    DATA_CLEAN_DIR.mkdir(exist_ok=True)
    OUTPUT_FILE.write_text(out.getvalue(), encoding="utf-8")
    print(f"Rapport écrit : {OUTPUT_FILE}")
    print(f"Lignes        : {len(out.getvalue().splitlines())}")


if __name__ == "__main__":
    main()
