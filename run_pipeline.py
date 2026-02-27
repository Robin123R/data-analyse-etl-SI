"""
run_pipeline.py — Orchestrateur du pipeline ETL complet

Exécute les étapes dans l'ordre :
  1. fetch_holidays.py    — téléchargement des jours fériés (nager.at + jiejiariapi)
  2. curated.py --format json    — OBT orders au format NDJSON
  3. curated_calendar.py --format json  — calendrier curated au format NDJSON
  4. Docker Compose       — MongoDB + import automatique des deux collections
  5. analyse.py           — statistiques descriptives + 4 graphiques PNG

Usage :
  python run_pipeline.py                  # pipeline complet
  python run_pipeline.py --skip-fetch     # sauter l'étape 1 (données déjà présentes)
  python run_pipeline.py --no-docker      # sauter l'étape 4 (MongoDB/Docker)
  python run_pipeline.py --skip-analyse   # sauter l'étape 5 (analyse / graphiques)
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
ETL_DIR      = PROJECT_ROOT / "etl"


def run(label: str, cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    print(f"\n{'═' * 60}")
    print(f"  {label}")
    print(f"{'═' * 60}")
    result = subprocess.run(cmd, check=check)
    if result.returncode != 0 and not check:
        print(f"  [AVERTISSEMENT] {label} s'est terminé avec le code {result.returncode}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Pipeline ETL complet")
    parser.add_argument(
        "--skip-fetch", action="store_true",
        help="Sauter l'étape 1 (fetch_holidays) — données déjà présentes dans data_raw/"
    )
    parser.add_argument(
        "--no-docker", action="store_true",
        help="Sauter l'étape 4 (Docker / MongoDB)"
    )
    parser.add_argument(
        "--skip-analyse", action="store_true",
        help="Sauter l'étape 5 (analyse statistique et graphiques)"
    )
    args = parser.parse_args()

    py = sys.executable

    # ── Dépendances Python ────────────────────────────────────────────────────
    req = PROJECT_ROOT / "requirements.txt"
    if req.exists():
        run(
            "Dépendances — pip install -r requirements.txt",
            [py, "-m", "pip", "install", "-r", str(req), "--quiet"]
        )

    # ── Étape 1 : Fetch holidays ──────────────────────────────────────────────
    if not args.skip_fetch:
        run(
            "Étape 1/5 — Téléchargement des données calendaires",
            [py, str(ETL_DIR / "fetch_holidays.py")]
        )
    else:
        print("\n[Étape 1/5 ignorée — --skip-fetch]")

    # ── Étape 2 : Curated orders (JSON) ───────────────────────────────────────
    run(
        "Étape 2/5 — Curated orders → data_clean/curated_orders.json",
        [py, str(ETL_DIR / "curated.py"), "--format", "json"]
    )

    # ── Étape 3 : Curated calendar (JSON) ─────────────────────────────────────
    run(
        "Étape 3/5 — Curated calendrier → data_clean/curated_calendar.json",
        [py, str(ETL_DIR / "curated_calendar.py"), "--format", "json"]
    )

    # ── Étape 4 : Docker — MongoDB + import ───────────────────────────────────
    if not args.no_docker:
        print(f"\n{'═' * 60}")
        print("  Étape 4/5 — Docker : arrêt éventuel + démarrage MongoDB")
        print(f"{'═' * 60}")

        # Arrêt propre du stack existant (ignoré si rien ne tourne)
        subprocess.run(
            ["docker", "compose", "down"],
            cwd=str(PROJECT_ROOT),
            check=False
        )

        # Démarrage en arrière-plan
        subprocess.run(
            ["docker", "compose", "up", "--detach"],
            cwd=str(PROJECT_ROOT),
            check=True
        )

        # Suivi de l'import (bloquant jusqu'à la fin du conteneur importer)
        print("\n  Suivi de l'import (Ctrl+C pour détacher, MongoDB restera actif) :\n")
        subprocess.run(
            ["docker", "compose", "logs", "--follow", "importer"],
            cwd=str(PROJECT_ROOT),
            check=False
        )
    else:
        print("\n[Étape 4/5 ignorée — --no-docker]")

    # ── Étape 5 : Analyse & visualisation ─────────────────────────────────────
    if not args.skip_analyse:
        run(
            "Étape 5/5 — Analyse statistique et graphiques → analyse/output/",
            [py, str(ETL_DIR / "analyse.py")]
        )
    else:
        print("\n[Étape 5/5 ignorée — --skip-analyse]")

    # ── Résumé final ──────────────────────────────────────────────────────────
    print(f"\n{'═' * 60}")
    print("  Pipeline terminé.")
    if not args.no_docker:
        print()
        print("  MongoDB disponible sur :")
        print("    mongodb://localhost:27017/etl_db")
        print()
        print("  Collections :")
        print("    etl_db.orders    ← curated_orders.json")
        print("    etl_db.calendar  ← curated_calendar.json")
        print()
        print("  Pour arrêter MongoDB :")
        print("    docker compose down")
    if not args.skip_analyse:
        print()
        print("  Graphiques et rapport :")
        print("    analyse/output/stats_report.txt")
        print("    analyse/output/graph1_calendar_composition.png")
        print("    analyse/output/graph2_top_products.png")
        print("    analyse/output/graph3_top_clients.png")
        print("    analyse/output/graph4_avg_orders_by_day_type.png")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
