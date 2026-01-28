#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${BASE_DIR}/data"
BACKUP_DIR="${BASE_DIR}/backups"
TS="$(date +%Y-%m-%d_%H%M%S)"

mkdir -p "${BACKUP_DIR}"

if [ ! -f "${DATA_DIR}/newclinica.db" ]; then
  echo "Banco não encontrado em ${DATA_DIR}/newclinica.db"
  exit 1
fi

# Backup simples (cópia do DB)
cp "${DATA_DIR}/newclinica.db" "${BACKUP_DIR}/newclinica_${TS}.db"

# Mantém só os últimos 14 backups
ls -1t "${BACKUP_DIR}"/newclinica_*.db | tail -n +15 | xargs -r rm -f

echo "Backup ok: ${BACKUP_DIR}/newclinica_${TS}.db"
