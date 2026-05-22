"""Serializers for trading tasks."""

import logging

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.market.models import OandaAccounts
from apps.trading.enums import TradingMode
from apps.trading.models import StrategyConfiguration, TradingTask
from apps.trading.serializers.instrument import TaskInstrumentContextSerializer
from apps.trading.serializers.money import TaskMoneyContextSerializer
from apps.trading.services.task_currencies import (
    default_currency_for_language,
    instrument_currency_options,
    normalize_currency,
)
from apps.trading.services.task_instrument_context import TASK_INSTRUMENT_CONTEXT
from apps.trading.services.task_money_context import TASK_MONEY_CONTEXT
from apps.trading.services.task_policy import (
    action_policy_for_task,
    task_update_validation_error,
)
from apps.trading.services.public_errors import (
    task_public_error_code,
    task_public_error_message,
)

logger = logging.getLogger(__name__)


class TradingTaskSerializer(serializers.ModelSerializer):
    """
    Serializer for TradingTask full details.
    """

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    config_id = serializers.UUIDField(source="config.id", read_only=True)
    config_name = serializers.CharField(source="config.name", read_only=True)
    config_revision = serializers.IntegerField(source="config.revision", read_only=True)
    config_hash = serializers.CharField(source="config.config_hash", read_only=True)
    strategy_type = serializers.CharField(source="config.strategy_type", read_only=True)
    instrument = serializers.CharField(read_only=True)
    account_id = serializers.IntegerField(source="oanda_account.id", read_only=True)
    account_name = serializers.CharField(source="oanda_account.account_id", read_only=True)
    account_type = serializers.CharField(source="oanda_account.api_type", read_only=True)
    account_currency = serializers.CharField(read_only=True)
    display_currency = serializers.SerializerMethodField()
    action_policy = serializers.SerializerMethodField()
    error_message = serializers.SerializerMethodField()
    error_code = serializers.SerializerMethodField()
    instrument_context = serializers.SerializerMethodField()
    money_context = serializers.SerializerMethodField()
    # State management fields for frontend button logic
    has_strategy_state = serializers.SerializerMethodField()
    can_resume = serializers.SerializerMethodField()

    class Meta:
        model = TradingTask
        fields = [
            "id",
            "user_id",
            "config_id",
            "config_name",
            "config_revision",
            "config_hash",
            "strategy_type",
            "instrument",
            "account_id",
            "account_name",
            "account_type",
            "account_currency",
            "display_currency",
            "money_context",
            "name",
            "description",
            "sell_on_stop",
            "dry_run",
            "hedging_enabled",
            "tick_granularity",
            "initial_positions_enabled",
            "initial_position_cycles",
            "pip_size",
            "instrument_context",
            "status",
            "execution_id",
            "started_at",
            "completed_at",
            "error_message",
            "error_code",
            # Broker API retry policy
            "api_retry_max_attempts",
            "api_retry_backoff_base_seconds",
            "api_retry_backoff_max_seconds",
            # Drain / market-aware idle
            "drain_duration_hours",
            "market_idle_pre_close_minutes",
            "market_idle_resume_delay_minutes",
            "live_tick_stale_guard_enabled",
            "live_tick_max_age_seconds",
            "live_tick_status_log_interval_seconds",
            "broker_drift_check_interval_seconds",
            # State management fields
            "has_strategy_state",
            "can_resume",
            "action_policy",
            "created_at",
            "updated_at",
            "debug_options",
        ]
        read_only_fields = [
            "id",
            "user_id",
            "config_id",
            "config_name",
            "config_revision",
            "config_hash",
            "strategy_type",
            "instrument",
            "account_id",
            "account_name",
            "account_type",
            "account_currency",
            "display_currency",
            "status",
            "execution_id",
            "started_at",
            "completed_at",
            "error_message",
            "error_code",
            "pip_size",
            "instrument_context",
            "money_context",
            "has_strategy_state",
            "can_resume",
            "action_policy",
            "created_at",
            "updated_at",
        ]

    def get_has_strategy_state(self, obj: TradingTask) -> bool:
        """Check if task has saved strategy state."""
        return obj.has_strategy_state()

    def get_can_resume(self, obj: TradingTask) -> bool:
        """Check if task can be resumed with state recovery."""
        return obj.can_resume()

    def get_action_policy(self, obj: TradingTask) -> dict[str, bool]:
        """Return task action permissions."""
        return action_policy_for_task(obj, task_type="trading").as_dict()

    def get_error_message(self, obj: TradingTask) -> str | None:
        """Return a fixed public failure message without internal details."""
        return task_public_error_message(obj.status)

    def get_error_code(self, obj: TradingTask) -> str | None:
        """Return the stable public failure code."""
        return task_public_error_code(obj.status)

    def get_display_currency(self, obj: TradingTask) -> str:
        """Return the effective display currency."""
        return obj.effective_display_currency

    @extend_schema_field(TaskInstrumentContextSerializer)
    def get_instrument_context(self, obj: TradingTask) -> dict[str, object]:
        """Return instrument metadata and pip-size diagnostics."""
        return TASK_INSTRUMENT_CONTEXT.build(obj).as_dict()

    @extend_schema_field(TaskMoneyContextSerializer)
    def get_money_context(self, obj: TradingTask) -> dict[str, object]:
        """Return task currency choices and money DTOs."""
        return TASK_MONEY_CONTEXT.build(obj, task_type="trading").as_dict()


class TradingTaskListSerializer(serializers.ModelSerializer):
    """
    Serializer for TradingTask list view (summary only).
    """

    user_id = serializers.IntegerField(source="user.id", read_only=True)
    config_id = serializers.UUIDField(source="config.id", read_only=True)
    config_name = serializers.CharField(source="config.name", read_only=True)
    config_revision = serializers.IntegerField(source="config.revision", read_only=True)
    config_hash = serializers.CharField(source="config.config_hash", read_only=True)
    strategy_type = serializers.CharField(source="config.strategy_type", read_only=True)
    instrument = serializers.CharField(read_only=True)
    account_id = serializers.IntegerField(source="oanda_account.id", read_only=True)
    account_name = serializers.CharField(source="oanda_account.account_id", read_only=True)
    account_type = serializers.CharField(source="oanda_account.api_type", read_only=True)
    account_currency = serializers.CharField(read_only=True)
    display_currency = serializers.SerializerMethodField()
    action_policy = serializers.SerializerMethodField()
    error_message = serializers.SerializerMethodField()
    error_code = serializers.SerializerMethodField()
    instrument_context = serializers.SerializerMethodField()
    money_context = serializers.SerializerMethodField()

    class Meta:
        model = TradingTask
        fields = [
            "id",
            "user_id",
            "config_id",
            "config_name",
            "config_revision",
            "config_hash",
            "strategy_type",
            "instrument",
            "account_id",
            "account_name",
            "account_type",
            "account_currency",
            "display_currency",
            "money_context",
            "name",
            "description",
            "sell_on_stop",
            "dry_run",
            "hedging_enabled",
            "tick_granularity",
            "initial_positions_enabled",
            "initial_position_cycles",
            "pip_size",
            "instrument_context",
            "status",
            "execution_id",
            "started_at",
            "completed_at",
            "error_message",
            "error_code",
            "api_retry_max_attempts",
            "api_retry_backoff_base_seconds",
            "api_retry_backoff_max_seconds",
            "drain_duration_hours",
            "market_idle_pre_close_minutes",
            "market_idle_resume_delay_minutes",
            "live_tick_stale_guard_enabled",
            "live_tick_max_age_seconds",
            "live_tick_status_log_interval_seconds",
            "broker_drift_check_interval_seconds",
            "action_policy",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_action_policy(self, obj: TradingTask) -> dict[str, bool]:
        """Return task action permissions."""
        return action_policy_for_task(obj, task_type="trading").as_dict()

    def get_error_message(self, obj: TradingTask) -> str | None:
        """Return a fixed public failure message without internal details."""
        return task_public_error_message(obj.status)

    def get_error_code(self, obj: TradingTask) -> str | None:
        """Return the stable public failure code."""
        return task_public_error_code(obj.status)

    def get_display_currency(self, obj: TradingTask) -> str:
        """Return the effective display currency."""
        return obj.effective_display_currency

    @extend_schema_field(TaskInstrumentContextSerializer)
    def get_instrument_context(self, obj: TradingTask) -> dict[str, object]:
        """Return instrument metadata and pip-size diagnostics."""
        return TASK_INSTRUMENT_CONTEXT.build(obj).as_dict()

    @extend_schema_field(TaskMoneyContextSerializer)
    def get_money_context(self, obj: TradingTask) -> dict[str, object]:
        """Return task currency choices and money DTOs."""
        return TASK_MONEY_CONTEXT.build(obj, task_type="trading").as_dict()


class TradingTaskCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating and updating TradingTask.

    Accepts config_id and account_id from the frontend, mapping them
    to the config and oanda_account FK fields.
    """

    config_id = serializers.PrimaryKeyRelatedField(
        queryset=StrategyConfiguration.objects.all(),
        source="config",
        required=False,
    )
    account_id = serializers.PrimaryKeyRelatedField(
        queryset=OandaAccounts.objects.all(),
        source="oanda_account",
        required=False,
    )

    class Meta:
        model = TradingTask
        fields = [
            "config_id",
            "account_id",
            "name",
            "description",
            "instrument",
            "display_currency",
            "sell_on_stop",
            "dry_run",
            "hedging_enabled",
            "tick_granularity",
            "initial_positions_enabled",
            "initial_position_cycles",
            "api_retry_max_attempts",
            "api_retry_backoff_base_seconds",
            "api_retry_backoff_max_seconds",
            "drain_duration_hours",
            "market_idle_pre_close_minutes",
            "market_idle_resume_delay_minutes",
            "live_tick_stale_guard_enabled",
            "live_tick_max_age_seconds",
            "live_tick_status_log_interval_seconds",
            "broker_drift_check_interval_seconds",
            "debug_options",
        ]
        extra_kwargs = {
            "name": {"required": False},
            "description": {"required": False},
            "instrument": {"required": False},
            "display_currency": {"required": False},
            "sell_on_stop": {"required": False},
            "dry_run": {"required": False},
            "hedging_enabled": {"required": False},
            "tick_granularity": {"required": False},
            "initial_positions_enabled": {"required": False},
            "initial_position_cycles": {"required": False},
            "api_retry_max_attempts": {"required": False, "min_value": 1},
            "api_retry_backoff_base_seconds": {"required": False, "min_value": 0},
            "api_retry_backoff_max_seconds": {"required": False, "min_value": 0},
            "drain_duration_hours": {"required": False, "min_value": 0},
            "market_idle_pre_close_minutes": {"required": False, "min_value": 0},
            "market_idle_resume_delay_minutes": {"required": False, "min_value": 0},
            "live_tick_stale_guard_enabled": {"required": False},
            "live_tick_max_age_seconds": {"required": False, "min_value": 1},
            "live_tick_status_log_interval_seconds": {"required": False, "min_value": 0},
            "broker_drift_check_interval_seconds": {"required": False, "min_value": 0},
            "debug_options": {"required": False},
        }

    def validate_config_id(self, value: StrategyConfiguration) -> StrategyConfiguration:
        """Validate that config belongs to the user."""
        user = self.context["request"].user
        if value.user != user:
            raise serializers.ValidationError("Configuration does not belong to the current user")
        return value

    def validate_account_id(self, value: OandaAccounts) -> OandaAccounts:
        """Validate that account belongs to the user and is active."""
        user = self.context["request"].user
        if value.user != user:
            raise serializers.ValidationError("Account does not belong to the current user")
        if not value.is_active:
            raise serializers.ValidationError("Account is not active")
        return value

    def validate_name(self, value: str) -> str:
        """Validate task name uniqueness per user."""
        user = self.context["request"].user
        query = TradingTask.objects.filter(user=user, name=value)
        if self.instance is not None:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError("A trading task with this name already exists.")
        return value

    def validate_display_currency(self, value: str) -> str:
        """Normalize optional display currency codes."""
        if value in (None, ""):
            return ""
        currency = normalize_currency(value)
        if not currency:
            raise serializers.ValidationError("Display currency must be a 3-letter code")
        return currency

    def validate(self, attrs: dict) -> dict:
        """Validate configuration parameters."""
        # On create, config and oanda_account are required
        if not self.instance:
            if "config" not in attrs:
                raise serializers.ValidationError({"config_id": "This field is required."})
            if "oanda_account" not in attrs:
                raise serializers.ValidationError({"account_id": "This field is required."})

        config = attrs.get("config") or getattr(self.instance, "config", None)
        instrument = self._resolve_instrument(attrs, config)
        if instrument and "instrument" not in attrs and self.instance is None:
            attrs["instrument"] = instrument

        # Validate hedging: if hedging_enabled, check account supports hedging
        hedging_enabled = attrs.get("hedging_enabled", True)
        oanda_account = attrs.get("oanda_account") or (
            self.instance.oanda_account if self.instance else None
        )
        if hedging_enabled and oanda_account:
            try:
                from apps.market.services.oanda import OandaService

                client = OandaService(oanda_account)
                account_resource = client.get_account_resource()
                account_hedging = bool(account_resource.get("hedgingEnabled", False))
                if not account_hedging:
                    raise serializers.ValidationError(
                        {
                            "hedging_enabled": (
                                "This OANDA account does not support hedging. "
                                "Disable hedging or use a hedging-enabled account."
                            )
                        }
                    )
            except serializers.ValidationError:
                raise
            except Exception as e:
                logger.warning(
                    "Failed to check hedging support for account %s: %s",
                    oanda_account.account_id,
                    e,
                )

        # Validate configuration parameters
        if config:
            is_valid, error_message = config.validate_parameters()
            if not is_valid:
                raise serializers.ValidationError({"config_id": error_message})

        if not instrument:
            raise serializers.ValidationError({"instrument": "Instrument is required"})

        initial_positions_enabled = attrs.get(
            "initial_positions_enabled",
            getattr(self.instance, "initial_positions_enabled", False),
        )
        initial_position_cycles = attrs.get(
            "initial_position_cycles",
            getattr(self.instance, "initial_position_cycles", []),
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

        self._apply_display_currency_default(attrs, instrument)
        self._validate_display_currency_option(attrs, instrument)

        return attrs

    def _request_language(self) -> str:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        return str(getattr(user, "language", "") or "")

    def _resolve_instrument(self, attrs: dict, config: StrategyConfiguration | None) -> str:
        instrument = attrs.get("instrument")
        if instrument:
            return str(instrument)
        if self.instance is not None:
            return str(getattr(self.instance, "instrument", "") or "")
        if config and config.parameters:
            config_instrument = config.parameters.get("instrument")
            if config_instrument:
                return str(config_instrument)
        return "USD_JPY"

    def _apply_display_currency_default(self, attrs: dict, instrument: str) -> None:
        options = instrument_currency_options(instrument)
        default_currency = default_currency_for_language(instrument, self._request_language())
        if self.instance is None:
            attrs["display_currency"] = (
                normalize_currency(attrs.get("display_currency")) or default_currency
            )
            return

        if "instrument" in attrs and options:
            current_display = normalize_currency(
                attrs.get("display_currency", self.instance.display_currency)
            )
            if "display_currency" not in attrs and current_display not in options:
                attrs["display_currency"] = default_currency

        if "display_currency" in attrs:
            attrs["display_currency"] = (
                normalize_currency(attrs["display_currency"]) or default_currency
            )

    def _validate_display_currency_option(self, attrs: dict, instrument: str) -> None:
        options = instrument_currency_options(instrument)
        if not options:
            return
        if self.instance is not None and "display_currency" not in attrs:
            return
        display_currency = normalize_currency(attrs.get("display_currency"))
        if not display_currency:
            raise serializers.ValidationError({"display_currency": "Display currency is required."})
        if display_currency not in options:
            raise serializers.ValidationError(
                {
                    "display_currency": (
                        f"Currency must be one of {', '.join(options)} for {instrument}."
                    )
                }
            )

    def create(self, validated_data: dict) -> TradingTask:
        """Create trading task with user from context."""
        from apps.trading.utils import pip_size_for_instrument

        user = self.context["request"].user
        validated_data["user"] = user
        hedging_enabled = validated_data.get("hedging_enabled", True)
        validated_data.setdefault(
            "trading_mode",
            TradingMode.HEDGING if hedging_enabled else TradingMode.NETTING,
        )

        # Set instrument: prefer explicit value, then fall back to config parameter
        if not validated_data.get("instrument"):
            config = validated_data.get("config")
            if config and config.parameters:
                instrument = config.parameters.get("instrument")
                if instrument:
                    validated_data["instrument"] = instrument

        # Derive pip_size from instrument
        instrument = validated_data.get("instrument")
        if instrument:
            validated_data.setdefault("pip_size", pip_size_for_instrument(instrument))
            validated_data["display_currency"] = normalize_currency(
                validated_data.get("display_currency")
            ) or default_currency_for_language(instrument, getattr(user, "language", ""))

        task = TradingTask.objects.create(**validated_data)
        from apps.trading.services.backtest_initial_positions import (
            BacktestInitialPositionService,
        )

        BacktestInitialPositionService().sync_for_task(task)
        return task

    def update(self, instance: TradingTask, validated_data: dict) -> TradingTask:
        """Update trading task."""
        from apps.trading.services.task_audit import audit_task_update, changed_field_values

        error = task_update_validation_error(
            task=instance,
            changed_fields=set(validated_data),
            task_type="trading",
        )
        if error is not None:
            raise serializers.ValidationError(error)

        changes = changed_field_values(instance, validated_data)
        if "hedging_enabled" in validated_data:
            validated_data["trading_mode"] = (
                TradingMode.HEDGING if validated_data["hedging_enabled"] else TradingMode.NETTING
            )
            changes.update(
                changed_field_values(instance, {"trading_mode": validated_data["trading_mode"]})
            )
        if "display_currency" in validated_data:
            validated_data["display_currency"] = normalize_currency(
                validated_data["display_currency"]
            )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        preview_seed_fields = {
            "initial_positions_enabled",
            "initial_position_cycles",
            "config",
            "hedging_enabled",
            "oanda_account",
        }
        if preview_seed_fields & set(validated_data):
            from apps.trading.services.backtest_initial_positions import (
                BacktestInitialPositionService,
            )

            BacktestInitialPositionService().sync_for_task(instance)
        audit_task_update(task=instance, task_type="trading", changes=changes)
        return instance
