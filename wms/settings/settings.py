from pathlib import Path

# pyrefly: ignore [missing-import]
import environ
from datetime import timedelta

env = environ.Env(
    DEBUG=(bool, False),
)


BASE_DIR = Path(__file__).resolve().parent.parent.parent

environ.Env.read_env(BASE_DIR / ".env", overwrite=True)

SECRET_KEY = env("SECRET_KEY", default="changeme")

DEBUG = env.bool("DEBUG", default=True)

# CORS Configuration — explicit allow-list defined below (line ~193)
# CORS_ALLOW_ALL_ORIGINS is intentionally left unset here; it is set to False below.

ALLOWED_HOSTS: list[str] = ["*"]
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "https://stockpad-smoky.vercel.app",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ],
)

INSTALLED_APPS = [
    # Media & Static Storage
    'cloudinary',
    'cloudinary_storage',
    
    # Django core apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party apps
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "corsheaders",
    "drf_spectacular",

    # Local apps
    "users",
    "inventory",
    "notifications",
    "reports",
    "settings_app",
]

AUTH_USER_MODEL = "users.User"

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "wms.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

WSGI_APPLICATION = "wms.wsgi.application"
ASGI_APPLICATION = "wms.asgi.application"

# WM site PostgreSQL schema — single source of truth for all environments.
WM_SITE_DB_OPTIONS = {"options": '-c search_path="WM_site"'}

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgresql://USER:PASSWORD@HOST:6543/postgres?sslmode=require",
    )
}

DATABASES["default"].setdefault("OPTIONS", {}).update(WM_SITE_DB_OPTIONS)



AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

SESSION_COOKIE_AGE = 60 * 60 * 24  # Exactly 24 hours in seconds
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/day",
        "user": "1000/day",
        "site_b_catalog": "60/minute",
        "site_b_request_create": "30/minute",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# Celery & Redis Task Queue Configuration
CELERY_BROKER_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

import sys
if "test" in sys.argv or getattr(sys, "_called_from_test", False):
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
        }
    }

CELERY_BEAT_SCHEDULE = {
    "recompute-ai-insights-hourly": {
        "task": "inventory.tasks.recompute_ai_insights_task",
        "schedule": 3600.0,
    },
    # Phase 5: check for webhook retry spikes every 15 minutes
    "check-webhook-retry-spike-every-15min": {
        "task": "inventory.tasks.check_webhook_retry_spike",
        "schedule": 900.0,
    },
}

# Phase 5: Webhook Retry Spike Alerting
# Fires a CRITICAL log when rolling 1-hour retry count reaches this value.
WEBHOOK_RETRY_SPIKE_THRESHOLD = env.int("WEBHOOK_RETRY_SPIKE_THRESHOLD", default=5)


SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "WMS API",
    "DESCRIPTION": "Warehouse Management System API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOW_ALL_ORIGINS = False

# Additional CORS settings for better frontend compatibility
# Static list covers the canonical production URL and local dev.
# All Vercel preview deployments are covered by CORS_ALLOWED_ORIGIN_REGEXES below.
_DEFAULT_CORS_ORIGINS = [
    "https://stockpad-smoky.vercel.app",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=_DEFAULT_CORS_ORIGINS)

# Allow ALL Vercel preview deployments via regex so that new per-commit
# preview URLs (e.g. stockpad-abc123-user-projects.vercel.app) work
# automatically without having to update CORS_ALLOWED_ORIGINS each time.
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://stockpad[\w-]*\.vercel\.app$",
    r"^https://[\w-]+-amirbinalaas-projects\.vercel\.app$",
]

APPEND_SLASH = False

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

# Email Configuration
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='StockPad <noreply@stockpad.com>')

GOOGLE_CLIENT_ID = env('GOOGLE_CLIENT_ID', default='')
GOOGLE_CLIENT_SECRET = env('GOOGLE_CLIENT_SECRET', default='')

SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"
SECURE_CROSS_ORIGIN_EMBEDDER_POLICY = "unsafe-none"

SITE_B_API_KEY = env("SITE_B_API_KEY", default="")

# Phase 5 — Key rotation transition window.
# During a rotation, populate *_NEW while keeping the old key active.
# Once Site B has switched to the new key, blank out the old one.
# Site A accepts BOTH keys during the overlap window (see HasSiteBAPIKey permission).
# SITE_A_API_KEY_NEW is used for outbound HMAC signing on webhook delivery.
SITE_A_API_KEY_NEW = env("SITE_A_API_KEY_NEW", default="")
SITE_B_API_KEY_NEW = env("SITE_B_API_KEY_NEW", default="")


import sys
if "test" in sys.argv:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db_test.sqlite3",
        }
    }

# Cloudinary Configuration for Media Files
from django.core.exceptions import ImproperlyConfigured

CLOUDINARY_STORAGE = {
    'CLOUD_NAME': env('CLOUDINARY_CLOUD_NAME', default=''),
    'API_KEY': env('CLOUDINARY_API_KEY', default=''),
    'API_SECRET': env('CLOUDINARY_API_SECRET', default=''),
}

# Determine if running in production
IS_PRODUCTION = (
    env('DJANGO_ENV', default='') == 'production'
    or env('ENVIRONMENT', default='') == 'production'
    or env.get_value('DJANGO_SETTINGS_MODULE', default='').endswith('.production')
    or not env.bool("DEBUG", default=False)
)
IS_TESTING = 'test' in sys.argv

has_cloudinary_creds = bool(
    CLOUDINARY_STORAGE.get('CLOUD_NAME')
    and CLOUDINARY_STORAGE.get('API_KEY')
    and CLOUDINARY_STORAGE.get('API_SECRET')
)

if IS_PRODUCTION and not IS_TESTING:
    if not has_cloudinary_creds:
        raise ImproperlyConfigured(
            "Cloudinary credentials (CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET) "
            "must be configured in the production environment."
        )
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
else:
    # Local/testing fallback
    if has_cloudinary_creds:
        DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
    else:
        DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# NOTE: SECURE_CROSS_ORIGIN_OPENER_POLICY is set to "same-origin-allow-popups"
# above (line ~229) and must NOT be overridden to None — Google Sign-In popups
# require this header to be present on every response.

import os
# Relax SSL security settings in local/dev environments only.
# DEBUG itself is controlled by:
#   - development.py  (local:  DEBUG=True)
#   - production.py   (prod:   DEBUG=env.bool("DEBUG", default=False))
# This guard only suppresses SSL redirects that would break local HTTP.
if os.environ.get('DJANGO_ENV') not in ('production', 'staging'):
    SECURE_SSL_REDIRECT = False
    SECURE_PROXY_SSL_HEADER = None
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

