import { queryClient, queryKeys } from '../config/reactQuery';
import type { PaginatedResponse, TaskExecution } from '../types';
import { TaskType } from '../types/common';
import type { StrategyCyclesResponse } from '../types/strategyVisualization';
import type { TaskSummary } from './useTaskSummary';

export function getTaskExecutionsKey(
  taskId: string,
  taskType: TaskType,
  params?: { page?: number; page_size?: number; include_metrics?: boolean }
) {
  return taskType === TaskType.BACKTEST
    ? queryKeys.backtestTasks.executions(taskId, params)
    : queryKeys.tradingTasks.executions(taskId, params);
}

export function getTaskExecutionKey(
  taskId: string,
  executionId: string,
  taskType: TaskType
) {
  return taskType === TaskType.BACKTEST
    ? queryKeys.backtestTasks.execution(taskId, executionId)
    : queryKeys.tradingTasks.execution(taskId, executionId);
}

export function refreshTaskExecutions(
  taskId: string,
  taskType: TaskType,
  params?: { page?: number; page_size?: number; include_metrics?: boolean }
) {
  return queryClient.invalidateQueries({
    queryKey: getTaskExecutionsKey(taskId, taskType, params),
  });
}

export function refreshTaskExecution(
  taskId: string,
  executionId: string,
  taskType: TaskType
) {
  return queryClient.invalidateQueries({
    queryKey: getTaskExecutionKey(taskId, executionId, taskType),
  });
}

export function refreshTaskSummary(
  taskId: string,
  taskType: TaskType,
  executionRunId?: string
) {
  return queryClient.invalidateQueries({
    queryKey: queryKeys.taskResources.summary(taskType, taskId, executionRunId),
  });
}

export function refreshTaskStrategyEvents(
  taskId: string,
  taskType: TaskType,
  executionRunId?: string,
  cycleId?: string
) {
  return queryClient.invalidateQueries({
    queryKey: queryKeys.taskResources.strategyEvents(
      taskType,
      taskId,
      executionRunId,
      cycleId
    ),
  });
}

export async function invalidateTaskDerivedResources(
  taskId: string,
  taskType: TaskType
): Promise<void> {
  await Promise.all([
    refreshTaskExecutions(taskId, taskType),
    refreshTaskSummary(taskId, taskType),
    refreshTaskStrategyEvents(taskId, taskType),
  ]);
}

export function invalidateTaskDerivedByKind(
  taskId: string,
  taskKind: 'backtest' | 'trading'
): Promise<void> {
  return invalidateTaskDerivedResources(
    taskId,
    taskKind === 'backtest' ? TaskType.BACKTEST : TaskType.TRADING
  );
}

export function clearTaskStrategyEvents(
  taskId: string,
  taskType: TaskType,
  executionRunId?: string
): void {
  queryClient.removeQueries({
    queryKey: queryKeys.taskResources.strategyEvents(
      taskType,
      taskId,
      executionRunId
    ),
  });
}

export function clearTaskLogComponents(
  taskId: string,
  taskType: TaskType,
  executionRunId?: string
): void {
  queryClient.removeQueries({
    queryKey: queryKeys.taskResources.logComponents(
      taskType,
      taskId,
      executionRunId
    ),
  });
}

export function patchTaskLogComponents(
  taskId: string,
  taskType: TaskType,
  components: string[]
): void {
  queryClient.setQueriesData<string[] | undefined>(
    { queryKey: queryKeys.taskResources.logComponents(taskType, taskId) },
    () => components
  );
}

export function patchTaskStrategyEventsExecution(
  taskId: string,
  taskType: TaskType,
  executionId: string | null
): void {
  queryClient.setQueriesData<StrategyCyclesResponse | null | undefined>(
    { queryKey: queryKeys.taskResources.strategyEvents(taskType, taskId) },
    (cached) => {
      if (!cached) {
        return cached;
      }
      return {
        ...cached,
        execution_id: executionId,
      };
    }
  );
}

export function patchTaskStrategyEventsLifecycle(
  taskId: string,
  taskType: TaskType,
  options: {
    executionId: string | null;
    clearVisualization?: boolean;
  }
): void {
  queryClient.setQueriesData<StrategyCyclesResponse | null | undefined>(
    { queryKey: queryKeys.taskResources.strategyEvents(taskType, taskId) },
    (cached) => {
      if (!cached) {
        return cached;
      }
      if (options.clearVisualization) {
        return {
          execution_id: options.executionId,
          cycles: [],
          summary: {
            cycle_count: 0,
            active_count: 0,
            pending_count: 0,
            completed_count: 0,
            total_trades: 0,
          },
          pagination: null,
          last_tick_timestamp: null,
        };
      }
      return {
        ...cached,
        execution_id: options.executionId,
      };
    }
  );
}

export function patchTaskSummaryStatus(
  taskId: string,
  taskType: TaskType,
  status: string,
  reason?: {
    statusReasonCode?: string | null;
    statusReasonMessage?: string | null;
  }
): void {
  queryClient.setQueriesData<TaskSummary | undefined>(
    { queryKey: queryKeys.taskResources.summary(taskType, taskId) },
    (cached) =>
      cached
        ? {
            ...cached,
            task: {
              ...cached.task,
              status,
              ...(reason && 'statusReasonCode' in reason
                ? { statusReasonCode: reason.statusReasonCode ?? null }
                : {}),
              ...(reason && 'statusReasonMessage' in reason
                ? { statusReasonMessage: reason.statusReasonMessage ?? null }
                : {}),
              ...(reason && 'statusReasonMessage' in reason
                ? {
                    stopReason:
                      reason.statusReasonMessage ?? cached.task.stopReason,
                  }
                : {}),
            },
          }
        : cached
  );
}

export function clearTaskExecutions(taskId: string, taskType: TaskType): void {
  queryClient.removeQueries({
    queryKey:
      taskType === TaskType.BACKTEST
        ? queryKeys.backtestTasks.executions(taskId)
        : queryKeys.tradingTasks.executions(taskId),
  });
}

export function prependTaskExecution(
  taskId: string,
  taskType: TaskType,
  execution: TaskExecution
): void {
  const executionsKey =
    taskType === TaskType.BACKTEST
      ? queryKeys.backtestTasks.executions(taskId)
      : queryKeys.tradingTasks.executions(taskId);
  queryClient.setQueriesData<PaginatedResponse<TaskExecution> | undefined>(
    { queryKey: executionsKey },
    (cached) => {
      if (!cached) {
        return cached;
      }
      const existing = cached.results.find(
        (entry) => entry.id === execution.id
      );
      if (existing) {
        return {
          ...cached,
          results: cached.results.map((entry) =>
            entry.id === execution.id ? { ...entry, ...execution } : entry
          ),
        };
      }
      return {
        ...cached,
        count: cached.count + 1,
        results: [execution, ...cached.results],
      };
    }
  );
}
