import { useMemo, useState } from 'react';
import { Box, Divider, Grid, Link, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';
import { Link as RouterLink } from 'react-router-dom';
import { ExecutionHistoryTable } from '../../tasks/display/ExecutionHistoryTable';
import { ExecutionStatusSummary } from '../../tasks/detail/ExecutionStatusSummary';
import { ExecutionWatermarkSummary } from '../../tasks/detail/ExecutionWatermarkSummary';
import { HistoricalStrategyConfigDialog } from '../../tasks/detail/HistoricalStrategyConfigDialog';
import {
  InitialPositionSettingValue,
  selectInitialPositionSettingValue,
} from '../../tasks/detail/InitialPositionSettingValue';
import { TaskSettingsList } from '../../tasks/detail/TaskSettingsList';
import { buildBacktestTaskSettingDefinitions } from '../../tasks/detail/taskSettingDefinitions';
import type { TaskSummary } from '../../../hooks/useTaskSummary';
import { getStrategyDisplayName } from '../../../hooks/useStrategies';
import type { Strategy } from '../../../services/api/strategies';
import { TaskType, type TaskStatus } from '../../../types/common';
import type { BacktestTask } from '../../../types';
import type { TaskExecution } from '../../../types/execution';
import type { StrategySnapshotResponse } from '../../../types/strategyVisualization';
import type { MetricPoint } from '../../../utils/fetchMetrics';
import { useAuth } from '../../../contexts/AuthContext';
import { useDateTimeFormatter } from '../../../hooks/useDateTimeFormatter';
import { useNumberFormatter } from '../../../hooks/useNumberFormatter';
import {
  canEditDisplayedStrategyConfig,
  formatStrategyConfigRevisionLabel,
  getStrategyConfigSnapshotName,
  getStrategyConfigSnapshotRevision,
  getStrategyConfigSnapshotType,
} from '../../../utils/strategyConfigRevision';

const BACKTEST_PERIOD_SETTING_KEYS = new Set([
  'start_time',
  'end_time',
  'tick_granularity',
  'tick_window_value_mode',
  'max_tick_gap_hours',
  'backtest_tick_batch_size',
  'spread_filter_enabled',
  'max_spread_pips',
  'oanda_candle_filter_enabled',
  'oanda_candle_filter_account_name',
  'oanda_candle_filter_granularity',
  'oanda_candle_filter_tolerance_pips',
]);

interface BacktestOverviewTabProps {
  taskId: string;
  task: BacktestTask;
  summary: TaskSummary;
  currentStatus?: TaskStatus;
  strategies: Strategy[];
  pnlCurrency: string;
  latestMetrics?: MetricPoint | null;
  strategySnapshot?: StrategySnapshotResponse | null;
  strategySnapshotLoading?: boolean;
  strategySnapshotError?: Error | null;
  onRefreshExecutionStatus?: () => void | Promise<unknown>;
  executionStatusRefreshing?: boolean;
  timezone: string;
  language?: string;
  isViewingHistorical?: boolean;
  historicalStrategyConfig?: TaskExecution['strategy_config'];
  executionId?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  historicalTaskConfig?: Record<string, any> | null;
  onOpenConfiguration: () => void;
}

export function BacktestOverviewTab({
  taskId,
  task,
  summary,
  strategies,
  pnlCurrency,
  latestMetrics,
  strategySnapshot,
  strategySnapshotLoading,
  strategySnapshotError,
  onRefreshExecutionStatus,
  executionStatusRefreshing = false,
  timezone,
  language,
  isViewingHistorical = false,
  historicalStrategyConfig,
  executionId,
  historicalTaskConfig,
  onOpenConfiguration,
}: BacktestOverviewTabProps) {
  const { t } = useTranslation(['backtest', 'common']);
  const { user } = useAuth();
  const { formatDateTime } = useDateTimeFormatter({
    includeTimezone: true,
  });
  const { separators } = useNumberFormatter();
  const isSuperuser = Boolean(user?.is_superuser);
  const [historicalConfigOpen, setHistoricalConfigOpen] = useState(false);
  const hasExecutionConfigSnapshot = Boolean(historicalStrategyConfig);
  const canEditDisplayedConfig = canEditDisplayedStrategyConfig({
    configId: task.config_id,
    config: historicalStrategyConfig,
    isViewingHistorical,
    currentRevision: task.config_revision,
    currentHash: task.config_hash,
  });

  // Prefer execution snapshots when available, including the current run.
  const effectiveStartTime =
    historicalTaskConfig?.start_time || task.start_time;
  const effectiveEndTime = historicalTaskConfig?.end_time || task.end_time;
  const effectiveInstrument =
    historicalTaskConfig?.instrument || task.instrument;
  const latestMarginRatioRaw = latestMetrics?.metrics.margin_ratio;
  const latestMarginRatio =
    latestMarginRatioRaw != null && latestMarginRatioRaw !== ''
      ? Number(latestMarginRatioRaw)
      : null;
  const displayedMarginRatio = Number.isFinite(latestMarginRatio)
    ? latestMarginRatio
    : summary.execution.marginRatio;

  const taskSettings = useMemo(
    () =>
      buildBacktestTaskSettingDefinitions(t, timezone, language, {
        includeDebugOptions: isSuperuser,
        numberSeparators: separators,
      })
        .filter(
          (definition) => !BACKTEST_PERIOD_SETTING_KEYS.has(definition.key)
        )
        .map((definition) => {
          if (definition.key === 'config_name') {
            return {
              ...definition,
              render: () => {
                const label =
                  (hasExecutionConfigSnapshot &&
                    formatStrategyConfigRevisionLabel(
                      getStrategyConfigSnapshotName(historicalStrategyConfig),
                      getStrategyConfigSnapshotRevision(
                        historicalStrategyConfig
                      )
                    )) ||
                  formatStrategyConfigRevisionLabel(
                    task.config_name,
                    task.config_revision
                  );

                if (hasExecutionConfigSnapshot) {
                  if (!historicalStrategyConfig) {
                    return (
                      <Typography
                        variant="body1"
                        sx={{ wordBreak: 'break-word' }}
                      >
                        {label}
                      </Typography>
                    );
                  }

                  return (
                    <Link
                      component="button"
                      type="button"
                      variant="body1"
                      aria-haspopup="dialog"
                      onClick={() => setHistoricalConfigOpen(true)}
                      sx={{
                        display: 'inline-block',
                        maxWidth: '100%',
                        textAlign: 'left',
                      }}
                    >
                      {label}
                    </Link>
                  );
                }

                if (task.config_id) {
                  return (
                    <Link
                      component={RouterLink}
                      to={`/configurations/${task.config_id}`}
                      variant="body1"
                      sx={{ display: 'inline-block', maxWidth: '100%' }}
                    >
                      {label}
                    </Link>
                  );
                }

                return (
                  <Link
                    component="button"
                    variant="body1"
                    onClick={onOpenConfiguration}
                    sx={{ textAlign: 'left' }}
                  >
                    {label}
                  </Link>
                );
              },
            };
          }

          if (definition.key === 'strategy_type') {
            return {
              ...definition,
              render: () =>
                getStrategyDisplayName(
                  strategies,
                  (hasExecutionConfigSnapshot &&
                    getStrategyConfigSnapshotType(historicalStrategyConfig)) ||
                    task.strategy_type
                ),
            };
          }

          if (definition.key === 'initial_position_cycles') {
            return {
              ...definition,
              render: (
                value: unknown,
                context: {
                  task: Record<string, unknown>;
                  snapshot?: Record<string, unknown> | null;
                  source: Record<string, unknown>;
                }
              ) => (
                <InitialPositionSettingValue
                  value={selectInitialPositionSettingValue(value, context)}
                  executionId={executionId}
                />
              ),
            };
          }

          return definition;
        }),
    [
      executionId,
      historicalStrategyConfig,
      hasExecutionConfigSnapshot,
      isSuperuser,
      language,
      onOpenConfiguration,
      separators,
      strategies,
      t,
      task.config_id,
      task.config_name,
      task.config_revision,
      task.strategy_type,
      timezone,
    ]
  );
  const normalizedHistoricalTaskConfig = useMemo(() => {
    if (!historicalTaskConfig) {
      return historicalTaskConfig;
    }

    const sellAtCompletion =
      historicalTaskConfig.sell_on_stop ??
      historicalTaskConfig.sell_at_completion;

    if (sellAtCompletion === undefined) {
      return historicalTaskConfig;
    }

    return {
      ...historicalTaskConfig,
      sell_at_completion: sellAtCompletion,
    };
  }, [historicalTaskConfig]);

  return (
    <Box sx={{ p: { xs: 1.5, sm: 3 } }}>
      <Grid container spacing={{ xs: 2, sm: 3 }}>
        <Grid size={{ xs: 12 }}>
          <TaskSettingsList
            title={t('common:labels.taskInformation')}
            task={task as unknown as Record<string, unknown>}
            snapshot={normalizedHistoricalTaskConfig}
            definitions={taskSettings}
          />
        </Grid>

        <Grid size={{ xs: 12 }}>
          <Divider sx={{ my: 2 }} />
          <Typography variant="h6" gutterBottom>
            {t('backtest:detail.backtestPeriod')}
          </Typography>
          <Box sx={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t('backtest:detail.startTime')}
              </Typography>
              <Typography variant="body1">
                {formatDateTime(effectiveStartTime)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t('backtest:detail.endTime')}
              </Typography>
              <Typography variant="body1">
                {formatDateTime(effectiveEndTime)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t('backtest:detail.tickGranularity')}
              </Typography>
              <Typography variant="body1">
                {t(
                  `backtest:form.tickGranularityOptions.${task.tick_granularity}`,
                  task.tick_granularity
                )}
              </Typography>
            </Box>
            {task.tick_granularity !== 'tick' && (
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('backtest:detail.tickWindowValueMode')}
                </Typography>
                <Typography variant="body1">
                  {t(
                    `backtest:form.tickWindowValueModeOptions.${task.tick_window_value_mode}`,
                    task.tick_window_value_mode
                  )}
                </Typography>
              </Box>
            )}
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t(
                  'backtest:form.maxTickGapHours',
                  'Max tick gap before fail (hours)'
                )}
              </Typography>
              <Typography variant="body1">
                {task.max_tick_gap_hours ?? 120}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary">
                {t('backtest:form.backtestTickBatchSize', 'Tick batch size')}
              </Typography>
              <Typography variant="body1">
                {task.backtest_tick_batch_size ?? 1000}
              </Typography>
            </Box>
          </Box>
        </Grid>

        <Grid size={{ xs: 12 }}>
          <ExecutionStatusSummary
            taskNamespace="backtest"
            summary={summary}
            latestMetrics={latestMetrics ?? null}
            pnlCurrency={pnlCurrency}
            displayedMarginRatio={displayedMarginRatio}
            snapshot={strategySnapshot ?? null}
            isSnapshotLoading={strategySnapshotLoading}
            snapshotError={strategySnapshotError}
            onRefresh={onRefreshExecutionStatus}
            isRefreshing={executionStatusRefreshing}
          />
          <ExecutionWatermarkSummary
            summary={summary}
            pnlCurrency={pnlCurrency}
          />
        </Grid>

        <Grid size={{ xs: 12 }}>
          <Divider sx={{ my: 2 }} />
          <ExecutionHistoryTable
            taskId={taskId}
            taskType={TaskType.BACKTEST}
            instrument={effectiveInstrument}
          />
        </Grid>
      </Grid>
      <HistoricalStrategyConfigDialog
        open={historicalConfigOpen}
        onClose={() => setHistoricalConfigOpen(false)}
        config={historicalStrategyConfig}
        strategies={strategies}
        editHref={
          canEditDisplayedConfig
            ? `/configurations/${task.config_id}/edit`
            : undefined
        }
      />
    </Box>
  );
}
