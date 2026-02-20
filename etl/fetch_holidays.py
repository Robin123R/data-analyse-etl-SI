"""
fetch_holidays.py — Télécharge des données calendaires depuis deux sources
et les sauvegarde dans data_raw/.

Sources disponibles :
  nager       → jours fériés par pays (nager.at)
  jiejiariapi → week-ends et jours ajustés CN (api.jiejiariapi.com)
  all         → les deux (défaut)

Usage :
  python etl/fetch_holidays.py                               # all, années 2022 2023, pays US
  python etl/fetch_holidays.py --source nager --years 2022 2023 2024
  python etl/fetch_holidays.py --source nager --country FR --years 2022 2023
  python etl/fetch_holidays.py --source jiejiariapi --years 2022 2023
  python etl/fetch_holidays.py --source all --years 2022 2023

Outputs :
  nager       → data_raw/{country}_public_holidays_{year}.json
  jiejiariapi → data_raw/cn_weekends_{year}.json
"""

import argparse
import json
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data_raw"

NAGER_URL       = "https://date.nager.at/api/v3/publicholidays/{year}/{country}"
JIEJIARIAPI_URL = "https://api.jiejiariapi.com/v1/weekends/{year}"


# ─── nager.at ─────────────────────────────────────────────────────────────────

def fetch_nager(year: int, country: str) -> list:
    url = NAGER_URL.format(year=year, country=country)
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


def save_nager(data: list, year: int, country: str) -> Path:
    filename = f"{country.lower()}_public_holidays_{year}.json"
    out = DATA_RAW_DIR / filename
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return out


def run_nager(years: list, country: str) -> None:
    print(f"\n[nager.at — {country}]")
    for year in years:
        print(f"  {country} {year}...", end=" ", flush=True)
        try:
            data = fetch_nager(year, country)
            out  = save_nager(data, year, country)
            print(f"{len(data)} entrées → {out.name}")
        except Exception as e:
            print(f"ERREUR : {e}")


# ─── jiejiariapi.com ──────────────────────────────────────────────────────────

def fetch_jiejiariapi(year: int) -> list:
    """
    Retourne la liste des entrées calendaires CN pour l'année donnée.
    L'API renvoie un objet JSON dont les clés sont des dates (YYYY-MM-DD) ;
    on convertit en liste de valeurs pour cohérence avec le format nager.at.

    Chaque entrée :
      {
        "date":     "2022-01-01",
        "name":     "周六",       ← jour de la semaine en chinois
        "isOffDay": false         ← false = jour travaillé malgré le week-end
      }

    Un User-Agent navigateur est nécessaire : l'API bloque Python-urllib/3.x (403).
    """
    url = JIEJIARIAPI_URL.format(year=year)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req) as response:
        raw = json.loads(response.read())
    return list(raw.values())


def save_jiejiariapi(data: list, year: int) -> Path:
    filename = f"cn_weekends_{year}.json"
    out = DATA_RAW_DIR / filename
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return out


def run_jiejiariapi(years: list) -> None:
    print("\n[jiejiariapi.com — CN weekends]")
    for year in years:
        print(f"  CN {year}...", end=" ", flush=True)
        try:
            data = fetch_jiejiariapi(year)
            out  = save_jiejiariapi(data, year)
            print(f"{len(data)} entrées → {out.name}")
        except Exception as e:
            print(f"ERREUR : {e}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch calendrier data (nager.at et/ou jiejiariapi.com)"
    )
    parser.add_argument(
        "--years", nargs="+", type=int, default=[2022, 2023],
        help="Années à télécharger (défaut : 2022 2023)"
    )
    parser.add_argument(
        "--country", default="US",
        help="Code pays ISO 3166-1 alpha-2, utilisé par nager.at uniquement (défaut : US)"
    )
    parser.add_argument(
        "--source", choices=["nager", "jiejiariapi", "all"], default="all",
        help="Source à utiliser : nager, jiejiariapi, all (défaut : all)"
    )
    args = parser.parse_args()

    DATA_RAW_DIR.mkdir(exist_ok=True)

    if args.source in ("nager", "all"):
        run_nager(args.years, args.country)

    if args.source in ("jiejiariapi", "all"):
        run_jiejiariapi(args.years)


if __name__ == "__main__":
    main()
