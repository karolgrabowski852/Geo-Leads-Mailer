import re

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

EMAIL_CANDIDATE_REGEX = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)
_email_validator = EmailValidator()


def extract_valid_emails(value: str) -> list[str]:
    emails = {}
    for candidate in EMAIL_CANDIDATE_REGEX.findall(value or ""):
        try:
            _email_validator(candidate)
        except ValidationError:
            continue
        emails.setdefault(candidate.casefold(), candidate)
    return list(emails.values())
