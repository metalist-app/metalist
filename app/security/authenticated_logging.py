"""Authenticated encryption of what the process prints while a vault is unlocked."""

from __future__ import annotations

from app.security.crypto_sizes import AES_256_KEY_BYTES, GCM_NONCE_BYTES, GCM_TAG_BYTES
import base64
import os
import threading
from typing import TextIO

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


_ENVELOPE_PREFIX = b"MLLOG1 "
_ENVELOPE_AAD = b"MetaList authenticated diagnostic log v1"
_LOG_KEY_INFO = b"MetaList authenticated diagnostic log key v1"


def _validate_dek(dek: bytes) -> None:
    if not isinstance(dek, bytes):
        raise TypeError(f"dek must be bytes, got {type(dek)}")
    if len(dek) != AES_256_KEY_BYTES:
        raise ValueError(f"dek must be {AES_256_KEY_BYTES} bytes, got {len(dek)}")


def _derive_log_key(dek: bytes) -> bytes:
    _validate_dek(dek)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=AES_256_KEY_BYTES,
        salt=None,
        info=_LOG_KEY_INFO,
    ).derive(dek)


def encrypt_log_record(*, plaintext: str, dek: bytes) -> bytes:
    if not isinstance(plaintext, str):
        raise TypeError(f"plaintext must be a string, got {type(plaintext)}")
    log_key = _derive_log_key(dek)
    nonce = os.urandom(GCM_NONCE_BYTES)
    ciphertext_and_tag = AESGCM(log_key).encrypt(
        nonce,
        plaintext.encode("utf-8"),
        _ENVELOPE_AAD,
    )
    payload = base64.b64encode(nonce + ciphertext_and_tag)
    return _ENVELOPE_PREFIX + payload + b"\n"


def decrypt_log_record(*, envelope: bytes, dek: bytes) -> str:
    if not isinstance(envelope, bytes):
        raise TypeError(f"envelope must be bytes, got {type(envelope)}")
    log_key = _derive_log_key(dek)
    normalized = envelope.rstrip(b"\r\n")
    if not normalized.startswith(_ENVELOPE_PREFIX):
        raise ValueError("Encrypted log record is missing the MLLOG1 envelope prefix")
    payload = base64.b64decode(normalized[len(_ENVELOPE_PREFIX):], validate=True)
    minimum_payload_bytes = GCM_NONCE_BYTES + GCM_TAG_BYTES
    if len(payload) < minimum_payload_bytes:
        raise ValueError(
            "Encrypted log record payload is too short: "
            f"expected at least {minimum_payload_bytes} bytes, got {len(payload)}"
        )
    nonce = payload[:GCM_NONCE_BYTES]
    ciphertext_and_tag = payload[GCM_NONCE_BYTES:]
    plaintext = AESGCM(log_key).decrypt(nonce, ciphertext_and_tag, _ENVELOPE_AAD)
    return plaintext.decode("utf-8")


class EncryptedTextStream:
    """Encrypt every text write before forwarding it to a process stream."""

    def __init__(self, *, destination: TextIO, dek: bytes) -> None:
        if not hasattr(destination, "write") or not hasattr(destination, "flush"):
            raise TypeError("destination must be a writable text stream")
        _validate_dek(dek)
        self._destination = destination
        self._dek = dek
        self._lock = threading.Lock()
        self._closed = False

    @property
    def encoding(self) -> str:
        return "ascii"

    @property
    def closed(self) -> bool:
        return self._closed

    def writable(self) -> bool:
        return not self._closed

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        raise RuntimeError("Raw file-descriptor access is disabled during authenticated logging")

    def write(self, message: str) -> int:
        # Under the lock from the check to the write: a close (at logout) waits for a
        # write already under way, and a write after it finds the stream closed.
        with self._lock:
            if self._closed:
                raise RuntimeError("Encrypted text stream is closed")
            if not isinstance(message, str):
                raise TypeError(f"message must be a string, got {type(message)}")
            if message == "":
                return 0
            envelope = encrypt_log_record(plaintext=message, dek=self._dek).decode("ascii")
            self._destination.write(envelope)
            self._destination.flush()
        return len(message)

    def flush(self) -> None:
        with self._lock:
            self._destination.flush()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._destination.flush()
            self._dek = b""
            self._closed = True
