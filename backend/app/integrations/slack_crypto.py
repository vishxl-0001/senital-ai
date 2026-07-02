"""
Encryption for per-tenant Slack bot tokens at rest (Phase 4, item 13).

Bot tokens (xoxb-...) grant posting to a customer's workspace, so they are
encrypted with Fernet (AES-128-CBC + HMAC) before being stored in the tenants
table, keyed by SLACK_TOKEN_ENCRYPTION_KEY. Losing that key makes stored tokens
unreadable (re-install required); rotating it requires re-encrypting rows.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SlackTokenCryptoError(RuntimeError):
    """Raised when encryption isn't configured or a token can't be decrypted."""


def _fernet() -> Fernet:
    key = settings.SLACK_TOKEN_ENCRYPTION_KEY
    if not key:
        raise SlackTokenCryptoError(
            "SLACK_TOKEN_ENCRYPTION_KEY is not set — cannot store/read Slack bot "
            "tokens. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str) -> str:
    """Encrypt a bot token for storage. Returns a URL-safe token string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored bot token. Raises SlackTokenCryptoError on tamper/wrong key."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise SlackTokenCryptoError("Failed to decrypt Slack token (wrong key or corrupted)") from e
