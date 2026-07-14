from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if not SCRIPTS.exists():
    pytest.skip("Repository-level operation scripts are not copied into the API image.", allow_module_level=True)


def test_backup_script_uses_custom_database_dump_without_secret_volume() -> None:
    script = (SCRIPTS / "backup.sh").read_text()

    assert "set -euo pipefail" in script
    assert "pg_dump" in script
    assert "--format=custom" in script
    assert "--no-owner" in script
    assert "--no-acl" in script
    assert "secret_data" not in script
    assert "fernet" not in script.lower()


def test_restore_script_requires_confirmation_and_creates_safety_backup() -> None:
    script = (SCRIPTS / "restore.sh").read_text()

    assert "set -euo pipefail" in script
    assert "--yes" in script
    assert "pre-restore" in script
    assert "pg_restore" in script
    assert "--clean" in script
    assert "--if-exists" in script
    assert "--no-owner" in script
    assert "--no-acl" in script
    assert "docker compose stop api worker" in script
    assert "docker compose start api worker" in script
    assert "secret_data" not in script
    assert "fernet" not in script.lower()
