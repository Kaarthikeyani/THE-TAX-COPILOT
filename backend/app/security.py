"""Field-level encryption at rest (Fernet) for the raw SMS text.

Key: COPILOT_SECRET_KEY (environment) wins; otherwise data/secret.key is created on first run (chmod 600 where the
OS supports it). The key file is excluded from source control by .gitignore. If the key is LOST or CHANGED, stored
raw SMS text becomes unreadable ("[unable to decrypt: key mismatch]") but amounts, dates, merchants and categories
are stored in clear columns and keep working. Back the key up separately from the database.
"""
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from .database import DATA_DIR

KEY_PATH = DATA_DIR / "secret.key"


def _load_key() -> bytes:
    env = os.environ.get("COPILOT_SECRET_KEY")
    if env:
        return env.encode()
    if KEY_PATH.exists():
        return KEY_PATH.read_bytes()
    key = Fernet.generate_key()
    KEY_PATH.write_bytes(key)
    try:
        os.chmod(KEY_PATH, 0o600)
    except OSError:
        pass
    return key


_fernet = Fernet(_load_key())


def encrypt_text(plain: str) -> str:
    return _fernet.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    try:
        return _fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return "[unable to decrypt: key mismatch]"


def key_source() -> str:
    return "environment" if os.environ.get("COPILOT_SECRET_KEY") else "file"
