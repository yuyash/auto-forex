import { tradingTasksApi } from '../services/api';
import type { BackendTaskStopResponse } from '../services/api/contracts';
import type {
  TradingTask,
  TradingTaskCreateData,
  TradingTaskUpdateData,
} from '../types';
import { TaskStatus } from '../types/common';
import {
  beginTaskStatusTransition,
  clearTaskStatusTransitionByKind,
  invalidateTaskDerivedCaches,
  patchTaskDerivedCaches,
  patchTaskStatusCache,
  refreshTaskStatusCaches,
  upsertTaskCaches,
} from './taskMutationCache';
import {
  createCopyHook,
  createDeleteHook,
  createPauseHook,
  createRestartHook,
  createResumeHook,
  createStartHook,
} from './useTaskMutationFactory';
import { useWrappedMutation } from './useWrappedMutation';

export type StopMode = 'immediate' | 'graceful' | 'graceful_close' | 'drain';

function optimisticStopStatus(mode?: StopMode): TaskStatus {
  return mode === 'drain' ? TaskStatus.DRAINING : TaskStatus.STOPPING;
}

function stopSettleStatuses(mode?: StopMode): TaskStatus[] {
  return mode === 'drain'
    ? [
        TaskStatus.DRAINING,
        TaskStatus.STOPPING,
        TaskStatus.STOPPED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
      ]
    : [
        TaskStatus.STOPPING,
        TaskStatus.STOPPED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
      ];
}

// --- hooks that need custom create/update logic (not generic) -------------

export function useCreateTradingTask(options?: {
  onSuccess?: (data: TradingTask) => void;
  onError?: (error: Error) => void;
}) {
  return useWrappedMutation(
    (variables: TradingTaskCreateData) =>
      tradingTasksApi.create({
        config_id: variables.config_id,
        account_id: variables.account_id,
        name: variables.name,
        description: variables.description,
        instrument: variables.instrument,
        display_currency: variables.display_currency,
        sell_on_stop: variables.sell_on_stop,
        dry_run: variables.dry_run,
        hedging_enabled: variables.hedging_enabled,
        tick_granularity: variables.tick_granularity,
        initial_positions_enabled: variables.initial_positions_enabled,
        initial_position_cycles: variables.initial_position_cycles,
        api_retry_max_attempts: variables.api_retry_max_attempts,
        api_retry_backoff_base_seconds:
          variables.api_retry_backoff_base_seconds,
        api_retry_backoff_max_seconds: variables.api_retry_backoff_max_seconds,
        drain_duration_hours: variables.drain_duration_hours,
        market_idle_pre_close_minutes: variables.market_idle_pre_close_minutes,
        market_idle_resume_delay_minutes:
          variables.market_idle_resume_delay_minutes,
        live_tick_stale_guard_enabled: variables.live_tick_stale_guard_enabled,
        live_tick_max_age_seconds: variables.live_tick_max_age_seconds,
        live_tick_status_log_interval_seconds:
          variables.live_tick_status_log_interval_seconds,
        broker_drift_check_interval_seconds:
          variables.broker_drift_check_interval_seconds,
        debug_options: variables.debug_options,
      }),
    {
      onSuccess: async (data) => {
        upsertTaskCaches('trading', data);
        patchTaskDerivedCaches('trading', data);
        await invalidateTaskDerivedCaches('trading', data.id);
        options?.onSuccess?.(data);
      },
      onError: (error) => options?.onError?.(error),
    }
  );
}

export function useUpdateTradingTask(options?: {
  onSuccess?: (data: TradingTask) => void;
  onError?: (error: Error) => void;
}) {
  return useWrappedMutation(
    (variables: { id: string; data: TradingTaskUpdateData }) =>
      tradingTasksApi.partialUpdate(variables.id, {
        config_id: variables.data.config,
        account_id: variables.data.account_id,
        name: variables.data.name,
        description: variables.data.description,
        display_currency: variables.data.display_currency,
        sell_on_stop: variables.data.sell_on_stop,
        dry_run: variables.data.dry_run,
        hedging_enabled: variables.data.hedging_enabled,
        tick_granularity: variables.data.tick_granularity,
        initial_positions_enabled: variables.data.initial_positions_enabled,
        initial_position_cycles: variables.data.initial_position_cycles,
        api_retry_max_attempts: variables.data.api_retry_max_attempts,
        api_retry_backoff_base_seconds:
          variables.data.api_retry_backoff_base_seconds,
        api_retry_backoff_max_seconds:
          variables.data.api_retry_backoff_max_seconds,
        drain_duration_hours: variables.data.drain_duration_hours,
        market_idle_pre_close_minutes:
          variables.data.market_idle_pre_close_minutes,
        market_idle_resume_delay_minutes:
          variables.data.market_idle_resume_delay_minutes,
        live_tick_stale_guard_enabled:
          variables.data.live_tick_stale_guard_enabled,
        live_tick_max_age_seconds: variables.data.live_tick_max_age_seconds,
        live_tick_status_log_interval_seconds:
          variables.data.live_tick_status_log_interval_seconds,
        broker_drift_check_interval_seconds:
          variables.data.broker_drift_check_interval_seconds,
        debug_options: variables.data.debug_options,
      }),
    {
      onSuccess: async (data, variables) => {
        let nextTask = data;
        try {
          nextTask = await tradingTasksApi.get(variables.id);
        } catch {
          nextTask = data;
        }

        upsertTaskCaches('trading', nextTask);
        patchTaskDerivedCaches('trading', nextTask);
        await invalidateTaskDerivedCaches('trading', nextTask.id);
        options?.onSuccess?.(nextTask);
      },
      onError: (error) => options?.onError?.(error),
    }
  );
}

// --- stop needs a custom status-patch + mode parameter --------------------

export function useStopTradingTask(options?: {
  onSuccess?: (data: BackendTaskStopResponse) => void;
  onError?: (error: Error) => void;
}) {
  return useWrappedMutation(
    (variables: {
      id: string;
      mode?: StopMode;
      drainDurationMinutes?: number;
    }) =>
      tradingTasksApi.stop(
        variables.id,
        variables.mode ?? 'graceful',
        variables.drainDurationMinutes
      ),
    {
      onMutate: (variables) => {
        beginTaskStatusTransition(
          'trading',
          variables.id,
          optimisticStopStatus(variables.mode),
          stopSettleStatuses(variables.mode)
        );
      },
      onSuccess: async (data, variables) => {
        const fallbackStatus =
          variables.mode === 'drain' ? 'draining' : 'stopping';
        const nextStatus =
          (data.next_status ?? data.status).toLowerCase() || fallbackStatus;
        await patchTaskStatusCache('trading', variables.id, nextStatus);
        await invalidateTaskDerivedCaches('trading', variables.id);
        options?.onSuccess?.(data);
      },
      onError: (error, variables) => {
        clearTaskStatusTransitionByKind('trading', variables.id);
        void refreshTaskStatusCaches('trading', variables.id);
        options?.onError?.(error);
      },
    }
  );
}

// --- lifecycle hooks via factory ------------------------------------------

export const useDeleteTradingTask = createDeleteHook<TradingTask>(
  'trading',
  tradingTasksApi
);

export const useCopyTradingTask = createCopyHook<TradingTask>(
  'trading',
  tradingTasksApi as Parameters<typeof createCopyHook<TradingTask>>[1]
);

export const useStartTradingTask = createStartHook<TradingTask>(
  'trading',
  tradingTasksApi
);

export const usePauseTradingTask = createPauseHook<TradingTask>(
  'trading',
  tradingTasksApi
);

export const useResumeTradingTask = createResumeHook<TradingTask>(
  'trading',
  tradingTasksApi
);

export const useRestartTradingTask = createRestartHook<TradingTask>(
  'trading',
  tradingTasksApi
);
