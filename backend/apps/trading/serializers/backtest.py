"""Serializers for backtest tasks."""

import logging
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.market.models import OandaAccounts
from apps.trading.enums import TaskStatus
from apps.trading.money import Money
from apps.trading.models import BacktestTask, StrategyConfiguration
from apps.trading.services.task_policy import (
    action_policy_for_task,
    task_update_validation_error,
)
from apps.trading.services.public_errors import (
    task_public_error_code,
    task_public_error_message,
)
from apps.trading.serializers.money import (
    CurrencyConversionContextSerializer,
    MoneySerializer,
    TaskMoneyContextSerializer,
)
from apps.trading.serializers.instrument import TaskInstrumentContextSerializer
from apps.trading.services.task_currencies import (
    default_currency_for_language,
    instrument_currency_options,
    normalize_currency,
)
from apps.trading.services.task_instrument_context import TASK_INSTRUMENT_CONTEXT
from apps.trading.services.task_money_context import TASK_MONEY_CONTEXT

logger = logging.getLogger(__name__)


class BacktestTaskSerializer(serializers.ModelSerializer):
    """Serializer for BacktestTask full details."""

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    config_id = serializers.UUIDField(source="config.id", read_only=True)
    config_name = serializers.CharField(source="config.name", read_only=True)
    config_revision = serializers.IntegerField(source="config.revision", read_only=True)
    config_hash = serializers.CharField(source="config.config_hash", read_only=True)
    strategy_type = serializers.CharField(source="config.strategy_type", read_only=True)
    can_resume = serializers.SerializerMethodField()
    action_policy = serializers.SerializerMethodField()
    error_message = serializers.SerializerMethodField()
    error_code = serializers.SerializerMethodField()
    display_currency = serializers.SerializerMethodField()
    initial_balance_money = serializers.SerializerMethodField()
    commission_per_trade_money = serializers.SerializerMethodField()
    instrument_context = serializers.SerializerMethodField()
    money_context = serializers.SerializerMethodField()
    oanda_candle_filter_account_name = serializers.CharField(
        source="oanda_candle_filter_account.account_id",
        read_only=True,
    )

    class Meta:
        model = BacktestTask
        fields = [
            "id",
            "user_id",
            "config_id",
            "config_name",
            "config_revision",
            "config_hash",
            "strategy_type",
            "name",
            "description",
            "data_source",
            "start_time",
            "end_time",
            "initial_balance",
            "initial_balance_money",
            "account_currency",
            "display_currency",
            "money_context",
            "commission_per_trade",
            "commission_per_trade_money",
            "pip_size",
            "instrument_context",
            "instrument",
            "hedging_enabled",
            "tick_granularity",
            "tick_window_value_mode",
            "drain_duration_hours",
            "market_idle_pre_close_minutes",
            "market_idle_resume_delay_minutes",
            "market_close_enabled",
            "market_close_weekday",
            "market_close_hour_utc",
            "market_open_weekday",
            "market_open_hour_utc",
            "max_tick_gap_hours",
            "backtest_tick_batch_size",
            "spread_filter_enabled",
            "max_spread_pips",
            "oanda_candle_filter_enabled",
            "oanda_candle_filter_account",
            "oanda_candle_filter_account_name",
            "oanda_candle_filter_granularity",
            "oanda_candle_filter_tolerance_pips",
            "holidays_enabled",
            "excluded_dates",
            "initial_positions_enabled",
            "initial_position_cycles",
            "in_memory_mode",
            "sell_on_stop",
            "status",
            "execution_id",
            "started_at",
            "completed_at",
            "error_message",
            "error_code",
            "status_reason_code",
            "status_reason_message",
            "created_at",
            "updated_at",
            "debug_options",
            "can_resume",
            "action_policy",
        ]
        read_only_fields = [
            "id",
            "user_id",
            "config_id",
            "config_name",
            "config_revision",
            "config_hash",
            "strategy_type",
            "status",
            "execution_id",
            "started_at",
            "completed_at",
            "error_message",
            "error_code",
            "status_reason_code",
            "status_reason_message",
            "created_at",
            "updated_at",
            "initial_balance_money",
            "commission_per_trade_money",
            "instrument_context",
            "money_context",
            "oanda_candle_filter_account_name",
            "can_resume",
            "action_policy",
        ]

    def get_can_resume(self, obj: BacktestTask) -> bool:
        """Check if task can be resumed with state recovery."""
        return obj.can_resume()

    def get_action_policy(self, obj: BacktestTask) -> dict[str, bool]:
        """Return task action permissions."""
        return action_policy_for_task(obj, task_type="backtest").as_dict()

    def get_error_message(self, obj: BacktestTask) -> str | None:
        """Return a fixed public failure message without internal details."""
        return task_public_error_message(obj.status)

    def get_error_code(self, obj: BacktestTask) -> str | None:
        """Return the stable public failure code."""
        return task_public_error_code(obj.status)

    def get_display_currency(self, obj: BacktestTask) -> str:
        """Return the effective display currency."""
        return obj.effective_display_currency

    @extend_schema_field(MoneySerializer)
    def get_initial_balance_money(self, obj: BacktestTask) -> dict[str, str]:
        """Return the initial balance with its account currency."""
        return Money.coerce(obj.initial_balance, obj.account_currency).as_dict()

    @extend_schema_field(MoneySerializer)
    def get_commission_per_trade_money(self, obj: BacktestTask) -> dict[str, str]:
        """Return the per-trade commission with its account currency."""
        return Money.coerce(obj.commission_per_trade, obj.account_currency).as_dict()

    @extend_schema_field(TaskInstrumentContextSerializer)
    def get_instrument_context(self, obj: BacktestTask) -> dict[str, object]:
        """Return instrument metadata and pip-size diagnostics."""
        return TASK_INSTRUMENT_CONTEXT.build(obj).as_dict()

    @extend_schema_field(TaskMoneyContextSerializer)
    def get_money_context(self, obj: BacktestTask) -> dict[str, object]:
        """Return task currency choices and money DTOs."""
        return TASK_MONEY_CONTEXT.build(obj, task_type="backtest").as_dict()


class BacktestTaskListSerializer(BacktestTaskSerializer):
    """Serializer for BacktestTask list view (summary only).

    Inherits all fields from BacktestTaskSerializer but drops
    commission details and ``execution_id``, and marks everything read-only.
    """

    class Meta(BacktestTaskSerializer.Meta):
        fields = [
            f
            for f in BacktestTaskSerializer.Meta.fields
            if f not in {"commission_per_trade", "commission_per_trade_money", "execution_id"}
        ]
        read_only_fields = fields


class BacktestBalanceAdjustmentSerializer(serializers.Serializer):
    """Request serializer for changing a resumable backtest execution balance."""

    current_balance = serializers.DecimalField(
        max_digits=20,
        decimal_places=10,
        min_value=Decimal("0"),
        help_text="New current balance for the paused or stopped backtest execution.",
    )
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Optional audit note for the balance change.",
    )


class BacktestBalanceAdjustmentResponseSerializer(serializers.Serializer):
    """Response serializer for backtest balance changes."""

    task_id = serializers.UUIDField()
    execution_id = serializers.UUIDField()
    previous_balance = serializers.DecimalField(max_digits=20, decimal_places=10)
    previous_balance_currency = serializers.CharField(max_length=3)
    previous_balance_money = MoneySerializer()
    current_balance = serializers.DecimalField(max_digits=20, decimal_places=10)
    current_balance_currency = serializers.CharField(max_length=3)
    current_balance_money = MoneySerializer()
    current_balance_display_money = MoneySerializer(allow_null=True, required=False)
    adjustment = serializers.DecimalField(max_digits=20, decimal_places=10)
    adjustment_currency = serializers.CharField(max_length=3)
    adjustment_money = MoneySerializer()
    adjustment_display_money = MoneySerializer(allow_null=True, required=False)
    previous_balance_display_money = MoneySerializer(allow_null=True, required=False)
    display_conversion_context = CurrencyConversionContextSerializer(
        allow_null=True,
        required=False,
    )
    currency = serializers.CharField(max_length=3)
    state_version = serializers.IntegerField()


class BacktestTaskCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating and updating BacktestTask."""

    oanda_candle_filter_account = serializers.PrimaryKeyRelatedField(
        queryset=OandaAccounts.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = BacktestTask
        fields = [
            "config",
            "name",
            "description",
            "data_source",
            "start_time",
            "end_time",
            "initial_balance",
            "account_currency",
            "display_currency",
            "commission_per_trade",
            "pip_size",
            "instrument",
            "hedging_enabled",
            "tick_granularity",
            "tick_window_value_mode",
            "drain_duration_hours",
            "market_idle_pre_close_minutes",
            "market_idle_resume_delay_minutes",
            "market_close_enabled",
            "market_close_weekday",
            "market_close_hour_utc",
            "market_open_weekday",
            "market_open_hour_utc",
            "max_tick_gap_hours",
            "backtest_tick_batch_size",
            "spread_filter_enabled",
            "max_spread_pips",
            "oanda_candle_filter_enabled",
            "oanda_candle_filter_account",
            "oanda_candle_filter_granularity",
            "oanda_candle_filter_tolerance_pips",
            "holidays_enabled",
            "excluded_dates",
            "initial_positions_enabled",
            "initial_position_cycles",
            "in_memory_mode",
            "sell_on_stop",
            "debug_options",
        ]
        # Make fields optional for partial updates (PATCH)
        extra_kwargs = {
            "name": {"required": False},
            "data_source": {"required": False},
            "start_time": {"required": False},
            "end_time": {"required": False},
            "initial_balance": {"required": False},
            "account_currency": {"required": False},
            "display_currency": {"required": False},
            "commission_per_trade": {"required": False},
            "pip_size": {"required": False},
            "instrument": {"required": False},
            "hedging_enabled": {"required": False},
            "tick_granularity": {"required": False},
            "tick_window_value_mode": {"required": False},
            "drain_duration_hours": {"required": False, "min_value": 0},
            "market_idle_pre_close_minutes": {"required": False, "min_value": 0},
            "market_idle_resume_delay_minutes": {"required": False, "min_value": 0},
            "market_close_enabled": {"required": False},
            "market_close_weekday": {
                "required": False,
                "min_value": 0,
                "max_value": 6,
            },
            "market_close_hour_utc": {
                "required": False,
                "min_value": 0,
                "max_value": 23,
            },
            "market_open_weekday": {
                "required": False,
                "min_value": 0,
                "max_value": 6,
            },
            "market_open_hour_utc": {
                "required": False,
                "min_value": 0,
                "max_value": 23,
            },
            "max_tick_gap_hours": {"required": False, "min_value": 1},
            "backtest_tick_batch_size": {
                "required": False,
                "min_value": 1,
                "max_value": 50000,
            },
            "spread_filter_enabled": {"required": False},
            "max_spread_pips": {"required": False, "min_value": Decimal("0")},
            "oanda_candle_filter_enabled": {"required": False},
            "oanda_candle_filter_granularity": {"required": False},
            "oanda_candle_filter_tolerance_pips": {
                "required": False,
                "min_value": Decimal("0"),
            },
            "holidays_enabled": {"required": False},
            "excluded_dates": {"required": False},
            "initial_positions_enabled": {"required": False},
            "initial_position_cycles": {"required": False},
            "in_memory_mode": {"required": False},
            "sell_on_stop": {"required": False},
            "debug_options": {"required": False},
        }

    def validate_config(self, value: StrategyConfiguration) -> StrategyConfiguration:
        """Validate that config belongs to the user."""
        user = self.context["request"].user
        if value.user != user:
            raise serializers.ValidationError("Configuration does not belong to the current user")
        return value

    def validate_initial_balance(self, value: Decimal) -> Decimal:
        """Validate initial balance is positive."""
        if value <= 0:
            raise serializers.ValidationError("Initial balance must be positive")
        return value

    def validate_account_currency(self, value: str) -> str:
        """Normalize account currency codes."""
        currency = normalize_currency(value)
        if not currency:
            raise serializers.ValidationError("Account currency must be a 3-letter code")
        return currency

    def validate_display_currency(self, value: str) -> str:
        """Normalize optional display currency codes."""
        if value in (None, ""):
            return ""
        currency = normalize_currency(value)
        if not currency:
            raise serializers.ValidationError("Display currency must be a 3-letter code")
        return currency

    def validate_pip_size(self, value: Decimal | None) -> Decimal | None:
        """Validate pip size is positive if provided."""
        if value is not None and value <= 0:
            raise serializers.ValidationError("Pip size must be positive")
        return value

    def validate_oanda_candle_filter_account(
        self, value: OandaAccounts | None
    ) -> OandaAccounts | None:
        """Validate that the candle-validation account belongs to the user."""
        if value is None:
            return None
        user = self.context["request"].user
        if value.user != user:
            raise serializers.ValidationError("Account does not belong to the current user")
        if not value.is_active:
            raise serializers.ValidationError("Account is not active")
        return value

    def validate_excluded_dates(self, value: list | None) -> list:
        """Validate legacy excluded dates and explicit market-closed windows."""
        from datetime import date
        import re
        from zoneinfo import ZoneInfoNotFoundError

        from apps.trading.services.market_holidays import (
            parse_closed_window_datetime,
            serialize_closed_window_datetime,
        )

        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(
                "excluded_dates must be a list of date strings or closed-window objects."
            )

        month_day_pattern = re.compile(r"^\d{2}-\d{2}$")
        seen: set[object] = set()
        normalized: list = []
        for raw in value:
            normalized_value: str | dict
            if isinstance(raw, dict):
                timezone = str(raw.get("timezone") or "").strip()
                if not timezone:
                    raise serializers.ValidationError("Closed window timezone is required.")
                try:
                    start = parse_closed_window_datetime(raw.get("start"), timezone=timezone)
                    end = parse_closed_window_datetime(raw.get("end"), timezone=timezone)
                except ZoneInfoNotFoundError:
                    raise serializers.ValidationError(
                        f"Invalid timezone '{timezone}'. Use an IANA timezone name."
                    ) from None
                except (TypeError, ValueError):
                    raise serializers.ValidationError(
                        "Closed windows require valid start and end datetimes."
                    ) from None
                if start >= end:
                    raise serializers.ValidationError("Closed window start must be before end.")
                normalized_value = {
                    "start": serialize_closed_window_datetime(start),
                    "end": serialize_closed_window_datetime(end),
                    "timezone": timezone,
                }
                dedupe_key = (
                    normalized_value["start"],
                    normalized_value["end"],
                    normalized_value["timezone"],
                )
            elif isinstance(raw, date):
                normalized_value = raw.isoformat()
                dedupe_key = normalized_value
            else:
                text = str(raw or "").strip()
                if not text:
                    continue
                try:
                    normalized_value = date.fromisoformat(text).isoformat()
                except ValueError:
                    if not month_day_pattern.fullmatch(text):
                        raise serializers.ValidationError(
                            f"Invalid date '{raw}'. Expected YYYY-MM-DD or MM-DD."
                        ) from None
                    month, day = (int(part) for part in text.split("-", 1))
                    try:
                        date(2000, month, day)
                    except ValueError:
                        raise serializers.ValidationError(
                            f"Invalid date '{raw}'. Expected YYYY-MM-DD or MM-DD."
                        ) from None
                    normalized_value = f"{month:02d}-{day:02d}"
                dedupe_key = normalized_value
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append(normalized_value)
        return normalized

    def validate_name(self, value: str) -> str:
        """Validate task name uniqueness per user."""
        user = self.context["request"].user
        query = BacktestTask.objects.filter(user=user, name=value)
        if self.instance is not None:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError("A backtest task with this name already exists.")
        return value

    def validate(self, attrs: dict) -> dict:
        """Validate date ranges and configuration."""
        from django.utils import timezone

        start_time = attrs.get("start_time", getattr(self.instance, "start_time", None))
        end_time = attrs.get("end_time", getattr(self.instance, "end_time", None))
        now = timezone.now()

        # Validate date range
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({"start_time": "start_time must be before end_time"})

        # Validate end_time is not in the future
        if end_time and end_time > now:
            raise serializers.ValidationError(
                {
                    "end_time": (
                        "end_time cannot be in the future. Backtesting requires historical data."
                    )
                }
            )

        # Validate start_time is not in the future
        if start_time and start_time > now:
            raise serializers.ValidationError(
                {
                    "start_time": (
                        "start_time cannot be in the future. Backtesting requires historical data."
                    )
                }
            )

        # Validate configuration parameters
        tick_granularity = attrs.get(
            "tick_granularity",
            getattr(self.instance, "tick_granularity", BacktestTask.TickGranularity.TICK),
        )
        tick_window_value_mode = attrs.get(
            "tick_window_value_mode",
            getattr(
                self.instance,
                "tick_window_value_mode",
                BacktestTask.TickWindowValueMode.LAST,
            ),
        )

        valid_granularities = {choice for choice, _ in BacktestTask.TickGranularity.choices}
        if tick_granularity not in valid_granularities:
            raise serializers.ValidationError(
                {"tick_granularity": f"Unsupported tick granularity: {tick_granularity}"}
            )

        valid_modes = {choice for choice, _ in BacktestTask.TickWindowValueMode.choices}
        if tick_window_value_mode not in valid_modes:
            raise serializers.ValidationError(
                {
                    "tick_window_value_mode": (
                        f"Unsupported tick window value mode: {tick_window_value_mode}"
                    )
                }
            )

        spread_filter_enabled = attrs.get(
            "spread_filter_enabled",
            getattr(self.instance, "spread_filter_enabled", False),
        )
        max_spread_pips = attrs.get(
            "max_spread_pips",
            getattr(self.instance, "max_spread_pips", Decimal("0")),
        )
        if spread_filter_enabled and max_spread_pips <= 0:
            raise serializers.ValidationError(
                {"max_spread_pips": "Max spread pips must be greater than zero when enabled."}
            )

        candle_filter_enabled = attrs.get(
            "oanda_candle_filter_enabled",
            getattr(self.instance, "oanda_candle_filter_enabled", False),
        )
        candle_filter_account = attrs.get(
            "oanda_candle_filter_account",
            getattr(self.instance, "oanda_candle_filter_account", None),
        )
        candle_granularity = attrs.get(
            "oanda_candle_filter_granularity",
            getattr(
                self.instance,
                "oanda_candle_filter_granularity",
                BacktestTask.OandaCandleGranularity.MINUTE_1,
            ),
        )
        candle_tolerance_pips = attrs.get(
            "oanda_candle_filter_tolerance_pips",
            getattr(self.instance, "oanda_candle_filter_tolerance_pips", Decimal("5")),
        )
        valid_candle_granularities = {
            choice for choice, _ in BacktestTask.OandaCandleGranularity.choices
        }
        if candle_granularity not in valid_candle_granularities:
            raise serializers.ValidationError(
                {
                    "oanda_candle_filter_granularity": (
                        f"Unsupported OANDA candle granularity: {candle_granularity}"
                    )
                }
            )
        if candle_filter_enabled and candle_filter_account is None:
            raise serializers.ValidationError(
                {
                    "oanda_candle_filter_account": (
                        "OANDA account is required when candle validation is enabled."
                    )
                }
            )
        if candle_filter_enabled and candle_tolerance_pips <= 0:
            raise serializers.ValidationError(
                {
                    "oanda_candle_filter_tolerance_pips": (
                        "Candle tolerance pips must be greater than zero when enabled."
                    )
                }
            )

        config = attrs.get("config") or getattr(self.instance, "config", None)
        if not config:
            raise serializers.ValidationError({"config": "Strategy configuration is required"})
        is_valid, error_message = config.validate_parameters()
        if not is_valid:
            raise serializers.ValidationError({"config": error_message})

        initial_positions_enabled = attrs.get(
            "initial_positions_enabled",
            getattr(self.instance, "initial_positions_enabled", False),
        )
        initial_position_cycles = attrs.get(
            "initial_position_cycles",
            getattr(self.instance, "initial_position_cycles", []),
        )
        in_memory_mode = attrs.get(
            "in_memory_mode",
            getattr(self.instance, "in_memory_mode", False),
        )
        if in_memory_mode is True and initial_positions_enabled:
            raise serializers.ValidationError(
                {
                    "initial_positions_enabled": (
                        "Initial positions are not supported in in-memory mode."
                    )
                }
            )
        if initial_positions_enabled:
            from apps.trading.services.backtest_initial_positions import (
                InitialPositionValidationError,
                validate_initial_position_cycles,
            )

            try:
                validate_initial_position_cycles(
                    task=self.instance,
                    config=config,
                    cycles=initial_position_cycles,
                    pip_size=attrs.get("pip_size", getattr(self.instance, "pip_size", None)),
                )
            except InitialPositionValidationError as exc:
                raise serializers.ValidationError(exc.errors) from exc

        # Validate instrument is provided
        instrument = attrs.get("instrument", getattr(self.instance, "instrument", None))
        if not instrument:
            raise serializers.ValidationError({"instrument": "Instrument is required"})
        self._apply_currency_defaults(attrs, instrument)
        self._validate_currency_options(attrs, instrument)

        # Validate tick data exists for the requested date range
        if start_time and end_time and instrument:
            from django.db.models import Max, Min

            from apps.market.models import TickData

            agg = TickData.objects.filter(instrument=instrument).aggregate(
                min_ts=Min("timestamp"),
                max_ts=Max("timestamp"),
            )
            if agg["min_ts"] is None:
                raise serializers.ValidationError(
                    {
                        "instrument": (
                            f"No tick data available for {instrument}. "
                            "Please choose an instrument that has historical data."
                        )
                    }
                )
            if start_time < agg["min_ts"]:
                raise serializers.ValidationError(
                    {
                        "start_time": (
                            f"start_time is before the earliest available tick data "
                            f"({agg['min_ts'].isoformat()}). "
                            "Please choose a later start time."
                        )
                    }
                )
            if end_time > agg["max_ts"]:
                raise serializers.ValidationError(
                    {
                        "end_time": (
                            f"end_time is after the latest available tick data "
                            f"({agg['max_ts'].isoformat()}). "
                            "Please choose an earlier end time."
                        )
                    }
                )

        return attrs

    def _request_language(self) -> str:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return str(getattr(user, "language", "") or "")

    def _apply_currency_defaults(self, attrs: dict, instrument: str) -> None:
        options = instrument_currency_options(instrument)
        default_currency = default_currency_for_language(instrument, self._request_language())
        if self.instance is None:
            attrs["account_currency"] = (
                normalize_currency(attrs.get("account_currency")) or default_currency
            )
            attrs["display_currency"] = (
                normalize_currency(attrs.get("display_currency")) or default_currency
            )
            return

        if "instrument" in attrs and options:
            current_account = normalize_currency(
                attrs.get("account_currency", self.instance.account_currency)
            )
            current_display = normalize_currency(
                attrs.get(
                    "display_currency",
                    self.instance.display_currency or self.instance.account_currency,
                )
            )
            if "account_currency" not in attrs and current_account not in options:
                attrs["account_currency"] = default_currency
            if "display_currency" not in attrs and current_display not in options:
                attrs["display_currency"] = default_currency

        if "account_currency" in attrs:
            attrs["account_currency"] = normalize_currency(attrs["account_currency"])
        if "display_currency" in attrs:
            attrs["display_currency"] = (
                normalize_currency(attrs["display_currency"]) or default_currency
            )

    def _validate_currency_options(self, attrs: dict, instrument: str) -> None:
        options = instrument_currency_options(instrument)
        if not options:
            return
        errors: dict[str, str] = {}
        for field in ("account_currency", "display_currency"):
            if self.instance is not None and field not in attrs:
                continue
            currency = normalize_currency(attrs.get(field))
            if not currency:
                errors[field] = "Currency is required."
            elif currency not in options:
                errors[field] = f"Currency must be one of {', '.join(options)} for {instrument}."
        if errors:
            raise serializers.ValidationError(errors)

    def create(self, validated_data: dict) -> BacktestTask:
        """Create backtest task with user from context."""
        from apps.trading.utils import pip_size_for_instrument

        user = self.context["request"].user
        validated_data["user"] = user
        instrument = validated_data.get("instrument") or "USD_JPY"
        default_currency = default_currency_for_language(
            instrument,
            getattr(user, "language", ""),
        )
        validated_data["account_currency"] = (
            normalize_currency(validated_data.get("account_currency")) or default_currency
        )
        validated_data["display_currency"] = (
            normalize_currency(validated_data.get("display_currency")) or default_currency
        )

        # Auto-populate pip_size from instrument when not explicitly provided
        if instrument and not validated_data.get("pip_size"):
            validated_data["pip_size"] = pip_size_for_instrument(instrument)

        task = BacktestTask.objects.create(**validated_data)
        if not task.in_memory_mode:
            from apps.trading.services.backtest_initial_positions import (
                BacktestInitialPositionService,
            )

            BacktestInitialPositionService().sync_for_task(task)
        return task

    def update(self, instance: BacktestTask, validated_data: dict) -> BacktestTask:
        """Update backtest task."""
        from apps.trading.services.task_audit import audit_task_update, changed_field_values

        error = task_update_validation_error(
            task=instance,
            changed_fields=set(validated_data),
            task_type="backtest",
        )
        if error is not None:
            raise serializers.ValidationError(error)

        changes = changed_field_values(instance, validated_data)
        if "account_currency" in validated_data:
            validated_data["account_currency"] = normalize_currency(
                validated_data["account_currency"]
            )
        if "display_currency" in validated_data:
            validated_data["display_currency"] = normalize_currency(
                validated_data["display_currency"]
            )
        replay_settings_changed = any(
            field in validated_data and validated_data[field] != getattr(instance, field)
            for field in (
                "tick_granularity",
                "tick_window_value_mode",
                "backtest_tick_batch_size",
                "spread_filter_enabled",
                "max_spread_pips",
                "oanda_candle_filter_enabled",
                "oanda_candle_filter_account",
                "oanda_candle_filter_granularity",
                "oanda_candle_filter_tolerance_pips",
            )
        )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if replay_settings_changed and instance.status != TaskStatus.CREATED:
            # Replay settings affect execution continuity. Existing runs must start fresh.
            instance.status = TaskStatus.CREATED
            if instance.execution_id is not None or instance.started_at or instance.completed_at:
                instance.status = TaskStatus.STOPPED

        instance.save()
        preview_seed_fields = {
            "initial_positions_enabled",
            "initial_position_cycles",
            "config",
            "pip_size",
            "instrument",
            "start_time",
            "initial_balance",
            "account_currency",
            "hedging_enabled",
            "in_memory_mode",
        }
        if instance.in_memory_mode:
            from apps.trading.services.backtest_initial_positions import (
                BacktestInitialPositionService,
            )

            BacktestInitialPositionService().clear_preview(instance)
        elif preview_seed_fields & set(validated_data):
            from apps.trading.services.backtest_initial_positions import (
                BacktestInitialPositionService,
            )

            BacktestInitialPositionService().sync_for_task(instance)
        audit_task_update(task=instance, task_type="backtest", changes=changes)
        return instance
