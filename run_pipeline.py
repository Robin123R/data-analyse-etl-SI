"""
run_pipeline.py — Orchestrateur du pipeline ETL complet

Exécute les étapes dans l'ordre :
  1. fetch_holidays.py         — téléchargement des jours fériés (nager.at + jiejiariapi)
  2. curated.py --format json  — OBT orders au format NDJSON
  3. stats_curated.py          — statistiques descriptives sur l'OBT curated
  4. curated_calendar.py --format json  — calendrier curated au format NDJSON
  5. Docker Compose            — MongoDB + import automatique des deux collections
  6. analyse.py                — statistiques descriptives + 4 graphiques PNG

Usage :
  python run_pipeline.py                  # pipeline complet
  python run_pipeline.py --skip-fetch     # sauter l'étape 1 (données déjà présentes)
  python run_pipeline.py --skip-stats     # sauter l'étape 3 (stats curated)
  python run_pipeline.py --no-docker      # sauter l'étape 5 (MongoDB/Docker)
  python run_pipeline.py --skip-analyse   # sauter l'étape 6 (analyse / graphiques)
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
ETL_DIR      = PROJECT_ROOT / "etl"


def _docker_compose_cmd() -> list:
    """Retourne le préfixe de commande Docker Compose disponible sur le système."""
    # Docker Compose V2 (plugin intégré)
    try:
        subprocess.run(["docker", "compose", "version"], capture_output=True, check=True)
        return ["docker", "compose"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Docker Compose V1 (binaire standalone)
    try:
        subprocess.run(["docker-compose", "version"], capture_output=True, check=True)
        return ["docker-compose"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    print("\n  ERREUR : Docker Compose introuvable.")
    print("  Installe-le avec : sudo apt-get install docker-compose-plugin")
    print("  ou : https://docs.docker.com/compose/install/\n")
    sys.exit(1)


def run(label: str, cmd: list, check: bool = True) -> subprocess.CompletedProcess:
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    result = subprocess.run(cmd, check=check)
    if result.returncode != 0 and not check:
        print(f"  [AVERTISSEMENT] {label} s'est termine avec le code {result.returncode}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Pipeline ETL complet")
    parser.add_argument(
        "--skip-fetch", action="store_true",
        help="Sauter l'etape 1 (fetch_holidays) — donnees deja presentes dans data_raw/"
    )
    parser.add_argument(
        "--skip-stats", action="store_true",
        help="Sauter l'etape 3 (stats_curated) — statistiques descriptives sur l'OBT"
    )
    parser.add_argument(
        "--no-docker", action="store_true",
        help="Sauter l'etape 5 (Docker / MongoDB)"
    )
    parser.add_argument(
        "--skip-analyse", action="store_true",
        help="Sauter l'etape 6 (analyse statistique et graphiques)"
    )
    args = parser.parse_args()

    py = sys.executable

    # ── Dépendances Python ────────────────────────────────────────────────────
    req = PROJECT_ROOT / "requirements.txt"
    if req.exists():
        run(
            "Dependances — pip install -r requirements.txt",
            [py, "-m", "pip", "install", "-r", str(req), "--quiet"]
        )

    # ── Étape 1 : Fetch holidays ──────────────────────────────────────────────
    if not args.skip_fetch:
        run(
            "Etape 1/6 — Telechargement des donnees calendaires",
            [py, str(ETL_DIR / "fetch_holidays.py")]
        )
    else:
        print("\n[Etape 1/6 ignoree — --skip-fetch]")

    # ── Étape 2 : Curated orders (JSON) ───────────────────────────────────────
    run(
        "Etape 2/6 — Curated orders → data_clean/curated_orders.json",
        [py, str(ETL_DIR / "curated.py"), "--format", "json"]
    )

    # ── Étape 3 : Statistiques descriptives curated ───────────────────────────
    if not args.skip_stats:
        run(
            "Etape 3/6 — Statistiques descriptives OBT → data_clean/stats_curated_report.txt",
            [py, str(ETL_DIR / "stats_curated.py")]
        )
    else:
        print("\n[Etape 3/6 ignoree — --skip-stats]")

    # ── Étape 4 : Curated calendar (JSON) ─────────────────────────────────────
    run(
        "Etape 4/6 — Curated calendrier → data_clean/curated_calendar.json",
        [py, str(ETL_DIR / "curated_calendar.py"), "--format", "json"]
    )

    # ── Étape 5 : Docker — MongoDB + import ───────────────────────────────────
    if not args.no_docker:
        print(f"\n{'=' * 60}")
        print("  Etape 5/6 — Docker : arret eventuel + demarrage MongoDB")
        print(f"{'=' * 60}")

        dc = _docker_compose_cmd()

        # Arrêt propre du stack existant (ignoré si rien ne tourne)
        subprocess.run(
            dc + ["down"],
            cwd=str(PROJECT_ROOT),
            check=False
        )

        # Démarrage en arrière-plan
        detach_flag = "--detach" if dc[0] == "docker" else "-d"
        subprocess.run(
            dc + ["up", detach_flag],
            cwd=str(PROJECT_ROOT),
            check=True
        )

        # Suivi de l'import (bloquant jusqu'à la fin du conteneur importer)
        print("\n  Suivi de l'import (Ctrl+C pour detacher, MongoDB restera actif) :\n")
        subprocess.run(
            dc + ["logs", "--follow", "importer"],
            cwd=str(PROJECT_ROOT),
            check=False
        )
    else:
        print("\n[Etape 5/6 ignoree — --no-docker]")

    # ── Étape 6 : Analyse & visualisation ─────────────────────────────────────
    if not args.skip_analyse:
        run(
            "Etape 6/6 — Analyse statistique et graphiques → analyse/output/",
            [py, str(ETL_DIR / "analyse.py")]
        )
    else:
        print("\n[Etape 6/6 ignoree — --skip-analyse]")

    # ── Résumé final ──────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("  Pipeline termine.")
    if not args.no_docker:
        print()
        print("  MongoDB disponible sur :")
        print("    mongodb://localhost:27017/etl_db")
        print()
        print("  Collections :")
        print("    etl_db.orders    <- curated_orders.json")
        print("    etl_db.calendar  <- curated_calendar.json")
        print()
        print("  Pour arreter MongoDB :")
        print("    docker compose down")
    if not args.skip_stats:
        print()
        print("  Statistiques currees :")
        print("    data_clean/stats_curated_report.txt")
    if not args.skip_analyse:
        print()
        print("  Graphiques et rapport :")
        print("    analyse/output/stats_report.txt")
        print("    analyse/output/graph1_calendar_composition.png")
        print("    analyse/output/graph2_top_products.png")
        print("    analyse/output/graph3_top_clients.png")
        print("    analyse/output/graph4_avg_orders_by_day_type.png")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
