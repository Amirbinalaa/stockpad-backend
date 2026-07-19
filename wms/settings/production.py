from .settings import *
import dj_database_url

DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["stockpad-backend-production.up.railway.app", "127.0.0.1", "localhost"])

# Database — Parse DATABASE_URL from environment, then enforce WM_site schema routing.
_db = dj_database_url.config(
    default=env("DATABASE_URL"),
    conn_max_age=600,
    ssl_require=True,
)
_db.setdefault("OPTIONS", {}).update(WM_SITE_DB_OPTIONS)
DATABASES = {"default": _db}

# Static files
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Security
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO' if DEBUG else 'ERROR',
    },
}

import sys
if "test" in sys.argv:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db_test.sqlite3",
        }
    }
