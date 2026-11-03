from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured
from encrypted_fields.fields import EncryptedTextField as FernetEncryptedTextField


class StrictEncryptedTextField(FernetEncryptedTextField):
    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return self.f.decrypt(value.encode()).decode()
        except (InvalidToken, UnicodeEncodeError, ValueError) as exc:
            raise ImproperlyConfigured(
                "Could not decrypt a Gmail token. Check FIELD_ENCRYPTION_SALT_KEYS "
                "and DJANGO_SECRET_KEY."
            ) from exc
