from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any


_VAULT_META_KEY = "_vault"


def _load_crypto() -> tuple[Any, Any, Any]:
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "cryptography is required only when ContextVault encryption is enabled. "
            "Install it with: pip install cryptography"
        ) from exc
    return hashes, AESGCM, PBKDF2HMAC


@dataclass(frozen=True)
class VaultPayload:
    version: int
    salt_b64: str
    nonce_b64: str
    ciphertext_b64: str
    kdf: str = "PBKDF2-HMAC-SHA256"
    iterations: int = 390000
    cipher: str = "AES-256-GCM"

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "salt": self.salt_b64,
            "nonce": self.nonce_b64,
            "ciphertext": self.ciphertext_b64,
            "kdf": self.kdf,
            "iterations": int(self.iterations),
            "cipher": self.cipher,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VaultPayload":
        return cls(
            version=int(raw.get("version", 1)),
            salt_b64=str(raw.get("salt") or ""),
            nonce_b64=str(raw.get("nonce") or ""),
            ciphertext_b64=str(raw.get("ciphertext") or ""),
            kdf=str(raw.get("kdf") or "PBKDF2-HMAC-SHA256"),
            iterations=int(raw.get("iterations") or 390000),
            cipher=str(raw.get("cipher") or "AES-256-GCM"),
        )


class ContextVault:
    def __init__(
        self,
        *,
        enabled: bool = False,
        passphrase: str | None = None,
        iterations: int = 390000,
    ) -> None:
        self.enabled = bool(enabled)
        self.iterations = int(iterations)
        self._passphrase = (passphrase or "").encode("utf-8")
        if self.enabled and not self._passphrase:
            raise ValueError("ContextVault is enabled but no passphrase was provided")

    @classmethod
    def from_env(
        cls,
        *,
        enabled: bool,
        passphrase_env_var: str = "OPENMIURA_VAULT_PASSPHRASE",
        iterations: int = 390000,
    ) -> "ContextVault":
        return cls(
            enabled=enabled,
            passphrase=os.environ.get(passphrase_env_var, ""),
            iterations=iterations,
        )

    def is_enabled(self) -> bool:
        return bool(self.enabled)

    def _derive_key(self, salt: bytes, *, iterations: int | None = None) -> bytes:
        hashes, _, PBKDF2HMAC = _load_crypto()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=int(iterations or self.iterations),
        )
        return kdf.derive(self._passphrase)

    def encrypt_text(self, plaintext: str, *, aad: bytes | None = None) -> VaultPayload:
        if not self.enabled:
            raise RuntimeError("ContextVault is disabled")
        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = self._derive_key(salt)
        _, AESGCM, _ = _load_crypto()
        ciphertext = AESGCM(key).encrypt(nonce, (plaintext or "").encode("utf-8"), aad)
        return VaultPayload(
            version=1,
            salt_b64=base64.b64encode(salt).decode("ascii"),
            nonce_b64=base64.b64encode(nonce).decode("ascii"),
            ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
            iterations=self.iterations,
        )

    def decrypt_text(self, payload: VaultPayload | dict[str, Any], *, aad: bytes | None = None) -> str:
        if not self.enabled:
            raise RuntimeError("ContextVault is disabled")
        if isinstance(payload, dict):
            payload = VaultPayload.from_dict(payload)
        salt = base64.b64decode(payload.salt_b64.encode("ascii"))
        nonce = base64.b64decode(payload.nonce_b64.encode("ascii"))
        ciphertext = base64.b64decode(payload.ciphertext_b64.encode("ascii"))
        key = self._derive_key(salt, iterations=payload.iterations)
        _, AESGCM, _ = _load_crypto()
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
        return plaintext.decode("utf-8")

    def encrypt_meta(self, text: str, meta: dict[str, Any] | None = None, *, aad: bytes | None = None) -> tuple[str, dict[str, Any]]:
        meta = dict(meta or {})
        if not self.enabled:
            return text, meta
        payload = self.encrypt_text(text, aad=aad)
        meta[_VAULT_META_KEY] = payload.as_dict()
        return "[encrypted]", meta

    def decrypt_meta(self, stored_text: str, meta: dict[str, Any] | None = None, *, aad: bytes | None = None) -> str:
        meta = dict(meta or {})
        payload = meta.get(_VAULT_META_KEY)
        if not payload:
            return stored_text
        if not self.enabled:
            raise RuntimeError("Encrypted memory found but ContextVault is disabled")
        return self.decrypt_text(payload, aad=aad)

    @staticmethod
    def is_encrypted_meta(meta: dict[str, Any] | None = None) -> bool:
        return bool(meta and isinstance(meta, dict) and meta.get(_VAULT_META_KEY))

    @staticmethod
    def strip_vault_meta(meta: dict[str, Any] | None = None) -> dict[str, Any]:
        meta = dict(meta or {})
        meta.pop(_VAULT_META_KEY, None)
        return meta


def memory_aad(*, user_key: str, kind: str) -> bytes:
    return f"{user_key}:{kind}".encode("utf-8")
