"""Encryption helpers for customer data stored for durable payment dispatch."""

from cryptography.fernet import Fernet, InvalidToken


class PhoneNumberCipher:
    """Encrypt phone numbers at rest when a Fernet key is configured."""

    PREFIX = "enc:v1:"

    def __init__(self, key: str | None, *, required: bool = False) -> None:
        if required and not key:
            raise ValueError("FRINGEPAY_PII_ENCRYPTION_KEY is required in production")
        try:
            self._fernet = Fernet(key.encode("ascii")) if key else None
        except (ValueError, UnicodeEncodeError) as exc:
            raise ValueError("FRINGEPAY_PII_ENCRYPTION_KEY must be a valid Fernet key") from exc

    def encrypt(self, value: str | None) -> str | None:
        if value is None or self._fernet is None:
            return value
        token = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return f"{self.PREFIX}{token}"

    def decrypt(self, value: str | None) -> str | None:
        if value is None or not value.startswith(self.PREFIX):
            return value
        if self._fernet is None:
            raise RuntimeError("encrypted phone number cannot be read without its key")
        token = value[len(self.PREFIX) :]
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeEncodeError) as exc:
            raise RuntimeError("stored phone number could not be decrypted") from exc
