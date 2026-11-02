#!/usr/bin/env bash
# WASH Sentinel — démarrage complet : conteneurs + migrations + seeders + modèles Ollama.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n==> %s\n' "$1"; }

command -v docker >/dev/null 2>&1 || { echo "Docker n'est pas installé. Voir https://docs.docker.com/engine/install/ubuntu/"; exit 1; }
if ! docker info >/dev/null 2>&1; then
  echo "Le daemon Docker est injoignable. Causes possibles :"
  echo "  1) Daemon éteint :        sudo systemctl start docker"
  echo "  2) Docker installé via snap :  sudo snap start docker"
  echo "  3) Permissions :          sudo usermod -aG docker $USER  puis rouvrez le terminal"
  echo "  4) Moteur non installé :  https://docs.docker.com/engine/install/ubuntu/"
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Le plugin Compose manque :  sudo apt update && sudo apt install -y docker-compose-plugin"
  exit 1
fi

[ -f .env ] || { cp .env.example .env; echo "Fichier .env racine créé."; }
[ -f backend/.env ] || cp backend/.env.example backend/.env
[ -f frontend/.env ] || cp frontend/.env.example frontend/.env
mkdir -p models/omnilingual models/whisper models/piper

set -a
. ./.env
set +a

# Le conteneur PHP tourne en www-data : storage doit être inscriptible (dev uniquement).
if ! chmod -R u+rwX,go+rwX backend/storage backend/bootstrap/cache >/dev/null 2>&1 \
  || ! chmod u+rwx,go+rwx backend/public >/dev/null 2>&1; then
  echo "chmod refusé (fichiers root d'un run précédent), tentative avec sudo..."
  sudo chmod -R 777 backend/storage backend/bootstrap/cache backend/public
fi

say "Démarrage des conteneurs (build si besoin)"
docker compose up -d --build

say "Attente de PostgreSQL"
until docker compose exec -T pgsql pg_isready -U "${DB_USERNAME:-sentinel_user}" -d "${DB_DATABASE:-wash_sentinel}" >/dev/null 2>&1; do
  sleep 2
done

if ! grep -q "^APP_KEY=.\+" backend/.env 2>/dev/null; then
  say "Génération de la clé applicative Laravel"
  docker compose exec -T laravel php artisan key:generate --force
fi

say "Attente du conteneur Laravel (running, pas restarting)"
for _ in $(seq 1 60); do
  id="$(docker compose ps -q laravel 2>/dev/null || true)"
  if [ -n "$id" ] && [ "$(docker inspect -f '{{.State.Status}}' "$id" 2>/dev/null)" = "running" ]; then
    break
  fi
  sleep 2
done

say "Migrations + seeders (écoles du Cameroun, rôles, profils IA)"
docker compose exec -T -u www-data laravel php artisan storage:link >/dev/null 2>&1 || true
docker compose exec -T -u www-data laravel php artisan migrate --force
docker compose exec -T -u www-data laravel php artisan db:seed --force

say "Attente d'Ollama"
for _ in $(seq 1 60); do
  docker compose exec -T ollama ollama list >/dev/null 2>&1 && break
  sleep 2
done

say "Téléchargement des modèles (long la première fois, non bloquant)"
if ! docker compose exec -T ollama ollama pull "${OLLAMA_MODEL:-llama3.2:3b}"; then
  echo "!! Echec du pull ${OLLAMA_MODEL:-llama3.2:3b} (souvent un timeout reseau vers le registry)."
  echo "   La stack reste utilisable : utilisez un profil API externe depuis la page Reglages IA,"
  echo "   ou relancez : docker compose exec ollama ollama pull ${OLLAMA_MODEL:-llama3.2:3b}"
fi
docker compose exec -T ollama ollama pull "${OLLAMA_EMBED_MODEL:-nomic-embed-text}" || echo "!! Echec du pull ${OLLAMA_EMBED_MODEL:-nomic-embed-text} (non bloquant, relancez-le plus tard)."
echo "Vision optionnelle : docker compose exec ollama ollama pull ${OLLAMA_VISION_MODEL:-llama3.2-vision:11b}"

say "WASH Sentinel est prêt"
echo "  Frontend admin : http://localhost:${FRONTEND_PORT:-5173}"
echo "  API Laravel    : http://localhost:${APP_PORT:-80}/api"
echo "  Moteur IA      : http://localhost:${FORWARD_AI_PORT:-8000}/docs"
echo "  Comptes démo   : admin@wash.cm / tech@wash.cm / directeur@ecole.cm (mot de passe : password)"
