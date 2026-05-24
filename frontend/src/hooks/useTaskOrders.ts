/**
 * useTaskOrders Hook
 *
 * Fetches orders from task-based API endpoints with DRF pagination.
 * Supports incremental fetching via the `since` parameter — during polling
 * cycles only new/updated records are fetched and merged into the local cache.
 */

import type { TaskType } from '../types/common';
import { toIncrementalCollectionState } from './useTaskCollections';
import { useIncrementalTaskResource } from './useIncrementalTaskResource';

export interface TaskOrder {
  id: string;
  broker_order_id?: string | null;
  oanda_trade_id?: string | null;
  instrument: string;
  order_type: string;
  direction?: string | null;
  units: number;
  requested_price?: string | null;
  fill_price?: string | null;
  status: string;
  submitted_at: string;
  filled_at?: string | null;
  oanda_response_seconds?: string | null;
  cancelled_at?: string | null;
  stop_loss?: string | null;
  error_message?: string | null;
  is_dry_run: boolean;
  replayed_at?: string | null;
  updated_at?: string | null;
}

interface UseTaskOrdersOptions {
  taskId: string | number;
  taskType: TaskType;
  /** Filter orders by execution run ID. */
  executionRunId?: string;
  status?: string;
  orderType?: string;
  direction?: string;
  /** Filter orders by order ID prefix (e.g. first 8 chars of UUID). */
  orderId?: string;
  page?: number;
  pageSize?: number;
  ordering?: string;
  /** ISO 8601 timestamp — only return records updated after this time. */
  since?: string;
  /** Filter orders with submitted_at >= this value. */
  timestampFrom?: string;
  /** Filter orders with submitted_at <= this value. */
  timestampTo?: string;
  enableRealTimeUpdates?: boolean;
  refreshInterval?: number;
}

interface UseTaskOrdersResult {
  orders: TaskOrder[];
  totalCount: number;
  hasNext: boolean;
  hasPrevious: boolean;
  isLoading: boolean;
  error: Error | null;
  refresh: () => Promise<unknown>;
}

function getLatestUpdatedAt(orders: TaskOrder[]): string | null {
  let latest: string | null = null;
  for (const o of orders) {
    if (o.updated_at && (!latest || o.updated_at > latest)) {
      latest = o.updated_at;
    }
  }
  return latest;
}

export const useTaskOrders = ({
  taskId,
  taskType,
  executionRunId,
  status,
  orderType,
  direction,
  orderId,
  page = 1,
  pageSize = 100,
  ordering = '-submitted_at',
  since,
  timestampFrom,
  timestampTo,
  enableRealTimeUpdates = false,
  refreshInterval = 5_000,
}: UseTaskOrdersOptions): UseTaskOrdersResult => {
  const paramsKey = `${taskId}-${taskType}-${executionRunId ?? ''}-${status}-${orderType}-${direction}-${orderId ?? ''}-${ordering}-${page}-${pageSize}-${since ?? ''}-${timestampFrom ?? ''}-${timestampTo ?? ''}`;
  const {
    items: orders,
    totalCount,
    hasNext,
    hasPrevious,
    isLoading,
    error,
    refresh,
  } = useIncrementalTaskResource<TaskOrder>({
    taskId,
    taskType,
    endpoint: 'orders',
    paramsKey,
    page,
    pageSize,
    since,
    enableRealTimeUpdates,
    refreshInterval,
    errorContext: 'task_orders',
    fallbackErrorMessage: 'Failed to load orders',
    buildParams: () => {
      const params: Record<string, string> = {};
      if (status) params.status = status;
      if (orderType) params.order_type = orderType;
      if (direction) params.direction = direction;
      if (orderId) params.order_id = orderId;
      if (executionRunId != null) {
        params.execution_id = String(executionRunId);
      }
      if (timestampFrom) params.timestamp_from = timestampFrom;
      if (timestampTo) params.timestamp_to = timestampTo;
      if (ordering) params.ordering = ordering;
      return params;
    },
    getLatestCursor: getLatestUpdatedAt,
    getItemId: (order) => order.id,
  });

  return {
    ...toIncrementalCollectionState({
      items: orders,
      totalCount,
      hasNext,
      hasPrevious,
      isLoading,
      error,
      refresh,
    }),
    orders,
  };
};
