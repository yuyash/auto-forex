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
import { backtestTasksApi } from '../services/api/backtestTasks';
import type { BacktestTask } from '../types/backtestTask';
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

function backtestTaskSettings(
  task: BacktestTask,
  strategyName: string
): Record<string, unknown> {
  const settings: Record<string, unknown> = {};
  setIfPresent(settings, 'name', task.name);
  setIfPresent(settings, 'description', task.description);
  setIfPresent(settings, 'strategy_type', strategyName);
  setIfPresent(settings, 'config_name', task.config_name);
  setIfPresent(settings, 'config_revision', task.config_revision);
  setIfPresent(settings, 'config_hash', task.config_hash);
  setIfPresent(settings, 'data_source', task.data_source);
  setIfPresent(settings, 'start_time', task.start_time);
  setIfPresent(settings, 'end_time', task.end_time);
  setIfPresent(settings, 'instrument', task.instrument);
  setIfPresent(settings, 'initial_balance', task.initial_balance);
  setIfPresent(settings, 'account_currency', task.account_currency);
  setIfPresent(settings, 'display_currency', task.display_currency);
  setIfPresent(settings, 'commission_per_trade', task.commission_per_trade);
  setIfPresent(settings, 'pip_size', task.pip_size);
  setIfPresent(settings, 'tick_granularity', task.tick_granularity);
  setIfPresent(settings, 'tick_window_value_mode', task.tick_window_value_mode);
  setIfPresent(settings, 'sell_at_completion', task.sell_at_completion);
  setIfPresent(settings, 'sell_on_stop', task.sell_on_stop);
  setIfPresent(settings, 'hedging_enabled', task.hedging_enabled);
  setIfPresent(settings, 'in_memory_mode', task.in_memory_mode);
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
  setIfPresent(settings, 'market_close_enabled', task.market_close_enabled);
  setIfPresent(settings, 'market_close_weekday', task.market_close_weekday);
  setIfPresent(settings, 'market_close_hour_utc', task.market_close_hour_utc);
  setIfPresent(settings, 'market_open_weekday', task.market_open_weekday);
  setIfPresent(settings, 'market_open_hour_utc', task.market_open_hour_utc);
  setIfPresent(settings, 'max_tick_gap_hours', task.max_tick_gap_hours);
  setIfPresent(
    settings,
    'backtest_tick_batch_size',
    task.backtest_tick_batch_size
  );
  setIfPresent(settings, 'spread_filter_enabled', task.spread_filter_enabled);
  setIfPresent(settings, 'max_spread_pips', task.max_spread_pips);
  setIfPresent(
    settings,
    'oanda_candle_filter_enabled',
    task.oanda_candle_filter_enabled
  );
  setIfPresent(
    settings,
    'oanda_candle_filter_account_name',
    task.oanda_candle_filter_account_name
  );
  setIfPresent(
    settings,
    'oanda_candle_filter_granularity',
    task.oanda_candle_filter_granularity
  );
  setIfPresent(
    settings,
    'oanda_candle_filter_tolerance_pips',
    task.oanda_candle_filter_tolerance_pips
  );
  setIfPresent(settings, 'holidays_enabled', task.holidays_enabled);
  setIfPresent(settings, 'excluded_dates', task.excluded_dates);
  setIfPresent(
    settings,
    'initial_positions_enabled',
    task.initial_positions_enabled
  );
  setIfPresent(
    settings,
    'initial_position_cycles',
    task.initial_position_cycles
  );
  setIfPresent(settings, 'debug_options', task.debug_options);
  return settings;
}

export default function BacktestTasksComparePage() {
  const { t } = useTranslation(['common', 'backtest']);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const ids = useMemo(() => parseCompareIds(searchParams), [searchParams]);
  const { strategies } = useStrategies();

  const queries = useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.backtestTasks.detail(id),
      queryFn: () => backtestTasksApi.get(id),
      enabled: ids.length >= 2,
    })),
  });

  const isLoading = queries.some((query) => query.isLoading);
  const error = queries.find((query) => query.error)?.error;
  const tasks = queries
    .map((query) => query.data)
    .filter((task): task is BacktestTask => Boolean(task));

  const labelMap = useMemo(
    () =>
      buildTaskComparisonLabelMap(t, 'backtest', {
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
          subtitle: `${strategyName} / ${task.instrument}`,
          settings: backtestTaskSettings(task, strategyName),
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
          {t('comparison.backtestTaskTitle', {
            defaultValue: 'Compare Backtest Tasks',
          })}
        </Typography>
        <Button
          variant="outlined"
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/backtest-tasks')}
        >
          {t('breadcrumbs.backtestTasks')}
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
            'data_source',
            'start_time',
            'end_time',
            'instrument',
            'initial_balance',
            'account_currency',
            'display_currency',
            'commission_per_trade',
            'pip_size',
            'tick_granularity',
            'tick_window_value_mode',
            'sell_at_completion',
            'sell_on_stop',
            'hedging_enabled',
            'in_memory_mode',
            'drain_duration_hours',
            'market_idle_pre_close_minutes',
            'market_idle_resume_delay_minutes',
            'market_close_enabled',
            'market_close_weekday',
            'market_close_hour_utc',
            'market_open_weekday',
            'market_open_hour_utc',
            'max_tick_gap_hours',
            'backtest_tick_batch_size',
            'spread_filter_enabled',
            'max_spread_pips',
            'oanda_candle_filter_enabled',
            'oanda_candle_filter_account_name',
            'oanda_candle_filter_granularity',
            'oanda_candle_filter_tolerance_pips',
            'holidays_enabled',
            'excluded_dates',
            'initial_positions_enabled',
            'initial_position_cycles',
            'debug_options',
          ]}
        />
      )}
    </PageContainer>
  );
}
