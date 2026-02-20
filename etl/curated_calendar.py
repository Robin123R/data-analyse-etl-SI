"""
curated_calendar.py — Job 3 : calendrier curated 2022–2023

Produit une ligne par date couvrant toutes les dates de chaque année demandée :

  date         : YYYY-MM-DD
  isWeekend    : True si samedi ou dimanche
  isUSHoliday  : True si jour férié US national de type Public (source : nager.at,
                 global=true uniquement — exclut les fêtes d'états spécifiques)

Sources lues depuis data_raw/ :
  us_public_holidays_{year}.json   (produit par fetch_holidays.py --source nager)

Output :
  data_clean/curated_calendar.csv
"""

import json
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT   = Path(__file__).parent.parent
DATA_RAW_DIR   = PROJECT_ROOT / "data_raw"
DATA_CLEAN_DIR = PROJECT_ROOT / "data_clean"


# ─── Chargement des jours fériés US ───────────────────────────────────────────

def load_us_holidays(years: list) -> set:
    """
    Retourne l'ensemble des dates (str YYYY-MM-DD) qui sont des jours fériés
    US nationaux (global=true, type Public) d'après les fichiers nager.at.
    """
    holidays = set()
    for year in years:
        fp = DATA_RAW_DIR / f"us_public_holidays_{year}.json"
        if not fp.exists():
            print(f"  AVERTISSEMENT : {fp.name} introuvable — année {year} ignorée")
            continue
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
        before = len(holidays)
        for entry in data:
            if entry.get("global") is True and "Public" in entry.get("types", []):
                holidays.add(entry["date"])
        print(f"  {fp.name} : {len(holidays) - before} jours fériés US chargés")
    return holidays


# ─── Construction du calendrier ───────────────────────────────────────────────

def build_calendar(years: list, us_holidays: set) -> pd.DataFrame:
    """
    Génère une ligne pour chaque jour de chaque année.
    isWeekend    : weekday() >= 5  (5 = samedi, 6 = dimanche)
    isUSHoliday  : date dans l'ensemble us_holidays
    """
    rows = []
    for year in years:
        d   = date(year, 1, 1)
        end = date(year, 12, 31)
        while d <= end:
            iso = d.isoformat()
            rows.append({
                "date":        iso,
                "isWeekend":   d.weekday() >= 5,
                "isUSHoliday": iso in us_holidays,
            })
            d += timedelta(days=1)
    return pd.DataFrame(rows)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Job 3 — Calendrier curated")
    parser.add_argument(
        "--years", nargs="+", type=int, default=[2022, 2023],
        help="Années à inclure (défaut : 2022 2023)"
    )
    parser.add_argument(
        "--format", choices=["csv", "json"], default="csv",
        help="Format de sortie : csv (défaut) ou json (NDJSON pour mongoimport)"
    )
    args = parser.parse_args()

    DATA_CLEAN_DIR.mkdir(exist_ok=True)

    print("[Chargement des jours fériés US]")
    us_holidays = load_us_holidays(args.years)
    print(f"  Total : {len(us_holidays)} dates uniques")

    print("\n[Construction du calendrier]")
    df = build_calendar(args.years, us_holidays)

    n_weekend   = df["isWeekend"].sum()
    n_holiday   = df["isUSHoliday"].sum()
    n_both      = (df["isWeekend"] & df["isUSHoliday"]).sum()
    print(f"  Lignes        : {len(df):,}")
    print(f"  Week-ends     : {n_weekend:,}")
    print(f"  Jours fériés  : {n_holiday:,}  (dont {n_both} tombant un week-end)")

    if args.format == "json":
        output = DATA_CLEAN_DIR / "curated_calendar.json"
        df.to_json(output, orient="records", lines=True,
                   force_ascii=False, default_handler=str)
    else:
        output = DATA_CLEAN_DIR / "curated_calendar.csv"
        df.to_csv(output, index=False, encoding="utf-8")

    print(f"\n{'─' * 55}")
    print(f"Format    : {args.format.upper()}")
    print(f"Curated   : {output}")
    print(f"Lignes    : {len(df):,}")
    print(f"Colonnes  : {', '.join(df.columns)}")


if __name__ == "__main__":
    main()
