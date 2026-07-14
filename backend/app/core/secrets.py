from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet


class SecretStore:
    def __init__(self, key_path: Path) -> None:
        self.key_path = key_path
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.key_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as key_file:
                key_file.write(Fernet.generate_key())
        self.key_path.chmod(0o600)
        self.fernet = Fernet(self.key_path.read_bytes())

    def encrypt(self, value: str) -> bytes:
        return self.fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, value: bytes) -> str:
        return self.fernet.decrypt(value).decode("utf-8")
