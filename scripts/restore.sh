#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

assume_yes=false
dump_file=""
for argument in "$@"; do
  case "${argument}" in
    --yes) assume_yes=true ;;
    -*) echo "Unknown option: ${argument}" >&2; exit 2 ;;
    *)
      if [[ -n "${dump_file}" ]]; then
        echo "Usage: $0 [--yes] path/to/backup.dump" >&2
        exit 2
      fi
      dump_file="${argument}"
      ;;
  esac
done

if [[ -z "${dump_file}" ]]; then
  echo "Usage: $0 [--yes] path/to/backup.dump" >&2
  exit 2
fi
if [[ "${dump_file}" != /* ]]; then
  dump_file="${PROJECT_ROOT}/${dump_file}"
fi
if [[ ! -f "${dump_file}" ]]; then
  echo "Backup file does not exist: ${dump_file}" >&2
  exit 1
fi

if [[ "${assume_yes}" != true ]]; then
  printf 'Restore %s and replace the current database? [y/N] ' "${dump_file}"
  read -r confirmation
  if [[ "${confirmation}" != "y" && "${confirmation}" != "Y" ]]; then
    echo "Restore cancelled."
    exit 0
  fi
fi

if ! docker compose ps --status running --services | grep -qx db; then
  echo "Database service is not running. Start it with: docker compose up -d db" >&2
  exit 1
fi

services_stopped=false
restart_services() {
  if [[ "${services_stopped}" == true ]]; then
    docker compose start api worker >/dev/null || true
  fi
}
trap restart_services EXIT INT TERM

docker compose stop api worker
services_stopped=true

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
safety_backup="${BACKUP_DIR:-backups}/pre-restore-${timestamp}.dump"
"${SCRIPT_DIR}/backup.sh" "${safety_backup}"

docker compose exec -T db sh -lc \
  'exec pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  < "${dump_file}"

restart_services
services_stopped=false
trap - EXIT INT TERM
echo "Restore completed from: ${dump_file}"
echo "Safety backup created at: ${safety_backup}"
