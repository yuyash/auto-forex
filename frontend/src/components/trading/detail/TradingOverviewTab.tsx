import { useMemo, useState } from 'react';
import { Alert, Box, Divider, Grid, Link } from '@mui/material';
import { useTranslation } from 'react-i18next';
import { Link as RouterLink } from 'react-router-dom';
import { ExecutionHistoryTable } from '../../tasks/display/ExecutionHistoryTable';
import {
  ExecutionStatusSummary,
  type ExecutionStatusExtraItem,
} from '../../tasks/detail/ExecutionStatusSummary';
import { ExecutionWatermarkSummary } from '../../tasks/detail/ExecutionWatermarkSummary';
import { HistoricalStrategyConfigDialog } from '../../tasks/detail/HistoricalStrategyConfigDialog';
import {
  InitialPositionSettingValue,
  selectInitialPositionSettingValue,
} from '../../tasks/detail/InitialPositionSettingValue';
import { TaskSettingsList } from '../../tasks/detail/TaskSettingsList';
import { buildTradingTaskSettingDefinitions } from '../../tasks/detail/taskSettingDefinitions';
import type { TaskSummary } from '../../../hooks/useTaskSummary';
import { getStrategyDisplayName } from '../../../hooks/useStrategies';
import type { Strategy } from '../../../services/api/strategies';
import { TaskType, type TaskStatus } from '../../../types/common';
import type { TradingTask } from '../../../types';
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

interface TradingOverviewTabProps {
  taskId: string;
  task: TradingTask;
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
  isViewingHistorical?: boolean;
  historicalStrategyConfig?: TaskExecution['strategy_config'];
  executionId?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  historicalTaskConfig?: Record<string, any> | null;
  onOpenConfiguration: () => void;
}

export function TradingOverviewTab({
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
  isViewingHistorical = false,
  historicalStrategyConfig,
  executionId,
  historicalTaskConfig,
  onOpenConfiguration,
}: TradingOverviewTabProps) {
  const { t } = useTranslation(['trading', 'common', 'backtest']);
  const { user } = useAuth();
  const { formatDateTime } = useDateTimeFormatter({
    includeSeconds: true,
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

  // When viewing a historical execution, prefer snapshot values
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
      buildTradingTaskSettingDefinitions(t, {
        includeDebugOptions: isSuperuser,
        numberSeparators: separators,
      }).map((definition) => {
        if (definition.key === 'config_name') {
          return {
            ...definition,
            render: () => {
              const label =
                (hasExecutionConfigSnapshot &&
                  formatStrategyConfigRevisionLabel(
                    getStrategyConfigSnapshotName(historicalStrategyConfig),
                    getStrategyConfigSnapshotRevision(historicalStrategyConfig)
                  )) ||
                formatStrategyConfigRevisionLabel(
                  task.config_name,
                  task.config_revision
                );

              if (hasExecutionConfigSnapshot) {
                if (!historicalStrategyConfig) {
                  return label;
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
      onOpenConfiguration,
      separators,
      strategies,
      t,
      task.config_id,
      task.config_name,
      task.config_revision,
      task.strategy_type,
    ]
  );
  const recoveryBlockers = summary.execution.recoveryBlockers ?? [];
  const recoveryWarnings = summary.execution.recoveryWarnings ?? [];
  const tickDelivery = summary.execution.tickDelivery;
  const tickDeliveryAlert = buildTickDeliveryAlert(
    tickDelivery,
    t,
    formatDateTime
  );
  const executionStatusExtraItems: ExecutionStatusExtraItem[] = [
    ...(tickDelivery
      ? [
          {
            id: 'live_tick_delivery',
            label: t('trading:detail.tickDelivery'),
            value: formatTickDeliveryValue(tickDelivery, t, formatDateTime),
            color: tickDeliveryColor(tickDelivery.status),
          },
        ]
      : []),
    ...(summary.execution.resumeCursorTimestamp
      ? [
          {
            id: 'resume_cursor',
            label: t('trading:detail.resumeCursor'),
            value: formatDateTime(summary.execution.resumeCursorTimestamp),
          },
        ]
      : []),
    ...(summary.execution.reconciledAt
      ? [
          {
            id: 'broker_reconciled',
            label: t('trading:detail.brokerReconciled'),
            value: formatDateTime(summary.execution.reconciledAt),
          },
        ]
      : []),
  ];

  return (
    <Box sx={{ p: { xs: 1.5, sm: 3 } }}>
      <Grid container spacing={{ xs: 2, sm: 3 }}>
        <Grid size={{ xs: 12 }}>
          <TaskSettingsList
            title={t('common:labels.taskInformation')}
            task={task as unknown as Record<string, unknown>}
            snapshot={historicalTaskConfig}
            definitions={taskSettings}
          />
        </Grid>

        <Grid size={{ xs: 12 }}>
          {recoveryBlockers.length > 0 ? (
            <Alert severity="error" sx={{ mb: 2 }}>
              {recoveryBlockers[0]}
            </Alert>
          ) : null}
          {recoveryWarnings.length > 0 ? (
            <Alert severity="warning" sx={{ mb: 2 }}>
              {recoveryWarnings[0]}
            </Alert>
          ) : null}
          {tickDeliveryAlert ? (
            <Alert severity={tickDeliveryAlert.severity} sx={{ mb: 2 }}>
              {tickDeliveryAlert.message}
            </Alert>
          ) : null}
          <ExecutionStatusSummary
            taskNamespace="trading"
            summary={summary}
            latestMetrics={latestMetrics ?? null}
            pnlCurrency={pnlCurrency}
            displayedMarginRatio={displayedMarginRatio}
            snapshot={strategySnapshot ?? null}
            isSnapshotLoading={strategySnapshotLoading}
            snapshotError={strategySnapshotError}
            extraItems={executionStatusExtraItems}
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
            taskType={TaskType.TRADING}
            instrument={task.instrument}
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

type TickDelivery = NonNullable<TaskSummary['execution']['tickDelivery']>;

function formatTickDeliveryValue(
  delivery: TickDelivery,
  t: ReturnType<typeof useTranslation>['t'],
  formatDateTime: (value: string) => string
) {
  const status = tickDeliveryStatusLabel(delivery.status, t);
  const age = formatDeliveryAge(delivery.ageSeconds);
  const timestamp = delivery.tickTimestamp
    ? formatDateTime(delivery.tickTimestamp)
    : null;
  return [status, age, timestamp].filter(Boolean).join(' / ');
}

function buildTickDeliveryAlert(
  delivery: TickDelivery | null,
  t: ReturnType<typeof useTranslation>['t'],
  formatDateTime: (value: string) => string
) {
  if (!delivery || delivery.status !== 'stale') {
    return null;
  }
  const age = formatDeliveryAge(delivery.ageSeconds) ?? '-';
  const max = formatDeliveryAge(delivery.maxAgeSeconds) ?? '-';
  const timestamp = delivery.tickTimestamp
    ? formatDateTime(delivery.tickTimestamp)
    : '-';
  return {
    severity: 'error' as const,
    message: t('trading:detail.tickDeliveryStaleAlert', {
      age,
      max,
      timestamp,
    }),
  };
}

function tickDeliveryStatusLabel(
  status: string | null,
  t: ReturnType<typeof useTranslation>['t']
) {
  const normalized = status || 'unknown';
  return t(`trading:detail.tickDeliveryStatuses.${normalized}`, {
    defaultValue: normalized,
  });
}

function tickDeliveryColor(status: string | null) {
  if (status === 'stale') return 'error.main' as const;
  if (status === 'waiting') return 'warning.main' as const;
  if (status === 'ok') return 'success.main' as const;
  return undefined;
}

function formatDeliveryAge(seconds: number | null) {
  if (seconds == null || !Number.isFinite(seconds)) {
    return null;
  }
  if (seconds < 60) {
    return `${seconds < 10 ? seconds.toFixed(1) : seconds.toFixed(0)}s`;
  }
  const minutes = seconds / 60;
  if (minutes < 60) {
    return `${minutes < 10 ? minutes.toFixed(1) : minutes.toFixed(0)}m`;
  }
  const hours = minutes / 60;
  return `${hours < 10 ? hours.toFixed(1) : hours.toFixed(0)}h`;
}
