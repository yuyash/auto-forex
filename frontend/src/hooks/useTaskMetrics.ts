/**
 * useTaskMetrics Hook
 *
 * Fetches all metrics for a task execution and provides both the full
 * time-series data (for charts) and the latest snapshot (for overview).
 */

import { useEffect, useCallback, useReducer, useRef } from 'react';
import type { TaskType } from '../types/common';
import {
  fetchLatestMetrics,
  fetchPaginatedMetrics,
  type MetricPoint,
  type MetricsPage,
} from '../utils/fetchMetrics';

export interface UseTaskMetricsOptions {
  taskId: string;
  taskType: TaskType;
  executionRunId?: string;
  /** Aggregation interval in minutes (default: 1) */
  interval?: number;
  /** RFC3339 lower-bound timestamp */
  since?: string;
  /** RFC3339 upper-bound timestamp */
  until?: string;
  enabled?: boolean;
  /** Fetch the full chart series. Keep false outside the metrics tab. */
  fetchSeries?: boolean;
  /** Metric keys needed by the current view. Reduces payload size. */
  metricKeys?: string[];
  /** Polling interval in ms (0 = no polling) */
  pollingInterval?: number;
}

export interface UseTaskMetricsResult {
  /** Full time-series data */
  data: MetricPoint[];
  /** Latest metric snapshot (last element of data) */
  latest: MetricPoint | null;
  dataSource: string;
  resumeCursorTimestamp: string | null;
  consistencyWarnings: Array<Record<string, unknown>>;
  isLoading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

interface MetricsState {
  data: MetricPoint[];
  latest: MetricPoint | null;
  dataSource: string;
  resumeCursorTimestamp: string | null;
  consistencyWarnings: Array<Record<string, unknown>>;
  isLoading: boolean;
  error: Error | null;
}

type MetricsAction =
  | { type: 'loading' }
  | { type: 'failed'; error: Error }
  | {
      type: 'latestLoaded';
      latest: MetricPoint | null;
      dataSource: string;
      resumeCursorTimestamp: string | null;
      consistencyWarnings: Array<Record<string, unknown>>;
    }
  | {
      type: 'seriesLoaded';
      data: MetricPoint[];
      latest: MetricPoint | null;
      dataSource: string;
      resumeCursorTimestamp: string | null;
      consistencyWarnings: Array<Record<string, unknown>>;
    }
  | { type: 'clearSeries' }
  | { type: 'loaded' };

const initialMetricsState: MetricsState = {
  data: [],
  latest: null,
  dataSource: 'unknown',
  resumeCursorTimestamp: null,
  consistencyWarnings: [],
  isLoading: false,
  error: null,
};

const MAX_RENDERED_METRIC_POINTS = 5000;

function mergeMetricPoints(points: MetricPoint[]): MetricPoint[] {
  const deduped = new Map<number, MetricPoint>();
  for (const point of points) {
    deduped.set(point.t, point);
  }
  return Array.from(deduped.values()).sort((a, b) => a.t - b.t);
}

function trimMetricPoints(points: MetricPoint[]): MetricPoint[] {
  if (points.length <= MAX_RENDERED_METRIC_POINTS) return points;
  return points.slice(points.length - MAX_RENDERED_METRIC_POINTS);
}

function timestampToSeconds(timestamp: string | undefined): number | null {
  if (!timestamp) return null;
  const ms = Date.parse(timestamp);
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

function metricsReducer(
  state: MetricsState,
  action: MetricsAction
): MetricsState {
  switch (action.type) {
    case 'loading':
      if (state.isLoading && state.error == null) return state;
      return { ...state, isLoading: true, error: null };
    case 'failed':
      return { ...state, isLoading: false, error: action.error };
    case 'latestLoaded':
      return {
        ...state,
        latest: action.latest,
        dataSource: action.dataSource,
        resumeCursorTimestamp: action.resumeCursorTimestamp,
        consistencyWarnings: action.consistencyWarnings,
      };
    case 'seriesLoaded':
      return {
        ...state,
        data: action.data,
        latest: action.latest,
        dataSource: action.dataSource,
        resumeCursorTimestamp: action.resumeCursorTimestamp,
        consistencyWarnings: action.consistencyWarnings,
      };
    case 'clearSeries':
      if (state.data.length === 0) return state;
      return { ...state, data: [] };
    case 'loaded':
      if (!state.isLoading) return state;
      return { ...state, isLoading: false };
    default:
      return state;
  }
}

export function useTaskMetrics({
  taskId,
  taskType,
  executionRunId,
  interval = 1,
  since,
  until,
  enabled = true,
  fetchSeries = true,
  metricKeys,
  pollingInterval = 0,
}: UseTaskMetricsOptions): UseTaskMetricsResult {
  const [state, dispatch] = useReducer(metricsReducer, initialMetricsState);
  const mountedRef = useRef(true);
  const latestTimestampRef = useRef<string | undefined>(undefined);
  const inFlightRef = useRef(false);
  const dataRef = useRef<MetricPoint[]>([]);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    dataRef.current = state.data;
  }, [state.data]);

  const fetchData = useCallback(
    async (incremental = false) => {
      if (!taskId || !enabled) return;
      if (inFlightRef.current) return;
      const requestSeq = ++requestSeqRef.current;
      inFlightRef.current = true;
      if (!incremental) {
        dispatch({ type: 'loading' });
      }
      try {
        if (!fetchSeries) {
          const latestPage = await fetchLatestMetrics({
            taskId,
            taskType,
            executionRunId,
            metricKeys,
          });
          if (mountedRef.current && requestSeq === requestSeqRef.current) {
            dispatch({
              type: 'latestLoaded',
              latest: latestPage.result,
              dataSource: latestPage.data_source,
              resumeCursorTimestamp: latestPage.resume_cursor_timestamp,
              consistencyWarnings: latestPage.consistency_warnings,
            });
          }
          return;
        }

        const effectiveSince =
          incremental && !since ? latestTimestampRef.current : since;
        const previousLatestSeconds = timestampToSeconds(
          latestTimestampRef.current
        );
        const publishSeries = (
          points: MetricPoint[],
          pageMeta: Pick<
            MetricsPage,
            'data_source' | 'resume_cursor_timestamp' | 'consistency_warnings'
          >
        ) => {
          if (!mountedRef.current || requestSeq !== requestSeqRef.current) {
            return;
          }
          if (
            incremental &&
            previousLatestSeconds != null &&
            !points.some((point) => point.t > previousLatestSeconds)
          ) {
            return;
          }
          const nextData = trimMetricPoints(mergeMetricPoints(points));
          const nextLatest =
            nextData.length > 0 ? nextData[nextData.length - 1] : null;
          dataRef.current = nextData;
          latestTimestampRef.current = nextLatest
            ? new Date(nextLatest.t * 1000).toISOString()
            : latestTimestampRef.current;
          dispatch({
            type: 'seriesLoaded',
            data: nextData,
            latest: nextLatest,
            dataSource: pageMeta.data_source,
            resumeCursorTimestamp: pageMeta.resume_cursor_timestamp,
            consistencyWarnings: pageMeta.consistency_warnings,
          });
        };
        const page = await fetchPaginatedMetrics({
          taskId,
          taskType,
          executionRunId,
          interval: interval >= 1 ? interval : undefined,
          since: effectiveSince,
          until,
          metricKeys,
          pageSize: 500,
          maxPages: incremental ? 2 : 4,
          existingResults: incremental ? dataRef.current : undefined,
          onProgress: ({ accumulatedResults, response }) => {
            publishSeries(accumulatedResults, response);
          },
        });
        publishSeries(page.results, page);
      } catch (err) {
        if (mountedRef.current && requestSeq === requestSeqRef.current) {
          dispatch({
            type: 'failed',
            error: err instanceof Error ? err : new Error(String(err)),
          });
        }
      } finally {
        if (mountedRef.current && requestSeq === requestSeqRef.current) {
          dispatch({ type: 'loaded' });
        }
        inFlightRef.current = false;
      }
    },
    [
      taskId,
      taskType,
      executionRunId,
      interval,
      since,
      until,
      enabled,
      fetchSeries,
      metricKeys,
    ]
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestSeqRef.current += 1;
    };
  }, []);

  useEffect(() => {
    latestTimestampRef.current = undefined;
    if (!fetchSeries) {
      dispatch({ type: 'clearSeries' });
    }
    fetchData();
  }, [fetchData, fetchSeries]);

  useEffect(() => {
    if (!pollingInterval || pollingInterval <= 0 || !enabled) return;
    const id = setInterval(() => fetchData(true), pollingInterval);
    return () => clearInterval(id);
  }, [pollingInterval, fetchData, enabled]);

  return {
    data: state.data,
    latest: state.latest,
    dataSource: state.dataSource,
    resumeCursorTimestamp: state.resumeCursorTimestamp,
    consistencyWarnings: state.consistencyWarnings,
    isLoading: state.isLoading,
    error: state.error,
    refresh: fetchData,
  };
}
