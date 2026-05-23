"""Unit tests for Django settings."""

from django.conf import settings

from config.settings_parts.rest import build_rest_settings
from config.settings_parts.security import build_security_settings


class TestSettings:
    """Test Django settings configuration."""

    def test_debug_setting_exists(self):
        """Test DEBUG setting exists."""
        assert hasattr(settings, "DEBUG")
        assert isinstance(settings.DEBUG, bool)

    def test_secret_key_exists(self):
        """Test SECRET_KEY is configured."""
        assert hasattr(settings, "SECRET_KEY")
        assert len(settings.SECRET_KEY) > 0

    def test_installed_apps_includes_required_apps(self):
        """Test required apps are installed."""
        required_apps = [
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "rest_framework",
        ]

        for app in required_apps:
            assert app in settings.INSTALLED_APPS

    def test_custom_apps_installed(self):
        """Test custom apps are installed."""
        custom_apps = [
            "apps.accounts",
            "apps.market",
            "apps.trading",
            "apps.health",
        ]

        for app in custom_apps:
            assert app in settings.INSTALLED_APPS

    def test_database_configured(self):
        """Test database is configured."""
        assert hasattr(settings, "DATABASES")
        assert "default" in settings.DATABASES
        assert "ENGINE" in settings.DATABASES["default"]

    def test_jwt_settings_configured(self):
        """Test JWT settings are configured."""
        assert hasattr(settings, "JWT_SECRET_KEY")
        assert hasattr(settings, "JWT_ALGORITHM")
        assert hasattr(settings, "JWT_EXPIRATION_DELTA")
        assert hasattr(settings, "OANDA_TOKEN_ENCRYPTION_KEY")

    def test_celery_settings_configured(self):
        """Test Celery settings are configured."""
        assert hasattr(settings, "CELERY_BROKER_URL")
        assert hasattr(settings, "CELERY_RESULT_BACKEND")

    def test_cors_settings_configured(self):
        """Test CORS settings are configured."""
        assert hasattr(settings, "CORS_ALLOWED_ORIGINS") or hasattr(
            settings, "CORS_ALLOW_ALL_ORIGINS"
        )
        assert "corsheaders" in settings.INSTALLED_APPS
        assert "corsheaders.middleware.CorsMiddleware" in settings.MIDDLEWARE

    def test_default_local_csrf_origins_include_vite_proxy(self, monkeypatch):
        """Default local origins include the Vite dev server used by the frontend."""
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        monkeypatch.delenv("CSRF_TRUSTED_ORIGINS", raising=False)

        security_settings = build_security_settings(debug=True)

        assert "http://localhost:5173" in security_settings["CORS_ALLOWED_ORIGINS"]
        assert "http://127.0.0.1:5173" in security_settings["CORS_ALLOWED_ORIGINS"]
        assert "http://localhost:5173" in security_settings["CSRF_TRUSTED_ORIGINS"]
        assert "http://127.0.0.1:5173" in security_settings["CSRF_TRUSTED_ORIGINS"]

    def test_local_security_origins_append_vite_proxy_when_env_is_legacy(self, monkeypatch):
        """Legacy local .env values still allow the Vite dev server."""
        monkeypatch.setenv("DJANGO_ENV", "development")
        monkeypatch.setenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        )
        monkeypatch.setenv(
            "CSRF_TRUSTED_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        )

        security_settings = build_security_settings(debug=False)

        assert "http://localhost:5173" in security_settings["CORS_ALLOWED_ORIGINS"]
        assert "http://localhost:5173" in security_settings["CSRF_TRUSTED_ORIGINS"]

    def test_rest_framework_configured(self):
        """Test REST framework is configured."""
        assert hasattr(settings, "REST_FRAMEWORK")
        assert isinstance(settings.REST_FRAMEWORK, dict)

    def test_default_throttles_are_redis_resilient(self):
        """Default DRF throttles should not 500 when Redis throttle cache is saturated."""
        rest_settings, _schema_settings = build_rest_settings(debug=False, version="test")

        assert rest_settings["DEFAULT_THROTTLE_CLASSES"] == [
            "apps.common.throttling.ResilientUserRateThrottle",
            "apps.common.throttling.ResilientAnonRateThrottle",
        ]
