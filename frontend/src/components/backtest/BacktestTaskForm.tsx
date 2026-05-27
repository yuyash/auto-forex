import { useState, useEffect, useRef, useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Box,
  Stepper,
  Step,
  StepLabel,
  Button,
  Typography,
  Paper,
  TextField,
  Alert,
  FormControlLabel,
  Checkbox,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material';
import Grid from '@mui/material/Grid';
import { useNavigate } from 'react-router-dom';
import { useForm, Controller, type Resolver } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { ConfigurationSelector } from '../tasks/forms/ConfigurationSelector';
import { DateRangePicker } from '../tasks/forms/DateRangePicker';
import { BalanceInput } from '../tasks/forms/BalanceInput';
import { InstrumentSelector } from '../tasks/forms/InstrumentSelector';
import { CurrencyCodeField } from '../tasks/forms/CurrencyCodeField';
import { TaskReviewErrors } from '../tasks/forms/TaskReviewErrors';
import { DebugOptionsSection } from '../tasks/forms/DebugOptionsSection';
import { BacktestInitialPositionsEditor } from './BacktestInitialPositionsEditor';
import { MarketClosedWindowsEditor } from './MarketClosedWindowsEditor';
import {
  backtestTaskSchema,
  type BacktestTaskSchemaOutput,
} from '../tasks/forms/validationSchemas';
import { DataSource } from '../../types/common';
import { buildBacktestTaskCreatePayload } from '../tasks/forms/backtestTaskPayload';
import {
  useCreateBacktestTask,
  useUpdateBacktestTask,
} from '../../hooks/useBacktestTaskMutations';
import {
  useConfiguration,
  useConfigurations,
} from '../../hooks/useConfigurations';
import {
  useStrategies,
  getStrategyDisplayName,
} from '../../hooks/useStrategies';
import {
  useFirstTick,
  useSupportedInstruments,
  useTickDataRange,
} from '../../hooks/useMarketConfig';
import { useAuth } from '../../contexts/AuthContext';
import { useAppSettings } from '../../hooks/useAppSettings';
import { useOandaAccounts } from '../../hooks/useOandaAccounts';
import { useToast } from '../common/useToast';
import { DEFAULT_ACCOUNT_CURRENCY } from '../../constants/currencies';
import { formatMoneyAmount } from '../../utils/numberFormat';
import {
  currencyOptionsForInstrument,
  normalizeInstrumentName,
  preferredCurrencyForInstrument,
  preferredCurrencyFromOptions,
} from '../../utils/instruments';
import {
  firstValidationError,
  hasValidationErrors,
} from '../../utils/formValidation';
import {
  fromTimezonePickerDate,
  formatDateTimeInTimezone,
  formatTimestampWithTimezone,
  toTimezonePickerDate,
} from '../../utils/timezone';

const DEFAULT_DATE_RANGE_DAYS = 30;

const weekdayOptions: ReadonlyArray<{
  value: number;
  key:
    | 'monday'
    | 'tuesday'
    | 'wednesday'
    | 'thursday'
    | 'friday'
    | 'saturday'
    | 'sunday';
  label: string;
}> = [
  { value: 0, key: 'monday', label: 'Monday' },
  { value: 1, key: 'tuesday', label: 'Tuesday' },
  { value: 2, key: 'wednesday', label: 'Wednesday' },
  { value: 3, key: 'thursday', label: 'Thursday' },
  { value: 4, key: 'friday', label: 'Friday' },
  { value: 5, key: 'saturday', label: 'Saturday' },
  { value: 6, key: 'sunday', label: 'Sunday' },
];

const oandaCandleGranularityOptions = [
  'S5',
  'S10',
  'S15',
  'S30',
  'M1',
  'M5',
  'M15',
  'M30',
  'H1',
  'H4',
  'D',
] as const;

function getTodayAtMidnightForTimezone(timezone: string): Date {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const values = Object.fromEntries(
    parts
      .filter((part) => part.type !== 'literal')
      .map((part) => [part.type, part.value])
  ) as Record<string, string | undefined>;
  return new Date(
    Number(values.year),
    Number(values.month) - 1,
    Number(values.day),
    0,
    0,
    0,
    0
  );
}

const createDefaultDateRange = (timezone: string) => {
  const end = getTodayAtMidnightForTimezone(timezone);
  const start = new Date(end);
  start.setDate(start.getDate() - DEFAULT_DATE_RANGE_DAYS);
  return {
    start_time: fromTimezonePickerDate(start, timezone) ?? start.toISOString(),
    end_time: fromTimezonePickerDate(end, timezone) ?? end.toISOString(),
  };
};

interface BacktestTaskFormProps {
  taskId?: string;
  initialData?: Partial<BacktestTaskSchemaOutput>;
}

// Separate component to avoid infinite loop with watch()
interface ReviewContentProps {
  timezone: string;
  language?: string;
  selectedConfig: {
    name: string;
    id: string;
    description?: string;
    parameters?: Record<string, unknown>;
  };
  formValues: {
    config_id: string;
    name: string;
    description?: string;
    data_source: DataSource;
    start_time: string;
    end_time: string;
    initial_balance: number;
    account_currency: string;
    display_currency?: string;
    commission_per_trade: number;
    pip_size?: number;
    instrument: string;
    tick_granularity: string;
    tick_window_value_mode: string;
    backtest_tick_batch_size?: number;
    spread_filter_enabled?: boolean;
    max_spread_pips?: number;
    oanda_candle_filter_enabled?: boolean;
    oanda_candle_filter_account?: number | null;
    oanda_candle_filter_granularity?: string;
    oanda_candle_filter_tolerance_pips?: number;
    sell_at_completion?: boolean;
    hedging_enabled?: boolean;
    in_memory_mode?: boolean;
    initial_positions_enabled?: boolean;
    initial_position_cycles?: BacktestTaskSchemaOutput['initial_position_cycles'];
  };
}

function ReviewContent({
  timezone,
  language,
  selectedConfig,
  formValues,
}: ReviewContentProps) {
  const { t } = useTranslation(['backtest', 'common']);
  const { settings } = useAppSettings();
  const {
    name,
    description,
    start_time,
    end_time,
    initial_balance,
    account_currency,
    display_currency,
    commission_per_trade,
    pip_size,
    instrument,
    sell_at_completion,
  } = formValues;

  return (
    <Grid container spacing={2}>
      <Grid size={{ xs: 12 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:form.taskName')}
        </Typography>
        <Typography variant="body1">{name}</Typography>
      </Grid>

      {description && (
        <Grid size={{ xs: 12 }}>
          <Typography variant="subtitle2" color="text.secondary">
            {t('common:labels.description')}
          </Typography>
          <Typography variant="body1">{description}</Typography>
        </Grid>
      )}

      <Grid size={{ xs: 12 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('common:labels.configuration')}
        </Typography>
        <Typography variant="body1">{selectedConfig.name}</Typography>
        {selectedConfig.description && (
          <Typography variant="body2" color="text.secondary">
            {selectedConfig.description}
          </Typography>
        )}
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:detail.dataSource')}
        </Typography>
        <Typography variant="body1">PostgreSQL</Typography>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:config.dateRange')}
        </Typography>
        <Typography variant="body1">
          {formatDateTimeInTimezone(start_time, timezone, language, {
            includeTimezone: true,
            dateFormat: settings.dateFormat,
          })}{' '}
          -{' '}
          {formatDateTimeInTimezone(end_time, timezone, language, {
            includeTimezone: true,
            dateFormat: settings.dateFormat,
          })}
        </Typography>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('common:labels.instrument')}
        </Typography>
        <Typography variant="body1">{instrument}</Typography>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:detail.initialBalance')}
        </Typography>
        <Typography variant="body1">
          {formatMoneyAmount(
            Number(initial_balance),
            account_currency,
            {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            },
            settings
          )}
        </Typography>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('common:labels.currency', { defaultValue: 'Currency' })}
        </Typography>
        <Typography variant="body1">
          {display_currency || account_currency || DEFAULT_ACCOUNT_CURRENCY}
        </Typography>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:detail.commissionPerTrade')}
        </Typography>
        <Typography variant="body1">
          {formatMoneyAmount(
            Number(commission_per_trade),
            account_currency,
            {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            },
            settings
          )}
        </Typography>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('common:labels.pipSize')}
        </Typography>
        <Typography variant="body1">
          {pip_size !== undefined && pip_size !== null
            ? pip_size
            : t('backtest:form.pipSizeHelperText')}
        </Typography>
      </Grid>

      <Grid size={{ xs: 12 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:form.closePositionsAtCompletion')}
        </Typography>
        <Typography variant="body1">
          {sell_at_completion ? t('common:labels.yes') : t('common:labels.no')}
        </Typography>
      </Grid>

      <Grid size={{ xs: 12 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:form.hedgingEnabled')}
        </Typography>
        <Typography variant="body1">
          {formValues.hedging_enabled !== false
            ? t('common:labels.yes')
            : t('common:labels.no')}
        </Typography>
      </Grid>

      <Grid size={{ xs: 12 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:form.inMemoryMode', {
            defaultValue: 'In-memory mode',
          })}
        </Typography>
        <Typography variant="body1">
          {formValues.in_memory_mode
            ? t('common:labels.yes')
            : t('common:labels.no')}
        </Typography>
      </Grid>

      <Grid size={{ xs: 12 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:form.initialPositionsEnabled', {
            defaultValue: 'Create initial positions',
          })}
        </Typography>
        <Typography variant="body1">
          {formValues.initial_positions_enabled
            ? t('common:labels.yes')
            : t('common:labels.no')}
        </Typography>
        {formValues.initial_positions_enabled ? (
          <Typography variant="body2" color="text.secondary">
            {t('backtest:form.initialPositionsSummary', {
              defaultValue: '{{cycles}} cycles, {{positions}} positions',
              cycles: formValues.initial_position_cycles?.length ?? 0,
              positions:
                formValues.initial_position_cycles?.reduce(
                  (sum, cycle) => sum + cycle.positions.length,
                  0
                ) ?? 0,
            })}
          </Typography>
        ) : null}
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:form.tickGranularity')}
        </Typography>
        <Typography variant="body1">
          {t(
            `backtest:form.tickGranularityOptions.${formValues.tick_granularity}`
          )}
        </Typography>
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:form.backtestTickBatchSize')}
        </Typography>
        <Typography variant="body1">
          {formValues.backtest_tick_batch_size ?? 1000}
        </Typography>
      </Grid>

      {formValues.tick_granularity !== 'tick' && (
        <Grid size={{ xs: 12, md: 6 }}>
          <Typography variant="subtitle2" color="text.secondary">
            {t('backtest:form.tickWindowValueMode')}
          </Typography>
          <Typography variant="body1">
            {t(
              `backtest:form.tickWindowValueModeOptions.${formValues.tick_window_value_mode}`
            )}
          </Typography>
        </Grid>
      )}

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:form.spreadFilterEnabled')}
        </Typography>
        <Typography variant="body1">
          {formValues.spread_filter_enabled
            ? t('common:labels.yes')
            : t('common:labels.no')}
        </Typography>
        {formValues.spread_filter_enabled ? (
          <Typography variant="body2" color="text.secondary">
            {t('backtest:form.maxSpreadPipsValue', {
              defaultValue: 'Max {{value}} pips',
              value: formValues.max_spread_pips,
            })}
          </Typography>
        ) : null}
      </Grid>

      <Grid size={{ xs: 12, md: 6 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {t('backtest:form.oandaCandleFilterEnabled')}
        </Typography>
        <Typography variant="body1">
          {formValues.oanda_candle_filter_enabled
            ? t('common:labels.yes')
            : t('common:labels.no')}
        </Typography>
        {formValues.oanda_candle_filter_enabled ? (
          <Typography variant="body2" color="text.secondary">
            {t('backtest:form.oandaCandleFilterSummary', {
              defaultValue:
                'Account ID {{account}}, {{granularity}}, tolerance {{tolerance}} pips',
              account: formValues.oanda_candle_filter_account ?? '-',
              granularity: formValues.oanda_candle_filter_granularity ?? 'M1',
              tolerance: formValues.oanda_candle_filter_tolerance_pips ?? 5,
            })}
          </Typography>
        ) : null}
      </Grid>
    </Grid>
  );
}

export default function BacktestTaskForm({
  taskId,
  initialData,
}: BacktestTaskFormProps) {
  const { t } = useTranslation(['backtest', 'common']);
  const { user } = useAuth();
  const navigate = useNavigate();
  const { showError } = useToast();
  const timezone = user?.timezone || 'UTC';
  const language = user?.language;
  const isSuperuser = Boolean(user?.is_superuser);
  const steps = [
    t('backtest:form.steps.configuration'),
    t('backtest:form.steps.parameters'),
    t('backtest:form.steps.review'),
  ];
  const defaultDateRange = useMemo(() => {
    const range = createDefaultDateRange(timezone);
    return {
      start_time: initialData?.start_time || range.start_time,
      end_time: initialData?.end_time || range.end_time,
    };
  }, [initialData?.start_time, initialData?.end_time, timezone]);

  const resolvedDefaultValues = useMemo(() => {
    const defaultInstrument = initialData?.instrument || 'USD_JPY';
    const defaultCurrency =
      preferredCurrencyForInstrument(defaultInstrument, language) ||
      DEFAULT_ACCOUNT_CURRENCY;
    const baseDefaults: BacktestTaskSchemaOutput = {
      config_id: '',
      name: '',
      description: '',
      data_source: DataSource.POSTGRESQL,
      start_time: defaultDateRange.start_time,
      end_time: defaultDateRange.end_time,
      initial_balance: 1000000,
      account_currency: defaultCurrency,
      display_currency: defaultCurrency,
      commission_per_trade: 0,
      pip_size: 0.01,
      instrument: defaultInstrument,
      tick_granularity: 'tick',
      tick_window_value_mode: 'first',
      sell_at_completion: false,
      hedging_enabled: true,
      in_memory_mode: false,
      initial_positions_enabled: false,
      initial_position_cycles: [],
      drain_duration_hours: 0,
      market_idle_pre_close_minutes: 0,
      market_idle_resume_delay_minutes: 0,
      market_close_enabled: false,
      market_close_weekday: 4,
      market_close_hour_utc: 21,
      market_open_weekday: 6,
      market_open_hour_utc: 21,
      max_tick_gap_hours: 120,
      backtest_tick_batch_size: 1000,
      spread_filter_enabled: false,
      max_spread_pips: 10,
      oanda_candle_filter_enabled: false,
      oanda_candle_filter_account: null,
      oanda_candle_filter_granularity: 'M1',
      oanda_candle_filter_tolerance_pips: 5,
      holidays_enabled: false,
      excluded_dates: [],
    };

    return {
      ...baseDefaults,
      ...initialData,
      start_time: initialData?.start_time || baseDefaults.start_time,
      end_time: initialData?.end_time || baseDefaults.end_time,
    } as BacktestTaskSchemaOutput;
  }, [
    defaultDateRange.end_time,
    defaultDateRange.start_time,
    initialData,
    language,
  ]);

  const [activeStep, setActiveStep] = useState(0);
  const [formData, setFormData] = useState<Partial<BacktestTaskSchemaOutput>>(
    initialData || {}
  );
  const [tracemalloc, setTracemalloc] = useState(false);
  const canSubmitRef = useRef(false); // Flag to prevent auto-submission
  const createTask = useCreateBacktestTask();
  const updateTask = useUpdateBacktestTask();

  const {
    control,
    handleSubmit,
    watch,
    getValues,
    setValue,
    formState: { errors },
    trigger,
  } = useForm<BacktestTaskSchemaOutput>({
    resolver: zodResolver(
      backtestTaskSchema
    ) as Resolver<BacktestTaskSchemaOutput>,
    mode: 'onChange',
    reValidateMode: 'onChange',
    shouldUnregister: false,
    defaultValues: resolvedDefaultValues,
  });
  const submitValidationError = firstValidationError(errors);
  const isSubmitBlockedByValidation = hasValidationErrors(errors);
  const submitValidationBlockReason = isSubmitBlockedByValidation
    ? t(
        submitValidationError
          ? 'common:validation.fixFormErrorsBeforeSubmitWithMessage'
          : 'common:validation.fixFormErrorsBeforeSubmit',
        {
          message:
            submitValidationError ??
            t('common:validation.unknownFormError', {
              defaultValue: 'Review the highlighted fields.',
            }),
          defaultValue: submitValidationError
            ? 'Fix validation errors before submitting: {{message}}'
            : 'Fix validation errors before submitting.',
        }
      )
    : null;

  // eslint-disable-next-line react-hooks/incompatible-library
  const selectedConfigId = watch('config_id');

  const watchedTickGranularity = watch('tick_granularity');
  const showTickWindowValueMode = watchedTickGranularity !== 'tick';

  const watchedMarketCloseEnabled = watch('market_close_enabled');
  const watchedSpreadFilterEnabled = watch('spread_filter_enabled');
  const watchedOandaCandleFilterEnabled = watch('oanda_candle_filter_enabled');
  const watchedInMemoryMode = watch('in_memory_mode');
  const watchedInitialPositionsEnabled = watch('initial_positions_enabled');
  const watchedPipSize = watch('pip_size');
  const watchedAccountCurrency =
    watch('account_currency') || DEFAULT_ACCOUNT_CURRENCY;
  const watchedDisplayCurrency = watch('display_currency') || '';

  // Sync saved formData back into React Hook Form when changing steps
  // This ensures form values persist when navigating between steps
  useEffect(() => {
    if (Object.keys(formData).length > 0) {
      // Manually set each field value to restore saved state
      Object.entries(formData).forEach(([key, value]) => {
        if (value !== undefined) {
          setValue(key as keyof BacktestTaskSchemaOutput, value, {
            shouldValidate: false,
          });
        }
      });
    }
  }, [formData, setValue]); // Removed activeStep dependency so it runs on initial render too

  useEffect(() => {
    if (!watchedInMemoryMode || !watchedInitialPositionsEnabled) {
      return;
    }
    setValue('initial_positions_enabled', false, {
      shouldDirty: true,
      shouldValidate: true,
    });
    setValue('initial_position_cycles', [], {
      shouldDirty: true,
      shouldValidate: true,
    });
  }, [setValue, watchedInMemoryMode, watchedInitialPositionsEnabled]);

  // Fetch all configurations and strategies
  const { strategies } = useStrategies();
  const {
    instruments: availableInstruments,
    metadata: instrumentMetadata,
    usingFallback: usingInstrumentFallback,
  } = useSupportedInstruments();
  const { accounts: oandaAccounts, isLoading: oandaAccountsLoading } =
    useOandaAccounts();
  const activeOandaAccounts = useMemo(
    () => oandaAccounts.filter((account) => account.is_active),
    [oandaAccounts]
  );

  // config_id is now a UUID string
  const configIdString = selectedConfigId || '';

  const { data: selectedConfig } = useConfiguration(configIdString);
  const { data: configurationsData } = useConfigurations({
    page: 1,
    page_size: 200,
  });
  const selectedListConfig = useMemo(
    () =>
      (configurationsData?.results ?? []).find(
        (config) => config.id === configIdString
      ),
    [configIdString, configurationsData?.results]
  );
  const selectedStrategyType =
    selectedConfig?.strategy_type ?? selectedListConfig?.strategy_type;
  const selectedStrategy = useMemo(
    () =>
      selectedStrategyType
        ? strategies.find((strategy) => strategy.id === selectedStrategyType)
        : undefined,
    [selectedStrategyType, strategies]
  );
  const strategySupportsHedging =
    selectedStrategy?.capabilities?.runtime?.hedging !== false;

  useEffect(() => {
    if (!strategySupportsHedging) {
      setValue('hedging_enabled', false, {
        shouldValidate: false,
        shouldDirty: true,
      });
    }
  }, [setValue, strategySupportsHedging]);

  const watchedInstrument = watch('instrument');
  const currencyOptions = useMemo(
    () => currencyOptionsForInstrument(watchedInstrument || 'USD_JPY'),
    [watchedInstrument]
  );
  const defaultCurrencyForSelectedInstrument =
    preferredCurrencyFromOptions(currencyOptions, language) ||
    DEFAULT_ACCOUNT_CURRENCY;
  useEffect(() => {
    if (!currencyOptions.length) return;
    if (!currencyOptions.includes(watchedAccountCurrency)) {
      setValue('account_currency', defaultCurrencyForSelectedInstrument, {
        shouldDirty: true,
        shouldValidate: true,
      });
    }
    if (
      !watchedDisplayCurrency ||
      !currencyOptions.includes(watchedDisplayCurrency)
    ) {
      setValue('display_currency', defaultCurrencyForSelectedInstrument, {
        shouldDirty: true,
        shouldValidate: true,
      });
    }
  }, [
    currencyOptions,
    defaultCurrencyForSelectedInstrument,
    setValue,
    watchedAccountCurrency,
    watchedDisplayCurrency,
  ]);
  const watchedStartTime = watch('start_time');
  const watchedEndTime = watch('end_time');
  const selectedInstrumentMetadata = watchedInstrument
    ? instrumentMetadata[normalizeInstrumentName(watchedInstrument)]
    : undefined;
  const pipSizeHelperText = selectedInstrumentMetadata
    ? t('backtest:form.pipSizeMetadataHelperText', {
        defaultValue:
          'Default pip size for {{instrument}} is {{pipSize}} ({{base}}/{{quote}}).',
        instrument: selectedInstrumentMetadata.normalized_name,
        pipSize: selectedInstrumentMetadata.pip_size,
        base: selectedInstrumentMetadata.base_currency,
        quote: selectedInstrumentMetadata.quote_currency,
      })
    : t('backtest:form.pipSizeHelperTextLong');
  const {
    dataRange,
    error: dataRangeError,
    isLoading: dataRangeLoading,
  } = useTickDataRange(watchedInstrument);
  const {
    firstTick,
    error: firstTickError,
    isLoading: firstTickLoading,
  } = useFirstTick(watchedInstrument, watchedStartTime, watchedEndTime, {
    enabled: watchedInitialPositionsEnabled === true && !watchedInMemoryMode,
  });

  // When tick data range is loaded for a new task (no initialData dates),
  // set the default date range to [max - 1 month, max] at 12:00 AM in
  // the user's configured timezone.
  const dataRangeAppliedRef = useRef(false);
  useEffect(() => {
    if (
      dataRange?.has_data &&
      dataRange.max_timestamp &&
      !initialData?.start_time &&
      !initialData?.end_time &&
      !dataRangeAppliedRef.current
    ) {
      dataRangeAppliedRef.current = true;
      const maxDate =
        toTimezonePickerDate(dataRange.max_timestamp, timezone) ??
        new Date(dataRange.max_timestamp);
      maxDate.setHours(0, 0, 0, 0);
      const startDate = new Date(maxDate);
      startDate.setMonth(startDate.getMonth() - 1);
      setValue(
        'end_time',
        fromTimezonePickerDate(maxDate, timezone) ?? maxDate.toISOString()
      );
      setValue(
        'start_time',
        fromTimezonePickerDate(startDate, timezone) ?? startDate.toISOString()
      );
    }
  }, [
    dataRange,
    initialData?.start_time,
    initialData?.end_time,
    setValue,
    timezone,
  ]);

  // Reset when instrument changes so the next dataRange load re-applies defaults
  useEffect(() => {
    dataRangeAppliedRef.current = false;
  }, [watchedInstrument]);

  // Compute data coverage warning
  const dataCoverageWarning = useMemo<string | null>(() => {
    if (!dataRange || !dataRange.has_data) {
      if (dataRange && !dataRange.has_data && watchedInstrument) {
        return t('backtest:form.noTickDataFound', {
          instrument: watchedInstrument,
        });
      }
      return null;
    }
    const warnings: string[] = [];
    if (watchedStartTime && dataRange.min_timestamp) {
      const start = new Date(watchedStartTime);
      const minTs = new Date(dataRange.min_timestamp);
      if (start < minTs) {
        warnings.push(
          t('backtest:form.startTimeBeforeMinData', {
            timestamp: formatTimestampWithTimezone(minTs, timezone),
          })
        );
      }
    }
    if (watchedEndTime && dataRange.max_timestamp) {
      const end = new Date(watchedEndTime);
      const maxTs = new Date(dataRange.max_timestamp);
      if (end > maxTs) {
        warnings.push(
          t('backtest:form.endTimeAfterMaxData', {
            timestamp: formatTimestampWithTimezone(maxTs, timezone),
          })
        );
      }
    }
    return warnings.length > 0 ? warnings.join(' ') : null;
  }, [
    dataRange,
    t,
    timezone,
    watchedInstrument,
    watchedStartTime,
    watchedEndTime,
  ]);

  const handleNext = async () => {
    // Save current form values to state BEFORE validation
    const currentValues = getValues();
    setFormData((prev) => ({ ...prev, ...currentValues }));

    // Validate current step before proceeding
    let fieldsToValidate: (keyof BacktestTaskSchemaOutput)[] = [];

    switch (activeStep) {
      case 0: // Configuration step
        fieldsToValidate = ['config_id', 'name'];
        break;
      case 1: // Parameters step
        fieldsToValidate = [
          'start_time',
          'end_time',
          'initial_balance',
          'commission_per_trade',
          'pip_size',
          'tick_granularity',
          'tick_window_value_mode',
          'backtest_tick_batch_size',
          'spread_filter_enabled',
          'max_spread_pips',
          'oanda_candle_filter_enabled',
          'oanda_candle_filter_account',
          'oanda_candle_filter_granularity',
          'oanda_candle_filter_tolerance_pips',
          'in_memory_mode',
          'initial_positions_enabled',
          'initial_position_cycles',
        ];
        break;
      default:
        // No validation needed for review step
        break;
    }

    // Only validate if we have fields to validate
    if (fieldsToValidate.length > 0) {
      const isValid = await trigger(fieldsToValidate);

      if (!isValid) {
        // Validation failed, don't proceed
        return;
      }
    }

    // Block proceeding from Parameters step if data coverage is insufficient
    if (activeStep === 1 && dataCoverageWarning) {
      return;
    }

    // Validation passed or no validation needed, proceed to next step
    canSubmitRef.current = false; // Reset submit flag when navigating
    setActiveStep((prevActiveStep) => prevActiveStep + 1);
  };

  const handleBack = () => {
    // Save current form values to state before going back
    const currentValues = getValues();
    setFormData((prev) => ({ ...prev, ...currentValues }));

    canSubmitRef.current = false; // Reset submit flag when navigating
    setActiveStep((prevActiveStep) => prevActiveStep - 1);
  };

  const onSubmit = async (data: BacktestTaskSchemaOutput) => {
    // Prevent auto-submission - only allow explicit user submission
    if (!canSubmitRef.current) {
      return;
    }

    // Merge the saved formData with the current form data to ensure we have all values
    const completeData = { ...formData, ...data } as BacktestTaskSchemaOutput;

    // Zod has already validated and converted types, so we can use the data directly
    const apiData = buildBacktestTaskCreatePayload(
      {
        config_id: completeData.config_id,
        name: completeData.name,
        description: completeData.description,
        start_time: completeData.start_time,
        end_time: completeData.end_time,
        initial_balance: completeData.initial_balance,
        account_currency: completeData.account_currency,
        display_currency: completeData.display_currency,
        commission_per_trade: completeData.commission_per_trade,
        pip_size: completeData.pip_size,
        instrument: completeData.instrument,
        tick_granularity: completeData.tick_granularity,
        tick_window_value_mode: completeData.tick_window_value_mode,
        sell_at_completion: completeData.sell_at_completion,
        hedging_enabled: strategySupportsHedging
          ? completeData.hedging_enabled
          : false,
        drain_duration_hours: completeData.drain_duration_hours,
        market_idle_pre_close_minutes:
          completeData.market_idle_pre_close_minutes,
        market_idle_resume_delay_minutes:
          completeData.market_idle_resume_delay_minutes,
        market_close_enabled: completeData.market_close_enabled,
        market_close_weekday: completeData.market_close_weekday,
        market_close_hour_utc: completeData.market_close_hour_utc,
        market_open_weekday: completeData.market_open_weekday,
        market_open_hour_utc: completeData.market_open_hour_utc,
        max_tick_gap_hours: completeData.max_tick_gap_hours,
        backtest_tick_batch_size: completeData.backtest_tick_batch_size,
        spread_filter_enabled: completeData.spread_filter_enabled,
        max_spread_pips: completeData.max_spread_pips,
        oanda_candle_filter_enabled: completeData.oanda_candle_filter_enabled,
        oanda_candle_filter_account: completeData.oanda_candle_filter_account,
        oanda_candle_filter_granularity:
          completeData.oanda_candle_filter_granularity,
        oanda_candle_filter_tolerance_pips:
          completeData.oanda_candle_filter_tolerance_pips,
        holidays_enabled: completeData.holidays_enabled,
        excluded_dates: completeData.excluded_dates,
        initial_positions_enabled: completeData.initial_positions_enabled,
        initial_position_cycles: completeData.initial_position_cycles,
        in_memory_mode: completeData.in_memory_mode,
      },
      isSuperuser ? { tracemalloc } : undefined
    );

    try {
      if (taskId) {
        await updateTask.mutate({ id: taskId, data: apiData });
      } else {
        await createTask.mutate(apiData);
      }

      navigate('/backtest-tasks');
    } catch (error: unknown) {
      const err = error as {
        details?: Record<string, string | string[]>;
        message?: string;
      };

      // Extract backend validation errors if available
      let errorMessage = 'Failed to create task';
      if (err?.details && typeof err.details === 'object') {
        const backendErrors = err.details as Record<string, string | string[]>;
        const errorMessages: string[] = [];

        // Map backend field names to frontend field names
        const fieldMapping: Record<string, string> = {
          config: t('common:labels.configuration'),
          name: t('backtest:form.taskName'),
          start_time: t('backtest:config.startDate'),
          end_time: t('backtest:config.endDate'),
          initial_balance: t('backtest:detail.initialBalance'),
          max_spread_pips: t('backtest:form.maxSpreadPips'),
          oanda_candle_filter_account: t(
            'backtest:form.oandaCandleFilterAccount'
          ),
          oanda_candle_filter_tolerance_pips: t(
            'backtest:form.oandaCandleTolerancePips'
          ),
        };

        Object.entries(backendErrors).forEach(([field, messages]) => {
          const fieldName = fieldMapping[field] || field;
          const fieldErrors = Array.isArray(messages) ? messages : [messages];
          fieldErrors.forEach((msg: string) => {
            errorMessages.push(`${fieldName}: ${msg}`);
          });
        });

        if (errorMessages.length > 0) {
          errorMessage = errorMessages.join('\n');
        }
      } else if (err?.message) {
        errorMessage = err.message;
      }

      showError(errorMessage, 8000);
    }
  };

  const getStepContent = (step: number) => {
    switch (step) {
      case 0:
        return (
          <Box>
            <Typography variant="h6" gutterBottom>
              {t('backtest:form.selectConfiguration')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              {t('backtest:form.chooseStrategyConfig')}
            </Typography>

            <Grid container spacing={3}>
              <Grid size={{ xs: 12 }}>
                <Controller
                  name="config_id"
                  control={control}
                  render={({ field }) => (
                    <ConfigurationSelector
                      value={field.value as string | undefined}
                      onChange={field.onChange}
                      error={errors.config_id?.message}
                      helperText={errors.config_id?.message}
                      required
                    />
                  )}
                />
              </Grid>

              {selectedConfig && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="info">
                    <Typography variant="subtitle2" gutterBottom>
                      {t('trading:form.configurationPreview')}
                    </Typography>
                    <Typography variant="body2">
                      <strong>{t('trading:form.type')}:</strong>{' '}
                      {getStrategyDisplayName(
                        strategies,
                        selectedConfig.strategy_type
                      )}
                    </Typography>
                    <Typography variant="body2">
                      <strong>{t('common:labels.description')}:</strong>{' '}
                      {selectedConfig.description ||
                        t('trading:form.noDescription')}
                    </Typography>
                  </Alert>
                </Grid>
              )}

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="name"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      fullWidth
                      label={t('backtest:form.taskName')}
                      required
                      error={!!errors.name}
                      helperText={errors.name?.message}
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="description"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      fullWidth
                      label={t('common:labels.description')}
                      multiline
                      rows={3}
                      error={!!errors.description}
                      helperText={errors.description?.message}
                    />
                  )}
                />
              </Grid>
            </Grid>
          </Box>
        );

      case 1:
        return (
          <Box>
            <Typography variant="h6" gutterBottom>
              {t('backtest:form.backtestParameters')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              {t('backtest:form.configureParameters')}
            </Typography>

            <Grid container spacing={3}>
              <Grid size={{ xs: 12 }}>
                <Controller
                  name="start_time"
                  control={control}
                  render={({ field: startField }) => (
                    <Controller
                      name="end_time"
                      control={control}
                      render={({ field: endField }) => (
                        <DateRangePicker
                          startDate={startField.value}
                          endDate={endField.value}
                          onStartDateChange={startField.onChange}
                          onEndDateChange={endField.onChange}
                          startLabel={t('backtest:config.startDate')}
                          endLabel={t('backtest:config.endDate')}
                          minDate={
                            dataRange?.min_timestamp
                              ? new Date(dataRange.min_timestamp)
                              : undefined
                          }
                          maxDate={
                            dataRange?.max_timestamp
                              ? new Date(dataRange.max_timestamp)
                              : new Date()
                          }
                          required
                          helperText={t('backtest:form.dateRangeHelperText')}
                          timezone={timezone}
                        />
                      )}
                    />
                  )}
                />
              </Grid>

              {/* Tick data availability info */}
              {dataRangeLoading && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="info">
                    {t('backtest:form.checkingTickDataRange')}
                  </Alert>
                </Grid>
              )}
              {dataRangeError && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="warning">
                    {t('backtest:form.tickDataRangeFetchFailed')}
                  </Alert>
                </Grid>
              )}
              {dataRange && dataRange.has_data && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="info">
                    {t('backtest:form.dataRange', {
                      instrument: dataRange.instrument,
                    })}{' '}
                    {formatTimestampWithTimezone(
                      dataRange.min_timestamp,
                      timezone
                    )}{' '}
                    –{' '}
                    {formatTimestampWithTimezone(
                      dataRange.max_timestamp,
                      timezone
                    )}
                  </Alert>
                </Grid>
              )}
              {dataCoverageWarning && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="warning">{dataCoverageWarning}</Alert>
                </Grid>
              )}
              {usingInstrumentFallback && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="warning">
                    {t('common:tables.trend.instrumentFallbackWarning')}
                  </Alert>
                </Grid>
              )}

              <Grid size={{ xs: 12, md: 6 }}>
                <Controller
                  name="initial_balance"
                  control={control}
                  render={({ field }) => (
                    <BalanceInput
                      value={field.value}
                      onChange={field.onChange}
                      label={t('backtest:detail.initialBalance')}
                      currency={watchedAccountCurrency}
                      error={errors.initial_balance?.message}
                      helperText={errors.initial_balance?.message}
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, md: 3 }}>
                <Controller
                  name="account_currency"
                  control={control}
                  render={({ field }) => (
                    <CurrencyCodeField
                      id="backtest-account-currency"
                      label={t('common:labels.accountCurrency', {
                        defaultValue: 'Account currency',
                      })}
                      value={field.value}
                      onChange={field.onChange}
                      options={currencyOptions}
                      error={!!errors.account_currency}
                      helperText={errors.account_currency?.message}
                      required
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, md: 3 }}>
                <Controller
                  name="display_currency"
                  control={control}
                  render={({ field }) => (
                    <CurrencyCodeField
                      id="backtest-display-currency"
                      label={t('common:labels.displayCurrency', {
                        defaultValue: 'Display currency',
                      })}
                      value={
                        field.value || defaultCurrencyForSelectedInstrument
                      }
                      onChange={field.onChange}
                      options={currencyOptions}
                      error={!!errors.display_currency}
                      helperText={errors.display_currency?.message}
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, md: 6 }}>
                <Controller
                  name="commission_per_trade"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      fullWidth
                      label={t('backtest:form.commissionPerTrade')}
                      type="text"
                      inputMode="decimal"
                      inputProps={{ min: 0, step: 0.01 }}
                      error={!!errors.commission_per_trade}
                      helperText={errors.commission_per_trade?.message}
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, md: 6 }}>
                <Controller
                  name="instrument"
                  control={control}
                  render={({ field }) => (
                    <InstrumentSelector
                      value={field.value}
                      onChange={field.onChange}
                      availableInstrument={availableInstruments}
                      label={t('common:labels.instrument')}
                      error={errors.instrument?.message}
                      helperText={
                        errors.instrument?.message ||
                        t('backtest:form.instrumentHelperText')
                      }
                      required
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, md: 6 }}>
                <Controller
                  name="pip_size"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      value={field.value ?? ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        field.onChange(val === '' ? undefined : val);
                      }}
                      fullWidth
                      label={t('backtest:form.pipSizeOptional')}
                      type="text"
                      inputMode="decimal"
                      inputProps={{ min: 0, step: 0.00001 }}
                      error={!!errors.pip_size}
                      helperText={errors.pip_size?.message || pipSizeHelperText}
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, md: 6 }}>
                <Controller
                  name="tick_granularity"
                  control={control}
                  render={({ field }) => (
                    <FormControl fullWidth error={!!errors.tick_granularity}>
                      <InputLabel id="backtest-tick-granularity-label">
                        {t('backtest:form.tickGranularity')}
                      </InputLabel>
                      <Select
                        {...field}
                        labelId="backtest-tick-granularity-label"
                        label={t('backtest:form.tickGranularity')}
                      >
                        {['tick'].map((value) => (
                          <MenuItem key={value} value={value}>
                            {t(`backtest:form.tickGranularityOptions.${value}`)}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, md: 6 }}>
                <Controller
                  name="tick_window_value_mode"
                  control={control}
                  render={({ field }) => (
                    <FormControl
                      fullWidth
                      error={!!errors.tick_window_value_mode}
                      disabled={!showTickWindowValueMode}
                      sx={{
                        display: showTickWindowValueMode ? 'flex' : 'none',
                      }}
                    >
                      <InputLabel id="backtest-tick-window-value-mode-label">
                        {t('backtest:form.tickWindowValueMode')}
                      </InputLabel>
                      <Select
                        {...field}
                        labelId="backtest-tick-window-value-mode-label"
                        label={t('backtest:form.tickWindowValueMode')}
                      >
                        {['first', 'last', 'average', 'median'].map((value) => (
                          <MenuItem key={value} value={value}>
                            {t(
                              `backtest:form.tickWindowValueModeOptions.${value}`
                            )}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, md: 6 }}>
                <Controller
                  name="backtest_tick_batch_size"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      value={field.value ?? 1000}
                      onChange={(e) => {
                        const val = e.target.value;
                        field.onChange(val === '' ? undefined : Number(val));
                      }}
                      fullWidth
                      label={t('backtest:form.backtestTickBatchSize')}
                      type="number"
                      inputProps={{ min: 1, max: 50000, step: 1 }}
                      error={!!errors.backtest_tick_batch_size}
                      helperText={
                        errors.backtest_tick_batch_size?.message ||
                        t('backtest:form.backtestTickBatchSizeHelp')
                      }
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="spread_filter_enabled"
                  control={control}
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={field.value ?? false}
                          onChange={(e) => field.onChange(e.target.checked)}
                        />
                      }
                      label={
                        <Box>
                          <Typography variant="body1">
                            {t('backtest:form.spreadFilterEnabled')}
                          </Typography>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ mt: 0.5 }}
                          >
                            {t('backtest:form.spreadFilterDescription')}
                          </Typography>
                        </Box>
                      }
                    />
                  )}
                />
              </Grid>

              {watchedSpreadFilterEnabled ? (
                <Grid size={{ xs: 12, md: 6 }}>
                  <Controller
                    name="max_spread_pips"
                    control={control}
                    render={({ field }) => (
                      <TextField
                        {...field}
                        value={field.value ?? ''}
                        onChange={(e) => {
                          const val = e.target.value;
                          field.onChange(val === '' ? undefined : Number(val));
                        }}
                        fullWidth
                        label={t('backtest:form.maxSpreadPips')}
                        type="text"
                        inputMode="decimal"
                        inputProps={{ min: 0, step: 0.1 }}
                        error={!!errors.max_spread_pips}
                        helperText={
                          errors.max_spread_pips?.message ||
                          t('backtest:form.maxSpreadPipsHelp')
                        }
                      />
                    )}
                  />
                </Grid>
              ) : null}

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="oanda_candle_filter_enabled"
                  control={control}
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={field.value ?? false}
                          onChange={(e) => field.onChange(e.target.checked)}
                        />
                      }
                      label={
                        <Box>
                          <Typography variant="body1">
                            {t('backtest:form.oandaCandleFilterEnabled')}
                          </Typography>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ mt: 0.5 }}
                          >
                            {t('backtest:form.oandaCandleFilterDescription')}
                          </Typography>
                        </Box>
                      }
                    />
                  )}
                />
              </Grid>

              {watchedOandaCandleFilterEnabled ? (
                <>
                  <Grid size={{ xs: 12, md: 4 }}>
                    <Controller
                      name="oanda_candle_filter_account"
                      control={control}
                      render={({ field }) => (
                        <FormControl
                          fullWidth
                          error={!!errors.oanda_candle_filter_account}
                        >
                          <InputLabel id="backtest-oanda-candle-account-label">
                            {t('backtest:form.oandaCandleFilterAccount')}
                          </InputLabel>
                          <Select
                            value={field.value ?? ''}
                            onChange={(e) => field.onChange(e.target.value)}
                            labelId="backtest-oanda-candle-account-label"
                            label={t('backtest:form.oandaCandleFilterAccount')}
                            disabled={oandaAccountsLoading}
                          >
                            {activeOandaAccounts.map((account) => {
                              const accountApiType =
                                account.api_type ??
                                (account.is_practice === false
                                  ? 'live'
                                  : 'practice');
                              const accountTypeLabel = t(
                                `backtest:form.oandaCandleAccountTypes.${accountApiType}`
                              );

                              return (
                                <MenuItem key={account.id} value={account.id}>
                                  {t('backtest:form.oandaCandleAccountOption', {
                                    accountId: account.account_id,
                                    type: accountTypeLabel,
                                  })}
                                </MenuItem>
                              );
                            })}
                          </Select>
                          <Typography
                            variant="caption"
                            color={
                              errors.oanda_candle_filter_account
                                ? 'error'
                                : 'text.secondary'
                            }
                            sx={{ mt: 0.5, ml: 1.75 }}
                          >
                            {errors.oanda_candle_filter_account?.message ||
                              t('backtest:form.oandaCandleFilterAccountHelp')}
                          </Typography>
                        </FormControl>
                      )}
                    />
                  </Grid>

                  <Grid size={{ xs: 12, md: 4 }}>
                    <Controller
                      name="oanda_candle_filter_granularity"
                      control={control}
                      render={({ field }) => (
                        <FormControl
                          fullWidth
                          error={!!errors.oanda_candle_filter_granularity}
                        >
                          <InputLabel id="backtest-oanda-candle-granularity-label">
                            {t('backtest:form.oandaCandleGranularity')}
                          </InputLabel>
                          <Select
                            {...field}
                            labelId="backtest-oanda-candle-granularity-label"
                            label={t('backtest:form.oandaCandleGranularity')}
                          >
                            {oandaCandleGranularityOptions.map((value) => (
                              <MenuItem key={value} value={value}>
                                {t(
                                  `backtest:form.oandaCandleGranularityOptions.${value}`
                                )}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      )}
                    />
                  </Grid>

                  <Grid size={{ xs: 12, md: 4 }}>
                    <Controller
                      name="oanda_candle_filter_tolerance_pips"
                      control={control}
                      render={({ field }) => (
                        <TextField
                          {...field}
                          value={field.value ?? ''}
                          onChange={(e) => {
                            const val = e.target.value;
                            field.onChange(
                              val === '' ? undefined : Number(val)
                            );
                          }}
                          fullWidth
                          label={t('backtest:form.oandaCandleTolerancePips')}
                          type="text"
                          inputMode="decimal"
                          inputProps={{ min: 0, step: 0.1 }}
                          error={!!errors.oanda_candle_filter_tolerance_pips}
                          helperText={
                            errors.oanda_candle_filter_tolerance_pips
                              ?.message ||
                            t('backtest:form.oandaCandleTolerancePipsHelp')
                          }
                        />
                      )}
                    />
                  </Grid>
                </>
              ) : null}

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="sell_at_completion"
                  control={control}
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={field.value ?? false}
                          onChange={(e) => field.onChange(e.target.checked)}
                        />
                      }
                      label={
                        <Box>
                          <Typography variant="body1">
                            {t('backtest:form.closePositionsAtCompletion')}
                          </Typography>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ mt: 0.5 }}
                          >
                            {t('backtest:form.closePositionsDescription')}
                          </Typography>
                        </Box>
                      }
                    />
                  )}
                />
              </Grid>

              {strategySupportsHedging ? (
                <Grid size={{ xs: 12 }}>
                  <Controller
                    name="hedging_enabled"
                    control={control}
                    render={({ field }) => (
                      <FormControlLabel
                        control={
                          <Checkbox
                            checked={field.value ?? true}
                            onChange={(e) => field.onChange(e.target.checked)}
                          />
                        }
                        label={
                          <Box>
                            <Typography variant="body1">
                              {t('backtest:form.hedgingEnabled')}
                            </Typography>
                            <Typography
                              variant="body2"
                              color="text.secondary"
                              sx={{ mt: 0.5 }}
                            >
                              {t('backtest:form.hedgingDescription')}
                            </Typography>
                          </Box>
                        }
                      />
                    )}
                  />
                </Grid>
              ) : null}

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="in_memory_mode"
                  control={control}
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={field.value ?? false}
                          onChange={(e) => field.onChange(e.target.checked)}
                        />
                      }
                      label={
                        <Box>
                          <Typography variant="body1">
                            {t('backtest:form.inMemoryMode', {
                              defaultValue: 'In-memory mode',
                            })}
                          </Typography>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ mt: 0.5 }}
                          >
                            {t('backtest:form.inMemoryModeDescription', {
                              defaultValue:
                                'Skip persisting orders, positions, trades, logs, and strategy events. Overview and metrics remain available.',
                            })}
                          </Typography>
                        </Box>
                      }
                    />
                  )}
                />
              </Grid>

              {watchedInMemoryMode ? (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="info">
                    {t('backtest:form.inMemoryModeNotice', {
                      defaultValue:
                        'In-memory backtests only keep overview and metrics data. Positions, trades, orders, logs, strategy history, pause/resume, drain stop, and initial positions are unavailable.',
                    })}
                  </Alert>
                </Grid>
              ) : null}

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="initial_position_cycles"
                  control={control}
                  render={({ field }) => (
                    <BacktestInitialPositionsEditor
                      enabled={
                        !watchedInMemoryMode &&
                        (watchedInitialPositionsEnabled ?? false)
                      }
                      onEnabledChange={(enabled) =>
                        setValue(
                          'initial_positions_enabled',
                          watchedInMemoryMode ? false : enabled,
                          {
                            shouldDirty: true,
                            shouldValidate: true,
                          }
                        )
                      }
                      value={field.value ?? []}
                      onChange={field.onChange}
                      currentTaskId={taskId}
                      selectedConfig={
                        selectedConfig ?? selectedListConfig ?? undefined
                      }
                      strategyType={selectedStrategyType}
                      pipSize={watchedPipSize}
                      firstTick={firstTick}
                      firstTickLoading={firstTickLoading}
                      firstTickError={firstTickError}
                      error={
                        errors.initial_position_cycles?.message as
                          | string
                          | undefined
                      }
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12 }} sx={{ mt: 2 }}>
                <Typography variant="subtitle1" fontWeight={600}>
                  {t('backtest:form.advancedSettings', 'Advanced settings')}
                </Typography>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: 'block', mb: 2 }}
                >
                  {t(
                    'backtest:form.advancedSettingsDescription',
                    'Drain-on-stop and market-close idling behaviour. Market-idle thresholds are evaluated against the replayed tick timestamps, not wall-clock time.'
                  )}
                </Typography>
              </Grid>

              <Grid size={{ xs: 12, sm: 4 }}>
                <Controller
                  name="drain_duration_hours"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      value={field.value ?? ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        field.onChange(val === '' ? undefined : Number(val));
                      }}
                      fullWidth
                      type="text"
                      inputMode="decimal"
                      label={t(
                        'backtest:form.drainDurationHours',
                        'Drain duration (hours)'
                      )}
                      helperText={
                        errors.drain_duration_hours?.message ||
                        t(
                          'backtest:form.drainDurationHoursHelp',
                          'Maximum hours to keep draining before giving up. 0 = wait forever for breakeven.'
                        )
                      }
                      error={!!errors.drain_duration_hours}
                      inputProps={{ min: 0, step: 1 }}
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, sm: 4 }}>
                <Controller
                  name="market_idle_pre_close_minutes"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      value={field.value ?? ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        field.onChange(val === '' ? undefined : Number(val));
                      }}
                      fullWidth
                      type="text"
                      inputMode="decimal"
                      label={t(
                        'backtest:form.marketIdlePreCloseMinutes',
                        'Idle before market close (min)'
                      )}
                      helperText={
                        errors.market_idle_pre_close_minutes?.message ||
                        t(
                          'backtest:form.marketIdlePreCloseMinutesHelp',
                          'Switch to IDLE this many minutes before the weekly forex close. Evaluated against the replayed tick timestamp. 0 disables.'
                        )
                      }
                      error={!!errors.market_idle_pre_close_minutes}
                      inputProps={{ min: 0, max: 720, step: 1 }}
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, sm: 4 }}>
                <Controller
                  name="market_idle_resume_delay_minutes"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      value={field.value ?? ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        field.onChange(val === '' ? undefined : Number(val));
                      }}
                      fullWidth
                      type="text"
                      inputMode="decimal"
                      label={t(
                        'backtest:form.marketIdleResumeDelayMinutes',
                        'Resume delay after open (min)'
                      )}
                      helperText={
                        errors.market_idle_resume_delay_minutes?.message ||
                        t(
                          'backtest:form.marketIdleResumeDelayMinutesHelp',
                          'Wait this many minutes (replayed clock) after the market reopens before resuming trading.'
                        )
                      }
                      error={!!errors.market_idle_resume_delay_minutes}
                      inputProps={{ min: 0, max: 720, step: 1 }}
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, sm: 4 }}>
                <Controller
                  name="max_tick_gap_hours"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      value={field.value ?? ''}
                      onChange={(e) => {
                        const val = e.target.value;
                        field.onChange(val === '' ? undefined : Number(val));
                      }}
                      fullWidth
                      type="text"
                      inputMode="decimal"
                      label={t(
                        'backtest:form.maxTickGapHours',
                        'Max tick gap before fail (hours)'
                      )}
                      helperText={
                        errors.max_tick_gap_hours?.message ||
                        t(
                          'backtest:form.maxTickGapHoursHelp',
                          'Fail the backtest if replayed ticks jump forward by more than this many hours. Default: 120 (5 days).'
                        )
                      }
                      error={!!errors.max_tick_gap_hours}
                      inputProps={{ min: 1, step: 1 }}
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12 }} sx={{ mt: 1 }}>
                <Controller
                  name="market_close_enabled"
                  control={control}
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={field.value ?? false}
                          onChange={(e) => field.onChange(e.target.checked)}
                        />
                      }
                      label={
                        <Box>
                          <Typography variant="body1">
                            {t(
                              'backtest:form.marketCloseEnabled',
                              'Apply weekly market close'
                            )}
                          </Typography>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ mt: 0.5 }}
                          >
                            {t(
                              'backtest:form.marketCloseEnabledDescription',
                              'When disabled, the backtest never treats any replayed time as market-closed and the idle thresholds above have no effect.'
                            )}
                          </Typography>
                        </Box>
                      }
                    />
                  )}
                />
              </Grid>

              {watchedMarketCloseEnabled && (
                <>
                  <Grid size={{ xs: 12, sm: 3 }}>
                    <Controller
                      name="market_close_weekday"
                      control={control}
                      render={({ field }) => (
                        <FormControl
                          fullWidth
                          error={!!errors.market_close_weekday}
                        >
                          <InputLabel id="backtest-market-close-weekday-label">
                            {t(
                              'backtest:form.marketCloseWeekday',
                              'Close weekday (UTC)'
                            )}
                          </InputLabel>
                          <Select
                            labelId="backtest-market-close-weekday-label"
                            label={t(
                              'backtest:form.marketCloseWeekday',
                              'Close weekday (UTC)'
                            )}
                            value={field.value ?? 4}
                            onChange={(e) =>
                              field.onChange(Number(e.target.value))
                            }
                          >
                            {weekdayOptions.map((opt) => (
                              <MenuItem key={opt.value} value={opt.value}>
                                {t(
                                  `backtest:form.weekdays.${opt.key}`,
                                  opt.label
                                )}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      )}
                    />
                  </Grid>

                  <Grid size={{ xs: 12, sm: 3 }}>
                    <Controller
                      name="market_close_hour_utc"
                      control={control}
                      render={({ field }) => (
                        <TextField
                          {...field}
                          value={field.value ?? ''}
                          onChange={(e) => {
                            const val = e.target.value;
                            field.onChange(
                              val === '' ? undefined : Number(val)
                            );
                          }}
                          fullWidth
                          type="text"
                          inputMode="decimal"
                          label={t(
                            'backtest:form.marketCloseHourUtc',
                            'Close hour (UTC)'
                          )}
                          helperText={
                            errors.market_close_hour_utc?.message ||
                            t(
                              'backtest:form.marketCloseHourUtcHelp',
                              'Hour of day at which the market closes (0–23 UTC).'
                            )
                          }
                          error={!!errors.market_close_hour_utc}
                          inputProps={{ min: 0, max: 23, step: 1 }}
                        />
                      )}
                    />
                  </Grid>

                  <Grid size={{ xs: 12, sm: 3 }}>
                    <Controller
                      name="market_open_weekday"
                      control={control}
                      render={({ field }) => (
                        <FormControl
                          fullWidth
                          error={!!errors.market_open_weekday}
                        >
                          <InputLabel id="backtest-market-open-weekday-label">
                            {t(
                              'backtest:form.marketOpenWeekday',
                              'Open weekday (UTC)'
                            )}
                          </InputLabel>
                          <Select
                            labelId="backtest-market-open-weekday-label"
                            label={t(
                              'backtest:form.marketOpenWeekday',
                              'Open weekday (UTC)'
                            )}
                            value={field.value ?? 6}
                            onChange={(e) =>
                              field.onChange(Number(e.target.value))
                            }
                          >
                            {weekdayOptions.map((opt) => (
                              <MenuItem key={opt.value} value={opt.value}>
                                {t(
                                  `backtest:form.weekdays.${opt.key}`,
                                  opt.label
                                )}
                              </MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      )}
                    />
                  </Grid>

                  <Grid size={{ xs: 12, sm: 3 }}>
                    <Controller
                      name="market_open_hour_utc"
                      control={control}
                      render={({ field }) => (
                        <TextField
                          {...field}
                          value={field.value ?? ''}
                          onChange={(e) => {
                            const val = e.target.value;
                            field.onChange(
                              val === '' ? undefined : Number(val)
                            );
                          }}
                          fullWidth
                          type="text"
                          inputMode="decimal"
                          label={t(
                            'backtest:form.marketOpenHourUtc',
                            'Open hour (UTC)'
                          )}
                          helperText={
                            errors.market_open_hour_utc?.message ||
                            t(
                              'backtest:form.marketOpenHourUtcHelp',
                              'Hour of day at which the market reopens (0–23 UTC).'
                            )
                          }
                          error={!!errors.market_open_hour_utc}
                          inputProps={{ min: 0, max: 23, step: 1 }}
                        />
                      )}
                    />
                  </Grid>
                </>
              )}

              <Grid size={{ xs: 12 }} sx={{ mt: 1 }}>
                <Controller
                  name="holidays_enabled"
                  control={control}
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={field.value ?? false}
                          onChange={(e) => field.onChange(e.target.checked)}
                        />
                      }
                      label={
                        <Box>
                          <Typography variant="body1">
                            {t(
                              'backtest:form.holidaysEnabled',
                              'Skip major FX holidays'
                            )}
                          </Typography>
                          <Typography
                            variant="body2"
                            color="text.secondary"
                            sx={{ mt: 0.5 }}
                          >
                            {t(
                              'backtest:form.holidaysEnabledDescription',
                              "Treat days where two or more major FX centres (US, UK, Germany) observe a public holiday, such as Christmas, Good Friday, or New Year's Day, as market-closed during the backtest."
                            )}
                          </Typography>
                        </Box>
                      }
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="excluded_dates"
                  control={control}
                  render={({ field }) => (
                    <MarketClosedWindowsEditor
                      value={field.value}
                      onChange={field.onChange}
                      defaultTimezone={timezone}
                      helperText={
                        (errors.excluded_dates as { message?: string })
                          ?.message || t('backtest:form.excludedDatesHelp')
                      }
                      error={!!errors.excluded_dates}
                    />
                  )}
                />
              </Grid>
            </Grid>
          </Box>
        );

      case 2: {
        // Use the saved formData state which contains all values from all steps
        const formValues = {
          config_id: formData.config_id as string,
          name: formData.name as string,
          description: formData.description,
          data_source: formData.data_source as DataSource,
          start_time: formData.start_time as string,
          end_time: formData.end_time as string,
          initial_balance: formData.initial_balance as number,
          account_currency:
            (formData.account_currency as string | undefined) ||
            DEFAULT_ACCOUNT_CURRENCY,
          display_currency: formData.display_currency as string | undefined,
          commission_per_trade: formData.commission_per_trade as number,
          pip_size: formData.pip_size as number | undefined,
          instrument: formData.instrument as string,
          tick_granularity: formData.tick_granularity as string,
          tick_window_value_mode: formData.tick_window_value_mode as string,
          backtest_tick_batch_size: formData.backtest_tick_batch_size as
            | number
            | undefined,
          spread_filter_enabled: formData.spread_filter_enabled as
            | boolean
            | undefined,
          max_spread_pips: formData.max_spread_pips as number | undefined,
          oanda_candle_filter_enabled: formData.oanda_candle_filter_enabled as
            | boolean
            | undefined,
          oanda_candle_filter_account: formData.oanda_candle_filter_account as
            | number
            | null
            | undefined,
          oanda_candle_filter_granularity:
            formData.oanda_candle_filter_granularity as string | undefined,
          oanda_candle_filter_tolerance_pips:
            formData.oanda_candle_filter_tolerance_pips as number | undefined,
          sell_at_completion: formData.sell_at_completion as boolean,
          hedging_enabled: formData.hedging_enabled as boolean | undefined,
          initial_positions_enabled: formData.initial_positions_enabled as
            | boolean
            | undefined,
          initial_position_cycles: formData.initial_position_cycles as
            | BacktestTaskSchemaOutput['initial_position_cycles']
            | undefined,
          in_memory_mode: formData.in_memory_mode as boolean | undefined,
        };

        const fieldNameMapping: Record<string, string> = {
          config_id: t('common:labels.configuration'),
          name: t('backtest:form.taskName'),
          description: t('common:labels.description'),
          data_source: t('backtest:detail.dataSource'),
          start_time: t('backtest:config.startDate'),
          end_time: t('backtest:config.endDate'),
          initial_balance: t('backtest:detail.initialBalance'),
          account_currency: t('common:labels.accountCurrency', {
            defaultValue: 'Account currency',
          }),
          display_currency: t('common:labels.displayCurrency', {
            defaultValue: 'Display currency',
          }),
          commission_per_trade: t('backtest:detail.commissionPerTrade'),
          pip_size: t('common:labels.pipSize'),
          instrument: t('common:labels.instrument'),
          tick_granularity: t('backtest:form.tickGranularity'),
          tick_window_value_mode: t('backtest:form.tickWindowValueMode'),
          backtest_tick_batch_size: t('backtest:form.backtestTickBatchSize'),
          spread_filter_enabled: t('backtest:form.spreadFilterEnabled'),
          max_spread_pips: t('backtest:form.maxSpreadPips'),
          oanda_candle_filter_enabled: t(
            'backtest:form.oandaCandleFilterEnabled'
          ),
          oanda_candle_filter_account: t(
            'backtest:form.oandaCandleFilterAccount'
          ),
          oanda_candle_filter_granularity: t(
            'backtest:form.oandaCandleGranularity'
          ),
          oanda_candle_filter_tolerance_pips: t(
            'backtest:form.oandaCandleTolerancePips'
          ),
          in_memory_mode: t('backtest:form.inMemoryMode', {
            defaultValue: 'In-memory mode',
          }),
          initial_positions_enabled: t(
            'backtest:form.initialPositionsEnabled',
            {
              defaultValue: 'Create initial positions',
            }
          ),
        };

        return (
          <Box>
            <Typography variant="h6" gutterBottom>
              {t('backtest:form.reviewAndSubmit')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              {t('backtest:form.reviewBeforeSubmitting')}
            </Typography>

            <TaskReviewErrors
              errors={errors}
              fieldLabels={fieldNameMapping}
              title={t('common:validation.pleaseFixErrors')}
              correctionHint={t('backtest:form.reviewErrorsCorrectionHint')}
            />

            <Paper sx={{ p: 3 }}>
              {selectedConfig ? (
                <ReviewContent
                  timezone={timezone}
                  language={language}
                  selectedConfig={selectedConfig}
                  formValues={formValues}
                />
              ) : (
                <Alert severity="error">
                  {t('backtest:form.configurationNotFound')}
                </Alert>
              )}
            </Paper>

            {isSuperuser && (
              <DebugOptionsSection
                tracemalloc={tracemalloc}
                onTracemallocChange={setTracemalloc}
                sx={{ mt: 3 }}
              />
            )}
          </Box>
        );
      }

      default:
        return 'Unknown step';
    }
  };

  return (
    <Box>
      <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
        {steps.map((label) => (
          <Step key={label}>
            <StepLabel>{label}</StepLabel>
          </Step>
        ))}
      </Stepper>

      <form onSubmit={handleSubmit(onSubmit)}>
        <Paper sx={{ p: 3 }}>{getStepContent(activeStep)}</Paper>

        {activeStep === steps.length - 1 && submitValidationBlockReason ? (
          <Alert severity="warning" sx={{ mt: 3 }}>
            {submitValidationBlockReason}
          </Alert>
        ) : null}

        <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 4 }}>
          <Button
            disabled={activeStep === 0}
            onClick={handleBack}
            variant="outlined"
          >
            {t('common:actions.back')}
          </Button>

          <Box sx={{ display: 'flex', gap: 2 }}>
            <Button
              variant="outlined"
              onClick={() => navigate('/backtest-tasks')}
            >
              {t('common:actions.cancel')}
            </Button>

            {activeStep === steps.length - 1 ? (
              <Button
                type="submit"
                variant="contained"
                disabled={
                  createTask.isLoading ||
                  updateTask.isLoading ||
                  isSubmitBlockedByValidation
                }
                onClick={() => {
                  canSubmitRef.current = true;
                }}
              >
                {taskId
                  ? t('common:actions.updateTask')
                  : t('common:actions.createTask')}
              </Button>
            ) : (
              <Button variant="contained" onClick={handleNext}>
                {t('common:actions.next')}
              </Button>
            )}
          </Box>
        </Box>
      </form>
    </Box>
  );
}
