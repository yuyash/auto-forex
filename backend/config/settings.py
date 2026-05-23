"""
Django settings for auto_forex project.

Auto Forex Trader Backend Configuration

Configuration is done via environment variables and this settings file.
- .env file: Secrets (passwords, keys, credentials)
- Environment variables: Configuration overrides
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from config.settings_parts.celery import build_celery_settings
from config.settings_parts.logging import build_logging_settings
from config.settings_parts.rest import build_rest_settings
from config.settings_parts.security import build_secret_settings, build_security_settings
from config.version import get_version

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file in project root.
# Shell/container environment should take precedence over local .env values.
load_dotenv(BASE_DIR.parent / ".env", override=False)

# =============================================================================
# Server Configuration
# =============================================================================

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
_secret_settings = build_secret_settings(debug=DEBUG)
SECRET_KEY = _secret_settings["SECRET_KEY"]
IS_TEST_ENV = _secret_settings["IS_TEST_ENV"]
IS_LOCAL_ENV = _secret_settings["IS_LOCAL_ENV"]
IS_NON_PRODUCTION_ENV = _secret_settings["IS_NON_PRODUCTION_ENV"]

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]

TRUSTED_PROXY_CIDRS = [
    cidr.strip()
    for cidr in os.getenv("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128").split(",")
    if cidr.strip()
]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "django_celery_beat",
    # Local apps
    "apps.accounts",
    "apps.health",
    "apps.market",
    "apps.trading",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "apps.accounts.middlewares.csp.CSPMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Custom security and logging middleware
    "apps.accounts.middlewares.logging.HTTPAccessLoggingMiddleware",
    "apps.accounts.middlewares.security.SecurityMonitoringMiddleware",
]

ROOT_URLCONF = "config.urls"

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

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# =============================================================================
# Database Configuration
# =============================================================================

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.postgresql"),
        "NAME": os.getenv("DB_NAME", "auto-forex"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", "postgres"),
        "HOST": os.getenv("DB_HOST", "postgres"),
        "PORT": os.getenv("DB_PORT", "5432"),
        # In development we default to non-persistent DB connections to avoid
        # exhausting Postgres max_connections when running multiple local processes.
        "CONN_MAX_AGE": int(
            os.getenv(
                "DB_CONN_MAX_AGE",
                (
                    "0"
                    if os.getenv("DJANGO_ENV", "development").strip().lower()
                    in {"development", "dev", "local"}
                    else "600"
                ),
            )
        ),
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

db_application_name = os.getenv("DB_APPLICATION_NAME", "").strip()
if db_application_name:
    db_options = DATABASES["default"].get("OPTIONS")
    if isinstance(db_options, dict):
        db_options["application_name"] = db_application_name


# =============================================================================
# Redis Configuration
# =============================================================================

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
REDIS_CACHE_MAX_CONNECTIONS = int(os.getenv("REDIS_CACHE_MAX_CONNECTIONS", "20"))
REDIS_CACHE_POOL_TIMEOUT = float(os.getenv("REDIS_CACHE_POOL_TIMEOUT", "2"))

REDIS_URL = (
    f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    if REDIS_PASSWORD
    else f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
)


# =============================================================================
# Cache Configuration (Redis)
# =============================================================================

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "db": REDIS_DB,
            "pool_class": "redis.BlockingConnectionPool",
            "max_connections": REDIS_CACHE_MAX_CONNECTIONS,
            "timeout": REDIS_CACHE_POOL_TIMEOUT,
        },
        "KEY_PREFIX": "auto_forex",
        "TIMEOUT": 300,
    }
}


# =============================================================================
# Session Configuration (Redis)
# =============================================================================

# Security settings
JWT_EXPIRATION = int(os.getenv("JWT_EXPIRATION", "3600"))  # 1 hour
MAX_LOGIN_ATTEMPTS = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_DURATION = int(os.getenv("LOCKOUT_DURATION", "900"))  # 15 minutes
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # 1 minute

SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"
SESSION_COOKIE_AGE = JWT_EXPIRATION
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"


# =============================================================================
# Celery Configuration
# =============================================================================

globals().update(build_celery_settings(REDIS_URL, REDIS_DB))


# =============================================================================
# Market Tick Pub/Sub
# =============================================================================

REDIS_MARKET_DB = int(os.getenv("REDIS_MARKET_DB", "3"))
MARKET_REDIS_URL = (
    f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_MARKET_DB}"
    if REDIS_PASSWORD
    else f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_MARKET_DB}"
)

MARKET_TICK_CHANNEL = os.getenv("MARKET_TICK_CHANNEL", "market:ticks")
MARKET_TICK_INSTRUMENTS = [
    x.strip() for x in os.getenv("MARKET_TICK_INSTRUMENTS", "EUR_USD").split(",") if x.strip()
]

MARKET_TICK_PUBSUB_INIT_KEY = os.getenv("MARKET_TICK_PUBSUB_INIT_KEY", "market:tick_pubsub:init")
MARKET_TICK_ACCOUNT_KEY = os.getenv("MARKET_TICK_ACCOUNT_KEY", "market:tick_pubsub:account")
MARKET_TICK_PUBLISHER_LOCK_KEY = os.getenv(
    "MARKET_TICK_PUBLISHER_LOCK_KEY", "market:tick_publisher:lock"
)
MARKET_TICK_SUBSCRIBER_LOCK_KEY = os.getenv(
    "MARKET_TICK_SUBSCRIBER_LOCK_KEY", "market:tick_subscriber:lock"
)
MARKET_TICK_SUPERVISOR_LOCK_KEY = os.getenv(
    "MARKET_TICK_SUPERVISOR_LOCK_KEY", "market:tick_supervisor:lock"
)
MARKET_TICK_SUPERVISOR_INTERVAL = int(os.getenv("MARKET_TICK_SUPERVISOR_INTERVAL", "30"))
MARKET_TICK_SUBSCRIBER_BATCH_SIZE = int(os.getenv("MARKET_TICK_SUBSCRIBER_BATCH_SIZE", "200"))
MARKET_TICK_SUBSCRIBER_FLUSH_INTERVAL = int(os.getenv("MARKET_TICK_SUBSCRIBER_FLUSH_INTERVAL", "2"))


# =============================================================================
# Market Backtest Tick Stream (Redis Streams) — reliable delivery
# =============================================================================
#
# Backtest ticks are delivered over Redis Streams instead of Pub/Sub.  Pub/Sub
# messages are dropped silently when the subscriber's Redis output buffer
# overflows (``client-output-buffer-limit pubsub``), which caused silent tick
# loss during long backtests.  Streams are persistent and cap at ``MAXLEN``,
# providing natural backpressure.

# Per-request stream key: f"{MARKET_BACKTEST_TICK_STREAM_PREFIX}{request_id}"
MARKET_BACKTEST_TICK_STREAM_PREFIX = os.getenv(
    "MARKET_BACKTEST_TICK_STREAM_PREFIX",
    "market:backtest:stream:",
)

# Controls how many rows Django fetches from DB per chunk during publishing.
MARKET_BACKTEST_PUBLISH_BATCH_SIZE = int(os.getenv("MARKET_BACKTEST_PUBLISH_BATCH_SIZE", "1000"))

# Stream capacity: the publisher trims with ``XADD ... MAXLEN ~ N`` so the
# stream stays bounded even if the subscriber lags.  ``~`` allows approximate
# trimming for performance.  Should be comfortably larger than
# ``MARKET_BACKTEST_BACKPRESSURE_HIGH_WATERMARK``.
MARKET_BACKTEST_STREAM_MAXLEN = int(os.getenv("MARKET_BACKTEST_STREAM_MAXLEN", "200000"))

# Backpressure: when the pending entries in the stream exceed this high
# watermark the publisher pauses until the subscriber drains below the low
# watermark.  This keeps the publisher in lockstep with the consumer.
MARKET_BACKTEST_BACKPRESSURE_HIGH_WATERMARK = int(
    os.getenv("MARKET_BACKTEST_BACKPRESSURE_HIGH_WATERMARK", "100000")
)
MARKET_BACKTEST_BACKPRESSURE_LOW_WATERMARK = int(
    os.getenv("MARKET_BACKTEST_BACKPRESSURE_LOW_WATERMARK", "50000")
)
# Check Redis consumer lag once every N published ticks unless the publisher is
# already paused.  This removes a Redis round-trip from the hot path while the
# headroom clamp in the task keeps MAXLEN trimming safe.
MARKET_BACKTEST_BACKPRESSURE_CHECK_INTERVAL = int(
    os.getenv("MARKET_BACKTEST_BACKPRESSURE_CHECK_INTERVAL", "100")
)
# Sleep interval when waiting for the subscriber to drain.
MARKET_BACKTEST_BACKPRESSURE_SLEEP_SECONDS = float(
    os.getenv("MARKET_BACKTEST_BACKPRESSURE_SLEEP_SECONDS", "0.5")
)
# Stop checks are still invoked from the publisher loop, but DB probes are
# throttled to this interval to avoid one executor-status query per tick.
MARKET_BACKTEST_STOP_CHECK_INTERVAL_SECONDS = float(
    os.getenv("MARKET_BACKTEST_STOP_CHECK_INTERVAL_SECONDS", "1.0")
)

# XREAD BLOCK timeout in milliseconds.  Controls how long the subscriber waits
# for new entries before returning (and rechecking stop flags).
MARKET_BACKTEST_STREAM_BLOCK_MS = int(os.getenv("MARKET_BACKTEST_STREAM_BLOCK_MS", "1000"))

# How many entries the subscriber requests per ``XREAD`` call.
MARKET_BACKTEST_STREAM_READ_COUNT = int(os.getenv("MARKET_BACKTEST_STREAM_READ_COUNT", "500"))

# Number of ticks delivered from the backtest data source to the executor per
# batch.  Larger batches reduce Redis ACKs, heartbeat checks, and progress
# flush decisions.  The executor still checks stop signals inside each batch.
TRADING_BACKTEST_TICK_BATCH_SIZE = int(os.getenv("TRADING_BACKTEST_TICK_BATCH_SIZE", "1000"))

# Subscriber gives up after this many consecutive empty reads *while* it is
# caught up with the publisher (comparing its ``last_seen_id`` against the
# stream's ``last-generated-id``).  Empty reads that happen while the
# publisher is still producing or paused for backpressure do not count
# toward this timeout — otherwise the backpressure pause would misfire as
# "stream ended".
MARKET_BACKTEST_STREAM_IDLE_TIMEOUT_READS = int(
    os.getenv("MARKET_BACKTEST_STREAM_IDLE_TIMEOUT_READS", "300")
)

# Consumer group name shared by the publisher (to measure lag via
# ``XPENDING``) and the subscriber (to claim entries via ``XREADGROUP``).
# A single group is sufficient because there is exactly one consumer per
# backtest run.
MARKET_BACKTEST_STREAM_CONSUMER_GROUP = os.getenv(
    "MARKET_BACKTEST_STREAM_CONSUMER_GROUP", "backtest"
)

# Runtime gap detection: if the executor sees the delivered tick timestamp
# jump forward by more than this many hours (and the gap is not a regular
# weekend closure), the run is aborted.  This prevents silent data loss from
# being mistaken for a valid backtest result.
MARKET_BACKTEST_MAX_TICK_GAP_HOURS = int(os.getenv("MARKET_BACKTEST_MAX_TICK_GAP_HOURS", "120"))

# When replaying aggregated tick buckets (``tick_granularity != "tick"``),
# emit a WARNING log for any bucket whose intra-bar bid range (high - low)
# exceeds this many pips.  A wide intra-bar range means the bucket's single
# representative price hides significant movement, which can cause SL / TP
# trigger semantics to fire at prices far from the intended level (see the
# stop-loss drift issue on 1-minute replays).  Set to ``0`` to disable.
MARKET_BACKTEST_BAR_RANGE_WARNING_PIPS = float(
    os.getenv("MARKET_BACKTEST_BAR_RANGE_WARNING_PIPS", "30")
)
# Maximum per-bucket warning lines before switching to one summary line.  The
# range check remains enabled; only repeated log output is suppressed.
MARKET_BACKTEST_BAR_RANGE_WARNING_LIMIT = int(
    os.getenv("MARKET_BACKTEST_BAR_RANGE_WARNING_LIMIT", "25")
)


# Django REST Framework Configuration
# https://www.django-rest-framework.org/api-guide/settings/

REST_FRAMEWORK, SPECTACULAR_SETTINGS = build_rest_settings(debug=DEBUG, version=get_version())


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 8,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Custom User Model
# https://docs.djangoproject.com/en/5.2/topics/auth/customizing/#substituting-a-custom-user-model

AUTH_USER_MODEL = "accounts.User"


# =============================================================================
# Logging Configuration
# =============================================================================

globals().update(build_logging_settings(BASE_DIR))
TASK_LOG_BUFFER_SIZE = int(os.getenv("TASK_LOG_BUFFER_SIZE", "100"))
STRATEGY_METRICS_QUERY_LOG_THRESHOLD_SECONDS = float(
    os.getenv("STRATEGY_METRICS_QUERY_LOG_THRESHOLD_SECONDS", "0.5")
)


# =============================================================================
# Security Settings
# =============================================================================
# https://docs.djangoproject.com/en/5.2/topics/security/

globals().update(build_security_settings(debug=DEBUG))


# =============================================================================
# JWT Configuration
# =============================================================================

JWT_SECRET_KEY = _secret_settings["JWT_SECRET_KEY"]
JWT_ALGORITHM = _secret_settings["JWT_ALGORITHM"]
JWT_EXPIRATION_DELTA = JWT_EXPIRATION
OANDA_TOKEN_ENCRYPTION_KEY = _secret_settings["OANDA_TOKEN_ENCRYPTION_KEY"]
OANDA_TOKEN_ENCRYPTION_FALLBACK_KEYS = _secret_settings["OANDA_TOKEN_ENCRYPTION_FALLBACK_KEYS"]
REFRESH_TOKEN_EXPIRATION = _secret_settings["REFRESH_TOKEN_EXPIRATION"]  # 7 days
AUTH_REFRESH_COOKIE_NAME = _secret_settings["AUTH_REFRESH_COOKIE_NAME"]
AUTH_REFRESH_COOKIE_HTTPONLY = _secret_settings["AUTH_REFRESH_COOKIE_HTTPONLY"]
AUTH_REFRESH_COOKIE_SECURE = _secret_settings["AUTH_REFRESH_COOKIE_SECURE"]
AUTH_REFRESH_COOKIE_SAMESITE = _secret_settings["AUTH_REFRESH_COOKIE_SAMESITE"]
AUTH_REFRESH_COOKIE_PATH = _secret_settings["AUTH_REFRESH_COOKIE_PATH"]
AUTH_REFRESH_COOKIE_DOMAIN = _secret_settings["AUTH_REFRESH_COOKIE_DOMAIN"]
AUTH_REFRESH_COOKIE_MAX_AGE = _secret_settings["AUTH_REFRESH_COOKIE_MAX_AGE"]
AUTH_ACCESS_COOKIE_NAME = _secret_settings["AUTH_ACCESS_COOKIE_NAME"]
AUTH_ACCESS_COOKIE_HTTPONLY = _secret_settings["AUTH_ACCESS_COOKIE_HTTPONLY"]
AUTH_ACCESS_COOKIE_SECURE = _secret_settings["AUTH_ACCESS_COOKIE_SECURE"]
AUTH_ACCESS_COOKIE_SAMESITE = _secret_settings["AUTH_ACCESS_COOKIE_SAMESITE"]
AUTH_ACCESS_COOKIE_PATH = _secret_settings["AUTH_ACCESS_COOKIE_PATH"]
AUTH_ACCESS_COOKIE_DOMAIN = _secret_settings["AUTH_ACCESS_COOKIE_DOMAIN"]


# =============================================================================
# Frontend Configuration
# =============================================================================

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


# =============================================================================
# OANDA API Configuration
# =============================================================================

OANDA_PRACTICE_API = os.getenv("OANDA_PRACTICE_API", "https://api-fxpractice.oanda.com")
OANDA_LIVE_API = os.getenv("OANDA_LIVE_API", "https://api-fxtrade.oanda.com")
OANDA_STREAM_TIMEOUT = int(os.getenv("OANDA_STREAM_TIMEOUT", "30"))
OANDA_REST_TIMEOUT = int(os.getenv("OANDA_REST_TIMEOUT", "30"))
OANDA_REST_MAX_RETRIES = int(os.getenv("OANDA_REST_MAX_RETRIES", "2"))
OANDA_ACCOUNT_SNAPSHOT_STALE_SECONDS = int(os.getenv("OANDA_ACCOUNT_SNAPSHOT_STALE_SECONDS", "300"))
OANDA_ACCOUNT_SNAPSHOT_REFRESH_ACTIVE_TTL_SECONDS = int(
    os.getenv("OANDA_ACCOUNT_SNAPSHOT_REFRESH_ACTIVE_TTL_SECONDS", "900")
)

# Live-trading safety guardrails. These are enforced when a TradingTask is
# submitted, before the worker can place any broker orders.
TRADING_ALLOW_LIVE_OANDA = os.getenv("TRADING_ALLOW_LIVE_OANDA", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
TRADING_LIVE_ALLOWED_INSTRUMENTS = [
    instrument.strip().upper()
    for instrument in os.getenv(
        "TRADING_LIVE_ALLOWED_INSTRUMENTS",
        "USD_JPY,EUR_USD,GBP_USD,AUD_USD,USD_CAD,USD_CHF,NZD_USD",
    ).split(",")
    if instrument.strip()
]
TRADING_LIVE_MAX_INITIAL_UNITS = int(os.getenv("TRADING_LIVE_MAX_INITIAL_UNITS", "10000"))
TRADING_LIVE_MAX_ORDER_UNITS = int(os.getenv("TRADING_LIVE_MAX_ORDER_UNITS", "10000"))
TRADING_LIVE_MAX_ESTIMATED_EXPOSURE_UNITS = int(
    os.getenv("TRADING_LIVE_MAX_ESTIMATED_EXPOSURE_UNITS", "200000")
)
