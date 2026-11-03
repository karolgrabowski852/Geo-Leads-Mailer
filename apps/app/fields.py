from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


class EncryptedTextField(models.TextField):
    @staticmethod
    def _fernet() -> MultiFernet:
        keys = getattr(settings, "FIELD_ENCRYPTION_KEYS", [])
        if not keys:
            raise ImproperlyConfigured(
                "FIELD_ENCRYPTION_KEYS must contain a Fernet key to access Gmail tokens."
            )
        try:
            return MultiFernet(
                [Fernet(key.encode() if isinstance(key, str) else key) for key in keys]
            )
        except (TypeError, ValueError) as exc:
            raise ImproperlyConfigured(
                "FIELD_ENCRYPTION_KEYS must contain valid Fernet keys."
            ) from exc

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return self._fernet().decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ImproperlyConfigured(
                "Could not decrypt a Gmail token. Check FIELD_ENCRYPTION_KEYS."
            ) from exc

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return self._fernet().encrypt(value.encode()).decode()
