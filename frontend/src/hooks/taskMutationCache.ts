import { queryClient, queryKeys } from '../config/reactQuery';
import type { BacktestTask, PaginatedResponse, TradingTask } from '../types';
import { TaskStatus, TaskType } from '../types/common';
import {
  clearTaskExecutions,
  patchTaskLogComponents,
  patchTaskStrategyEventsLifecycle,
  invalidateTaskDerivedByKind,
  patchTaskSummaryStatus,
  prependTaskExecution,
} from './taskResourceCache';
import {
  patchListQueries,
  removePaginatedEntity,
  removeFromListQueries,
  upsertFilteredPaginatedEntity,
} from './listCacheUtils';
import {
  matchesEntityFilterSpec,
  readOrderingFilter,
  type EntityFilterSpec,
} from './listFilterUtils';
import {
  applyTaskStatusTransition,
  clearTaskStatusTransition,
  markTaskStatusTransition,
} from './taskStatusTransitions';

type TaskEntity = BacktestTask | TradingTask;
type TaskKind = 'backtest' | 'trading';
type SortValue = string | number | boolean | undefined;
type TaskSortAccessor = (task: TaskEntity) => SortValue;

function getTaskKeys(taskKind: TaskKind) {
  if (taskKind === 'backtest') {
    return {
      lists: queryKeys.backtestTasks.lists(),
      detail: queryKeys.backtestTasks.detail,
      executions: queryKeys.backtestTasks.executions,
    };
  }
  return {
    lists: queryKeys.tradingTasks.lists(),
    detail: queryKeys.tradingTasks.detail,
    executions: queryKeys.tradingTasks.executions,
  };
}

function getTaskDerivedKeys(taskKind: TaskKind, taskId: string) {
  const taskType = taskKind === 'backtest' ? 'backtest' : 'trading';
  return {
    summaries: queryKeys.taskResources.summary(taskType, taskId),
    strategyEvents: queryKeys.taskResources.strategyEvents(taskType, taskId),
    logComponents: queryKeys.taskResources.logComponents(taskType, taskId),
  };
}

function taskTypeForKind(taskKind: TaskKind): TaskType {
  return taskKind === 'backtest' ? TaskType.BACKTEST : TaskType.TRADING;
}

function applyTaskTransition<T extends TaskEntity>(
  taskKind: TaskKind,
  task: T
): T {
  return applyTaskStatusTransition(taskTypeForKind(taskKind), task);
}

const TASK_SORT_SPECS: Record<string, TaskSortAccessor> = {
  name: (task) => task.name,
  status: (task) => task.status,
  strategy_type: (task) => task.strategy_type,
  config_name: (task) => task.config_name,
  updated_at: (task) => task.updated_at,
  created_at: (task) => task.created_at,
  instrument: (task) => task.instrument,
  account_name: (task) => (task as TradingTask).account_name,
};

function compareValues(
  left: SortValue,
  right: SortValue,
  ordering: string
): number {
  const direction = ordering.startsWith('-') ? -1 : 1;
  const leftValue = left ?? '';
  const rightValue = right ?? '';
  if (leftValue < rightValue) {
    return -1 * direction;
  }
  if (leftValue > rightValue) {
    return 1 * direction;
  }
  return 0;
}

function sortTaskResults<T extends TaskEntity>(
  results: T[],
  ordering?: string
): T[] {
  if (!ordering) {
    return results;
  }

  const field = ordering.replace(/^-/, '');
  const accessor = TASK_SORT_SPECS[field];
  if (!accessor) {
    return results;
  }
  const sorted = [...results];
  sorted.sort((left, right) =>
    compareValues(accessor(left), accessor(right), ordering)
  );
  return sorted;
}

function getTaskListFilterSpec(
  taskKind: TaskKind
): EntityFilterSpec<TaskEntity> {
  const exact: EntityFilterSpec<TaskEntity>['exact'] = [
    { key: 'status', value: (task) => task.status },
    { key: 'config_id', value: (task) => task.config_id },
    { key: 'strategy_type', value: (task) => task.strategy_type },
  ];
  if (taskKind === 'trading') {
    exact.push({
      key: 'account_id',
      value: (task) => (task as TradingTask).account_id,
    });
  }

  return {
    exact,
    search: {
      haystack: (task) => [
        task.name,
        task.description,
        task.config_name,
        task.strategy_type,
      ],
    },
  };
}

function matchesTaskListFilter(
  taskKind: TaskKind,
  task: TaskEntity,
  params?: Record<string, unknown>
): boolean {
  return matchesEntityFilterSpec(params, task, getTaskListFilterSpec(taskKind));
}

export function upsertTaskCaches<T extends TaskEntity>(
  taskKind: TaskKind,
  task: T
): void {
  const keys = getTaskKeys(taskKind);
  const effectiveTask = applyTaskTransition(taskKind, task);
  queryClient.setQueryData(keys.detail(effectiveTask.id), effectiveTask);
  patchListQueries<PaginatedResponse<T>>(keys.lists, (cached, params) =>
    upsertFilteredPaginatedEntity(cached, effectiveTask, params, {
      matches: (entity, queryParams) =>
        matchesTaskListFilter(taskKind, entity, queryParams),
      sort: (items, queryParams) =>
        sortTaskResults(items, readOrderingFilter(queryParams)),
    })
  );
  // Ensure list queries refetch from the server so pages that mount after
  // this cache write (e.g. navigating back to the list) always show the
  // latest data including correct status and timestamps.
  void queryClient.invalidateQueries({ queryKey: keys.lists });
}

export function patchTaskStatusInMemory(
  taskKind: TaskKind,
  taskId: string,
  status: TaskStatus
): void {
  const keys = getTaskKeys(taskKind);
  queryClient.setQueryData<TaskEntity | undefined>(
    keys.detail(taskId),
    (cached) => (cached ? { ...cached, status } : cached)
  );
  patchListQueries<PaginatedResponse<TaskEntity>>(
    keys.lists,
    (cached, params) => {
      if (!cached) {
        return cached;
      }
      const current = cached.results.find((entry) => entry.id === taskId);
      if (!current) {
        return cached;
      }
      return upsertFilteredPaginatedEntity(
        cached,
        { ...current, status } as TaskEntity,
        params,
        {
          matches: (entity, queryParams) =>
            matchesTaskListFilter(taskKind, entity, queryParams),
          sort: (items, queryParams) =>
            sortTaskResults(items, readOrderingFilter(queryParams)),
        }
      );
    }
  );
  patchTaskSummaryStatus(taskId, taskTypeForKind(taskKind), status);
}

export function beginTaskStatusTransition(
  taskKind: TaskKind,
  taskId: string,
  status: TaskStatus,
  settleOn: TaskStatus[]
): void {
  markTaskStatusTransition(taskTypeForKind(taskKind), taskId, status, settleOn);
  patchTaskStatusInMemory(taskKind, taskId, status);
}

export function clearTaskStatusTransitionByKind(
  taskKind: TaskKind,
  taskId: string
): void {
  clearTaskStatusTransition(taskTypeForKind(taskKind), taskId);
}

export async function refreshTaskStatusCaches(
  taskKind: TaskKind,
  taskId: string
): Promise<void> {
  const keys = getTaskKeys(taskKind);
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: keys.detail(taskId),
      refetchType: 'active',
    }),
    queryClient.invalidateQueries({
      queryKey: keys.lists,
      refetchType: 'active',
    }),
  ]);
}

export async function removeTaskCaches(
  taskKind: TaskKind,
  taskId: string
): Promise<void> {
  const keys = getTaskKeys(taskKind);
  const derivedKeys = getTaskDerivedKeys(taskKind, taskId);
  await queryClient.cancelQueries({ queryKey: keys.lists });
  queryClient.removeQueries({ queryKey: keys.detail(taskId) });
  queryClient.removeQueries({ queryKey: keys.executions(taskId) });
  queryClient.removeQueries({ queryKey: derivedKeys.summaries });
  queryClient.removeQueries({ queryKey: derivedKeys.strategyEvents });
  queryClient.removeQueries({ queryKey: derivedKeys.logComponents });
  removeFromListQueries<PaginatedResponse<TaskEntity>>(keys.lists, (cached) =>
    removePaginatedEntity(cached, taskId)
  );
  await queryClient.invalidateQueries({
    queryKey: keys.lists,
    refetchType: 'active',
  });
}

export async function patchTaskStatusCache(
  taskKind: TaskKind,
  taskId: string,
  status: string
): Promise<void> {
  patchTaskStatusInMemory(taskKind, taskId, status as TaskStatus);
  await refreshTaskStatusCaches(taskKind, taskId);
}

export async function invalidateTaskDerivedCaches(
  taskKind: TaskKind,
  taskId: string
): Promise<void> {
  await invalidateTaskDerivedByKind(taskId, taskKind);
}

export function removeTaskListEntry(taskKind: TaskKind, taskId: string): void {
  const keys = getTaskKeys(taskKind);
  removeFromListQueries<PaginatedResponse<TaskEntity>>(keys.lists, (cached) => {
    if (!cached) {
      return cached;
    }
    const nextResults = cached.results.filter((entry) => entry.id !== taskId);
    if (nextResults.length === cached.results.length) {
      return cached;
    }
    return {
      ...cached,
      count: Math.max(0, cached.count - 1),
      results: nextResults,
    };
  });
}

export function patchTaskDerivedCaches(
  taskKind: TaskKind,
  task: TaskEntity
): void {
  const effectiveTask = applyTaskTransition(taskKind, task);
  const taskType = taskTypeForKind(taskKind);
  const clearsExecutionState =
    task.status === TaskStatus.CREATED ||
    effectiveTask.status === TaskStatus.CREATED;
  patchTaskSummaryStatus(
    effectiveTask.id,
    taskType,
    String(effectiveTask.status),
    {
      statusReasonCode: effectiveTask.status_reason_code ?? null,
      statusReasonMessage: effectiveTask.status_reason_message ?? null,
    }
  );
  patchTaskLogComponents(effectiveTask.id, taskType, []);

  const latestExecution = effectiveTask.latest_execution;
  if (!latestExecution?.id) {
    patchTaskStrategyEventsLifecycle(effectiveTask.id, taskType, {
      executionId: null,
      clearVisualization: clearsExecutionState,
    });
    if (clearsExecutionState) {
      clearTaskExecutions(effectiveTask.id, taskType);
    }
    return;
  }

  patchTaskStrategyEventsLifecycle(effectiveTask.id, taskType, {
    executionId: latestExecution.id,
    clearVisualization:
      clearsExecutionState || latestExecution.status === 'starting',
  });

  prependTaskExecution(effectiveTask.id, taskType, {
    id: latestExecution.id,
    task_type: taskType,
    task_id: effectiveTask.id,
    execution_number: latestExecution.execution_number,
    status: latestExecution.status,
    progress: latestExecution.progress,
    started_at: latestExecution.started_at,
    completed_at: latestExecution.completed_at,
    error_message: latestExecution.error_message,
    error_code: latestExecution.error_code,
    created_at: latestExecution.started_at,
    metrics: {
      total_return: latestExecution.total_return,
      total_pnl: latestExecution.total_pnl,
      total_trades: latestExecution.total_trades,
      winning_trades: latestExecution.winning_trades,
      losing_trades: latestExecution.losing_trades,
      win_rate: latestExecution.win_rate,
    },
  });
}
