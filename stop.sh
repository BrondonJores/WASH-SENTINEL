#!/usr/bin/env bash
# WASH Sentinel — arrêt des conteneurs.
# Usage : ./stop.sh (données conservées) | ./stop.sh --volumes (tout effacer : BDD, modèles Ollama)
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--volumes" ]; then
  echo "Arrêt + suppression des volumes (base de données, modèles Ollama)..."
  docker compose down -v
else
  docker compose down
fi
