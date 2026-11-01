#!/usr/bin/env bash
# Bundle le frontend construit dans desktop/resources puis compile le binaire.
# Requiert un accès réseau (télécharge binaires + client Neutralino) :
# en CI ou sur machine dev. Voir docs/INSTALL.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NEU="node node_modules/@neutralinojs/neu/bin/neu.js"

echo "1/4 build frontend…"
(cd "$ROOT/frontend" && npm run build --silent)

echo "2/4 copie vers desktop/resources…"
rm -rf "$ROOT/desktop/resources"
cp -r "$ROOT/frontend/dist" "$ROOT/desktop/resources"
ls "$ROOT/desktop/resources/index.html" >/dev/null

echo "3/4 binaires + client Neutralino (réseau)…"
(cd "$ROOT/desktop" && $NEU update)

echo "4/4 compilation…"
(cd "$ROOT/desktop" && $NEU build --release)

echo "OK — binaires dans desktop/dist/wash-relai/ + zip desktop/dist/wash-relai-release.zip"
