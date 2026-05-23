import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiConfig } from '../api/apiConfig';
import { queryKeys } from '../config/reactQuery';
import type { PaginatedResponse } from '../types';
import { TaskType, type TaskStatus } from '../types/common';
import { logger } from '../utils/logger';
import { patchTaskSummaryStatus } from './taskResourceCache';
import { applyTaskStatusTransition } from './taskStatusTransitions';

interface TaskSnapshot {
  id?: string;
  task_type?: TaskType;
  status?: string;
  progress?: number | null;
  execution_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  error_code?: string | null;
  status_reason_code?: string | null;
  status_reason_message?: string | null;
  updated_at?: string | null;
}

type StreamTask = {
  id: string;
  status: TaskStatus;
  progress?: number | null;
  execution_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  error_code?: string | null;
  status_reason_code?: string | null;
  status_reason_message?: string | null;
  updated_at?: string | null;
};

const STREAM_RETRY_DELAY_MS = 5000;
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function taskDetailKey(taskType: TaskType, taskId: string) {
  return taskType === TaskType.BACKTEST
    ? queryKeys.backtestTasks.detail(taskId)
    : queryKeys.tradingTasks.detail(taskId);
}

function taskListKey(taskType: TaskType) {
  return taskType === TaskType.BACKTEST
    ? queryKeys.backtestTasks.lists()
    : queryKeys.tradingTasks.lists();
}

function parseSseEvent(raw: string): { event: string; data: string } | null {
  const lines = raw.split('\n');
  const eventLine = lines.find((line) => line.startsWith('event:'));
  const dataLines = lines.filter((line) => line.startsWith('data:'));
  if (!eventLine || dataLines.length === 0) {
    return null;
  }
  return {
    event: eventLine.slice('event:'.length).trim(),
    data: dataLines.map((line) => line.slice('data:'.length).trim()).join('\n'),
  };
}

function applySnapshot<TTask extends StreamTask>(
  taskType: TaskType,
  current: TTask | undefined,
  snapshot: TaskSnapshot
): TTask | undefined {
  if (!current || typeof current !== 'object') {
    return current;
  }
  const merged = {
    ...current,
    status: (snapshot.status as TaskStatus | undefined) ?? current.status,
    progress: snapshot.progress ?? current.progress,
    execution_id: snapshot.execution_id ?? current.execution_id,
    started_at: snapshot.started_at ?? current.started_at,
    completed_at: snapshot.completed_at ?? current.completed_at,
    error_message: snapshot.error_message ?? current.error_message,
    error_code: snapshot.error_code ?? current.error_code,
    status_reason_code:
      snapshot.status_reason_code ?? current.status_reason_code,
    status_reason_message:
      snapshot.status_reason_message ?? current.status_reason_message,
    updated_at: snapshot.updated_at ?? current.updated_at,
  } satisfies TTask;
  return applyTaskStatusTransition(taskType, merged);
}

function applySnapshotToList<TTask extends StreamTask>(
  taskType: TaskType,
  current: PaginatedResponse<TTask> | undefined,
  snapshot: TaskSnapshot
): PaginatedResponse<TTask> | undefined {
  if (!current || !snapshot.id) {
    return current;
  }
  let changed = false;
  const results = current.results.map((task) => {
    if (task.id !== snapshot.id) {
      return task;
    }
    changed = true;
    return applyTaskStatusTransition(taskType, {
      ...task,
      status: (snapshot.status as TaskStatus | undefined) ?? task.status,
      execution_id: snapshot.execution_id ?? task.execution_id,
      started_at: snapshot.started_at ?? task.started_at,
      completed_at: snapshot.completed_at ?? task.completed_at,
      error_message: snapshot.error_message ?? task.error_message,
      error_code: snapshot.error_code ?? task.error_code,
      status_reason_code:
        snapshot.status_reason_code ?? task.status_reason_code,
      status_reason_message:
        snapshot.status_reason_message ?? task.status_reason_message,
      updated_at: snapshot.updated_at ?? task.updated_at,
    });
  });
  return changed ? { ...current, results } : current;
}

export function useTaskEventStream<TTask extends StreamTask>({
  taskType,
  taskId,
  enabled,
}: {
  taskType: TaskType;
  taskId?: string;
  enabled: boolean;
}): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (
      !enabled ||
      !taskId ||
      !UUID_PATTERN.test(taskId) ||
      typeof ReadableStream === 'undefined'
    ) {
      return;
    }

    const abortController = new AbortController();
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = async () => {
      try {
        const response = await fetch(
          `${apiConfig.BASE}/api/trading/tasks/${taskType}/${taskId}/stream/`,
          {
            method: 'GET',
            credentials: apiConfig.WITH_CREDENTIALS ? 'include' : 'same-origin',
            headers: { Accept: 'text/event-stream' },
            signal: abortController.signal,
          }
        );

        if (!response.ok || !response.body) {
          throw new Error(`Task stream failed with status ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (!closed) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }

          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split('\n\n');
          buffer = chunks.pop() ?? '';

          for (const chunk of chunks) {
            const parsed = parseSseEvent(chunk);
            if (!parsed || parsed.event !== 'snapshot') {
              continue;
            }

            const snapshot = JSON.parse(parsed.data) as TaskSnapshot;
            queryClient.setQueryData<TTask>(
              taskDetailKey(taskType, taskId),
              (current) => applySnapshot(taskType, current, snapshot)
            );
            queryClient.setQueriesData<PaginatedResponse<TTask> | undefined>(
              { queryKey: taskListKey(taskType) },
              (current) => applySnapshotToList(taskType, current, snapshot)
            );
            if (snapshot.status) {
              patchTaskSummaryStatus(taskId, taskType, snapshot.status, {
                ...(Object.prototype.hasOwnProperty.call(
                  snapshot,
                  'status_reason_code'
                )
                  ? { statusReasonCode: snapshot.status_reason_code ?? null }
                  : {}),
                ...(Object.prototype.hasOwnProperty.call(
                  snapshot,
                  'status_reason_message'
                )
                  ? {
                      statusReasonMessage:
                        snapshot.status_reason_message ?? null,
                    }
                  : {}),
              });
            }
            void queryClient.invalidateQueries({
              queryKey: taskListKey(taskType),
            });
          }
        }
      } catch (error) {
        if (closed || abortController.signal.aborted) {
          return;
        }
        logger.warn('Task event stream disconnected', {
          taskType,
          taskId,
          error: error instanceof Error ? error.message : String(error),
        });
        retryTimer = setTimeout(connect, STREAM_RETRY_DELAY_MS);
      }
    };

    void connect();

    return () => {
      closed = true;
      abortController.abort();
      if (retryTimer) {
        clearTimeout(retryTimer);
      }
    };
  }, [enabled, queryClient, taskId, taskType]);
}
