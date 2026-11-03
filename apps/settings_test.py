from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "test-secret-key"
DEBUG = True
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "apps.app.apps.AppConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "apps.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(BASE_DIR / "apps" / "app" / "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "apps.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "test.sqlite3"),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "admin_app.User"
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_API_FALLBACK_URLS: list[str] = []
OVERPASS_USER_AGENT = "GeoLeadsMailer-test/1.0"

GOOGLE_OAUTH_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
GOOGLE_OAUTH_CLIENT_SECRET = "test-client-secret"
PUBLIC_BASE_URL = "https://testserver"

# Staly klucz testowy - testy szyfrowania musza byc deterministyczne.
SALT_KEY = ["test-field-encryption-salt"]

COOKIE_SECURE = False
# Runner testow wymusza DEBUG=False, wiec checki produkcyjne trzeba wylaczyc jawnie.
AUTH_CONFIG_STRICT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=10),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "CHECK_REVOKE_TOKEN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": "test-jwt-signing-key",
    "ISSUER": "geoleadsmailer",
    "LEEWAY": 10,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "JTI_CLAIM": "jti",
}

AUTH_COOKIE = {
    "ACCESS_NAME": "gl_access",
    "REFRESH_NAME": "gl_refresh",
    "LINK_NAME": "gl_link",
    "PATH_ACCESS": "/",
    "PATH_REFRESH": "/api/auth",
    "DOMAIN": None,
    "SECURE": False,
    "HTTPONLY": True,
    "SAMESITE": "Lax",
    "LINK_MAX_AGE": 600,
}

MEDIA_ROOT = BASE_DIR / "test-uploads"
MEDIA_URL = "/media/"
EMAIL_ATTACHMENTS_DIR = str(MEDIA_ROOT / "email_attachments")

RABBITMQ_BROKER_URL = "memory://"
REDIS_BROKER_URL = "memory://"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}
