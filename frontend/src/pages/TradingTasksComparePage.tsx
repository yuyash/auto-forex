import { useMemo } from 'react';
import { useQueries } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useTranslation } from 'react-i18next';
import { queryKeys } from '../config/reactQuery';
import { tradingTasksApi } from '../services/api/tradingTasks';
import type { TradingTask } from '../types/tradingTask';
import { Breadcrumbs, PageContainer } from '../components/common';
import {
  SettingsComparisonTable,
  type SettingsComparisonItem,
} from '../components/comparison/SettingsComparisonTable';
import { buildTaskComparisonLabelMap } from '../components/tasks/detail/taskSettingDefinitions';
import { parseCompareIds } from '../utils/compareParams';
import { getStrategyDisplayName, useStrategies } from '../hooks/useStrategies';

function setIfPresent(
  target: Record<string, unknown>,
  key: string,
  value: unknown
) {
  if (value === undefined || value === null || value === '') return;
  target[key] = value;
}

function tradingTaskSettings(
  task: TradingTask,
  strategyName: string
): Record<string, unknown> {
  const settings: Record<string, unknown> = {};
  setIfPresent(settings, 'name', task.name);
  setIfPresent(settings, 'description', task.description);
  setIfPresent(settings, 'strategy_type', strategyName);
  setIfPresent(settings, 'config_name', task.config_name);
  setIfPresent(settings, 'config_revision', task.config_revision);
  setIfPresent(settings, 'config_hash', task.config_hash);
  setIfPresent(settings, 'instrument', task.instrument);
  setIfPresent(settings, 'account_name', task.account_name);
  setIfPresent(settings, 'account_type', task.account_type);
  setIfPresent(settings, 'account_currency', task.account_currency);
  setIfPresent(settings, 'display_currency', task.display_currency);
  setIfPresent(settings, 'sell_on_stop', task.sell_on_stop);
  setIfPresent(settings, 'dry_run', task.dry_run);
  setIfPresent(settings, 'hedging_enabled', task.hedging_enabled);
  setIfPresent(settings, 'api_retry_max_attempts', task.api_retry_max_attempts);
  setIfPresent(
    settings,
    'api_retry_backoff_base_seconds',
    task.api_retry_backoff_base_seconds
  );
  setIfPresent(
    settings,
    'api_retry_backoff_max_seconds',
    task.api_retry_backoff_max_seconds
  );
  setIfPresent(settings, 'drain_duration_hours', task.drain_duration_hours);
  setIfPresent(
    settings,
    'market_idle_pre_close_minutes',
    task.market_idle_pre_close_minutes
  );
  setIfPresent(
    settings,
    'market_idle_resume_delay_minutes',
    task.market_idle_resume_delay_minutes
  );
  setIfPresent(
    settings,
    'live_tick_stale_guard_enabled',
    task.live_tick_stale_guard_enabled
  );
  setIfPresent(
    settings,
    'live_tick_max_age_seconds',
    task.live_tick_max_age_seconds
  );
  setIfPresent(
    settings,
    'live_tick_status_log_interval_seconds',
    task.live_tick_status_log_interval_seconds
  );
  setIfPresent(
    settings,
    'broker_drift_check_interval_seconds',
    task.broker_drift_check_interval_seconds
  );
  setIfPresent(settings, 'debug_options', task.debug_options);
  return settings;
}

export default function TradingTasksComparePage() {
  const { t } = useTranslation(['common', 'trading']);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const ids = useMemo(() => parseCompareIds(searchParams), [searchParams]);
  const { strategies } = useStrategies();

  const queries = useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.tradingTasks.detail(id),
      queryFn: () => tradingTasksApi.get(id),
      enabled: ids.length >= 2,
    })),
  });

  const isLoading = queries.some((query) => query.isLoading);
  const error = queries.find((query) => query.error)?.error;
  const tasks = queries
    .map((query) => query.data)
    .filter((task): task is TradingTask => Boolean(task));

  const labelMap = useMemo(
    () =>
      buildTaskComparisonLabelMap(t, 'trading', {
        includeDebugOptions: true,
      }),
    [t]
  );

  const items = useMemo<SettingsComparisonItem[]>(
    () =>
      tasks.map((task) => {
        const strategyName = getStrategyDisplayName(
          strategies,
          task.strategy_type
        );
        return {
          id: task.id,
          title: task.name,
          subtitle: `${strategyName} / ${task.account_name}`,
          settings: tradingTaskSettings(task, strategyName),
        };
      }),
    [strategies, tasks]
  );

  return (
    <PageContainer sx={{ mt: { xs: 1, sm: 1.5 }, mb: 1.5 }}>
      <Breadcrumbs />
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1,
          flexWrap: 'wrap',
          mb: 1,
        }}
      >
        <Typography
          variant="h4"
          component="h1"
          sx={{ fontSize: { xs: '1.25rem', sm: '1.5rem' }, fontWeight: 600 }}
        >
          {t('comparison.tradingTaskTitle', {
            defaultValue: 'Compare Trading Tasks',
          })}
        </Typography>
        <Button
          variant="outlined"
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/trading-tasks')}
        >
          {t('breadcrumbs.tradingTasks')}
        </Button>
      </Box>

      {ids.length < 2 ? (
        <Alert severity="info">
          {t('comparison.selectAtLeastTwo', {
            defaultValue: 'Select at least two items to compare.',
          })}
        </Alert>
      ) : isLoading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      ) : error ? (
        <Alert severity="error">
          {error instanceof Error ? error.message : String(error)}
        </Alert>
      ) : (
        <SettingsComparisonTable
          items={items}
          labelMap={labelMap}
          keyOrder={[
            'name',
            'description',
            'strategy_type',
            'config_name',
            'config_revision',
            'config_hash',
            'instrument',
            'account_name',
            'account_type',
            'account_currency',
            'display_currency',
            'sell_on_stop',
            'dry_run',
            'hedging_enabled',
            'api_retry_max_attempts',
            'api_retry_backoff_base_seconds',
            'api_retry_backoff_max_seconds',
            'drain_duration_hours',
            'market_idle_pre_close_minutes',
            'market_idle_resume_delay_minutes',
            'live_tick_stale_guard_enabled',
            'live_tick_max_age_seconds',
            'live_tick_status_log_interval_seconds',
            'broker_drift_check_interval_seconds',
            'debug_options',
          ]}
        />
      )}
    </PageContainer>
  );
}
