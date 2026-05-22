import { api } from '../../api/apiClient';
import type {
  PaginatedResponse,
  TradingTask,
  TradingTaskListParams,
} from '../../types';
import type { BacktestInitialPositionCycle } from '../../types/backtestTask';
import type {
  BackendTaskExecutionSummary,
  BackendTaskStopResponse,
  BackendTradingTask,
} from './contracts';
import { createTaskApi } from './taskApiFactory';

interface TradingTaskCreateRequest {
  config_id: string;
  account_id: string;
  name: string;
  description?: string;
  instrument?: string;
  display_currency?: string;
  sell_on_stop?: boolean;
  dry_run?: boolean;
  hedging_enabled?: boolean;
  tick_granularity?: string;
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
  api_retry_max_attempts?: number;
  api_retry_backoff_base_seconds?: number;
  api_retry_backoff_max_seconds?: number;
  drain_duration_hours?: number;
  market_idle_pre_close_minutes?: number;
  market_idle_resume_delay_minutes?: number;
  live_tick_stale_guard_enabled?: boolean;
  live_tick_max_age_seconds?: number;
  live_tick_status_log_interval_seconds?: number;
  broker_drift_check_interval_seconds?: number;
  debug_options?: Record<string, unknown>;
}

interface TradingTaskUpdateRequest {
  config_id?: string;
  account_id?: string;
  name?: string;
  description?: string;
  display_currency?: string;
  sell_on_stop?: boolean;
  dry_run?: boolean;
  hedging_enabled?: boolean;
  tick_granularity?: string;
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
  api_retry_max_attempts?: number;
  api_retry_backoff_base_seconds?: number;
  api_retry_backoff_max_seconds?: number;
  drain_duration_hours?: number;
  market_idle_pre_close_minutes?: number;
  market_idle_resume_delay_minutes?: number;
  live_tick_stale_guard_enabled?: boolean;
  live_tick_max_age_seconds?: number;
  live_tick_status_log_interval_seconds?: number;
  broker_drift_check_interval_seconds?: number;
  debug_options?: Record<string, unknown>;
}

function toExecutionSummary(
  execution?: BackendTaskExecutionSummary | null
): TradingTask['latest_execution'] {
  if (!execution) return undefined;
  return {
    ...execution,
    execution_number: Number(execution.execution_number),
    status: execution.status as TradingTask['status'],
    started_at: execution.started_at ?? execution.created_at,
    completed_at: execution.completed_at ?? undefined,
    error_message: execution.error_message ?? undefined,
    error_code: execution.error_code ?? undefined,
  };
}

function toTradingTask(task: BackendTradingTask): TradingTask {
  return {
    ...task,
    account_id: String(task.account_id),
    status: task.status as TradingTask['status'],
    latest_execution: toExecutionSummary(task.latest_execution),
    pip_size: task.pip_size ?? undefined,
    initial_positions_enabled: task.initial_positions_enabled ?? false,
    initial_position_cycles: task.initial_position_cycles ?? [],
    execution_id: task.execution_id ?? undefined,
    started_at: task.started_at ?? undefined,
    completed_at: task.completed_at ?? undefined,
    error_message: task.error_message ?? undefined,
    error_code: task.error_code ?? undefined,
  };
}

const baseApi = createTaskApi<
  BackendTradingTask,
  TradingTask,
  TradingTaskListParams,
  TradingTaskCreateRequest,
  TradingTaskUpdateRequest
>({
  basePath: '/api/trading/tasks/trading',
  transform: toTradingTask,
  mapListParams: (params) => ({
    account_id: params?.account_id ? Number(params.account_id) : undefined,
    config_id: params?.config_id,
    ordering: params?.ordering,
    page: params?.page,
    page_size: params?.page_size,
    search: params?.search,
    status: params?.status,
  }),
});

export const tradingTasksApi = {
  ...baseApi,

  // Override: trading stop accepts a mode parameter and, for drain mode,
  // an optional ``drain_duration_minutes`` override.
  stop: async (
    id: string,
    mode: 'immediate' | 'graceful' | 'graceful_close' | 'drain' = 'graceful',
    drainDurationMinutes?: number
  ): Promise<BackendTaskStopResponse> => {
    const payload: Record<string, unknown> = { mode };
    if (mode === 'drain' && typeof drainDurationMinutes === 'number') {
      payload.drain_duration_minutes = drainDurationMinutes;
    }
    return api.post<BackendTaskStopResponse>(
      `/api/trading/tasks/trading/${id}/stop/`,
      payload
    );
  },

  // Override: list needs the same signature for callers expecting PaginatedResponse
  list: baseApi.list as (
    params?: TradingTaskListParams
  ) => Promise<PaginatedResponse<TradingTask>>,
};
