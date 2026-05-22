import { useState, useEffect, useMemo } from 'react';

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
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormHelperText,
  Checkbox,
  FormControlLabel,
  Chip,
} from '@mui/material';
import Grid from '@mui/material/Grid';
import { Warning as WarningIcon } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { useForm, Controller, useWatch, type Resolver } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useTranslation } from 'react-i18next';
import { ConfigurationSelector } from '../tasks/forms/ConfigurationSelector';
import { CurrencyCodeField } from '../tasks/forms/CurrencyCodeField';
import { addInitialPositionSlotStructureIssues } from '../tasks/forms/validationSchemas';
import { BacktestInitialPositionsEditor } from '../backtest/BacktestInitialPositionsEditor';
import { type TradingTaskCreateData } from '../../types/tradingTask';
import type { Account } from '../../types/strategy';
import {
  useCreateTradingTask,
  useUpdateTradingTask,
} from '../../hooks/useTradingTaskMutations';
import { useConfiguration } from '../../hooks/useConfigurations';
import { useAccounts, useAccount } from '../../hooks/useAccounts';
import { useTradingTasks } from '../../hooks/useTradingTasks';
import { TaskStatus } from '../../types/common';
import {
  useStrategies,
  getStrategyDisplayName,
} from '../../hooks/useStrategies';
import { useSupportedInstruments } from '../../hooks/useMarketConfig';
import { useAuth } from '../../contexts/AuthContext';
import { DebugOptionsSection } from '../tasks/forms/DebugOptionsSection';
import { formatMoneyAmount } from '../../utils/numberFormat';
import {
  currencyOptionsForInstrument,
  preferredCurrencyForInstrument,
  preferredCurrencyFromOptions,
} from '../../utils/instruments';
import {
  firstValidationError,
  hasValidationErrors,
} from '../../utils/formValidation';

const steps = [
  'trading:form.steps.account',
  'trading:form.steps.configuration',
  'trading:form.steps.review',
];
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

// Validation schema
const tradingTaskSchema = z
  .object({
    account_id: z.string().min(1, 'Account is required'),
    config_id: z.string().min(1, 'Configuration is required'),
    name: z.string().min(1, 'Name is required').max(255),
    description: z.string().optional(),
    instrument: z.string().min(1, 'Instrument is required'),
    display_currency: z
      .string()
      .trim()
      .toUpperCase()
      .regex(/^[A-Z]{3}$/, 'Display currency must be a 3-letter code'),
    sell_on_stop: z.boolean().optional().default(false),
    dry_run: z.boolean().optional(),
    hedging_enabled: z.boolean().optional(),
    tick_granularity: tickGranularitySchema,
    initial_positions_enabled: z.boolean().optional().default(false),
    initial_position_cycles: z
      .array(initialPositionCycleSchema)
      .optional()
      .default([]),
    risk_acknowledged: z.boolean().optional(),
    api_retry_max_attempts: z
      .number({ message: 'Must be a positive integer' })
      .int('Must be an integer')
      .min(1, 'Must be at least 1')
      .max(1000, 'Must not exceed 1000')
      .optional(),
    api_retry_backoff_base_seconds: z
      .number({ message: 'Must be a non-negative number' })
      .min(0, 'Must be non-negative')
      .max(600, 'Must not exceed 600 seconds')
      .optional(),
    api_retry_backoff_max_seconds: z
      .number({ message: 'Must be a non-negative number' })
      .min(0, 'Must be non-negative')
      .max(3600, 'Must not exceed 3600 seconds')
      .optional(),
    drain_duration_hours: z
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .optional(),
    market_idle_pre_close_minutes: z
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .max(720, 'Must not exceed 720 minutes (12 hours)')
      .optional(),
    market_idle_resume_delay_minutes: z
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .max(720, 'Must not exceed 720 minutes (12 hours)')
      .optional(),
    live_tick_stale_guard_enabled: z.boolean().optional(),
    live_tick_max_age_seconds: z
      .number({ message: 'Must be a positive integer' })
      .int('Must be an integer')
      .min(1, 'Must be at least 1 second')
      .max(3600, 'Must not exceed 3600 seconds')
      .optional(),
    live_tick_status_log_interval_seconds: z
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .max(3600, 'Must not exceed 3600 seconds')
      .optional(),
    broker_drift_check_interval_seconds: z
      .number({ message: 'Must be a non-negative integer' })
      .int('Must be an integer')
      .min(0, 'Must be non-negative')
      .max(3600, 'Must not exceed 3600 seconds')
      .optional(),
  })
  .superRefine((data, ctx) => {
    if (
      data.initial_positions_enabled &&
      !data.initial_position_cycles.length
    ) {
      ctx.addIssue({
        code: 'custom',
        path: ['initial_position_cycles'],
        message: 'At least one initial cycle is required',
      });
    }
    if (data.initial_positions_enabled) {
      addInitialPositionSlotStructureIssues(data.initial_position_cycles, ctx);
    }
  });

type TradingTaskFormData = z.infer<typeof tradingTaskSchema>;

interface TradingTaskFormProps {
  taskId?: string;
  initialData?: Partial<TradingTaskCreateData>;
}

export default function TradingTaskForm({
  taskId,
  initialData,
}: TradingTaskFormProps) {
  const { t } = useTranslation(['trading', 'common', 'backtest']);
  const { user } = useAuth();
  const language = user?.language;
  const navigate = useNavigate();
  const [activeStep, setActiveStep] = useState(0);
  const [formData, setFormData] = useState<Partial<TradingTaskFormData>>(
    initialData || {}
  );
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [tracemalloc, setTracemalloc] = useState(false);
  const isSuperuser = Boolean(user?.is_superuser);
  const createTask = useCreateTradingTask();
  const updateTask = useUpdateTradingTask();

  const {
    control,
    handleSubmit,
    formState: { errors },
    trigger,
    getValues,
    setValue,
  } = useForm<TradingTaskFormData>({
    resolver: zodResolver(tradingTaskSchema) as Resolver<TradingTaskFormData>,
    mode: 'onChange',
    reValidateMode: 'onChange',
    defaultValues: {
      account_id: initialData?.account_id || '',
      config_id: initialData?.config_id || '',
      name: initialData?.name || '',
      description: initialData?.description || '',
      instrument: initialData?.instrument || 'USD_JPY',
      display_currency:
        initialData?.display_currency ||
        preferredCurrencyForInstrument(
          initialData?.instrument || 'USD_JPY',
          language
        ),
      sell_on_stop: initialData?.sell_on_stop ?? false,
      dry_run: false,
      hedging_enabled: true,
      tick_granularity: initialData?.tick_granularity ?? 'tick',
      initial_positions_enabled:
        initialData?.initial_positions_enabled ?? false,
      initial_position_cycles: initialData?.initial_position_cycles ?? [],
      risk_acknowledged: false,
      api_retry_max_attempts: initialData?.api_retry_max_attempts ?? 50,
      api_retry_backoff_base_seconds:
        initialData?.api_retry_backoff_base_seconds ?? 1,
      api_retry_backoff_max_seconds:
        initialData?.api_retry_backoff_max_seconds ?? 60,
      drain_duration_hours: initialData?.drain_duration_hours ?? 0,
      market_idle_pre_close_minutes:
        initialData?.market_idle_pre_close_minutes ?? 0,
      market_idle_resume_delay_minutes:
        initialData?.market_idle_resume_delay_minutes ?? 0,
      live_tick_stale_guard_enabled:
        initialData?.live_tick_stale_guard_enabled ?? true,
      live_tick_max_age_seconds: initialData?.live_tick_max_age_seconds ?? 30,
      live_tick_status_log_interval_seconds:
        initialData?.live_tick_status_log_interval_seconds ?? 60,
      broker_drift_check_interval_seconds:
        initialData?.broker_drift_check_interval_seconds ?? 60,
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

  // Sync saved formData back into React Hook Form when changing steps
  useEffect(() => {
    if (Object.keys(formData).length > 0) {
      Object.entries(formData).forEach(([key, value]) => {
        if (value !== undefined) {
          setValue(key as keyof TradingTaskFormData, value, {
            shouldValidate: false,
          });
        }
      });
    }
  }, [formData, setValue]);

  const selectedAccountId = useWatch({ control, name: 'account_id' });
  const liveTickStaleGuardEnabled = useWatch({
    control,
    name: 'live_tick_stale_guard_enabled',
  });
  const watchedInitialPositionsEnabled = useWatch({
    control,
    name: 'initial_positions_enabled',
  });

  const selectedConfigId = useWatch({ control, name: 'config_id' });
  const watchedInstrument = useWatch({ control, name: 'instrument' });
  const watchedDisplayCurrency = useWatch({
    control,
    name: 'display_currency',
  });
  const currencyOptions = useMemo(
    () => currencyOptionsForInstrument(watchedInstrument || 'USD_JPY'),
    [watchedInstrument]
  );
  const defaultDisplayCurrency =
    preferredCurrencyFromOptions(currencyOptions, language) || 'USD';

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

  const watchedName = useWatch({ control, name: 'name' });

  const watchedDescription = useWatch({ control, name: 'description' });

  // Fetch accounts
  const { data: accountsData } = useAccounts();
  const accounts = (
    Array.isArray(accountsData)
      ? accountsData
      : (accountsData as unknown as { results?: Account[] })?.results || []
  ) as Account[];

  // For review step, use saved formData instead of watch
  // This ensures values persist across step changes
  const effectiveAccountId =
    activeStep === 2 && formData.account_id
      ? formData.account_id
      : selectedAccountId;

  const selectedAccountFromList = accounts.find(
    (account) => String(account.id) === effectiveAccountId
  );

  // Fetch live account details (balance, margin, etc.) from OANDA API
  const accountIdNum = effectiveAccountId ? Number(effectiveAccountId) : 0;
  const { data: accountDetail } = useAccount(accountIdNum, {
    enabled: accountIdNum > 0,
  });

  // Prefer live detail data over stale list data
  const selectedAccount = accountDetail
    ? (accountDetail as Account)
    : selectedAccountFromList;

  const { strategies } = useStrategies();

  const { instruments } = useSupportedInstruments();

  const { data: selectedConfig } = useConfiguration(
    selectedConfigId || undefined
  );
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
    if (
      selectedAccount?.hedging_enabled === false ||
      !strategySupportsHedging
    ) {
      setValue('hedging_enabled', false, {
        shouldValidate: false,
        shouldDirty: true,
      });
    }
  }, [selectedAccount?.hedging_enabled, setValue, strategySupportsHedging]);

  // Check if account already has an active task (only if valid account selected)
  const { data: existingTasks } = useTradingTasks(
    selectedAccountId
      ? {
          account_id: selectedAccountId,
          status: TaskStatus.RUNNING,
        }
      : undefined
  );

  const hasActiveTask =
    existingTasks && existingTasks.results.length > 0 && !taskId;

  const handleNext = async () => {
    // Save current form values to state BEFORE validation
    const currentValues = getValues();
    setFormData((prev) => ({ ...prev, ...currentValues }));

    // Validate current step before proceeding
    let fieldsToValidate: (keyof TradingTaskFormData)[] = [];

    switch (activeStep) {
      case 0: // Account step
        fieldsToValidate = ['account_id'];
        break;
      case 1: // Configuration step
        fieldsToValidate = [
          'config_id',
          'name',
          'instrument',
          'display_currency',
          'tick_granularity',
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

    // Validation passed or no validation needed, proceed to next step
    setActiveStep((prevActiveStep) => prevActiveStep + 1);
  };

  const handleBack = () => {
    // Save current form values to state before going back
    const currentValues = getValues();
    setFormData((prev) => ({ ...prev, ...currentValues }));
    setActiveStep((prevActiveStep) => prevActiveStep - 1);
  };

  const onSubmit = async (data: TradingTaskFormData) => {
    try {
      setSubmitError(null);

      // Merge the saved formData with the current form data to ensure we have all values
      const completeData = { ...formData, ...data } as TradingTaskFormData;

      // For live accounts, validate risk acknowledgment
      if (
        selectedAccount?.api_type === 'live' &&
        !completeData.risk_acknowledged
      ) {
        return;
      }

      const taskData: TradingTaskCreateData = {
        account_id: completeData.account_id,
        config_id: completeData.config_id,
        name: completeData.name,
        description: completeData.description,
        instrument: completeData.instrument,
        display_currency: completeData.display_currency,
        sell_on_stop: completeData.sell_on_stop ?? false,
        dry_run: completeData.dry_run,
        tick_granularity: completeData.tick_granularity,
        hedging_enabled:
          selectedAccount?.hedging_enabled === false || !strategySupportsHedging
            ? false
            : completeData.hedging_enabled,
        initial_positions_enabled: completeData.initial_positions_enabled,
        initial_position_cycles: completeData.initial_positions_enabled
          ? completeData.initial_position_cycles
          : [],
        api_retry_max_attempts: completeData.api_retry_max_attempts,
        api_retry_backoff_base_seconds:
          completeData.api_retry_backoff_base_seconds,
        api_retry_backoff_max_seconds:
          completeData.api_retry_backoff_max_seconds,
        drain_duration_hours: completeData.drain_duration_hours,
        market_idle_pre_close_minutes:
          completeData.market_idle_pre_close_minutes,
        market_idle_resume_delay_minutes:
          completeData.market_idle_resume_delay_minutes,
        live_tick_stale_guard_enabled:
          completeData.live_tick_stale_guard_enabled,
        live_tick_max_age_seconds: completeData.live_tick_max_age_seconds,
        live_tick_status_log_interval_seconds:
          completeData.live_tick_status_log_interval_seconds,
        broker_drift_check_interval_seconds:
          completeData.broker_drift_check_interval_seconds,
        debug_options: isSuperuser ? { tracemalloc } : undefined,
      };

      if (taskId) {
        await updateTask.mutate({ id: taskId, data: taskData });
      } else {
        await createTask.mutate(taskData);
      }
      navigate('/trading-tasks');
    } catch (error: unknown) {
      const err = error as {
        details?: Record<string, string | string[]>;
        message?: string;
      };

      let errorMessage = t(
        'trading:form.createFailed',
        'Failed to create trading task'
      );
      if (err?.details && typeof err.details === 'object') {
        const backendErrors = err.details as Record<string, string | string[]>;
        const errorMessages: string[] = [];
        const fieldMapping: Record<string, string> = {
          account_id: t('trading:form.account'),
          config_id: t('common:labels.configuration'),
          name: t('trading:form.taskName'),
          display_currency: t('common:labels.displayCurrency', {
            defaultValue: 'Display currency',
          }),
          sell_on_stop: t('common:labels.sellOnStop'),
          tick_granularity: t('trading:form.tickGranularity'),
          hedging_enabled: t('trading:form.hedgingEnabled'),
          live_tick_stale_guard_enabled: t(
            'trading:form.liveTickStaleGuardEnabled'
          ),
          live_tick_max_age_seconds: t('trading:form.liveTickMaxAgeSeconds'),
          live_tick_status_log_interval_seconds: t(
            'trading:form.liveTickStatusLogIntervalSeconds'
          ),
          broker_drift_check_interval_seconds: t(
            'trading:form.brokerDriftCheckIntervalSeconds'
          ),
          initial_position_cycles: t('backtest:form.initialPositionCycles', {
            defaultValue: 'Initial position cycles',
          }),
        };

        Object.entries(backendErrors).forEach(([field, messages]) => {
          const fieldName = fieldMapping[field] || field;
          const fieldErrors = Array.isArray(messages) ? messages : [messages];
          fieldErrors.forEach((msg: string) => {
            errorMessages.push(`${fieldName}: ${msg}`);
          });
        });

        if (errorMessages.length > 0) {
          errorMessage = errorMessages.join(' ');
        }
      } else if (err?.message) {
        errorMessage = err.message;
      }

      setSubmitError(errorMessage);
    }
  };

  const getStepContent = (step: number) => {
    switch (step) {
      case 0:
        return (
          <Box>
            <Typography variant="h6" gutterBottom>
              {t('trading:form.selectTradingAccount')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              {t('trading:form.chooseOandaAccount')}
            </Typography>

            <Grid container spacing={3}>
              <Grid size={{ xs: 12 }}>
                <Controller
                  name="account_id"
                  control={control}
                  render={({ field }) => (
                    <FormControl fullWidth error={!!errors.account_id} required>
                      <InputLabel>{t('trading:form.account')}</InputLabel>
                      <Select
                        {...field}
                        label={t('trading:form.account')}
                        value={field.value || ''}
                        onChange={(e) => {
                          field.onChange(String(e.target.value));
                        }}
                      >
                        <MenuItem value="">
                          <em>{t('trading:form.selectAnAccount')}</em>
                        </MenuItem>
                        {accounts.map((account) => (
                          <MenuItem key={account.id} value={account.id}>
                            {account.account_id} ({account.api_type},{' '}
                            {account.currency})
                          </MenuItem>
                        ))}
                      </Select>
                      {errors.account_id && (
                        <FormHelperText>
                          {errors.account_id.message}
                        </FormHelperText>
                      )}
                    </FormControl>
                  )}
                />
              </Grid>

              {selectedAccount && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="info">
                    <Typography variant="subtitle2" gutterBottom>
                      {t('trading:form.accountDetails')}
                    </Typography>
                    <Typography variant="body2">
                      <strong>{t('trading:form.accountId')}:</strong>{' '}
                      {selectedAccount.account_id}
                    </Typography>
                    <Typography variant="body2" component="div">
                      <strong>{t('trading:form.type')}:</strong>{' '}
                      <Chip
                        label={selectedAccount.api_type.toUpperCase()}
                        color={
                          selectedAccount.api_type === 'live'
                            ? 'error'
                            : 'warning'
                        }
                      />
                    </Typography>
                    <Typography variant="body2">
                      <strong>{t('trading:form.balance')}:</strong>{' '}
                      {formatMoneyAmount(
                        parseFloat(selectedAccount.balance),
                        selectedAccount.currency,
                        {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        }
                      )}
                    </Typography>
                    <Typography variant="body2">
                      <strong>{t('trading:form.currency')}:</strong>{' '}
                      {selectedAccount.currency}
                    </Typography>
                  </Alert>
                </Grid>
              )}

              {hasActiveTask && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="error" icon={<WarningIcon />}>
                    <Typography variant="subtitle2" gutterBottom>
                      {t('trading:form.activeTaskDetected')}
                    </Typography>
                    <Typography variant="body2">
                      {t('trading:form.activeTaskWarning')}{' '}
                      <strong>{existingTasks.results[0].name}</strong>
                    </Typography>
                    <Typography variant="body2" sx={{ mt: 1 }}>
                      {t('trading:form.activeTaskInstruction')}
                    </Typography>
                  </Alert>
                </Grid>
              )}
            </Grid>
          </Box>
        );

      case 1:
        return (
          <Box>
            <Typography variant="h6" gutterBottom>
              {t('trading:form.selectConfiguration')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              {t('trading:form.chooseStrategyConfig')}
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
                      {selectedConfig.description ||
                        t('trading:form.noDescription')}
                    </Typography>
                  </Alert>
                </Grid>
              )}

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="instrument"
                  control={control}
                  render={({ field }) => (
                    <FormControl fullWidth error={!!errors.instrument} required>
                      <InputLabel>{t('common:labels.instrument')}</InputLabel>
                      <Select
                        {...field}
                        label={t('common:labels.instrument')}
                        value={field.value || ''}
                      >
                        <MenuItem value="">
                          <em>
                            {t(
                              'trading:form.selectInstrument',
                              'Select an instrument'
                            )}
                          </em>
                        </MenuItem>
                        {instruments.map((inst) => (
                          <MenuItem key={inst} value={inst}>
                            {inst.replace('_', '/')}
                          </MenuItem>
                        ))}
                      </Select>
                      {errors.instrument && (
                        <FormHelperText>
                          {errors.instrument.message}
                        </FormHelperText>
                      )}
                    </FormControl>
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12, md: 6 }}>
                <Controller
                  name="display_currency"
                  control={control}
                  render={({ field }) => (
                    <CurrencyCodeField
                      id="trading-display-currency"
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

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="name"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      fullWidth
                      label={t('trading:form.taskName')}
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

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="sell_on_stop"
                  control={control}
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={field.value ?? false}
                          onChange={(event) =>
                            field.onChange(event.target.checked)
                          }
                        />
                      }
                      label={t('common:labels.sellOnStop')}
                    />
                  )}
                />
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: 'block', ml: 4 }}
                >
                  {t('trading:form.sellOnStopDescription')}
                </Typography>
              </Grid>

              <Grid size={{ xs: 12 }}>
                <Controller
                  name="dry_run"
                  control={control}
                  render={({ field }) => (
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={field.value ?? false}
                          onChange={field.onChange}
                        />
                      }
                      label={t('trading:form.dryRunMode')}
                    />
                  )}
                />
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: 'block', ml: 4 }}
                >
                  {t('trading:form.dryRunDescription')}
                </Typography>
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
                            onChange={field.onChange}
                            disabled={
                              selectedAccount?.hedging_enabled === false
                            }
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
                  {selectedAccount?.hedging_enabled === false && (
                    <Alert severity="warning" sx={{ mt: 2 }}>
                      {t(
                        'trading:form.hedgingUnsupported',
                        'This OANDA account uses netting mode and does not support hedging. Hedging has been disabled for this task.'
                      )}
                    </Alert>
                  )}
                </Grid>
              ) : null}

              <Grid size={{ xs: 12 }}>
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
                      accountId={selectedAccountId}
                      configId={selectedConfigId}
                      instrument={watchedInstrument}
                      error={
                        errors.initial_position_cycles?.message as
                          | string
                          | undefined
                      }
                    />
                  )}
                />
              </Grid>

              <Grid size={{ xs: 12 }}>
                <Typography
                  variant="subtitle2"
                  sx={{ mt: 2, mb: 1, fontWeight: 600 }}
                >
                  {t('trading:form.advancedSettings', 'Advanced settings')}
                </Typography>
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{ display: 'block', mb: 2 }}
                >
                  {t(
                    'trading:form.advancedSettingsDescription',
                    'Fine-tune broker retry behaviour, drain-on-stop, and market-close idling. Defaults work well for most tasks.'
                  )}
                </Typography>
              </Grid>

              <Grid size={{ xs: 12, sm: 4 }}>
                <Controller
                  name="tick_granularity"
                  control={control}
                  render={({ field }) => (
                    <FormControl fullWidth error={!!errors.tick_granularity}>
                      <InputLabel id="trading-tick-granularity-label">
                        {t('trading:form.tickGranularity', 'Tick granularity')}
                      </InputLabel>
                      <Select
                        {...field}
                        labelId="trading-tick-granularity-label"
                        label={t(
                          'trading:form.tickGranularity',
                          'Tick granularity'
                        )}
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
                          onChange={(event) =>
                            field.onChange(event.target.checked)
                          }
                        />
                      }
                      label={t(
                        'trading:form.liveTickStaleGuardEnabled',
                        'Enable live tick delay guard'
                      )}
                    />
                  )}
                />
                <FormHelperText>
                  {t(
                    'trading:form.liveTickStaleGuardEnabledHelp',
                    'Stop before strategy/order processing when live tick delivery is delayed.'
                  )}
                </FormHelperText>
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
          </Box>
        );

      case 2:
        return (
          <Box>
            <Typography variant="h6" gutterBottom>
              {t('trading:form.reviewAndConfirm')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              {t('trading:form.reviewBeforeCreating')}
            </Typography>

            <Grid container spacing={3}>
              <Grid size={{ xs: 12 }}>
                <Paper sx={{ p: 3 }}>
                  <Typography variant="subtitle1" gutterBottom>
                    {t('trading:form.taskSummary')}
                  </Typography>

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('trading:form.taskName')}
                    </Typography>
                    <Typography variant="body1" gutterBottom>
                      {watchedName}
                    </Typography>
                  </Box>

                  {watchedDescription && (
                    <Box sx={{ mt: 2 }}>
                      <Typography variant="body2" color="text.secondary">
                        {t('common:labels.description')}
                      </Typography>
                      <Typography variant="body1" gutterBottom>
                        {watchedDescription}
                      </Typography>
                    </Box>
                  )}

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('trading:form.account')}
                    </Typography>
                    <Typography variant="body1" gutterBottom>
                      {selectedAccount ? (
                        <>
                          {selectedAccount.account_id} (
                          {selectedAccount.api_type}, {selectedAccount.currency}
                          )
                        </>
                      ) : selectedAccountId ? (
                        t('trading:form.loadingAccounts')
                      ) : (
                        t('trading:form.noAccountsAvailable')
                      )}
                    </Typography>
                  </Box>

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('common:labels.accountCurrency', {
                        defaultValue: 'Account currency',
                      })}
                    </Typography>
                    <Typography variant="body1" gutterBottom>
                      {selectedAccount?.currency ?? '—'}
                    </Typography>
                  </Box>

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('common:labels.configuration')}
                    </Typography>
                    <Typography variant="body1" gutterBottom>
                      {selectedConfig ? (
                        <>
                          {selectedConfig.name} (
                          {getStrategyDisplayName(
                            strategies,
                            selectedConfig.strategy_type
                          )}
                          )
                        </>
                      ) : (
                        t('common:status.loading')
                      )}
                    </Typography>
                  </Box>

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('common:labels.instrument')}
                    </Typography>
                    <Typography variant="body1" gutterBottom>
                      {formData.instrument
                        ? formData.instrument.replace('_', '/')
                        : '\u2014'}
                    </Typography>
                  </Box>

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('common:labels.displayCurrency', {
                        defaultValue: 'Display currency',
                      })}
                    </Typography>
                    <Typography variant="body1" gutterBottom>
                      {formData.display_currency || defaultDisplayCurrency}
                    </Typography>
                  </Box>

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('trading:form.tickGranularity', 'Tick granularity')}
                    </Typography>
                    <Typography variant="body1" gutterBottom>
                      {t(
                        `backtest:form.tickGranularityOptions.${formData.tick_granularity ?? 'tick'}`
                      )}
                    </Typography>
                  </Box>

                  <Box sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('common:labels.sellOnStop')}
                    </Typography>
                    <Typography variant="body1" gutterBottom>
                      {formData.sell_on_stop
                        ? t('common:labels.yes')
                        : t('common:labels.no')}
                    </Typography>
                  </Box>
                </Paper>
              </Grid>

              {formData.dry_run && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="warning">
                    <Typography variant="subtitle2" gutterBottom>
                      {t('trading:form.dryRunModeEnabled')}
                    </Typography>
                    <Typography variant="body2">
                      {t('trading:form.dryRunWarning')}
                    </Typography>
                  </Alert>
                </Grid>
              )}

              {isSuperuser && (
                <Grid size={{ xs: 12 }}>
                  <DebugOptionsSection
                    tracemalloc={tracemalloc}
                    onTracemallocChange={setTracemalloc}
                  />
                </Grid>
              )}

              {selectedAccount?.api_type === 'live' && (
                <>
                  <Grid size={{ xs: 12 }}>
                    <Alert severity="error" icon={<WarningIcon />}>
                      <Typography variant="subtitle2" gutterBottom>
                        <strong>
                          {t('trading:risk.liveRiskWarningTitle')}
                        </strong>
                      </Typography>
                      <Typography variant="body2" gutterBottom>
                        {t('trading:risk.liveRiskWarningBody')}
                      </Typography>
                      <Typography variant="body2" gutterBottom>
                        • {t('trading:risk.realMoneyAtRisk')}
                      </Typography>
                      <Typography variant="body2" gutterBottom>
                        • {t('trading:risk.pastPerformance')}
                      </Typography>
                      <Typography variant="body2" gutterBottom>
                        • {t('trading:risk.monitorClosely')}
                      </Typography>
                      <Typography variant="body2">
                        • {t('trading:risk.canStopAnytime')}
                      </Typography>
                    </Alert>
                  </Grid>

                  <Grid size={{ xs: 12 }}>
                    <Controller
                      name="risk_acknowledged"
                      control={control}
                      render={({ field }) => (
                        <FormControl error={!!errors.risk_acknowledged}>
                          <FormControlLabel
                            control={
                              <Checkbox
                                checked={field.value}
                                onChange={field.onChange}
                              />
                            }
                            label={t('trading:risk.acknowledgeRisks')}
                          />
                          {errors.risk_acknowledged && (
                            <FormHelperText>
                              {errors.risk_acknowledged.message}
                            </FormHelperText>
                          )}
                        </FormControl>
                      )}
                    />
                  </Grid>
                </>
              )}

              {selectedAccount?.api_type === 'practice' && (
                <Grid size={{ xs: 12 }}>
                  <Alert severity="info">
                    <Typography variant="subtitle2" gutterBottom>
                      <strong>{t('trading:risk.practiceAccountTitle')}</strong>
                    </Typography>
                    <Typography variant="body2">
                      {t('trading:risk.practiceAccountBody')}
                    </Typography>
                  </Alert>
                </Grid>
              )}
            </Grid>
          </Box>
        );

      default:
        return 'Unknown step';
    }
  };

  return (
    <Box>
      <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
        {steps.map((label) => (
          <Step key={label}>
            <StepLabel>{t(label)}</StepLabel>
          </Step>
        ))}
      </Stepper>

      <Paper sx={{ p: 3 }}>
        {getStepContent(activeStep)}

        {submitError && (
          <Alert severity="error" sx={{ mt: 3 }}>
            {submitError}
          </Alert>
        )}

        {activeStep === steps.length - 1 && submitValidationBlockReason ? (
          <Alert severity="warning" sx={{ mt: 3 }}>
            {submitValidationBlockReason}
          </Alert>
        ) : null}

        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 3 }}>
          <Button onClick={() => navigate(-1)} sx={{ mr: 'auto' }}>
            {t('common:actions.cancel')}
          </Button>
          <Button
            disabled={activeStep === 0}
            onClick={handleBack}
            sx={{ mr: 1 }}
          >
            {t('common:actions.back')}
          </Button>
          {activeStep === steps.length - 1 ? (
            <Button
              variant="contained"
              onClick={handleSubmit(onSubmit)}
              disabled={
                createTask.isLoading ||
                updateTask.isLoading ||
                isSubmitBlockedByValidation
              }
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
      </Paper>
    </Box>
  );
}
