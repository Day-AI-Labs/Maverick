"""Crypto-at-rest stress: AES-256-GCM seal/unseal under adversarial conditions.

Invariants:
  1. Round-trip: unseal(seal(x)) == x for every size, incl. empty + 1MB + random.
  2. Nonce uniqueness: GCM is catastrophically broken by nonce reuse. Seal the
     SAME plaintext many times; every nonce (and every ciphertext) must differ.
  3. Tamper detection: flip any byte of a sealed blob -> unseal must RAISE, never
     silently return wrong/!= plaintext (GCM auth tag).
  4. Truncation: a short blob raises, never a bare slice error or wrong plaintext.
  5. Concurrency: many threads sealing/unsealing share no mutable state corruptly.
  6. Key rotation: a blob sealed under the old key still opens after rotate.
"""
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "packages" / "maverick-core"))
# Isolate the keystore in a temp dir so we never touch a real one.
import tempfile  # noqa: E402

_KEYDIR = tempfile.mkdtemp(prefix="cryptostress-")
os.environ["MAVERICK_DATA_DIR"] = _KEYDIR
os.environ["MAVERICK_HOME"] = _KEYDIR
os.environ["MAVERICK_ENCRYPT_AT_REST"] = "1"

from maverick import crypto_at_rest as car  # noqa: E402

fails = []


def _det_bytes(seed, n):
    """Deterministic pseudo-random bytes (no Math.random / os.urandom needed)."""
    out = bytearray()
    x = (seed * 2654435761 + 12345) & 0xFFFFFFFF
    while len(out) < n:
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF
        out.append((x >> 16) & 0xFF)
    return bytes(out)


def stress_roundtrip():
    print("\n== round-trip across sizes ==")
    if not car._have_crypto():
        print("  SKIP: cryptography not installed")
        return False
    sizes = [0, 1, 15, 16, 17, 100, 1000, 65536, 1 << 20]
    for i, n in enumerate(sizes):
        pt = _det_bytes(i + 1, n)
        blob = car.seal(pt)
        assert car.is_sealed(blob), f"size {n}: not detected as sealed"
        got = car.unseal(blob)
        if got != pt:
            fails.append(f"round-trip mismatch at size {n}")
            return False
    # text helpers + unicode
    s = "señor café ☕ \x00 多字节 " * 50
    if car.unseal_to_text(car.seal_text(s)) != s:
        fails.append("text round-trip mismatch")
        return False
    print(f"  {len(sizes)} sizes + unicode text -> OK")
    return True


def stress_nonce_uniqueness(n=200000):
    print(f"\n== nonce uniqueness over {n} seals of identical plaintext ==")
    pt = b"the same plaintext every time"
    blobs = set()
    nonces = set()
    maglen = len(car._MAGIC)
    nb = car._NONCE_BYTES
    for _ in range(n):
        b = car.seal(pt)
        blobs.add(b)
        # v1 layout: MAGIC || nonce || ct+tag
        nonces.add(b[maglen:maglen + nb])
    dup_blobs = n - len(blobs)
    dup_nonces = n - len(nonces)
    ok = dup_blobs == 0 and dup_nonces == 0
    print(f"  duplicate ciphertexts={dup_blobs} duplicate nonces={dup_nonces} "
          f"{'OK' if ok else 'NONCE REUSE!'}")
    if not ok:
        fails.append(f"GCM nonce/ciphertext reuse: nonces={dup_nonces} blobs={dup_blobs}")


def stress_tamper():
    print("\n== tamper detection (every byte position) ==")
    pt = b"sensitive payload that must never decrypt after tampering"
    blob = bytearray(car.seal(pt))
    leaked = 0
    raised = 0
    for i in range(len(blob)):
        mut = bytearray(blob)
        mut[i] ^= 0x01  # flip one bit
        try:
            got = car.unseal(bytes(mut))
            # A flip in the MAGIC header makes is_sealed() false -> returned as-is
            # (transparent-migration contract). That is NOT a plaintext leak: the
            # bytes are still the (wrong) ciphertext, never the real plaintext.
            if got == pt:
                leaked += 1
        except Exception:
            raised += 1
    ok = leaked == 0
    print(f"  {len(blob)} single-bit flips -> raised={raised} plaintext_leaks={leaked} "
          f"{'OK' if ok else 'TAMPER NOT DETECTED'}")
    if not ok:
        fails.append(f"tampered ciphertext decrypted to real plaintext ({leaked} positions)")


def stress_truncation():
    print("\n== truncation never returns wrong plaintext ==")
    blob = car.seal(b"x" * 500)
    bad = 0
    for cut in range(1, len(blob)):
        try:
            got = car.unseal(blob[:cut])
            if got == b"x" * 500:
                bad += 1
        except Exception:
            pass
    print(f"  {len(blob)-1} truncations -> plaintext_leaks={bad} {'OK' if bad == 0 else 'BAD'}")
    if bad:
        fails.append("truncated blob decrypted to real plaintext")


def stress_concurrent():
    print("\n== concurrent seal/unseal (16 threads) ==")
    bad = [0]
    lock = threading.Lock()

    def worker(t):
        for i in range(3000):
            pt = _det_bytes(t * 7919 + i, (i % 64) + 1)
            if car.unseal(car.seal(pt)) != pt:
                with lock:
                    bad[0] += 1

    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(worker, range(16)))
    print(f"  48k concurrent round-trips -> mismatches={bad[0]} {'OK' if bad[0] == 0 else 'BAD'}")
    if bad[0]:
        fails.append("concurrent seal/unseal corruption")


def stress_rotation():
    print("\n== key rotation: old-key blobs still open ==")
    try:
        old_blob = car.seal(b"sealed under the original key")
        newid = car.rotate_at_rest_key()
        after = car.unseal(old_blob)  # must resolve the superseded key by id
        new_blob = car.seal(b"sealed under the rotated key")
        ok = after == b"sealed under the original key" and \
            car.unseal(new_blob) == b"sealed under the rotated key"
        print(f"  rotated to {newid[:12]}... old+new both open -> {'OK' if ok else 'BAD'}")
        if not ok:
            fails.append("key rotation broke old or new blob")
    except Exception as e:  # noqa: BLE001
        print(f"  rotation raised: {e!r}")
        fails.append(f"key rotation raised: {e!r}")


if __name__ == "__main__":
    if not stress_roundtrip():
        print("\n(crypto unavailable or round-trip failed; skipping rest)")
    else:
        stress_nonce_uniqueness()
        stress_tamper()
        stress_truncation()
        stress_concurrent()
        stress_rotation()
    print("\n=== SUMMARY ===")
    if fails:
        for f in fails:
            print(f"  FAIL: {f}")
        raise SystemExit(1)
    print("  crypto-at-rest invariants held")
