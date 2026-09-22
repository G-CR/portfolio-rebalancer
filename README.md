# Portfolio Rebalancer

Local portfolio calibration and rebalancing application for Docker Desktop.

## Requirements

- Docker Desktop with Docker Compose v2.
- At least 4 GB of free memory for the four containers.
- No authentication or LAN exposure is provided; this release is local-only.

## First Run

```bash
cp .env.example .env
docker compose up -d
```

Open `http://localhost:3000`. Only the Nginx frontend is published, and it is bound to `127.0.0.1`. To use another local port, set `PORTFOLIO_PORT` in `.env` before startup.

```bash
curl -fsS http://localhost:3000/api/health
docker compose ps
docker compose logs -f
```

Stop services with `docker compose down`. Do not add `-v` unless you intentionally want to delete portfolio data and the credential key. Upgrade with `git pull`, `docker compose build`, and `docker compose up -d`; the API applies database migrations during startup.

## Browser logical backup and restore

The history page's **完整备份与恢复** section exports one versioned
`.portfolio-backup` archive and can restore it online. A confirmed restore replaces
the current logical portfolio state atomically; it does not merge records. Before
replacement, the API creates a durable logical safety backup. The five newest
successful safety backups remain available to list, download, restore, or delete.

Logical archives include all persisted business history and plaintext provider API
keys and SMTP passwords. Anyone who can read a downloaded archive can read those
credentials, so store and transfer it as sensitive plaintext. Export files,
validated uploads, and one-time restore tokens expire after 30 minutes. The first
release supports manual logical export and import only; it does not schedule
periodic logical backups.

Newer application versions keep explicit migrations for supported older archive
formats. Importing an old backup into the same or a newer application is supported;
importing a new-format backup into an older application is not. After a restore,
the worker checks the persisted market-data refresh schedule every 30 seconds and
applies a changed schedule within 60 seconds without a container restart.

## PostgreSQL disaster-recovery backup

The command-line PostgreSQL backup remains a separate recovery layer:

```bash
make backup
```

Backups are written to `backups/portfolio-<UTC timestamp>.dump` by default. They contain PostgreSQL data only. Keep the separate Docker secret volume with the deployment because encrypted provider credentials require its key.

## PostgreSQL disaster-recovery restore

```bash
make restore FILE=backups/portfolio-20260714T080000Z.dump
```

Restore requires confirmation, stops API and worker writes, and creates a `pre-restore` safety backup before replacing database objects. Use `./scripts/restore.sh --yes FILE` only for unattended recovery.

Use `make backup` / `make restore` when PostgreSQL is damaged or the API cannot
start, because browser-based logical restore is unavailable in that situation.

## Backend Tests

Run backend tests only through the isolated target:

```bash
make test-backend
```

The target uses a separate Compose project, a disposable PostgreSQL volume, and the dedicated `portfolio_test` database. Do not run `docker compose run api pytest`, `docker compose run --rm api uv run pytest`, or database integration tests directly in the normal Compose project: pytest intentionally refuses those commands before any business table can be cleared.

## Fonts

The frontend bundles Noto Sans SC and IBM Plex Mono through Fontsource packages during the Vite build. No font request depends on an external CDN.

- Noto Sans SC: [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+SC), SIL Open Font License 1.1.
- IBM Plex Mono: [IBM Plex](https://github.com/IBM/plex), SIL Open Font License 1.1.

## Documentation

- [User guide](docs/user-guide.md)
- [Operations and recovery](docs/operations.md)
- [Backend code deployment](docs/backend-deployment.md)
