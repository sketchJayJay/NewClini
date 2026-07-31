#!/usr/bin/env bash
set -euo pipefail
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${BASE_DIR}"

echo "Subindo containers (mantém dados em ./data)..."
docker compose up -d --build
echo "OK."
