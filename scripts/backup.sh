#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="${1:-${BACKUP_DIR:-backups}/portfolio-${timestamp}.dump}"
if [[ "${destination}" != /* ]]; then
  destination="${PROJECT_ROOT}/${destination}"
fi

mkdir -p "$(dirname "${destination}")"
temporary="${destination}.partial.$$"
trap 'rm -f "${temporary}"' EXIT

if ! docker compose ps --status running --services | grep -qx db; then
  echo "Database service is not running. Start it with: docker compose up -d db" >&2
  exit 1
fi

docker compose exec -T db sh -lc \
  'exec pg_dump --format=custom --no-owner --no-acl --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  > "${temporary}"

chmod 600 "${temporary}"
mv "${temporary}" "${destination}"
trap - EXIT
echo "Backup created: ${destination}"
