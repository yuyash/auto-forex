import type { TFunction } from 'i18next';
import type { TaskSettingDefinition } from './TaskSettingsList';
import {
  formatDateTimeSetting,
  type TaskSettingValue,
} from './taskSettingsFormat';
import {
  formatAppNumber,
  formatMoneyAmount,
  formatMoneyPayload,
  type NumberFormatSeparators,
} from '../../../utils/numberFormat';
import type { TaskInstrumentContext } from '../../../types/instrument';
import type { MoneyAmount, TaskMoneyContext } from '../../../types/money';

function formatBooleanWithTranslation(t: TFunction) {
  return (value: TaskSettingValue): string =>
    value ? t('common:labels.yes') : t('common:labels.no');
}

function formatPipSize(
  value: TaskSettingValue,
  source?: Record<string, unknown>,
  task?: Record<string, unknown>,
  t?: TFunction,
  separators?: NumberFormatSeparators
): string {
  const context = instrumentContext(source, task);
  const rawValue = context?.effective_pip_size || value;
  if (rawValue === null || rawValue === undefined || rawValue === '')
    return '-';
  const numericValue = Number(rawValue);
  if (!Number.isFinite(numericValue)) return String(rawValue);
  const formatted = formatAppNumber(
    numericValue,
    {
      minimumFractionDigits: 0,
      maximumFractionDigits: 8,
      useGrouping: false,
    },
    separators
  );
  if (!context || context.pip_size_source !== 'task_override') {
    return formatted;
  }
  const defaultFormatted = formatAppNumber(
    Number(context.default_pip_size),
    {
      minimumFractionDigits: 0,
      maximumFractionDigits: 8,
      useGrouping: false,
    },
    separators
  );
  return (
    t?.('common:labels.pipSizeOverrideValue', {
      defaultValue: '{{value}} (override, default {{defaultPipSize}})',
      value: formatted,
      defaultPipSize: defaultFormatted,
    }) ?? `${formatted} (override, default ${defaultFormatted})`
  );
}

function instrumentContext(
  source?: Record<string, unknown>,
  task?: Record<string, unknown>
): TaskInstrumentContext | null {
  const context = source?.instrument_context ?? task?.instrument_context;
  if (!context || typeof context !== 'object') return null;
  return context as TaskInstrumentContext;
}

function taskMoneyContext(
  source?: Record<string, unknown>,
  task?: Record<string, unknown>
): TaskMoneyContext | null {
  const context = source?.money_context ?? task?.money_context;
  if (!context || typeof context !== 'object') return null;
  return context as TaskMoneyContext;
}

function formatCurrencyWithMoneyContext(
  value: TaskSettingValue,
  source: Record<string, unknown>,
  task: Record<string, unknown>,
  field: 'account_currency' | 'display_currency'
): string {
  const context = taskMoneyContext(source, task);
  const currency =
    field === 'account_currency'
      ? context?.account_currency
      : context?.display_currency;
  const code = currency || value;
  if (code === null || code === undefined || code === '') return '-';
  return String(code);
}

function formatWeekday(t: TFunction) {
  const weekdays = [
    { key: 'monday', label: 'Monday' },
    { key: 'tuesday', label: 'Tuesday' },
    { key: 'wednesday', label: 'Wednesday' },
    { key: 'thursday', label: 'Thursday' },
    { key: 'friday', label: 'Friday' },
    { key: 'saturday', label: 'Saturday' },
    { key: 'sunday', label: 'Sunday' },
  ] as const;

  return (value: TaskSettingValue): string => {
    if (value === null || value === undefined || value === '') return '-';
    const weekday = weekdays[Number(value)];
    if (!weekday) return String(value);
    return t(`backtest:form.weekdays.${weekday.key}`, weekday.label);
  };
}

function formatInitialBalance(
  value: TaskSettingValue,
  source: Record<string, unknown>,
  task: Record<string, unknown>,
  separators?: NumberFormatSeparators
): string {
  if (value === null || value === undefined || value === '') return '-';
  const context = taskMoneyContext(source, task);
  const money =
    context?.initial_balance_money ??
    source.initial_balance_money ??
    task.initial_balance_money;
  if (money && typeof money === 'object') {
    return formatMoneyPayload(money as MoneyAmount, {}, separators);
  }
  const numericValue = Number(value);
  const currency =
    context?.account_currency ??
    source.account_currency ??
    task.account_currency;
  if (!Number.isFinite(numericValue)) return String(value);
  return formatMoneyAmount(
    numericValue,
    currency ? String(currency) : undefined,
    {},
    separators
  );
}

function formatCommissionPerTrade(
  value: TaskSettingValue,
  source: Record<string, unknown>,
  task: Record<string, unknown>,
  separators?: NumberFormatSeparators
): string {
  if (value === null || value === undefined || value === '') return '-';
  const context = taskMoneyContext(source, task);
  const money =
    context?.commission_per_trade_money ??
    source.commission_per_trade_money ??
    task.commission_per_trade_money;
  if (money && typeof money === 'object') {
    return formatMoneyPayload(money as MoneyAmount, {}, separators);
  }
  const numericValue = Number(value);
  const currency =
    context?.account_currency ??
    source.account_currency ??
    task.account_currency;
  if (!Number.isFinite(numericValue)) return String(value);
  return formatMoneyAmount(
    numericValue,
    currency ? String(currency) : undefined,
    {},
    separators
  );
}

function formatInitialPositionCycles(t: TFunction) {
  return (value: TaskSettingValue): string => {
    if (!Array.isArray(value) || value.length === 0) return '-';
    const positions = value.reduce((sum, cycle) => {
      if (
        cycle &&
        typeof cycle === 'object' &&
        Array.isArray((cycle as { positions?: unknown }).positions)
      ) {
        return sum + (cycle as { positions: unknown[] }).positions.length;
      }
      return sum;
    }, 0);
    return t('backtest:form.initialPositionsSummary', {
      defaultValue: '{{cycles}} cycles, {{positions}} positions',
      cycles: value.length,
      positions,
    });
  };
}

function formatMarketClosures(
  t: TFunction,
  timezone: string,
  language?: string
) {
  return (value: TaskSettingValue): string => {
    if (!Array.isArray(value) || value.length === 0) return '-';
    return value
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item);
        const window = item as {
          start?: string;
          end?: string;
          timezone?: string;
        };
        const windowTimezone = window.timezone || timezone;
        return t('backtest:form.closedWindowSummary', {
          defaultValue: '{{start}} to {{end}} ({{timezone}})',
          start: formatDateTimeSetting(window.start, windowTimezone, language),
          end: formatDateTimeSetting(window.end, windowTimezone, language),
          timezone: windowTimezone,
        });
      })
      .join(', ');
  };
}

export function buildBacktestTaskSettingDefinitions(
  t: TFunction,
  timezone: string,
  language?: string,
  options: {
    includeDebugOptions?: boolean;
    numberSeparators?: NumberFormatSeparators;
  } = {}
): Array<TaskSettingDefinition<Record<string, unknown>>> {
  const formatBoolean = formatBooleanWithTranslation(t);
  const formatWeekdayValue = formatWeekday(t);
  const formatInitialPositions = formatInitialPositionCycles(t);

  return [
    { key: 'id', label: t('common:labels.taskId', 'Task ID') },
    {
      key: 'execution_id',
      label: t('common:labels.executionId', 'Execution ID'),
    },
    { key: 'name', label: t('common:labels.name') },
    { key: 'description', label: t('common:labels.description') },
    { key: 'config_name', label: t('common:labels.strategyConfiguration') },
    { key: 'strategy_type', label: t('common:labels.strategyType') },
    { key: 'data_source', label: t('backtest:detail.dataSource') },
    { key: 'instrument', label: t('common:labels.instrument') },
    {
      key: 'pip_size',
      label: t('common:labels.pipSize'),
      render: (value, { source, task }) =>
        formatPipSize(value, source, task, t, options.numberSeparators),
    },
    {
      key: 'start_time',
      label: t('backtest:detail.startTime'),
      format: (v) => formatDateTimeSetting(v, timezone, language),
    },
    {
      key: 'end_time',
      label: t('backtest:detail.endTime'),
      format: (v) => formatDateTimeSetting(v, timezone, language),
    },
    {
      key: 'initial_balance',
      label: t('backtest:detail.initialBalance'),
      render: (value, { source, task }) =>
        formatInitialBalance(value, source, task, options.numberSeparators),
    },
    {
      key: 'account_currency',
      label: t('common:labels.accountCurrency', 'Account currency'),
      render: (value, { source, task }) =>
        formatCurrencyWithMoneyContext(value, source, task, 'account_currency'),
    },
    {
      key: 'display_currency',
      label: t('common:labels.displayCurrency', 'Display currency'),
      render: (value, { source, task }) =>
        formatCurrencyWithMoneyContext(value, source, task, 'display_currency'),
    },
    {
      key: 'commission_per_trade',
      label: t('backtest:detail.commissionPerTrade'),
      render: (value, { source, task }) =>
        formatCommissionPerTrade(value, source, task, options.numberSeparators),
    },
    {
      key: 'hedging_enabled',
      label: t('common:labels.hedgingEnabled', 'Hedging enabled'),
      format: formatBoolean,
    },
    {
      key: 'sell_at_completion',
      label: t('backtest:form.closePositionsAtCompletion'),
      format: formatBoolean,
    },
    {
      key: 'in_memory_mode',
      label: t('backtest:form.inMemoryMode', 'In-memory mode'),
      format: formatBoolean,
    },
    { key: 'tick_granularity', label: t('backtest:detail.tickGranularity') },
    {
      key: 'tick_window_value_mode',
      label: t('backtest:detail.tickWindowValueMode'),
    },
    {
      key: 'backtest_tick_batch_size',
      label: t('backtest:form.backtestTickBatchSize', 'Tick batch size'),
    },
    {
      key: 'drain_duration_hours',
      label: t('backtest:form.drainDurationHours', 'Drain duration (hours)'),
    },
    {
      key: 'market_idle_pre_close_minutes',
      label: t(
        'backtest:form.marketIdlePreCloseMinutes',
        'Market pre-close idle (minutes)'
      ),
    },
    {
      key: 'market_idle_resume_delay_minutes',
      label: t(
        'backtest:form.marketIdleResumeDelayMinutes',
        'Market resume delay (minutes)'
      ),
    },
    {
      key: 'market_close_enabled',
      label: t(
        'backtest:form.marketCloseEnabled',
        'Market close window enabled'
      ),
      format: formatBoolean,
    },
    {
      key: 'market_close_weekday',
      label: t('backtest:form.marketCloseWeekday', 'Market close weekday'),
      format: formatWeekdayValue,
    },
    {
      key: 'market_close_hour_utc',
      label: t('backtest:form.marketCloseHourUtc', 'Market close hour UTC'),
    },
    {
      key: 'market_open_weekday',
      label: t('backtest:form.marketOpenWeekday', 'Market open weekday'),
      format: formatWeekdayValue,
    },
    {
      key: 'market_open_hour_utc',
      label: t('backtest:form.marketOpenHourUtc', 'Market open hour UTC'),
    },
    {
      key: 'max_tick_gap_hours',
      label: t(
        'backtest:form.maxTickGapHours',
        'Max tick gap before fail (hours)'
      ),
    },
    {
      key: 'spread_filter_enabled',
      label: t('backtest:form.spreadFilterEnabled', 'Skip wide-spread ticks'),
      format: formatBoolean,
    },
    {
      key: 'max_spread_pips',
      label: t('backtest:form.maxSpreadPips', 'Max spread (pips)'),
    },
    {
      key: 'oanda_candle_filter_enabled',
      label: t(
        'backtest:form.oandaCandleFilterEnabled',
        'Validate ticks with OANDA candles'
      ),
      format: formatBoolean,
    },
    {
      key: 'oanda_candle_filter_account_name',
      label: t(
        'backtest:form.oandaCandleFilterAccount',
        'OANDA candle account'
      ),
    },
    {
      key: 'oanda_candle_filter_granularity',
      label: t('backtest:form.oandaCandleGranularity', 'Candle granularity'),
    },
    {
      key: 'oanda_candle_filter_tolerance_pips',
      label: t(
        'backtest:form.oandaCandleTolerancePips',
        'Candle tolerance (pips)'
      ),
    },
    {
      key: 'holidays_enabled',
      label: t('backtest:form.holidaysEnabled', 'Skip major FX holidays'),
      format: formatBoolean,
    },
    {
      key: 'excluded_dates',
      label: t('backtest:form.excludedDates', 'Additional closed windows'),
      format: formatMarketClosures(t, timezone, language),
    },
    {
      key: 'initial_positions_enabled',
      label: t(
        'backtest:form.initialPositionsEnabled',
        'Create initial positions'
      ),
      format: formatBoolean,
    },
    {
      key: 'initial_position_cycles',
      label: t(
        'backtest:form.initialPositionCycles',
        'Initial position cycles'
      ),
      format: formatInitialPositions,
    },
    ...(options.includeDebugOptions
      ? [{ key: 'debug_options', label: t('common:debug.title') }]
      : []),
  ];
}

export function buildTradingTaskSettingDefinitions(
  t: TFunction,
  options: {
    includeDebugOptions?: boolean;
    numberSeparators?: NumberFormatSeparators;
  } = {}
): Array<TaskSettingDefinition<Record<string, unknown>>> {
  const formatBoolean = formatBooleanWithTranslation(t);
  const formatInitialPositions = formatInitialPositionCycles(t);

  return [
    { key: 'id', label: t('common:labels.taskId', 'Task ID') },
    {
      key: 'execution_id',
      label: t('common:labels.executionId', 'Execution ID'),
    },
    { key: 'name', label: t('common:labels.name') },
    { key: 'description', label: t('common:labels.description') },
    { key: 'config_name', label: t('common:labels.strategyConfiguration') },
    { key: 'strategy_type', label: t('common:labels.strategyType') },
    { key: 'instrument', label: t('common:labels.instrument') },
    {
      key: 'pip_size',
      label: t('common:labels.pipSize'),
      render: (value, { source, task }) =>
        formatPipSize(value, source, task, t, options.numberSeparators),
    },
    { key: 'account_name', label: t('trading:detail.account', 'Account') },
    {
      key: 'account_type',
      label: t('trading:detail.accountType', 'Account type'),
    },
    {
      key: 'account_currency',
      label: t('common:labels.accountCurrency', 'Account currency'),
      render: (value, { source, task }) =>
        formatCurrencyWithMoneyContext(value, source, task, 'account_currency'),
    },
    {
      key: 'display_currency',
      label: t('common:labels.displayCurrency', 'Display currency'),
      render: (value, { source, task }) =>
        formatCurrencyWithMoneyContext(value, source, task, 'display_currency'),
    },
    {
      key: 'sell_on_stop',
      label: t('common:labels.sellOnStop'),
      format: formatBoolean,
    },
    {
      key: 'dry_run',
      label: t('trading:form.dryRun', 'Dry run'),
      format: formatBoolean,
    },
    {
      key: 'hedging_enabled',
      label: t('common:labels.hedgingEnabled', 'Hedging enabled'),
      format: formatBoolean,
    },
    {
      key: 'tick_granularity',
      label: t('trading:form.tickGranularity', 'Tick granularity'),
      format: (value) =>
        t(
          `backtest:form.tickGranularityOptions.${String(value)}`,
          String(value)
        ),
    },
    {
      key: 'initial_positions_enabled',
      label: t(
        'backtest:form.initialPositionsEnabled',
        'Create initial positions'
      ),
      format: formatBoolean,
    },
    {
      key: 'initial_position_cycles',
      label: t(
        'backtest:form.initialPositionCycles',
        'Initial position cycles'
      ),
      format: formatInitialPositions,
    },
    {
      key: 'api_retry_max_attempts',
      label: t('trading:form.apiRetryMaxAttempts', 'API retry attempts'),
    },
    {
      key: 'api_retry_backoff_base_seconds',
      label: t('trading:form.apiRetryBaseSeconds', 'API retry base backoff'),
    },
    {
      key: 'api_retry_backoff_max_seconds',
      label: t('trading:form.apiRetryMaxSeconds', 'API retry max backoff'),
    },
    {
      key: 'drain_duration_hours',
      label: t('trading:form.drainDurationHours', 'Drain duration (hours)'),
    },
    {
      key: 'market_idle_pre_close_minutes',
      label: t(
        'trading:form.marketIdlePreCloseMinutes',
        'Market pre-close idle (minutes)'
      ),
    },
    {
      key: 'market_idle_resume_delay_minutes',
      label: t(
        'trading:form.marketIdleResumeDelayMinutes',
        'Market resume delay (minutes)'
      ),
    },
    {
      key: 'live_tick_stale_guard_enabled',
      label: t(
        'trading:form.liveTickStaleGuardEnabled',
        'Enable live tick delay guard'
      ),
      format: formatBoolean,
    },
    {
      key: 'live_tick_max_age_seconds',
      label: t('trading:form.liveTickMaxAgeSeconds', 'Max live tick age (s)'),
    },
    {
      key: 'live_tick_status_log_interval_seconds',
      label: t(
        'trading:form.liveTickStatusLogIntervalSeconds',
        'Tick status log interval (s)'
      ),
    },
    {
      key: 'broker_drift_check_interval_seconds',
      label: t(
        'trading:form.brokerDriftCheckIntervalSeconds',
        'OANDA drift check interval (s)'
      ),
    },
    ...(options.includeDebugOptions
      ? [{ key: 'debug_options', label: t('common:debug.title') }]
      : []),
  ];
}
