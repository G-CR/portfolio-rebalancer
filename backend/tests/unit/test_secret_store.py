from app.core.secrets import SecretStore


def test_secret_store_round_trips_without_plaintext(tmp_path) -> None:
    store = SecretStore(tmp_path / "fernet.key")
    ciphertext = store.encrypt("alpha-secret-value")

    assert b"alpha-secret-value" not in ciphertext
    assert store.decrypt(ciphertext) == "alpha-secret-value"
    assert (tmp_path / "fernet.key").read_bytes() != b"alpha-secret-value"
    assert (tmp_path / "fernet.key").stat().st_mode & 0o777 == 0o600


def test_secret_store_reuses_the_same_key(tmp_path) -> None:
    key_path = tmp_path / "fernet.key"
    first = SecretStore(key_path)
    ciphertext = first.encrypt("persistent-secret")

    second = SecretStore(key_path)

    assert second.decrypt(ciphertext) == "persistent-secret"
