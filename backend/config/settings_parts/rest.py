"""REST and schema settings helpers."""

from __future__ import annotations


def build_rest_settings(
    *, debug: bool, version: str
) -> tuple[dict[str, object], dict[str, object]]:
    """Return DRF and drf-spectacular settings."""
    rest_framework = {
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "apps.accounts.auth.JWTAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
        "DEFAULT_RENDERER_CLASSES": [
            "rest_framework.renderers.JSONRenderer",
        ],
        "DEFAULT_PARSER_CLASSES": [
            "rest_framework.parsers.JSONParser",
        ],
        "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
        "PAGE_SIZE": 50,
        "DEFAULT_THROTTLE_CLASSES": [
            "apps.common.throttling.ResilientUserRateThrottle",
            "apps.common.throttling.ResilientAnonRateThrottle",
        ],
        "DEFAULT_THROTTLE_RATES": {
            "user": "120/minute",
            "anon": "30/minute",
            "task_data": "600/minute",
        },
        "DEFAULT_FILTER_BACKENDS": [
            "rest_framework.filters.SearchFilter",
            "rest_framework.filters.OrderingFilter",
        ],
        "EXCEPTION_HANDLER": "apps.accounts.api_logging.custom_exception_handler",
        "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%S.%fZ",
        "DATE_FORMAT": "%Y-%m-%d",
        "TIME_FORMAT": "%H:%M:%S",
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    }

    spectacular_settings = {
        "TITLE": "Auto Forex Trader API",
        "DESCRIPTION": (
            "Auto Forex Trader Backend API.\n\n"
            "## Authentication\n"
            "Most endpoints require JWT authentication. "
            "Include the token in the `Authorization: Bearer <token>` header.\n\n"
            "## Rate Limiting\n"
            "Authentication endpoints are rate-limited to prevent abuse."
        ),
        "VERSION": version,
        "SERVE_INCLUDE_SCHEMA": False,
        "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"] if debug else [],
        "SCHEMA_PATH_PREFIX": "/api/",
        "COMPONENT_SPLIT_REQUEST": True,
        "TAGS": [
            {"name": "Accounts", "description": "Authentication and user management"},
            {"name": "Health", "description": "System health checks"},
            {"name": "Market", "description": "Market data and OANDA integration"},
            {"name": "Trading", "description": "Trading tasks and strategy management"},
        ],
        "EXTENSIONS": [
            "apps.accounts.openapi.JWTAuthenticationExtension",
        ],
        "APPEND_COMPONENTS": {
            "schemas": {
                "ApiError": {
                    "type": "object",
                    "required": ["error", "error_code"],
                    "properties": {
                        "error": {"type": "string"},
                        "error_code": {"type": "string"},
                        "detail": {},
                        "message": {"type": "string"},
                        "retry_after": {"type": "integer"},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "ENUM_NAME_OVERRIDES": {
            "EventTypeEnum": "apps.trading.enums.EventType.choices",
        },
    }

    return rest_framework, spectacular_settings
