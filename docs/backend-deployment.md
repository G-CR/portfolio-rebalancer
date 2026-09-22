# Backend code deployment

`scripts/deploy_backend.py` deploys committed Python code from `backend/app` to an
existing Docker Compose server. It updates only the API and worker images. It
keeps the PostgreSQL container, volumes, `.env`, frontend image, and existing
credentials in place.

The script builds a new image from the server's current API image, so it checks
that `pyproject.toml`, `uv.lock`, `alembic.ini`, and all Alembic migration files
match the running image before deployment. It stops if dependencies or schema
migrations have changed. Use a full, separately reviewed release process for
those changes or for frontend changes.

## Run from Windows PowerShell

Install Paramiko locally, commit the code you want to deploy, then enter the
connection details for this PowerShell session. These prompts do not save the
values in the repository or shell history.

```powershell
python -m pip install paramiko
$env:DEPLOY_HOST = Read-Host 'SSH host'
$env:DEPLOY_USER = Read-Host 'SSH user'
$env:DEPLOY_SSH_PORT = Read-Host 'SSH port'
$env:DEPLOY_REMOTE_DIR = Read-Host 'Remote Compose directory'
$env:DEPLOY_HOST_KEY_SHA256 = Read-Host 'Trusted SSH host-key SHA256 fingerprint'
python scripts/deploy_backend.py
```

The script prompts for the SSH password without echoing or saving it. For key
authentication, provide `--identity-file PATH` or `--use-agent` instead. Obtain
the SSH host-key fingerprint from a trusted source before running. The script
refuses to connect if the fingerprint differs.

Afterward, clear the session values:

```powershell
Remove-Item Env:DEPLOY_HOST,Env:DEPLOY_USER,Env:DEPLOY_SSH_PORT,Env:DEPLOY_REMOTE_DIR,Env:DEPLOY_HOST_KEY_SHA256
```

The script requires a clean Git working tree. It packages only `.py` files under
`backend/app`, builds a versioned image on the server, checks that the image can
import the application, backs up the production Compose override, updates API
and worker, and waits for API health. On startup failure it restores the previous
override and image. The backup Compose override remains on the server for
inspection. Deployment does not trigger a market-data refresh or send email.

No host, port, username, password, fingerprint, or server directory is stored in
this repository. Files named `.deploy.local.*` are also Git-ignored if you choose
to maintain a private local deployment note.
