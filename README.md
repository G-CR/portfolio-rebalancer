# Portfolio Rebalancer

Local portfolio calibration and rebalancing application for Docker Desktop.

## Start

```bash
cp .env.example .env
docker compose up -d
```

Open `http://localhost:8080`. Only the Nginx frontend is published, and it is bound to `127.0.0.1`. To use another local port, set `PORTFOLIO_PORT` in `.env`.

## Backup

```bash
make backup
```

Backups are written to `backups/portfolio-<UTC timestamp>.dump` by default. They contain PostgreSQL data only. Keep the separate Docker secret volume with the deployment because encrypted provider credentials require its key.

## Restore

```bash
make restore FILE=backups/portfolio-20260714T080000Z.dump
```

Restore requires confirmation, stops API and worker writes, and creates a `pre-restore` safety backup before replacing database objects. Use `./scripts/restore.sh --yes FILE` only for unattended recovery.

## Fonts

The frontend bundles Noto Sans SC and IBM Plex Mono through Fontsource packages during the Vite build. No font request depends on an external CDN.

- Noto Sans SC: [Google Fonts](https://fonts.google.com/noto/specimen/Noto+Sans+SC), SIL Open Font License 1.1.
- IBM Plex Mono: [IBM Plex](https://github.com/IBM/plex), SIL Open Font License 1.1.
