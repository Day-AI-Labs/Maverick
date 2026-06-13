"""Plugin signing CA (roadmap: 2028 H2 ecosystem).

A **self-hostable** certificate authority for plugin/skill artifacts — the
in-house counterpart to sigstore's keyless flow (which depends on an external
CA + OIDC). An organization runs its own root, issues signer certificates to
publishers, and every install can verify a two-link chain offline:

    artifact signature  ──signed by──>  publisher key
    publisher cert      ──signed by──>  CA root key (the trust anchor)

* :class:`PluginCA` — create/load the root (Ed25519, key under
  ``~/.maverick/keys/plugin_ca/``, 0600/0700 like the audit signing key),
  ``issue(publisher, pubkey_hex)`` -> a signed **cert** (JSON: publisher,
  pubkey, issued_at, expires_at, root signature over the canonical bytes),
  and ``revoke(serial)`` -> a CA-signed revocation list.
* :func:`sign_artifact` — a publisher signs ``sha256(artifact)`` with their
  key into a **bundle** (JSON: digest, signature, cert).
* :func:`verify_artifact` — the install-side check, **fail-closed**: the
  bundle's cert must verify against the configured root pubkey, be unexpired
  and unrevoked, the publisher signature must verify over the artifact's
  actual digest. Any missing piece = refused.

Reuses the audit chain's Ed25519 primitives (``cryptography`` via the
``[audit-signing]`` extra); without the extra, signing/issuing raise an
actionable error and verification fails closed. Deterministic tests run with
real in-memory keys when ``cryptography`` is present (it is, in CI) and skip
otherwise.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CERT_DAYS = 365.0


def _have_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
        return True
    except ImportError:
        return False


def _require_crypto() -> None:
    if not _have_crypto():
        raise RuntimeError(
            "plugin CA needs the cryptography package. "
            "Install: pip install 'maverick-agent[audit-signing]'")


def _keypair() -> tuple[str, str]:
    """Generate an Ed25519 keypair; returns (priv_hex, pub_hex)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption()).hex()
    pub_hex = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    return priv_hex, pub_hex


def _sign(priv_hex: str, message: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    return priv.sign(message).hex()


def _verify(pub_hex: str, sig_hex: str, message: bytes) -> bool:
    from .audit.signing import verify_ed25519
    return verify_ed25519(pub_hex, sig_hex, message)


def _canonical(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _cert_payload(cert: dict) -> dict:
    return {k: v for k, v in cert.items() if k != "root_sig"}


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: str
    publisher: str | None = None


class PluginCA:
    """The organization's root: issue publisher certs, maintain revocations."""

    def __init__(self, ca_dir: Path | None = None):
        if ca_dir is None:
            from .paths import maverick_home
            ca_dir = maverick_home() / "keys" / "plugin_ca"
        self.dir = Path(ca_dir)
        self._priv_path = self.dir / "root.key"
        self._pub_path = self.dir / "root.pub"
        self._crl_path = self.dir / "revocations.json"

    # -- root lifecycle -----------------------------------------------------

    def init_root(self) -> str:
        """Create the root keypair (refuses to overwrite). Returns pub hex."""
        _require_crypto()
        if self._priv_path.exists():
            raise RuntimeError(f"root already exists at {self._priv_path}")
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:  # pragma: no cover
            pass
        priv_hex, pub_hex = _keypair()
        self._priv_path.write_text(priv_hex, encoding="utf-8")
        os.chmod(self._priv_path, 0o600)
        self._pub_path.write_text(pub_hex, encoding="utf-8")
        self._write_crl({"revoked": {}, "sig": ""})
        return pub_hex

    def root_pub(self) -> str:
        return self._pub_path.read_text(encoding="utf-8").strip()

    def _root_priv(self) -> str:
        return self._priv_path.read_text(encoding="utf-8").strip()

    # -- issuing ------------------------------------------------------------

    def issue(self, publisher: str, pubkey_hex: str, *,
              days: float = DEFAULT_CERT_DAYS, now: float | None = None) -> dict:
        """Issue a signer certificate binding ``publisher`` to ``pubkey_hex``."""
        _require_crypto()
        if not publisher or not publisher.strip():
            raise ValueError("publisher name is required")
        ts = float(now if now is not None else time.time())
        cert = {
            "serial": uuid.uuid4().hex,
            "publisher": publisher.strip(),
            "pubkey": pubkey_hex,
            "issued_at": ts,
            "expires_at": ts + days * 86400.0,
        }
        cert["root_sig"] = _sign(self._root_priv(), _canonical(_cert_payload(cert)))
        return cert

    # -- revocation ---------------------------------------------------------

    def revoke(self, serial: str, *, reason: str = "") -> None:
        crl = self._load_crl()
        crl["revoked"][serial] = {"at": time.time(), "reason": reason}
        self._write_crl(crl)

    def _write_crl(self, crl: dict) -> None:
        crl["sig"] = _sign(self._root_priv(),
                           _canonical({"revoked": crl["revoked"]}))
        tmp = self._crl_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(crl, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._crl_path)
        try:
            os.chmod(self._crl_path, 0o600)
        except OSError:  # pragma: no cover
            pass

    def _load_crl(self) -> dict:
        try:
            crl = json.loads(self._crl_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError("CRL missing; refusing to infer revocation state") from exc
        except ValueError as exc:
            raise RuntimeError("CRL is not valid JSON; refusing to infer revocation state") from exc
        if not isinstance(crl.get("revoked"), dict) or not isinstance(crl.get("sig"), str):
            raise RuntimeError("CRL malformed; refusing to infer revocation state")
        return crl

    def revoked_serials(self, *, root_pub: str | None = None) -> set[str]:
        """Serials on the CRL, failing closed if the CRL cannot be verified."""
        crl = self._load_crl()
        pub = root_pub or self.root_pub()
        if not _verify(pub, crl.get("sig", ""),
                       _canonical({"revoked": crl["revoked"]})):
            raise RuntimeError("CRL signature invalid; refusing to infer revocation state")
        return set(crl["revoked"])


def sign_artifact(path: Path, *, publisher_priv_hex: str, cert: dict) -> dict:
    """Publisher-side: sign ``path``'s sha256 into a verification bundle."""
    _require_crypto()
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return {
        "digest": digest,
        "sig": _sign(publisher_priv_hex, digest.encode("ascii")),
        "cert": cert,
    }


def verify_artifact(path: Path, bundle: dict, *, root_pub: str,
                    revoked: set[str] | None = None,
                    now: float | None = None) -> VerifyResult:
    """Install-side chain verification. FAIL-CLOSED on any missing piece."""
    if not _have_crypto():
        return VerifyResult(False, "cryptography not installed; refusing unverified plugin")
    cert = bundle.get("cert") or {}
    for fieldname in ("publisher", "pubkey", "root_sig", "serial", "expires_at"):
        if not cert.get(fieldname):
            return VerifyResult(False, f"cert missing {fieldname}")
    if not _verify(root_pub, cert["root_sig"], _canonical(_cert_payload(cert))):
        return VerifyResult(False, "cert not signed by the configured root")
    ts = float(now if now is not None else time.time())
    if ts >= float(cert["expires_at"]):
        return VerifyResult(False, f"cert expired ({cert['publisher']})")
    if revoked is None:
        return VerifyResult(False, "revocation data required")
    if cert["serial"] in revoked:
        return VerifyResult(False, f"cert revoked ({cert['publisher']})")
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest != bundle.get("digest"):
        return VerifyResult(False, "artifact digest mismatch (file changed after signing)")
    if not _verify(cert["pubkey"], bundle.get("sig", ""), digest.encode("ascii")):
        return VerifyResult(False, "artifact signature invalid")
    return VerifyResult(True, "ok", publisher=cert["publisher"])


def new_publisher_keypair() -> tuple[str, str]:
    """Convenience for publishers: (priv_hex, pub_hex)."""
    _require_crypto()
    return _keypair()


__all__ = ["PluginCA", "VerifyResult", "sign_artifact", "verify_artifact",
           "new_publisher_keypair", "DEFAULT_CERT_DAYS"]
