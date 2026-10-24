import os
from pathlib import Path

from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-secret")
DEBUG = False
ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "drf_spectacular",
    "django_celery_beat",
    "tally.adapters",
    "tally.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tally.api.throttle.RateLimitHeadersMiddleware",
]

ROOT_URLCONF = "tally.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    }
]
WSGI_APPLICATION = "tally.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "tally"),
        "USER": os.environ.get("POSTGRES_USER", "tally"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "tally"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5435"),
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6380/0")
CACHES = {"default": {"BACKEND": "django_redis.cache.RedisCache", "LOCATION": REDIS_URL}}
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_BEAT_SCHEDULE = {
    "expire-idempotency": {"task": "tally.adapters.tasks.expire_idempotency", "schedule": 3600},
    "bill-due-subscriptions": {
        "task": "tally.adapters.tasks.bill_due_subscriptions",
        "schedule": 60,
    },
    "deliver-due-webhooks": {"task": "tally.adapters.tasks.deliver_due_webhooks", "schedule": 10},
    "settle-yesterday": {
        "task": "tally.adapters.tasks.settle_yesterday",
        "schedule": crontab(hour=0, minute=5),
    },
}

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "tally.api.auth.ConsoleSessionAuthentication",
        "tally.api.auth.ApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["tally.api.throttle.ApiKeyTokenBucket"],
    "EXCEPTION_HANDLER": "tally.api.problems.handler",
    "UNAUTHENTICATED_USER": None,
}
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "100"))
PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
SPECTACULAR_SETTINGS = {
    "TITLE": "Tally API",
    "DESCRIPTION": "Double-entry ledger and billing. Writes need X-Api-Key and Idempotency-Key.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
    "SERVE_AUTHENTICATION": [],
}

TIME_ZONE = "UTC"
USE_TZ = True

# The built console (`npm run build` in console/) is served from the URL root by whitenoise;
# tally.urls falls back to its index.html for the SPA's deep links.
CONSOLE_DIST = Path(os.environ.get("CONSOLE_DIST", BASE_DIR / "console" / "dist"))
WHITENOISE_ROOT = CONSOLE_DIST
WHITENOISE_INDEX_FILE = True
WHITENOISE_IMMUTABLE_FILE_TEST = lambda path, url: "/assets/" in url  # Vite hashes every asset  # noqa: E731

STRIPE_API_BASE = os.environ.get("STRIPE_API_BASE", "")  # set to stripe-mock in compose and CI
# stripe-mock accepts any well-formed test key; against Stripe itself the env var is required.
STRIPE_TEST_SECRET_KEY = os.environ.get("STRIPE_TEST_SECRET_KEY") or (
    "sk_test_stripemock" if STRIPE_API_BASE else ""
)
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "tally")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "tally12345")
S3_BUCKET = os.environ.get("S3_BUCKET", "reports")
# Shared with Airflow (compose: AIRFLOW_VAR_TALLY_INTERNAL_TOKEN). Guards /internal/*.
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "dev-internal-token")

# OTLP/HTTP collector (Jaeger in compose). Empty disables export; spans are still recorded.
OTEL_EXPORTER_OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")

LOGGING_CONFIG = None  # structlog configured in tally.logging

from tally.logging import configure as _configure_logging  # noqa: E402

_configure_logging(json=True)
