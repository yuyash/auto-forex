import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Box,
  Button,
  Typography,
  Paper,
  Alert,
  FormControl,
  FormControlLabel,
  Checkbox,
  FormHelperText,
  InputLabel,
  MenuItem,
  Select,
  TextField,
} from '@mui/material';
import Grid from '@mui/material/Grid';
import { useNavigate } from 'react-router-dom';
import { useForm, Controller, type Resolver } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { ConfigurationSelector } from '../tasks/forms/ConfigurationSelector';
import { CurrencyCodeField } from '../tasks/forms/CurrencyCodeField';
import { addInitialPositionSlotStructureIssues } from '../tasks/forms/validationSchemas';
import { BacktestInitialPositionsEditor } from '../backtest/BacktestInitialPositionsEditor';
import { useUpdateTradingTask } from '../../hooks/useTradingTaskMutations';
import { useConfiguration } from '../../hooks/useConfigurations';
import { useAccount } from '../../hooks/useAccounts';
import {
  useStrategies,
  getStrategyDisplayName,
} from '../../hooks/useStrategies';
import { hasDirtyExecutionSettings } from '../tasks/forms/executionEditGuards';
import { useAuth } from '../../contexts/AuthContext';
import { DebugOptionsSection } from '../tasks/forms/DebugOptionsSection';
import {
  currencyOptionsForInstrument,
  preferredCurrencyForInstrument,
  preferredCurrencyFromOptions,
} from '../../utils/instruments';
import {
  firstValidationError,
  hasValidationErrors,
} from '../../utils/formValidation';

const requiredPositiveIntegerInputSchema = z
  .union([z.number(), z.string()])
  .refine(
    (value) => Number.isInteger(Number(value)) && Number(value) > 0,
    'Must be a positive integer'
  );
const nonNegativeIntegerInputSchema = z
  .union([z.number(), z.string()])
  .refine(
    (value) => Number.isInteger(Number(value)) && Number(value) >= 0,
    'Must be a non-negative integer'
  );
const optionalPositiveNumberSchema = z
  .union([z.number(), z.string(), z.null()])
  .optional()
  .refine(
    (value) =>
      value === undefined ||
      value === null ||
      value === '' ||
      (Number.isFinite(Number(value)) && Number(value) > 0),
    'Must be a positive number'
  );
const optionalPositiveIntegerInputSchema = z
  .union([z.number(), z.string(), z.null()])
  .optional()
  .refine(
    (value) =>
      value === undefined ||
      value === null ||
      value === '' ||
      (Number.isInteger(Number(value)) && Number(value) > 0),
    'Must be a positive integer'
  );
const TICK_GRANULARITY_OPTIONS = [
  'tick',
  '1s',
  '10s',
  '15s',
  '30s',
  '1m',
  '5m',
  '15m',
  '30m',
  '1h',
] as const;
const tickGranularitySchema = z
  .string()
  .refine(
    (value) => (TICK_GRANULARITY_OPTIONS as readonly string[]).includes(value),
    'Invalid tick granularity'
  );

const initialPositionSchema = z
  .object({
    layer_number: requiredPositiveIntegerInputSchema,
    retracement_count: nonNegativeIntegerInputSchema,
    units: optionalPositiveIntegerInputSchema,
    entry_price: optionalPositiveNumberSchema,
    planned_exit_price: optionalPositiveNumberSchema,
    stop_loss_price: optionalPositiveNumberSchema,
    status: z
      .enum(['open', 'closed', 'closed_slot', 'pending_rebuild'])
      .optional()
      .default('open'),
    exit_price: optionalPositiveNumberSchema,
    close_reason: z.string().optional(),
    oanda_trade_id: z.string().optional(),
  })
  .superRefine((position, ctx) => {
    if (position.status === 'closed_slot') {
      for (const field of [
        'units',
        'entry_price',
        'planned_exit_price',
        'stop_loss_price',
        'exit_price',
        'close_reason',
        'oanda_trade_id',
      ] as const) {
        if (hasInitialPositionInput(position[field])) {
          ctx.addIssue({
            code: 'custom',
            path: [field],
            message: 'Closed slot placeholders cannot define position values',
          });
        }
      }
      return;
    }

    if (!hasInitialPositionInput(position.units)) {
      ctx.addIssue({
        code: 'custom',
        path: ['units'],
        message: 'Must be a positive integer',
      });
    }
    if (!hasInitialPositionInput(position.entry_price)) {
      ctx.addIssue({
        code: 'custom',
        path: ['entry_price'],
        message: 'Must be a positive number',
      });
    }
  });

const initialPositionCycleSchema = z.object({
  direction: z.enum(['long', 'short']),
  positions: z.array(initialPositionSchema).min(1),
});

function hasInitialPositionInput(value: unknown): boolean {
  return value !== undefined && value !== null && value !== '';
}

// Update schema - editable fields for trading tasks
const tradingTaskUpdateSchema = z
  .object({
    name: z
      .string()
      .min(1, 'Task name is required')
      .max(100, 'Task name must be less than 100 characters'),
    description: z
      .string()
      .max(500, 'Description must be less than 500 characters')
      .optional(),
    config_id: z.string().min(1, 'Configuration is required'),
    display_currency: z
      .string()
      .trim()
      .toUpperCase()
      .regex(/^[A-Z]{3}$/, 'Display currency must be a 3-letter code'),
    sell_on_stop: z.boolean().optional().default(false),
    hedging_enabled: z.boolean().optional(),
    tick_granularity: tickGranularitySchema,
    initial_positions_enabled: z.boolean().optional().default(false),
    initial_position_cycles: z
      .array(initialPositionCycleSchema)
      .optional()
      .default([]),
    api_retry_max_attempts: z.coerce
      .number({ message: 'Must be a positive integer' })
      .int('Must be an integer')
      .min(1, 'Must be at least 1')
      .max(1000, 'Must not exceed 1000')
      .optional(),
    api_retry_backoff_base_seconds: z.coerce
      .number({ message: 'Must be a non-negative number' })
      .nonnegative('Must be non-negative')
      .optional(),
    api_retry_backoff_max_seconds: z.coerce
      .number({ message: 'Must be a non-negative number' })
      .nonnegative('Must be non-negative')
      .optional(),
    drain_duration_hours: z.coerce
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .optional(),
    market_idle_pre_close_minutes: z.coerce
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .max(720, 'Must not exceed 720 minutes (12 hours)')
      .optional(),
    market_idle_resume_delay_minutes: z.coerce
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .max(720, 'Must not exceed 720 minutes (12 hours)')
      .optional(),
    live_tick_stale_guard_enabled: z.boolean().optional(),
    live_tick_max_age_seconds: z.coerce
      .number({ message: 'Must be a positive integer' })
      .int('Must be an integer')
      .min(1, 'Must be at least 1 second')
      .max(3600, 'Must not exceed 3600 seconds')
      .optional(),
    live_tick_status_log_interval_seconds: z.coerce
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .max(3600, 'Must not exceed 3600 seconds')
      .optional(),
    broker_drift_check_interval_seconds: z.coerce
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .max(3600, 'Must not exceed 3600 seconds')
      .optional(),
  })
  .superRefine((data, ctx) => {
    if (!data.initial_positions_enabled) {
      return;
    }
    if (!data.initial_position_cycles.length) {
      ctx.addIssue({
        code: 'custom',
        path: ['initial_position_cycles'],
        message: 'At least one initial cycle is required',
      });
    }
    addInitialPositionSlotStructureIssues(data.initial_position_cycles, ctx);
  });

type TradingTaskUpdateData = z.infer<typeof tradingTaskUpdateSchema>;
type TradingTaskUpdateInitialData = Omit<
  TradingTaskUpdateData,
  'name' | 'description'
> & { instrument: string };

interface TradingTaskUpdateFormProps {
  taskId: string;
  taskName: string;
  taskDescription?: string;
  accountId: number;
  accountName: string;
  initialData: TradingTaskUpdateInitialData;
  debugOptions?: Record<string, unknown>;
  restartRequiredForExecutionEdits?: boolean;
}

export default function TradingTaskUpdateForm({
  taskId,
  taskName,
  taskDescription,
  accountId,
  accountName,
  initialData,
  debugOptions,
  restartRequiredForExecutionEdits = false,
}: TradingTaskUpdateFormProps) {
  const { t } = useTranslation(['trading', 'common', 'backtest']);
  const { user } = useAuth();
  const navigate = useNavigate();
  const language = user?.language;
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [tracemalloc, setTracemalloc] = useState(
    Boolean(debugOptions?.tracemalloc)
  );
  const isSuperuser = Boolean(user?.is_superuser);
  const updateTask = useUpdateTradingTask();

  const currencyOptions = useMemo(
    () => currencyOptionsForInstrument(initialData.instrument || 'USD_JPY'),
    [initialData.instrument]
  );
  const defaultDisplayCurrency =
    preferredCurrencyFromOptions(currencyOptions, language) ||
    preferredCurrencyForInstrument(
      initialData.instrument || 'USD_JPY',
      language
    ) ||
    'USD';

  const {
    control,
    handleSubmit,
    watch,
    setValue,
    formState: { dirtyFields, errors },
  } = useForm<TradingTaskUpdateData>({
    resolver: zodResolver(
      tradingTaskUpdateSchema
    ) as Resolver<TradingTaskUpdateData>,
    mode: 'onChange',
    reValidateMode: 'onChange',
    defaultValues: {
      ...initialData,
      name: taskName,
      description: taskDescription ?? '',
      display_currency: initialData.display_currency || defaultDisplayCurrency,
      tick_granularity: initialData.tick_granularity ?? 'tick',
      initial_positions_enabled: initialData.initial_positions_enabled ?? false,
      initial_position_cycles: initialData.initial_position_cycles ?? [],
    },
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

  const { strategies } = useStrategies();

  // Fetch account details to check hedging support
  const { data: accountDetail } = useAccount(accountId, {
    enabled: accountId > 0,
  });
  const accountHedgingEnabled = accountDetail
    ? (accountDetail as { hedging_enabled?: boolean }).hedging_enabled
    : undefined;
  const accountCurrency = accountDetail
    ? (accountDetail as { currency?: string }).currency
    : undefined;

  // Watch selected config
  // eslint-disable-next-line react-hooks/incompatible-library
  const selectedConfigId = watch('config_id');
  const liveTickStaleGuardEnabled = watch('live_tick_stale_guard_enabled');
  const watchedDisplayCurrency = watch('display_currency');
  const watchedInitialPositionsEnabled = watch('initial_positions_enabled');
  useEffect(() => {
    if (!currencyOptions.length) return;
    if (
      !watchedDisplayCurrency ||
      !currencyOptions.includes(watchedDisplayCurrency)
    ) {
      setValue('display_currency', defaultDisplayCurrency, {
        shouldDirty: true,
        shouldValidate: true,
      });
    }
  }, [
    currencyOptions,
    defaultDisplayCurrency,
    setValue,
    watchedDisplayCurrency,
  ]);
  const { data: selectedConfig } = useConfiguration(selectedConfigId);
  const selectedStrategy = useMemo(
    () =>
      selectedConfig
        ? strategies.find(
            (strategy) => strategy.id === selectedConfig.strategy_type
          )
        : undefined,
    [selectedConfig, strategies]
  );
  const strategySupportsHedging =
    selectedStrategy?.capabilities?.runtime?.hedging !== false;

  useEffect(() => {
    if (accountHedgingEnabled === false || !strategySupportsHedging) {
      setValue('hedging_enabled', false, {
        shouldValidate: false,
        shouldDirty: true,
      });
    }
  }, [accountHedgingEnabled, setValue, strategySupportsHedging]);
  const showRestartRequiredGuard =
    restartRequiredForExecutionEdits &&
    hasDirtyExecutionSettings(dirtyFields as Record<string, unknown>);

  const onSubmit = async (data: TradingTaskUpdateData) => {
    setSubmitError(null);

    try {
      await updateTask.mutate({
        id: taskId,
        data: {
          name: data.name,
          description: data.description,
          config: data.config_id,
          display_currency: data.display_currency,
          sell_on_stop: data.sell_on_stop ?? false,
          tick_granularity: data.tick_granularity,
          hedging_enabled:
            accountHedgingEnabled === false || !strategySupportsHedging
              ? false
              : data.hedging_enabled,
          api_retry_max_attempts: data.api_retry_max_attempts,
          api_retry_backoff_base_seconds: data.api_retry_backoff_base_seconds,
          api_retry_backoff_max_seconds: data.api_retry_backoff_max_seconds,
          drain_duration_hours: data.drain_duration_hours,
          market_idle_pre_close_minutes: data.market_idle_pre_close_minutes,
          market_idle_resume_delay_minutes:
            data.market_idle_resume_delay_minutes,
          live_tick_stale_guard_enabled: data.live_tick_stale_guard_enabled,
          live_tick_max_age_seconds: data.live_tick_max_age_seconds,
          live_tick_status_log_interval_seconds:
            data.live_tick_status_log_interval_seconds,
          broker_drift_check_interval_seconds:
            data.broker_drift_check_interval_seconds,
          initial_positions_enabled: data.initial_positions_enabled,
          initial_position_cycles: data.initial_positions_enabled
            ? data.initial_position_cycles
            : [],
          debug_options: isSuperuser ? { tracemalloc } : undefined,
        },
      });

      navigate('/trading-tasks');
    } catch (error: unknown) {
      const err = error as {
        details?: Record<string, string | string[]>;
        message?: string;
      };

      let errorMessage = 'Failed to update task';
      if (err?.details && typeof err.details === 'object') {
        const backendErrors = err.details as Record<string, string | string[]>;
        const errorMessages: string[] = [];

        const fieldMapping: Record<string, string> = {
          config: 'Configuration',
          name: 'Task name',
          description: 'Description',
          display_currency: 'Display currency',
          sell_on_stop: 'Sell on stop',
          tick_granularity: t('trading:form.tickGranularity'),
          hedging_enabled: 'Hedging',
          initial_position_cycles: t('backtest:form.initialPositionCycles', {
            defaultValue: 'Initial position cycles',
          }),
          api_retry_max_attempts: 'OANDA retry attempts',
          api_retry_backoff_base_seconds: 'Retry backoff base',
          api_retry_backoff_max_seconds: 'Retry backoff max',
          drain_duration_hours: 'Drain duration',
          market_idle_pre_close_minutes: 'Pre-close idle',
          market_idle_resume_delay_minutes: 'Resume delay',
          live_tick_stale_guard_enabled: 'Live tick delay guard',
          live_tick_max_age_seconds: 'Max live tick age',
          live_tick_status_log_interval_seconds: 'Tick status log interval',
          broker_drift_check_interval_seconds: 'OANDA drift check interval',
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

      setSubmitError(errorMessage);
    }
  };

  return (
    <Box component="form" onSubmit={handleSubmit(onSubmit)}>
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          {t('common:labels.taskDetails')}
        </Typography>
        <Grid container spacing={2}>
          <Grid size={{ xs: 12, md: 6 }}>
            <Controller
              name="name"
              control={control}
              render={({ field }) => (
                <TextField
                  {...field}
                  fullWidth
                  label={t('trading:form.taskName')}
                  error={!!errors.name}
                  helperText={errors.name?.message}
                />
              )}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <Typography variant="subtitle2" color="text.secondary">
              {t('common:labels.oandaAccount')}
            </Typography>
            <Typography variant="body1">{accountName}</Typography>
            {accountCurrency ? (
              <Typography variant="body2" color="text.secondary">
                {t('common:labels.accountCurrency', {
                  defaultValue: 'Account currency',
                })}
                : {accountCurrency}
              </Typography>
            ) : null}
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <Controller
              name="display_currency"
              control={control}
              render={({ field }) => (
                <CurrencyCodeField
                  id="trading-update-display-currency"
                  label={t('common:labels.displayCurrency', {
                    defaultValue: 'Display currency',
                  })}
                  value={field.value || defaultDisplayCurrency}
                  onChange={field.onChange}
                  options={currencyOptions}
                  error={!!errors.display_currency}
                  helperText={errors.display_currency?.message}
                  required
                />
              )}
            />
          </Grid>
          <Grid size={{ xs: 12, md: 6 }}>
            <Typography variant="subtitle2" color="text.secondary">
              {t('common:labels.instrument')}
            </Typography>
            <Typography variant="body1">
              {initialData.instrument.replace('_', '/')}
            </Typography>
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
      </Paper>

      {submitError && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {submitError}
        </Alert>
      )}
      {restartRequiredForExecutionEdits && (
        <Alert
          severity={showRestartRequiredGuard ? 'warning' : 'info'}
          sx={{ mb: 3 }}
        >
          {t('trading:updateForm.restartRequiredForExecutionEdits')}
        </Alert>
      )}

      <Typography variant="h6" gutterBottom>
        {t('common:labels.strategyConfiguration')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {t('trading:updateForm.updateStrategyConfig')}
      </Typography>

      <Grid container spacing={3}>
        <Grid size={{ xs: 12 }}>
          <Controller
            name="config_id"
            control={control}
            render={({ field }) => (
              <ConfigurationSelector
                value={field.value}
                onChange={field.onChange}
                error={errors.config_id?.message}
                helperText={errors.config_id?.message}
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
                {selectedConfig.description || t('trading:form.noDescription')}
              </Typography>
            </Alert>
          </Grid>
        )}
      </Grid>

      {strategySupportsHedging ? (
        <>
          <Typography variant="h6" gutterBottom sx={{ mt: 4 }}>
            {t('trading:form.hedgingEnabled', 'Hedging')}
          </Typography>
          <Grid container spacing={3}>
            <Grid size={{ xs: 12 }}>
              <Controller
                name="hedging_enabled"
                control={control}
                render={({ field }) => (
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={field.value ?? true}
                        onChange={field.onChange}
                        disabled={accountHedgingEnabled === false}
                      />
                    }
                    label={t(
                      'trading:form.hedgingEnabled',
                      'Enable Hedging (simultaneous long/short positions)'
                    )}
                  />
                )}
              />
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: 'block', ml: 4 }}
              >
                {t(
                  'trading:form.hedgingDescription',
                  'When enabled, the strategy can hold both long and short positions simultaneously. Requires a hedging-enabled OANDA account.'
                )}
              </Typography>
              {accountHedgingEnabled === false && (
                <Alert severity="warning" sx={{ mt: 2 }}>
                  {t(
                    'trading:form.hedgingUnsupported',
                    'This OANDA account uses netting mode and does not support hedging. Hedging has been disabled for this task.'
                  )}
                </Alert>
              )}
            </Grid>
          </Grid>
        </>
      ) : null}

      <Box sx={{ mt: 4 }}>
        <Controller
          name="initial_position_cycles"
          control={control}
          render={({ field }) => (
            <BacktestInitialPositionsEditor
              enabled={watchedInitialPositionsEnabled ?? false}
              onEnabledChange={(enabled) =>
                setValue('initial_positions_enabled', enabled, {
                  shouldDirty: true,
                  shouldValidate: true,
                })
              }
              value={field.value ?? []}
              onChange={field.onChange}
              currentTaskId={taskId}
              selectedConfig={selectedConfig ?? undefined}
              strategyType={selectedConfig?.strategy_type}
              taskType="trading"
              showFirstTickInfo={false}
              allowOandaImport
              accountId={accountId}
              configId={selectedConfigId}
              instrument={initialData.instrument}
              resetBaselineEnabled={
                initialData.initial_positions_enabled ?? false
              }
              resetBaselineValue={initialData.initial_position_cycles ?? []}
              error={
                errors.initial_position_cycles?.message as string | undefined
              }
            />
          )}
        />
      </Box>

      <Typography variant="h6" gutterBottom sx={{ mt: 4 }}>
        {t('common:labels.sellOnStop')}
      </Typography>
      <Grid container spacing={3}>
        <Grid size={{ xs: 12 }}>
          <Controller
            name="sell_on_stop"
            control={control}
            render={({ field }) => (
              <FormControlLabel
                control={
                  <Checkbox
                    checked={field.value ?? false}
                    onChange={(event) => field.onChange(event.target.checked)}
                  />
                }
                label={t('common:labels.sellOnStop')}
              />
            )}
          />
          <Typography variant="caption" color="text.secondary" display="block">
            {t('trading:form.sellOnStopDescription')}
          </Typography>
        </Grid>
      </Grid>

      <Typography variant="h6" gutterBottom sx={{ mt: 4 }}>
        {t('trading:form.advancedSettings', 'Advanced settings')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t(
          'trading:form.advancedSettingsDescription',
          'Fine-tune broker retry behaviour, drain-on-stop, and market-close idling. Defaults work well for most tasks.'
        )}
      </Typography>
      <Grid container spacing={3}>
        <Grid size={{ xs: 12, sm: 4 }}>
          <Controller
            name="tick_granularity"
            control={control}
            render={({ field }) => (
              <FormControl fullWidth error={!!errors.tick_granularity}>
                <InputLabel id="trading-update-tick-granularity-label">
                  {t('trading:form.tickGranularity', 'Tick granularity')}
                </InputLabel>
                <Select
                  {...field}
                  labelId="trading-update-tick-granularity-label"
                  label={t('trading:form.tickGranularity', 'Tick granularity')}
                >
                  {TICK_GRANULARITY_OPTIONS.map((value) => (
                    <MenuItem key={value} value={value}>
                      {t(`backtest:form.tickGranularityOptions.${value}`)}
                    </MenuItem>
                  ))}
                </Select>
                <FormHelperText>
                  {errors.tick_granularity?.message ||
                    t(
                      'trading:form.tickGranularityHelp',
                      'Use the first live tick in each selected interval.'
                    )}
                </FormHelperText>
              </FormControl>
            )}
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 4 }}>
          <Controller
            name="api_retry_max_attempts"
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
                  'trading:form.apiRetryMaxAttempts',
                  'OANDA retry attempts'
                )}
                helperText={
                  errors.api_retry_max_attempts?.message ||
                  t(
                    'trading:form.apiRetryMaxAttemptsHelp',
                    'Max retries for broker API calls before failing the task. Default: 50.'
                  )
                }
                error={!!errors.api_retry_max_attempts}
                inputProps={{ min: 1, max: 1000, step: 1 }}
              />
            )}
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 4 }}>
          <Controller
            name="api_retry_backoff_base_seconds"
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
                  'trading:form.apiRetryBaseSeconds',
                  'Retry backoff base (s)'
                )}
                helperText={
                  errors.api_retry_backoff_base_seconds?.message ||
                  t(
                    'trading:form.apiRetryBaseSecondsHelp',
                    'Initial wait between retries. Doubled on each attempt.'
                  )
                }
                error={!!errors.api_retry_backoff_base_seconds}
                inputProps={{ min: 0, step: 0.5 }}
              />
            )}
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 4 }}>
          <Controller
            name="api_retry_backoff_max_seconds"
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
                  'trading:form.apiRetryMaxSeconds',
                  'Retry backoff max (s)'
                )}
                helperText={
                  errors.api_retry_backoff_max_seconds?.message ||
                  t(
                    'trading:form.apiRetryMaxSecondsHelp',
                    'Upper bound on the wait between retries.'
                  )
                }
                error={!!errors.api_retry_backoff_max_seconds}
                inputProps={{ min: 0, step: 1 }}
              />
            )}
          />
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
                  'trading:form.drainDurationHours',
                  'Drain duration (hours)'
                )}
                helperText={
                  errors.drain_duration_hours?.message ||
                  t(
                    'trading:form.drainDurationHoursHelp',
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
                  'trading:form.marketIdlePreCloseMinutes',
                  'Idle before market close (min)'
                )}
                helperText={
                  errors.market_idle_pre_close_minutes?.message ||
                  t(
                    'trading:form.marketIdlePreCloseMinutesHelp',
                    'Switch to IDLE this many minutes before the weekly forex close. 0 disables.'
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
                  'trading:form.marketIdleResumeDelayMinutes',
                  'Resume delay after open (min)'
                )}
                helperText={
                  errors.market_idle_resume_delay_minutes?.message ||
                  t(
                    'trading:form.marketIdleResumeDelayMinutesHelp',
                    'Wait this many minutes after the market reopens before resuming trading.'
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
            name="live_tick_stale_guard_enabled"
            control={control}
            render={({ field }) => (
              <FormControlLabel
                control={
                  <Checkbox
                    checked={field.value ?? true}
                    onChange={(event) => field.onChange(event.target.checked)}
                  />
                }
                label={t(
                  'trading:form.liveTickStaleGuardEnabled',
                  'Enable live tick delay guard'
                )}
              />
            )}
          />
          <Typography variant="caption" color="text.secondary" display="block">
            {t(
              'trading:form.liveTickStaleGuardEnabledHelp',
              'Stop before strategy/order processing when live tick delivery is delayed.'
            )}
          </Typography>
        </Grid>

        <Grid size={{ xs: 12, sm: 4 }}>
          <Controller
            name="live_tick_max_age_seconds"
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
                disabled={liveTickStaleGuardEnabled === false}
                type="text"
                inputMode="decimal"
                label={t(
                  'trading:form.liveTickMaxAgeSeconds',
                  'Max live tick age (s)'
                )}
                helperText={
                  errors.live_tick_max_age_seconds?.message ||
                  t(
                    'trading:form.liveTickMaxAgeSecondsHelp',
                    'Fail the task if an incoming live tick is older than this many seconds.'
                  )
                }
                error={!!errors.live_tick_max_age_seconds}
                inputProps={{ min: 1, max: 3600, step: 1 }}
              />
            )}
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 4 }}>
          <Controller
            name="live_tick_status_log_interval_seconds"
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
                  'trading:form.liveTickStatusLogIntervalSeconds',
                  'Tick status log interval (s)'
                )}
                helperText={
                  errors.live_tick_status_log_interval_seconds?.message ||
                  t(
                    'trading:form.liveTickStatusLogIntervalSecondsHelp',
                    'Write periodic live tick delivery status to the task log. 0 disables OK-status logs.'
                  )
                }
                error={!!errors.live_tick_status_log_interval_seconds}
                inputProps={{ min: 0, max: 3600, step: 1 }}
              />
            )}
          />
        </Grid>

        <Grid size={{ xs: 12, sm: 4 }}>
          <Controller
            name="broker_drift_check_interval_seconds"
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
                  'trading:form.brokerDriftCheckIntervalSeconds',
                  'OANDA drift check interval (s)'
                )}
                helperText={
                  errors.broker_drift_check_interval_seconds?.message ||
                  t(
                    'trading:form.brokerDriftCheckIntervalSecondsHelp',
                    'Check OANDA/local exposure drift at this interval. 0 disables runtime checks after startup reconciliation.'
                  )
                }
                error={!!errors.broker_drift_check_interval_seconds}
                inputProps={{ min: 0, max: 3600, step: 1 }}
              />
            )}
          />
        </Grid>
      </Grid>

      {isSuperuser && (
        <DebugOptionsSection
          tracemalloc={tracemalloc}
          onTracemallocChange={setTracemalloc}
          sx={{ mt: 4 }}
        />
      )}

      {submitValidationBlockReason ? (
        <Alert severity="warning" sx={{ mt: 3 }}>
          {submitValidationBlockReason}
        </Alert>
      ) : null}

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 4 }}>
        <Button
          type="button"
          variant="outlined"
          onClick={() => navigate('/trading-tasks')}
        >
          {t('common:actions.cancel')}
        </Button>

        <Button
          type="submit"
          variant="contained"
          disabled={updateTask.isLoading || isSubmitBlockedByValidation}
        >
          {t('common:actions.updateTask')}
        </Button>
      </Box>
    </Box>
  );
}
