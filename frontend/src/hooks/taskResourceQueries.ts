import type { UseQueryOptions } from '@tanstack/react-query';
import { queryKeys } from '../config/reactQuery';
import { backtestTasksApi, tradingTasksApi } from '../services/api';
import {
  fetchTaskResourceObject,
  isApiErrorWithStatus,
} from '../services/api/taskResources';
import type {
  BacktestTask,
  BacktestTaskListParams,
  PaginatedResponse,
  TaskExecution,
  TradingTask,
  TradingTaskListParams,
} from '../types';
import { TaskType } from '../types/common';
import {
  applyPaginatedTaskStatusTransitions,
  applyTaskStatusTransition,
} from './taskStatusTransitions';
import type { StrategyCyclesResponse } from '../types/strategyVisualization';
import type { CurrencyConversionContext } from '../types/money';
import { handleAuthErrorStatus } from '../utils/authEvents';
import type { TaskSummary } from './useTaskSummary';

interface TaskSummaryResponse {
  timestamp?: string | null;
  pnl?: {
    realized?: string | number | null;
    unrealized?: string | number | null;
    currency?: string | null;
    realized_money?: {
      amount?: string | number | null;
      currency?: string | null;
    } | null;
    unrealized_money?: {
      amount?: string | number | null;
      currency?: string | null;
    } | null;
    total_money?: {
      amount?: string | number | null;
      currency?: string | null;
    } | null;
    realized_display_money?: {
      amount?: string | number | null;
      currency?: string | null;
    } | null;
    unrealized_display_money?: {
      amount?: string | number | null;
      currency?: string | null;
    } | null;
    total_display_money?: {
      amount?: string | number | null;
      currency?: string | null;
    } | null;
    display_conversion_context?: CurrencyConversionContext | null;
  };
  counts?: {
    total_trades?: number;
    open_positions?: number;
    closed_positions?: number;
    open_long_units?: number;
    open_short_units?: number;
    winning_trades?: number;
    losing_trades?: number;
  };
  execution?: {
    current_balance?: string | number | null;
    current_balance_money?: {
      amount?: string | number | null;
      currency?: string | null;
    } | null;
    ticks_processed?: number;
    account_currency?: string | null;
    current_balance_currency?: string | null;
    current_balance_display?: string | number | null;
    current_balance_display_money?: {
      amount?: string | number | null;
      currency?: string | null;
    } | null;
    current_balance_display_conversion_context?: CurrencyConversionContext | null;
    display_currency?: string | null;
    resume_cursor_timestamp?: string | null;
    margin_ratio?: string | number | null;
    current_atr?: string | number | null;
    recovery_status?: string | null;
    recovery_warnings?: string[];
    recovery_blockers?: string[];
    reconciled_at?: string | null;
    tick_delivery?: {
      status?: string | null;
      tick_timestamp?: string | null;
      observed_at?: string | null;
      age_seconds?: string | number | null;
      max_age_seconds?: string | number | null;
      message?: string | null;
    } | null;
  };
  tick?: {
    timestamp?: string | null;
    bid?: string | number | null;
    ask?: string | number | null;
    mid?: string | number | null;
  };
  task?: {
    status?: string;
    started_at?: string | null;
    completed_at?: string | null;
    error_message?: string | null;
    error_code?: string | null;
    status_reason_code?: string | null;
    status_reason_message?: string | null;
    stop_reason?: string | null;
    progress?: number;
  };
  watermarks?: {
    margin_ratio_max?: WatermarkResponse | null;
    base_units_max?: WatermarkResponse | null;
    open_long_units_max?: WatermarkResponse | null;
    open_short_units_max?: WatermarkResponse | null;
    realized_pnl_max?: WatermarkResponse | null;
    unrealized_pnl_min?: WatermarkResponse | null;
    open_positions_max?: WatermarkResponse | null;
    active_cycles_max?: WatermarkResponse | null;
  };
}

interface WatermarkResponse {
  value?: string | number | null;
  timestamp?: string | null;
  source_metric?: string | null;
}

type TaskListParams = BacktestTaskListParams | TradingTaskListParams;
type TaskEntity = BacktestTask | TradingTask;
const POLLING_STATUSES = new Set([
  'starting',
  'running',
  'paused',
  'idle',
  'draining',
  'stopping',
]);

function parseNumber(value: string | number | null | undefined): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function parseNullableNumber(
  value: string | number | null | undefined
): number | null {
  if (value == null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeMoney(
  value:
    | {
        amount?: string | number | null;
        currency?: string | null;
      }
    | null
    | undefined
): { amount: string; currency: string } | null {
  if (!value) return null;
  return {
    amount: String(value.amount ?? ''),
    currency: value.currency ?? '',
  };
}

function normalizeWatermark(value: WatermarkResponse | null | undefined): {
  value: number | null;
  timestamp: string | null;
  sourceMetric?: string | null;
} {
  return {
    value: parseNullableNumber(value?.value),
    timestamp: value?.timestamp ?? null,
    sourceMetric: value?.source_metric ?? null,
  };
}

export function shouldPollTaskStatus(status: string | undefined): boolean {
  return status != null && POLLING_STATUSES.has(status);
}

export function shouldEnableRealtimeTaskUpdates(
  status: string | undefined
): boolean {
  return shouldPollTaskStatus(status);
}

export function createTaskListQuery<TTask extends TaskEntity>(
  taskType: TaskType,
  params?: TaskListParams
): UseQueryOptions<PaginatedResponse<TTask>> {
  return {
    queryKey:
      taskType === TaskType.BACKTEST
        ? queryKeys.backtestTasks.list(params as Record<string, unknown>)
        : queryKeys.tradingTasks.list(params as Record<string, unknown>),
    queryFn: () =>
      taskType === TaskType.BACKTEST
        ? (backtestTasksApi.list(params as BacktestTaskListParams) as Promise<
            PaginatedResponse<TTask>
          >)
        : (tradingTasksApi.list(params as TradingTaskListParams) as Promise<
            PaginatedResponse<TTask>
          >),
    select: (data) => applyPaginatedTaskStatusTransitions(taskType, data),
    enabled: params !== undefined,
  };
}

export function createTaskDetailQuery<TTask extends TaskEntity>(
  taskType: TaskType,
  id: string | undefined,
  options?: {
    enabled?: boolean;
    enablePolling?: boolean;
    pollingInterval?: number;
  }
): UseQueryOptions<TTask> {
  return {
    queryKey:
      taskType === TaskType.BACKTEST
        ? id
          ? queryKeys.backtestTasks.detail(id)
          : ['backtest-task', 'empty']
        : id
          ? queryKeys.tradingTasks.detail(id)
          : ['trading-task', 'empty'],
    queryFn: () =>
      taskType === TaskType.BACKTEST
        ? (backtestTasksApi.get(id!) as Promise<TTask>)
        : (tradingTasksApi.get(id!) as Promise<TTask>),
    select: (data) => applyTaskStatusTransition(taskType, data),
    enabled: Boolean(id) && options?.enabled !== false,
  };
}

export function createTaskSummaryQuery(
  taskId: string,
  taskType: TaskType,
  executionRunId: string | undefined,
  fallback: TaskSummary
): UseQueryOptions<TaskSummary> {
  return {
    queryKey: queryKeys.taskResources.summary(taskType, taskId, executionRunId),
    enabled: Boolean(taskId),
    queryFn: async () => {
      if (!taskId) {
        return fallback;
      }

      try {
        const d = await fetchTaskResourceObject<TaskSummaryResponse>(
          taskType,
          taskId,
          'summary',
          executionRunId != null
            ? { execution_id: String(executionRunId) }
            : undefined
        );

        return {
          timestamp: d.timestamp ?? null,
          pnl: {
            realized: parseNumber(d.pnl?.realized),
            unrealized: parseNumber(d.pnl?.unrealized),
            currency: d.pnl?.currency ?? null,
            realizedMoney: normalizeMoney(d.pnl?.realized_money),
            unrealizedMoney: normalizeMoney(d.pnl?.unrealized_money),
            totalMoney: normalizeMoney(d.pnl?.total_money),
            realizedDisplayMoney: normalizeMoney(d.pnl?.realized_display_money),
            unrealizedDisplayMoney: normalizeMoney(
              d.pnl?.unrealized_display_money
            ),
            totalDisplayMoney: normalizeMoney(d.pnl?.total_display_money),
            displayConversionContext: d.pnl?.display_conversion_context ?? null,
          },
          counts: {
            totalTrades: d.counts?.total_trades ?? 0,
            openPositions: d.counts?.open_positions ?? 0,
            closedPositions: d.counts?.closed_positions ?? 0,
            openLongUnits: d.counts?.open_long_units ?? 0,
            openShortUnits: d.counts?.open_short_units ?? 0,
            winningTrades: d.counts?.winning_trades ?? 0,
            losingTrades: d.counts?.losing_trades ?? 0,
          },
          execution: {
            currentBalance: parseNullableNumber(d.execution?.current_balance),
            currentBalanceMoney: normalizeMoney(
              d.execution?.current_balance_money
            ),
            ticksProcessed: d.execution?.ticks_processed ?? 0,
            accountCurrency: d.execution?.account_currency ?? null,
            currentBalanceCurrency:
              d.execution?.current_balance_currency ?? null,
            currentBalanceDisplay: parseNullableNumber(
              d.execution?.current_balance_display
            ),
            currentBalanceDisplayMoney: normalizeMoney(
              d.execution?.current_balance_display_money
            ),
            currentBalanceDisplayConversionContext:
              d.execution?.current_balance_display_conversion_context ?? null,
            displayCurrency: d.execution?.display_currency ?? null,
            resumeCursorTimestamp: d.execution?.resume_cursor_timestamp ?? null,
            marginRatio: parseNullableNumber(d.execution?.margin_ratio),
            currentAtr: parseNullableNumber(d.execution?.current_atr),
            recoveryStatus: d.execution?.recovery_status ?? null,
            recoveryWarnings: Array.isArray(d.execution?.recovery_warnings)
              ? d.execution.recovery_warnings
              : [],
            recoveryBlockers: Array.isArray(d.execution?.recovery_blockers)
              ? d.execution.recovery_blockers
              : [],
            reconciledAt: d.execution?.reconciled_at ?? null,
            tickDelivery: d.execution?.tick_delivery
              ? {
                  status: d.execution.tick_delivery.status ?? null,
                  tickTimestamp:
                    d.execution.tick_delivery.tick_timestamp ?? null,
                  observedAt: d.execution.tick_delivery.observed_at ?? null,
                  ageSeconds: parseNullableNumber(
                    d.execution.tick_delivery.age_seconds
                  ),
                  maxAgeSeconds: parseNullableNumber(
                    d.execution.tick_delivery.max_age_seconds
                  ),
                  message: d.execution.tick_delivery.message ?? null,
                }
              : null,
          },
          tick: {
            timestamp: d.tick?.timestamp ?? null,
            bid: parseNullableNumber(d.tick?.bid),
            ask: parseNullableNumber(d.tick?.ask),
            mid: parseNullableNumber(d.tick?.mid),
          },
          task: {
            status: d.task?.status ?? '',
            startedAt: d.task?.started_at ?? null,
            completedAt: d.task?.completed_at ?? null,
            errorMessage: d.task?.error_message ?? null,
            errorCode: d.task?.error_code ?? null,
            statusReasonCode: d.task?.status_reason_code ?? null,
            statusReasonMessage: d.task?.status_reason_message ?? null,
            stopReason: d.task?.stop_reason ?? null,
            progress: d.task?.progress ?? 0,
          },
          watermarks: {
            marginRatioMax: normalizeWatermark(d.watermarks?.margin_ratio_max),
            baseUnitsMax: normalizeWatermark(d.watermarks?.base_units_max),
            openLongUnitsMax: normalizeWatermark(
              d.watermarks?.open_long_units_max
            ),
            openShortUnitsMax: normalizeWatermark(
              d.watermarks?.open_short_units_max
            ),
            realizedPnlMax: normalizeWatermark(d.watermarks?.realized_pnl_max),
            unrealizedPnlMin: normalizeWatermark(
              d.watermarks?.unrealized_pnl_min
            ),
            openPositionsMax: normalizeWatermark(
              d.watermarks?.open_positions_max
            ),
            activeCyclesMax: normalizeWatermark(
              d.watermarks?.active_cycles_max
            ),
          },
        } satisfies TaskSummary;
      } catch (err) {
        if (isApiErrorWithStatus(err)) {
          handleAuthErrorStatus(err.status, {
            source: 'http',
            status: err.status,
            context: 'task_summary',
          });
        }
        throw new Error(
          err instanceof Error ? err.message : 'Failed to load task summary'
        );
      }
    },
  };
}

export function createTaskExecutionsQuery(
  taskId: string,
  taskType: TaskType,
  params?: { page?: number; page_size?: number; include_metrics?: boolean }
): UseQueryOptions<PaginatedResponse<TaskExecution>> {
  return {
    queryKey:
      taskType === TaskType.BACKTEST
        ? queryKeys.backtestTasks.executions(taskId, params)
        : queryKeys.tradingTasks.executions(taskId, params),
    queryFn: async () => {
      const fetchParams =
        params?.page || params?.page_size
          ? {
              page: params.page,
              page_size: params.page_size,
              include_metrics: params.include_metrics,
            }
          : undefined;
      return taskType === TaskType.BACKTEST
        ? backtestTasksApi.getExecutions(taskId, fetchParams)
        : tradingTasksApi.getExecutions(taskId, fetchParams);
    },
    staleTime: 2000,
    refetchOnWindowFocus: true,
  };
}

export function createTaskExecutionQuery(
  taskId: string,
  executionId: string,
  taskType: TaskType
): UseQueryOptions<TaskExecution> {
  const hasExecutionId = Boolean(String(executionId || '').trim());
  return {
    queryKey:
      taskType === TaskType.BACKTEST
        ? queryKeys.backtestTasks.execution(taskId, executionId)
        : queryKeys.tradingTasks.execution(taskId, executionId),
    queryFn: () =>
      taskType === TaskType.BACKTEST
        ? backtestTasksApi.getExecution(taskId, executionId)
        : tradingTasksApi.getExecution(taskId, executionId),
    enabled: Boolean(taskId) && hasExecutionId,
    staleTime: 10000,
  };
}

export function createTaskStrategyEventsQuery(
  taskId: string | number,
  taskType: TaskType,
  executionRunId?: string,
  cycleId?: string,
  options?: {
    enabled?: boolean;
    params?: Record<string, string | number | undefined>;
  }
): UseQueryOptions<StrategyCyclesResponse | null> {
  return {
    queryKey: queryKeys.taskResources.strategyEvents(
      taskType,
      String(taskId),
      executionRunId,
      cycleId,
      options?.params
    ),
    enabled: Boolean(taskId) && options?.enabled !== false,
    staleTime: 0,
    refetchOnMount: 'always',
    queryFn: async () => {
      if (!taskId) {
        return null;
      }
      try {
        return await fetchTaskResourceObject<StrategyCyclesResponse>(
          taskType,
          taskId,
          'strategy-events',
          {
            ...(executionRunId ? { execution_id: executionRunId } : {}),
            ...(cycleId ? { cycle_id: cycleId } : {}),
            ...(options?.params ?? {}),
          }
        );
      } catch (err) {
        if (isApiErrorWithStatus(err)) {
          handleAuthErrorStatus(err.status, {
            source: 'http',
            status: err.status,
            context: 'task_strategy_events',
          });
        }
        throw new Error(
          err instanceof Error ? err.message : 'Failed to load strategy cycles'
        );
      }
    },
  };
}
