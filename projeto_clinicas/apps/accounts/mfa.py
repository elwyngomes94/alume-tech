"""
Autenticacao em dois fatores (TOTP - RFC 6238).

Implementacao sem dependencias externas, compativel com Google Authenticator,
Authy, Microsoft Authenticator e 1Password.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6
#: Tolerancia de 1 janela para tras/frente (relogios levemente dessincronizados)
ALLOWED_DRIFT = 1


def generate_secret() -> str:
    """Gera um segredo base32 de 160 bits."""
    return base64.b32encode(secrets.token_bytes(20)).decode("utf-8").rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    padding = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(secret.upper() + padding, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**DIGITS)).zfill(DIGITS)


def current_code(secret: str, at: float | None = None) -> str:
    counter = int((at or time.time()) // STEP_SECONDS)
    return _hotp(secret, counter)


def verify_code(secret: str, code: str, at: float | None = None) -> bool:
    """Valida o codigo informado considerando a tolerancia de relogio."""
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return False
    counter = int((at or time.time()) // STEP_SECONDS)
    for drift in range(-ALLOWED_DRIFT, ALLOWED_DRIFT + 1):
        if hmac.compare_digest(_hotp(secret, counter + drift), code):
            return True
    return False


def provisioning_uri(secret: str, email: str, issuer: str = "Alume Tech") -> str:
    """URI otpauth:// para leitura via QR Code."""
    label = quote(f"{issuer}:{email}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def generate_backup_codes(quantity: int = 8) -> list[str]:
    return [f"{secrets.randbelow(10**8):08d}" for _ in range(quantity)]
