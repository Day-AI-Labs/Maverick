"""Browser auth vault: encrypted-at-rest storage for browser sessions/credentials.

A long-running agent that logs into sites needs somewhere safe to keep session
cookies / tokens between runs. This is an encrypted local vault: each named entry
(a dict of cookies / storage_state / credentials) is sealed with Fernet
(AES-128-CBC + HMAC) under a key that lives only in a ``0600`` key file (or the
``MAVERICK_VAULT_KEY`` env var), never in the data file. The data file holds only
ciphertext, so it's safe to sync/back up.

``encrypt_entry`` / ``decrypt_entry`` / ``Vault`` take an explicit key so they're
unit-testable; the ``browser_auth_vault`` tool resolves the key from the key file.
Requires the ``cryptography`` extra (``pip install maverick-agent[audit-signing]``);
the tool degrades with an actionable error when it's missing.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from .paths import data_dir

_STORE = data_dir("vault")
_KEY_FILE = _STORE / "key"
_DATA_FILE = _STORE / "browser.json"


def _require_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:  # knob exemption: optional dep
        raise RuntimeError(
            "browser auth vault needs the 'cryptography' package. Install it "
            "with: pip install 'maverick-agent[audit-signing]'") from e
    return Fernet


def generate_key() -> bytes:
    """A fresh url-safe base64 Fernet key."""
    return _require_fernet().generate_key()


def encrypt_entry(key: bytes, data: dict) -> str:
    """Seal ``data`` (a JSON-able dict) into a Fernet token string."""
    Fernet = _require_fernet()
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return Fernet(key).encrypt(payload).decode("ascii")


def decrypt_entry(key: bytes, token: str) -> dict:
    """Open a Fernet token back into a dict. Raises on a wrong/forged key."""
    Fernet = _require_fernet()
    from cryptography.fernet import InvalidToken
    try:
        raw = Fernet(key).decrypt(token.encode("ascii"))
    except InvalidToken as e:
        raise ValueError("cannot decrypt entry: wrong key or corrupted data") from e
    return json.loads(raw.decode("utf-8"))


class Vault:
    """A file-backed map of name -> encrypted entry, sealed under ``key``."""

    def __init__(self, key: bytes, path: str | Path):
        self.key = key
        self.path = Path(path)

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _write(self, blob: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(blob, indent=2).encode("utf-8")
        # 0600 + atomic replace: the file holds sealed credential blobs; match
        # the key file's restrictive perms so entry names/sizes/timing aren't
        # readable by any other local user (the bare write_text inherited the
        # umask, typically 0644). os.open sets mode only on creation, so write
        # to a fresh temp then rename over the target.
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.replace(tmp, self.path)

    def store(self, name: str, data: dict) -> None:
        blob = self._read()
        blob[name] = encrypt_entry(self.key, data)
        self._write(blob)

    def load(self, name: str) -> dict:
        blob = self._read()
        if name not in blob:
            raise KeyError(f"no vault entry named {name!r}")
        return decrypt_entry(self.key, blob[name])

    def list_entries(self) -> list[str]:
        return sorted(self._read())

    def delete(self, name: str) -> bool:
        blob = self._read()
        if name not in blob:
            return False
        del blob[name]
        self._write(blob)
        return True


def resolve_key(key_file: Path = _KEY_FILE) -> bytes:
    """Key from ``MAVERICK_VAULT_KEY``, else a ``0600`` key file (created once).

    The key file is created **atomically** with ``O_CREAT|O_EXCL`` and mode
    ``0600`` so the secret never exists, even briefly, with default-umask
    permissions (a write-then-chmod leaves a TOCTOU window where it's
    group/world-readable). The parent dir is created/tightened to ``0700``.
    """
    env = os.environ.get("MAVERICK_VAULT_KEY", "").strip()
    if env:
        return env.encode("ascii")
    if key_file.exists():
        return key_file.read_bytes().strip()
    key = generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(key_file.parent, stat.S_IRWXU)  # 0700 — tighten a pre-existing dir
    except OSError:  # pragma: no cover -- Windows / unusual fs
        pass
    try:
        fd = os.open(str(key_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # lost a create race — read the winner's key
        return key_file.read_bytes().strip()
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    return key


_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["store", "load", "list", "delete"]},
        "name": {"type": "string", "description": "entry name (e.g. 'github')"},
        "data": {"type": "object",
                 "description": "session/credential dict to seal (store op)"},
    },
    "required": ["op"],
}


def _run(args: dict) -> str:
    op = args.get("op")
    try:
        key = resolve_key()
    except RuntimeError as e:
        return f"ERROR: {e}"
    vault = Vault(key, _DATA_FILE)
    name = args.get("name") or ""
    try:
        if op == "store":
            if not name:
                return "ERROR: store requires a name"
            vault.store(name, args.get("data") or {})
            return f"sealed entry {name!r}"
        if op == "load":
            data = vault.load(name)
            # Don't echo secrets back verbatim; report shape only.
            return (f"loaded {name!r}: {len(data)} field(s) "
                    f"({', '.join(sorted(data)[:10])})")
        if op == "list":
            entries = vault.list_entries()
            return "\n".join(entries) if entries else "(vault empty)"
        if op == "delete":
            return f"deleted {name!r}" if vault.delete(name) else f"no entry {name!r}"
    except (KeyError, ValueError, RuntimeError) as e:
        return f"ERROR: {e}"
    return f"ERROR: unknown op {op!r}"


def browser_auth_vault():
    from .tools import Tool
    return Tool(
        name="browser_auth_vault",
        description=(
            "Encrypted-at-rest vault for browser sessions / credentials. ops: "
            "store (name, data), load (name) -> field shape (never echoes "
            "secrets), list, delete. Sealed with Fernet under a 0600 key file; "
            "needs the cryptography extra."
        ),
        input_schema=_SCHEMA,
        fn=_run,
    )


__all__ = [
    "generate_key", "encrypt_entry", "decrypt_entry", "Vault", "resolve_key",
    "browser_auth_vault",
]
