/**
 * BacktestTaskDetail Component
 *
 * Main detail view for backtest tasks using task-based API endpoints.
 * Displays task info and tab navigation for Events, Logs, Trades, and Trend.
 *
 */

import React, {
  Suspense,
  useState,
  useEffect,
  useMemo,
  useCallback,
} from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Box,
  Button,
  Container,
  Paper,
  Typography,
  Breadcrumbs,
  Link,
  CircularProgress,
  Alert,
  Tooltip,
  IconButton,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { AccountBalanceWallet as AccountBalanceWalletIcon } from '@mui/icons-material';
import { useBacktestTask } from '../../hooks/useBacktestTasks';
import {
  shouldEnableRealtimeTaskUpdates,
  shouldPollTaskStatus,
} from '../../hooks/taskResourceQueries';
import {
  useStrategies,
  getStrategyDisplayName,
} from '../../hooks/useStrategies';
import { useAuth } from '../../contexts/AuthContext';
import { TaskLogsTable } from '../tasks/detail/TaskLogsTable';
import { TaskPositionsTable } from '../tasks/detail/TaskPositionsTable';
import { TaskTradesTable } from '../tasks/detail/TaskTradesTable';
import { TaskOrdersTable } from '../tasks/detail/TaskOrdersTable';
import { useTaskSummary } from '../../hooks/useTaskSummary';
import { TaskStatus, TaskType } from '../../types/common';
import type { BacktestTask } from '../../types';
import { DeleteTaskDialog } from '../tasks/actions/DeleteTaskDialog';
import {
  StopOptionsDialog,
  type StopOption,
} from '../tasks/actions/StopOptionsDialog';
import { TaskActionConfirmDialog } from '../tasks/actions/TaskActionConfirmDialog';
import { useTaskActionDialog } from '../../hooks/useTaskActionDialog';
import {
  useAdjustBacktestBalance,
  useDeleteBacktestTask,
  usePauseBacktestTask,
  useResumeBacktestTask,
  useRerunBacktestTask,
  useStartBacktestTask,
  useStopBacktestTask,
} from '../../hooks/useBacktestTaskMutations';
import { LazyTabPanel } from '../common/LazyTabPanel';
import { TabConfigDialog } from '../common/TabConfigDialog';
import { useTabConfig, type TabItem } from '../../hooks/useTabConfig';
import { useOptimisticTaskStatus } from '../../hooks/useOptimisticTaskStatus';
import { TaskDetailHeader } from '../tasks/detail/TaskDetailHeader';
import { TaskDetailTabs } from '../tasks/detail/TaskDetailTabs';
import { TaskStrategyTab } from '../tasks/detail/strategy/TaskStrategyTab';
import { SnowballNetStrategyTab } from '../tasks/detail/strategy/SnowballNetStrategyTab';
import { taskDetailLayout } from '../tasks/detail/detailLayout';
import { visibleTabsForStrategy } from '../tasks/detail/taskDetailTabsConfig';
import { BacktestOverviewTab } from './detail/BacktestOverviewTab';
import { useTaskMetrics } from '../../hooks/useTaskMetrics';
import {
  useStrategySnapshot,
  useLossCutEvents,
  usePeriodicTradeMetrics,
} from '../../hooks/useStrategyData';
import { computeAutoInterval } from '../../utils/autoGranularity';
import { metricKeysForStrategy } from '../../utils/taskMetricKeys';
import { useToast } from '../common';
import { formatTaskActionError } from '../../utils/taskActionError';
import { quoteCurrencyFromInstrument } from '../../utils/instrumentCurrency';
import { useTaskExecution } from '../../hooks/useTaskExecutions';
import { BacktestBalanceAdjustmentDialog } from './BacktestBalanceAdjustmentDialog';
import { formatMoneyPayload } from '../../utils/numberFormat';

const TaskMetricsTab = React.lazy(() =>
  import('../tasks/detail/TaskMetricsTab').then((module) => ({
    default: module.TaskMetricsTab,
  }))
);

export const BacktestTaskDetail: React.FC = () => {
  const { t } = useTranslation(['backtest', 'common']);
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const taskId = id || '';
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [stopDialogOpen, setStopDialogOpen] = useState(false);
  const [balanceDialogOpen, setBalanceDialogOpen] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [isRefreshingExecutionStatus, setIsRefreshingExecutionStatus] =
    useState(false);
  const [tabConfigOpen, setTabConfigOpen] = useState(false);
  const { pendingAction, requestConfirm, cancelAction } = useTaskActionDialog();
  const deleteTask = useDeleteBacktestTask();
  const startTask = useStartBacktestTask();
  const restartTask = useRerunBacktestTask();
  const resumeTask = useResumeBacktestTask();
  const pauseTask = usePauseBacktestTask();
  const stopTask = useStopBacktestTask();
  const adjustBalance = useAdjustBacktestBalance();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('sm'));
  const { showError, showSuccess } = useToast();
  const { user } = useAuth();
  const timezone = user?.timezone || 'UTC';
  const language = user?.language;

  // Tab configuration with localStorage persistence
  const defaultTabs: TabItem[] = [
    { id: 'overview', label: t('backtest:tabs.overview'), visible: true },
    { id: 'strategy', label: t('backtest:tabs.strategy'), visible: true },
    { id: 'positions', label: t('backtest:tabs.positions'), visible: true },
    { id: 'trades', label: t('backtest:tabs.trades'), visible: true },
    { id: 'orders', label: t('backtest:tabs.orders'), visible: true },
    { id: 'logs', label: t('backtest:tabs.logs'), visible: true },
    { id: 'metrics', label: t('backtest:tabs.metrics'), visible: true },
  ];
  const {
    tabs: allTabs,
    visibleTabs,
    updateTabs,
    resetToDefaults,
  } = useTabConfig('backtest_detail', defaultTabs);

  // Get tab from URL, default to 'overview'
  const tabParam = searchParams.get('tab') || 'overview';

  const {
    optimisticStatus,
    statusPollingIntervalMs,
    applyOptimisticStatus,
    clearOptimisticStatus,
  } = useOptimisticTaskStatus();
  const {
    data: task,
    isLoading,
    error,
    refresh: refreshTask,
  } = useBacktestTask(taskId || undefined, {
    enablePolling: true,
    pollingInterval: statusPollingIntervalMs,
  });
  const { strategies } = useStrategies();
  const actualStatus = task?.status;
  const currentStatus = optimisticStatus?.status ?? actualStatus;
  const isInMemoryMode = task?.in_memory_mode === true;
  const effectiveVisibleTabs = useMemo(() => {
    const strategyTabs = visibleTabsForStrategy(
      visibleTabs,
      task?.strategy_type
    );
    if (!isInMemoryMode) {
      return strategyTabs;
    }
    return strategyTabs.filter((tab) =>
      ['overview', 'metrics'].includes(tab.id)
    );
  }, [isInMemoryMode, task?.strategy_type, visibleTabs]);
  const visibleTabIds = effectiveVisibleTabs.map((tab) => tab.id);
  const activeTabId = visibleTabIds.includes(tabParam) ? tabParam : 'overview';

  useEffect(() => {
    if (!optimisticStatus || !actualStatus) {
      return;
    }

    if (optimisticStatus.settleOn.includes(actualStatus)) {
      clearOptimisticStatus();
    }
  }, [actualStatus, clearOptimisticStatus, optimisticStatus]);

  const selectedExecutionId = searchParams.get('execution');
  const effectiveExecutionId = selectedExecutionId || task?.execution_id;
  const isViewingHistorical =
    selectedExecutionId != null &&
    task?.execution_id != null &&
    selectedExecutionId !== task.execution_id;

  // Fetch execution detail (includes config snapshot) for historical runs
  const { data: executionDetail } = useTaskExecution(
    taskId,
    effectiveExecutionId ?? '',
    TaskType.BACKTEST
  );
  const historicalStrategyConfig = executionDetail?.strategy_config ?? null;

  const overviewSummary = useTaskSummary(
    taskId,
    TaskType.BACKTEST,
    effectiveExecutionId,
    {
      polling: !isViewingHistorical && shouldPollTaskStatus(currentStatus),
      interval: statusPollingIntervalMs,
    }
  );

  const { summary: s, refresh: refreshOverviewSummary } = overviewSummary;
  const overviewStrategySnapshot = useStrategySnapshot({
    taskId,
    taskType: TaskType.BACKTEST,
    executionRunId: effectiveExecutionId,
    enabled: Boolean(taskId) && activeTabId === 'overview',
    refetchInterval:
      !isViewingHistorical &&
      activeTabId === 'overview' &&
      shouldPollTaskStatus(currentStatus)
        ? statusPollingIntervalMs
        : false,
  });

  const [metricsInterval, setMetricsInterval] = useState(0);
  const [metricsSince, setMetricsSince] = useState('');
  const [metricsUntil, setMetricsUntil] = useState('');
  const metricsSinceIso = metricsSince
    ? new Date(metricsSince).toISOString()
    : undefined;
  const metricsUntilIso = metricsUntil
    ? new Date(metricsUntil).toISOString()
    : undefined;
  const metricKeys = useMemo(
    () => metricKeysForStrategy(task?.strategy_type),
    [task?.strategy_type]
  );

  const effectiveMetricsInterval = useMemo(() => {
    if (metricsInterval !== 0) return metricsInterval;
    // Auto: compute from task time range or since/until
    const start = metricsSince
      ? new Date(metricsSince).getTime() / 1000
      : task?.start_time
        ? new Date(task.start_time).getTime() / 1000
        : 0;
    const end = metricsUntil
      ? new Date(metricsUntil).getTime() / 1000
      : task?.end_time
        ? new Date(task.end_time).getTime() / 1000
        : 0;
    if (start && end && end > start) {
      return computeAutoInterval(end - start);
    }
    return 1;
  }, [metricsInterval, metricsSince, metricsUntil, task]);

  const metricsResult = useTaskMetrics({
    taskId,
    taskType: TaskType.BACKTEST,
    executionRunId: effectiveExecutionId,
    interval: effectiveMetricsInterval,
    since: metricsSinceIso,
    until: metricsUntilIso,
    enabled: !!taskId,
    fetchSeries: activeTabId === 'metrics',
    metricKeys,
    pollingInterval:
      !isViewingHistorical && shouldPollTaskStatus(currentStatus) ? 30000 : 0,
  });

  const [showLossCutMarkers, setShowLossCutMarkers] = useState(false);
  const periodicMetricsQuery = usePeriodicTradeMetrics({
    taskId,
    taskType: TaskType.BACKTEST,
    executionRunId: effectiveExecutionId,
    params: {
      since: metricsSinceIso,
      until: metricsUntilIso,
      timezone,
    },
    enabled: !!taskId && activeTabId === 'metrics' && !isInMemoryMode,
    refetchInterval:
      !isViewingHistorical &&
      activeTabId === 'metrics' &&
      !isInMemoryMode &&
      shouldPollTaskStatus(currentStatus)
        ? 30000
        : false,
  });
  const lossCutEventsQuery = useLossCutEvents({
    taskId,
    taskType: TaskType.BACKTEST,
    executionRunId: effectiveExecutionId,
    enabled: !!taskId && showLossCutMarkers && !isInMemoryMode,
  });

  const handleRefreshExecutionStatus = useCallback(async () => {
    setIsRefreshingExecutionStatus(true);
    try {
      const refreshes: Array<Promise<unknown>> = [
        refreshOverviewSummary(),
        metricsResult.refresh(),
        overviewStrategySnapshot.refetch(),
      ];
      if (!isInMemoryMode) {
        refreshes.push(periodicMetricsQuery.refetch());
      }
      await Promise.all(refreshes);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : t('common:errors.refreshFailed')
      );
    } finally {
      setIsRefreshingExecutionStatus(false);
    }
  }, [
    isInMemoryMode,
    metricsResult,
    overviewStrategySnapshot,
    periodicMetricsQuery,
    refreshOverviewSummary,
    showError,
    t,
  ]);

  const polledTick = s.tick.timestamp
    ? {
        timestamp: s.tick.timestamp,
        price: s.tick.mid != null ? String(s.tick.mid) : null,
      }
    : null;

  // Derive tab value from URL parameter (use this for rendering)
  const activeTabIndex = Math.max(0, visibleTabIds.indexOf(activeTabId));

  const handleTabChange = (_event: React.SyntheticEvent, newValue: number) => {
    const tabName = visibleTabIds[newValue] || 'overview';
    const next: Record<string, string> = { tab: tabName };
    const exec = searchParams.get('execution');
    if (exec) next.execution = exec;
    setSearchParams(next);
  };

  const handleBack = () => {
    navigate('/backtest-tasks');
  };

  const handleStopConfirm = async ({
    option,
    drainDurationMinutes,
  }: {
    option: StopOption;
    drainDurationMinutes?: number;
  }) => {
    setIsStopping(true);
    try {
      await stopTask.mutate({
        id: taskId,
        mode: option,
        ...(drainDurationMinutes !== undefined ? { drainDurationMinutes } : {}),
      });
      // Optimistic status depends on the chosen mode. DRAIN keeps the
      // executor running in DRAINING; other modes transition to STOPPING
      // and then STOPPED / COMPLETED.
      if (option === 'drain') {
        applyOptimisticStatus(TaskStatus.DRAINING, [
          TaskStatus.DRAINING,
          TaskStatus.STOPPING,
          TaskStatus.STOPPED,
          TaskStatus.COMPLETED,
          TaskStatus.FAILED,
        ]);
      } else {
        applyOptimisticStatus(TaskStatus.STOPPING, [
          TaskStatus.STOPPING,
          TaskStatus.STOPPED,
          TaskStatus.COMPLETED,
          TaskStatus.FAILED,
        ]);
      }
      await refreshTask();
      setStopDialogOpen(false);
    } catch (error) {
      showError(formatTaskActionError(error, 'Failed to stop task'));
      setStopDialogOpen(false);
    } finally {
      setIsStopping(false);
    }
  };

  const handleBalanceConfirm = async (data: {
    current_balance: string;
    reason?: string;
  }) => {
    try {
      const result = await adjustBalance.mutate({ id: taskId, data });
      setBalanceDialogOpen(false);
      showSuccess(
        t('backtest:toast.balanceAdjustedSuccessfullyWithBalance', {
          balance: formatMoneyPayload(
            result.current_balance_display_money ?? result.current_balance_money
          ),
          defaultValue: `Backtest balance updated to ${formatMoneyPayload(
            result.current_balance_display_money ?? result.current_balance_money
          )}`,
        })
      );
      await Promise.all([
        refreshTask(),
        refreshOverviewSummary(),
        metricsResult.refresh(),
        overviewStrategySnapshot.refetch(),
      ]);
    } catch (error) {
      showError(
        formatTaskActionError(
          error,
          t('backtest:detail.balanceAdjustmentFailed')
        )
      );
    }
  };

  if (isLoading) {
    return (
      <Container maxWidth={false} sx={{ py: 4 }}>
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            minHeight: '400px',
          }}
        >
          <CircularProgress />
        </Box>
      </Container>
    );
  }

  if (error || !task) {
    return (
      <Container maxWidth={false} sx={{ py: 4 }}>
        <Alert severity="error">
          {error?.message || t('common:errors.taskNotFound')}
        </Alert>
      </Container>
    );
  }

  const detailTask = task as BacktestTask;
  const activeExecutionId = effectiveExecutionId;
  const enableRealtime =
    !isViewingHistorical && shouldEnableRealtimeTaskUpdates(currentStatus);
  const pnlCurrency =
    s.pnl.currency ||
    quoteCurrencyFromInstrument(detailTask.instrument) ||
    detailTask.display_currency ||
    s.execution.accountCurrency ||
    detailTask.account_currency ||
    'N/A';
  const canAdjustBalance =
    (currentStatus === TaskStatus.PAUSED ||
      currentStatus === TaskStatus.STOPPED) &&
    s.execution.currentBalance != null;
  const balanceAdjustmentTooltip = canAdjustBalance
    ? t('backtest:detail.adjustBalance')
    : t('backtest:detail.pauseOrStopBeforeBalanceAdjustment');

  return (
    <Container maxWidth={false} sx={taskDetailLayout.container}>
      {/* Breadcrumbs */}
      <Breadcrumbs sx={{ mb: { xs: 1, sm: 2 } }}>
        <Link
          component="button"
          variant="body1"
          onClick={handleBack}
          sx={{ cursor: 'pointer', textDecoration: 'none' }}
        >
          {t('backtest:pages.title')}
        </Link>
        <Typography
          color="text.primary"
          noWrap
          sx={{ maxWidth: { xs: 160, sm: 'none' } }}
        >
          {task.name}
        </Typography>
      </Breadcrumbs>

      {isViewingHistorical && (
        <Alert
          severity="info"
          sx={{ mb: 2 }}
          action={
            <Button
              color="inherit"
              size="small"
              onClick={() => {
                const tab = searchParams.get('tab') || 'overview';
                setSearchParams({ tab });
              }}
            >
              {t('common:actions.backToCurrent')}
            </Button>
          }
        >
          {t('backtest:detail.viewingHistoricalExecution')}
        </Alert>
      )}

      <TaskDetailHeader
        taskId={taskId}
        taskName={detailTask.name}
        taskDescription={detailTask.description}
        taskStatus={detailTask.status}
        currentStatus={
          isViewingHistorical
            ? (executionDetail?.status as TaskStatus)
            : currentStatus
        }
        actionPolicy={detailTask.action_policy}
        taskType="backtest"
        strategyName={getStrategyDisplayName(
          strategies,
          detailTask.strategy_type
        )}
        instrument={detailTask.instrument}
        pipSize={detailTask.pip_size}
        tick={
          isViewingHistorical
            ? { timestamp: null, bid: null, ask: null, mid: null }
            : s.tick
        }
        timezone={timezone}
        progress={
          isViewingHistorical
            ? (executionDetail?.progress ?? 0)
            : s.task.progress
        }
        currentAtr={isViewingHistorical ? null : s.execution.currentAtr}
        completedLabel={t('backtest:detail.completed')}
        editLabel={t('common:actions.edit')}
        deleteLabel={t('common:actions.delete')}
        isViewingHistorical={isViewingHistorical}
        onStart={async (id) => {
          requestConfirm('start', id);
        }}
        onStop={async () => {
          setStopDialogOpen(true);
        }}
        onRestart={async (id) => {
          requestConfirm('restart', id);
        }}
        onResume={async (id) => {
          requestConfirm('resume', id);
        }}
        onPause={async (id) => {
          requestConfirm('pause', id);
        }}
        onEdit={() => navigate(`/backtest-tasks/${taskId}/edit`)}
        onDelete={() => setDeleteDialogOpen(true)}
        extraActions={
          <Tooltip title={balanceAdjustmentTooltip}>
            <span>
              <IconButton
                size={isMobile ? 'small' : 'medium'}
                color="primary"
                disabled={!canAdjustBalance}
                onClick={() => setBalanceDialogOpen(true)}
                aria-label={t('backtest:detail.adjustBalance')}
              >
                <AccountBalanceWalletIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
        }
      />

      {/* Tabs */}
      <Paper sx={taskDetailLayout.tabPaper}>
        <TaskDetailTabs
          activeTabIndex={activeTabIndex}
          visibleTabs={effectiveVisibleTabs}
          onTabChange={handleTabChange}
          onConfigureTabs={() => setTabConfigOpen(true)}
          configureTabsLabel={t('common:tabConfig.configureTabs')}
        />

        {/* Overview Tab — always rendered when visible */}
        {visibleTabIds.includes('overview') && (
          <LazyTabPanel
            value={activeTabIndex}
            index={visibleTabIds.indexOf('overview')}
          >
            <BacktestOverviewTab
              taskId={taskId}
              task={detailTask}
              summary={s}
              currentStatus={
                isViewingHistorical
                  ? (executionDetail?.status as TaskStatus)
                  : currentStatus
              }
              strategies={strategies}
              pnlCurrency={pnlCurrency}
              latestMetrics={metricsResult.latest}
              strategySnapshot={overviewStrategySnapshot.data ?? null}
              strategySnapshotLoading={overviewStrategySnapshot.isLoading}
              strategySnapshotError={overviewStrategySnapshot.error}
              onRefreshExecutionStatus={handleRefreshExecutionStatus}
              executionStatusRefreshing={isRefreshingExecutionStatus}
              timezone={timezone}
              language={language}
              isViewingHistorical={isViewingHistorical}
              historicalStrategyConfig={historicalStrategyConfig}
              historicalTaskConfig={executionDetail?.task_config ?? null}
              executionId={effectiveExecutionId}
              onOpenConfiguration={() =>
                navigate(`/configurations/${detailTask.config_id}`)
              }
            />
          </LazyTabPanel>
        )}

        {visibleTabIds.includes('strategy') && (
          <LazyTabPanel
            value={activeTabIndex}
            index={visibleTabIds.indexOf('strategy')}
          >
            {detailTask.strategy_type === 'snowball_net' ? (
              <SnowballNetStrategyTab
                taskId={taskId}
                taskType={TaskType.BACKTEST}
                instrument={detailTask.instrument}
                taskStartTime={detailTask.start_time}
                taskEndTime={detailTask.end_time}
                executionRunId={activeExecutionId}
                enableRealTimeUpdates={enableRealtime}
                timezone={timezone}
                lossCutEvents={lossCutEventsQuery.data?.results}
                showLossCutMarkers={showLossCutMarkers}
              />
            ) : (
              <TaskStrategyTab
                taskId={taskId}
                taskType={TaskType.BACKTEST}
                strategyType={detailTask.strategy_type}
                instrument={detailTask.instrument}
                executionRunId={activeExecutionId}
                enableRealTimeUpdates={enableRealtime}
                timezone={timezone}
              />
            )}
          </LazyTabPanel>
        )}

        {/* Positions Tab */}
        {visibleTabIds.includes('positions') && (
          <LazyTabPanel
            value={activeTabIndex}
            index={visibleTabIds.indexOf('positions')}
          >
            <TaskPositionsTable
              taskId={taskId}
              taskType={TaskType.BACKTEST}
              executionRunId={activeExecutionId}
              enableRealTimeUpdates={enableRealtime}
              currentPrice={
                polledTick?.price != null ? parseFloat(polledTick.price) : null
              }
              strategyType={detailTask.strategy_type}
              pipSize={
                detailTask.pip_size ? parseFloat(detailTask.pip_size) : null
              }
            />
          </LazyTabPanel>
        )}

        {/* Trades Tab */}
        {visibleTabIds.includes('trades') && (
          <LazyTabPanel
            value={activeTabIndex}
            index={visibleTabIds.indexOf('trades')}
          >
            <TaskTradesTable
              taskId={taskId}
              taskType={TaskType.BACKTEST}
              executionRunId={activeExecutionId}
              enableRealTimeUpdates={enableRealtime}
              strategyType={detailTask.strategy_type}
              pipSize={
                detailTask.pip_size ? parseFloat(detailTask.pip_size) : null
              }
            />
          </LazyTabPanel>
        )}

        {/* Orders Tab */}
        {visibleTabIds.includes('orders') && (
          <LazyTabPanel
            value={activeTabIndex}
            index={visibleTabIds.indexOf('orders')}
          >
            <TaskOrdersTable
              taskId={taskId}
              taskType={TaskType.BACKTEST}
              executionRunId={activeExecutionId}
              enableRealTimeUpdates={enableRealtime}
            />
          </LazyTabPanel>
        )}

        {/* Logs Tab */}
        {visibleTabIds.includes('logs') && (
          <LazyTabPanel
            value={activeTabIndex}
            index={visibleTabIds.indexOf('logs')}
          >
            <TaskLogsTable
              taskId={taskId}
              taskType={TaskType.BACKTEST}
              executionRunId={activeExecutionId}
              enableRealTimeUpdates={enableRealtime}
              strategyType={detailTask.strategy_type}
            />
          </LazyTabPanel>
        )}

        {/* Metrics Tab */}
        {visibleTabIds.includes('metrics') && (
          <LazyTabPanel
            value={activeTabIndex}
            index={visibleTabIds.indexOf('metrics')}
          >
            <Suspense
              fallback={
                <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
                  <CircularProgress size={24} />
                </Box>
              }
            >
              <TaskMetricsTab
                data={metricsResult.data}
                isLoading={metricsResult.isLoading}
                error={metricsResult.error}
                currency={
                  s.execution.displayCurrency ||
                  s.execution.accountCurrency ||
                  detailTask.display_currency ||
                  detailTask.account_currency ||
                  'USD'
                }
                dataSource={metricsResult.dataSource}
                periodicMetrics={periodicMetricsQuery.data}
                resumeCursorTimestamp={metricsResult.resumeCursorTimestamp}
                consistencyWarnings={metricsResult.consistencyWarnings}
                interval={metricsInterval}
                since={metricsSince}
                until={metricsUntil}
                onIntervalChange={setMetricsInterval}
                onSinceChange={setMetricsSince}
                onUntilChange={setMetricsUntil}
                onRefresh={async () => {
                  const refreshes: Array<Promise<unknown>> = [
                    metricsResult.refresh(),
                  ];
                  if (!isInMemoryMode) {
                    refreshes.push(periodicMetricsQuery.refetch());
                  }
                  await Promise.all(refreshes);
                }}
                instrument={detailTask.instrument}
                startTime={task?.start_time}
                endTime={task?.end_time}
                currentTickTimestamp={polledTick?.timestamp}
                currentTickPrice={
                  polledTick?.price != null
                    ? parseFloat(polledTick.price)
                    : null
                }
                timezone={timezone}
                strategyType={detailTask.strategy_type}
                lossCutEvents={lossCutEventsQuery.data?.results}
                showLossCutMarkers={showLossCutMarkers}
                onToggleLossCutMarkers={setShowLossCutMarkers}
              />
            </Suspense>
          </LazyTabPanel>
        )}
      </Paper>

      <TabConfigDialog
        open={tabConfigOpen}
        tabs={allTabs}
        onClose={() => setTabConfigOpen(false)}
        onSave={updateTabs}
        onReset={resetToDefaults}
      />

      <DeleteTaskDialog
        open={deleteDialogOpen}
        taskName={task.name}
        taskStatus={task.status}
        onCancel={() => setDeleteDialogOpen(false)}
        onConfirm={async () => {
          try {
            await deleteTask.mutate(taskId);
            setDeleteDialogOpen(false);
            navigate('/backtest-tasks', { state: { deleted: true } });
          } catch {
            // Error handled by mutation hook
          }
        }}
        isLoading={deleteTask.isLoading}
        hasExecutionHistory={true}
      />
      <StopOptionsDialog
        open={stopDialogOpen}
        taskName={task.name}
        taskType="backtest"
        drainAvailable={!detailTask.in_memory_mode}
        isLoading={isStopping}
        onCancel={() => setStopDialogOpen(false)}
        onConfirm={handleStopConfirm}
      />
      {balanceDialogOpen ? (
        <BacktestBalanceAdjustmentDialog
          open={balanceDialogOpen}
          currentBalance={s.execution.currentBalance}
          accountCurrency={
            s.execution.currentBalanceMoney?.currency ||
            s.execution.currentBalanceCurrency ||
            s.execution.accountCurrency ||
            pnlCurrency ||
            'USD'
          }
          currentBalanceMoney={s.execution.currentBalanceMoney}
          currentBalanceDisplayMoney={s.execution.currentBalanceDisplayMoney}
          currentBalanceDisplayConversionContext={
            s.execution.currentBalanceDisplayConversionContext
          }
          isLoading={adjustBalance.isLoading}
          onCancel={() => setBalanceDialogOpen(false)}
          onConfirm={handleBalanceConfirm}
        />
      ) : null}
      {pendingAction && (
        <TaskActionConfirmDialog
          open={true}
          action={pendingAction.type}
          taskName={task.name}
          onCancel={cancelAction}
          isLoading={
            startTask.isLoading ||
            pauseTask.isLoading ||
            resumeTask.isLoading ||
            restartTask.isLoading
          }
          onConfirm={async () => {
            const { type, taskId: actionTaskId } = pendingAction;
            cancelAction();
            try {
              if (type === 'start') {
                applyOptimisticStatus(TaskStatus.STARTING, [
                  TaskStatus.RUNNING,
                  TaskStatus.IDLE,
                  TaskStatus.DRAINING,
                ]);
                await startTask.mutate(actionTaskId);
              } else if (type === 'pause') {
                applyOptimisticStatus(TaskStatus.PAUSED, [
                  TaskStatus.PAUSED,
                  TaskStatus.RUNNING,
                  TaskStatus.FAILED,
                ]);
                await pauseTask.mutate(actionTaskId);
              } else if (type === 'resume') {
                applyOptimisticStatus(TaskStatus.STARTING, [
                  TaskStatus.RUNNING,
                  TaskStatus.IDLE,
                  TaskStatus.DRAINING,
                ]);
                await resumeTask.mutate(actionTaskId);
              } else if (type === 'restart') {
                applyOptimisticStatus(TaskStatus.STARTING, [
                  TaskStatus.RUNNING,
                  TaskStatus.IDLE,
                  TaskStatus.DRAINING,
                ]);
                await restartTask.mutate(actionTaskId);
              }
              await refreshTask();
              clearOptimisticStatus();
            } catch (error) {
              clearOptimisticStatus();
              showError(formatTaskActionError(error, 'Failed to update task'));
            }
          }}
        />
      )}
    </Container>
  );
};

export default BacktestTaskDetail;
