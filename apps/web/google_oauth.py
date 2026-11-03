import json

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow


def is_google_oauth_configured() -> bool:
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def create_google_oauth_flow(*, scopes, redirect_uri, state=None) -> Flow:
    if not is_google_oauth_configured():
        raise ImproperlyConfigured(
            "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET."
        )

    client_config = {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": (
                "https://www.googleapis.com/oauth2/v1/certs"
            ),
            "redirect_uris": [redirect_uri],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=scopes,
        state=state,
        redirect_uri=redirect_uri,
    )


def credentials_from_json(token_json: str, scopes) -> Credentials:
    token_info = json.loads(token_json)
    if not isinstance(token_info, dict):
        raise ValueError("Stored Google OAuth token must be a JSON object.")

    token_info["client_id"] = (
        token_info.get("client_id") or settings.GOOGLE_OAUTH_CLIENT_ID
    )
    token_info["client_secret"] = (
        token_info.get("client_secret") or settings.GOOGLE_OAUTH_CLIENT_SECRET
    )
    if not token_info["client_id"] or not token_info["client_secret"]:
        raise ImproperlyConfigured(
            "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET."
        )
    return Credentials.from_authorized_user_info(token_info, scopes)


def credentials_to_json(credentials: Credentials) -> str:
    token_info = json.loads(credentials.to_json())
    if (
        token_info.get("client_id") == settings.GOOGLE_OAUTH_CLIENT_ID
        and token_info.get("client_secret") == settings.GOOGLE_OAUTH_CLIENT_SECRET
    ):
        token_info.pop("client_id", None)
        token_info.pop("client_secret", None)
    return json.dumps(token_info)
