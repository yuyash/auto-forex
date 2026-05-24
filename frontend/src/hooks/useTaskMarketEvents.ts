import type { TaskType } from '../types/common';
import { toIncrementalCollectionState } from './useTaskCollections';
import { useIncrementalTaskResource } from './useIncrementalTaskResource';

export interface TaskMarketEvent {
  id: number;
  task_type: string;
  task_id: string | null;
  execution_id: string | null;
  created_at: string;
  category: string;
  severity: string;
  event_type: string;
  description: string;
  instrument: string;
  details?: Record<string, unknown>;
}

interface UseTaskMarketEventsOptions {
  taskId: string;
  taskType: TaskType;
  executionRunId?: string;
  eventType?: string;
  severity?: string[];
  category?: string[];
  instrument?: string;
  message?: string;
  createdFrom?: string;
  createdTo?: string;
  ordering?: string;
  page?: number;
  pageSize?: number;
  enableRealTimeUpdates?: boolean;
  refreshInterval?: number;
}

interface UseTaskMarketEventsResult {
  events: TaskMarketEvent[];
  totalCount: number;
  hasNext: boolean;
  hasPrevious: boolean;
  isLoading: boolean;
  error: Error | null;
  refresh: () => Promise<unknown>;
}

function getLatestCreatedAt(events: TaskMarketEvent[]): string | null {
  let latest: string | null = null;
  for (const event of events) {
    if (event.created_at && (!latest || event.created_at > latest)) {
      latest = event.created_at;
    }
  }
  return latest;
}

function getSortValue(event: TaskMarketEvent, field: string): string | number {
  if (field === 'created_at') {
    const parsed = Date.parse(event.created_at);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  const value = (event as unknown as Record<string, unknown>)[field];
  if (typeof value === 'number') return value;
  return String(value ?? '');
}

function mergeEventsByOrdering(
  currentItems: TaskMarketEvent[],
  incoming: TaskMarketEvent[],
  ordering: string
): TaskMarketEvent[] {
  const field = ordering.startsWith('-') ? ordering.slice(1) : ordering;
  const direction = ordering.startsWith('-') ? 'desc' : 'asc';
  const merged = new Map(currentItems.map((event) => [event.id, event]));
  for (const event of incoming) {
    merged.set(event.id, event);
  }
  return Array.from(merged.values()).sort((a, b) => {
    const aValue = getSortValue(a, field || 'created_at');
    const bValue = getSortValue(b, field || 'created_at');
    if (aValue < bValue) return direction === 'desc' ? 1 : -1;
    if (aValue > bValue) return direction === 'desc' ? -1 : 1;
    return Number(a.id) - Number(b.id);
  });
}

export const useTaskMarketEvents = ({
  taskId,
  taskType,
  executionRunId,
  eventType,
  severity,
  category,
  instrument,
  message,
  createdFrom,
  createdTo,
  ordering = '-created_at',
  page = 1,
  pageSize = 100,
  enableRealTimeUpdates = false,
  refreshInterval = 5_000,
}: UseTaskMarketEventsOptions): UseTaskMarketEventsResult => {
  const paramsKey = [
    taskId,
    taskType,
    executionRunId ?? '',
    eventType ?? '',
    (severity || []).join(','),
    (category || []).join(','),
    instrument ?? '',
    message ?? '',
    createdFrom ?? '',
    createdTo ?? '',
    ordering,
    page,
    pageSize,
  ].join('-');

  const {
    items: events,
    totalCount,
    hasNext,
    hasPrevious,
    isLoading,
    error,
    refresh,
  } = useIncrementalTaskResource<TaskMarketEvent>({
    taskId,
    taskType,
    endpoint: 'market-events',
    paramsKey,
    page,
    pageSize,
    enableRealTimeUpdates,
    refreshInterval,
    errorContext: 'task_market_events',
    fallbackErrorMessage: 'Failed to load market events',
    buildParams: () => {
      const params: Record<string, string> = {};
      if (executionRunId != null) {
        params.execution_id = String(executionRunId);
      }
      if (eventType) params.event_type = eventType;
      if (severity && severity.length > 0) params.severity = severity.join(',');
      if (category && category.length > 0) params.category = category.join(',');
      if (instrument) params.instrument = instrument;
      if (message) params.message = message;
      if (createdFrom) params.created_from = createdFrom;
      if (createdTo) params.created_to = createdTo;
      if (ordering) params.ordering = ordering;
      return params;
    },
    getLatestCursor: getLatestCreatedAt,
    getItemId: (event) => event.id,
    mergeIncremental: ({ currentItems, incoming }) =>
      mergeEventsByOrdering(currentItems, incoming, ordering),
  });

  return {
    ...toIncrementalCollectionState({
      items: events,
      totalCount,
      hasNext,
      hasPrevious,
      isLoading,
      error,
      refresh,
    }),
    events,
  };
};
