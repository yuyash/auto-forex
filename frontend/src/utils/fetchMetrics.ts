/**
 * Fetch paginated metrics for replay overlay charts.
 */

import { api } from '../api/apiClient';
import { TaskType } from '../types/common';

export interface MetricPoint {
  /** Unix timestamp (seconds) */
  t: number;
  /** Strategy-specific metrics JSON */
  metrics: Record<string, unknown>;
}

export interface MetricsPage {
  count: number;
  count_is_exact?: boolean;
  next: string | null;
  previous: string | null;
  data_source: string;
  resume_cursor_timestamp: string | null;
  consistency_warnings: Array<Record<string, unknown>>;
  results: MetricPoint[];
}

export interface MetricsPageProgress {
  page: number;
  pageResults: MetricPoint[];
  accumulatedResults: MetricPoint[];
  response: MetricsPage;
  hasMore: boolean;
}

export type MetricsPeriod = 'day' | 'week' | 'month' | 'year';

export interface PeriodicTradeMetricPoint {
  t: number;
  timestamp: string;
  label: string;
  tp_profit: string;
  sl_loss: string;
  open_positions: number;
  tp_closes: number;
  sl_closes: number;
  rebuild_opens: number;
}

export interface PeriodicReturnMetricPoint {
  t: number;
  timestamp: string;
  label: string;
  period_return: string;
}

export interface PeriodicTradeMetricsResponse {
  execution_id: string | null;
  strategy_type: string;
  instrument: string | null;
  currency: string | null;
  timezone: string;
  periods: Record<MetricsPeriod, PeriodicTradeMetricPoint[]>;
  returns: Record<MetricsPeriod, PeriodicReturnMetricPoint[]>;
}

export interface LatestMetricsResponse {
  execution_id?: string | null;
  strategy_type?: string;
  instrument?: string | null;
  data_source: string;
  resume_cursor_timestamp: string | null;
  consistency_warnings: Array<Record<string, unknown>>;
  result: MetricPoint | null;
}

export function intervalToGranularity(interval?: number): string | undefined {
  if (interval == null || !Number.isFinite(interval) || interval < 1) {
    return undefined;
  }
  return `M${Math.trunc(interval)}`;
}

function buildTaskPrefix(taskType: TaskType): string {
  return taskType === TaskType.BACKTEST
    ? '/api/trading/tasks/backtest'
    : '/api/trading/tasks/trading';
}

function normalizeMetricPoint(point: Partial<MetricPoint>): MetricPoint {
  let metrics: Record<string, unknown> = {};
  if (typeof point.metrics === 'string') {
    try {
      const parsed = JSON.parse(point.metrics);
      metrics =
        parsed && typeof parsed === 'object'
          ? (parsed as Record<string, unknown>)
          : {};
    } catch {
      metrics = {};
    }
  } else if (point.metrics && typeof point.metrics === 'object') {
    metrics = point.metrics;
  }

  return {
    t: Number(point.t ?? 0),
    metrics,
  };
}

export async function fetchMetrics(opts: {
  taskId: string;
  taskType: TaskType;
  since?: string;
  until?: string;
  executionRunId?: string;
  interval?: number;
  granularity?: string;
  metricKeys?: string[];
  page?: number;
  pageSize?: number;
}): Promise<MetricsPage> {
  const prefix = buildTaskPrefix(opts.taskType);

  const searchParams = new URLSearchParams();
  if (opts.since) searchParams.set('since', opts.since);
  if (opts.until) searchParams.set('until', opts.until);
  if (opts.executionRunId != null)
    searchParams.set('execution_id', String(opts.executionRunId));
  const granularity = opts.granularity ?? intervalToGranularity(opts.interval);
  if (granularity) searchParams.set('granularity', granularity);
  if (opts.metricKeys?.length)
    searchParams.set('metric_keys', opts.metricKeys.join(','));
  if (opts.page) searchParams.set('page', String(opts.page));
  if (opts.pageSize) searchParams.set('page_size', String(opts.pageSize));

  const body = await api.get<Partial<MetricsPage>>(
    `${prefix}/${opts.taskId}/strategy/metrics/`,
    Object.fromEntries(searchParams.entries())
  );

  const results = (body.results ?? []).map((point) =>
    normalizeMetricPoint(point)
  );

  return {
    count: body.count ?? 0,
    count_is_exact:
      typeof body.count_is_exact === 'boolean' ? body.count_is_exact : true,
    next: body.next ?? null,
    previous: body.previous ?? null,
    data_source:
      typeof body.data_source === 'string' ? body.data_source : 'unknown',
    resume_cursor_timestamp:
      typeof body.resume_cursor_timestamp === 'string'
        ? body.resume_cursor_timestamp
        : null,
    consistency_warnings: Array.isArray(body.consistency_warnings)
      ? (body.consistency_warnings as Array<Record<string, unknown>>)
      : [],
    results,
  };
}

export async function fetchLatestMetrics(opts: {
  taskId: string;
  taskType: TaskType;
  executionRunId?: string;
}): Promise<LatestMetricsResponse> {
  const body = await api.get<Partial<LatestMetricsResponse>>(
    `${buildTaskPrefix(opts.taskType)}/${opts.taskId}/strategy/metrics/latest/`,
    {
      ...(opts.executionRunId != null
        ? { execution_id: String(opts.executionRunId) }
        : {}),
    }
  );
  const result = body.result;

  return {
    execution_id:
      typeof body.execution_id === 'string' ? body.execution_id : null,
    strategy_type:
      typeof body.strategy_type === 'string' ? body.strategy_type : undefined,
    instrument: typeof body.instrument === 'string' ? body.instrument : null,
    data_source:
      typeof body.data_source === 'string' ? body.data_source : 'unknown',
    resume_cursor_timestamp:
      typeof body.resume_cursor_timestamp === 'string'
        ? body.resume_cursor_timestamp
        : null,
    consistency_warnings: Array.isArray(body.consistency_warnings)
      ? (body.consistency_warnings as Array<Record<string, unknown>>)
      : [],
    result: result ? normalizeMetricPoint(result) : null,
  };
}

export async function fetchPaginatedMetrics(opts: {
  taskId: string;
  taskType: TaskType;
  since?: string;
  until?: string;
  executionRunId?: string;
  interval?: number;
  granularity?: string;
  metricKeys?: string[];
  pageSize?: number;
  /** Maximum number of pages to fetch (default: unlimited). */
  maxPages?: number;
  /** Existing points to merge with fetched pages. */
  existingResults?: MetricPoint[];
  /** Called after each fetched page so charts can render progressively. */
  onProgress?: (progress: MetricsPageProgress) => void;
}): Promise<MetricsPage> {
  const {
    pageSize: requestedPageSize,
    maxPages: requestedMaxPages,
    existingResults,
    onProgress,
    ...fetchOpts
  } = opts;
  const pageSize = requestedPageSize ?? 250;
  const maxPages = requestedMaxPages ?? Infinity;
  const results: MetricPoint[] = existingResults ? [...existingResults] : [];
  let page = 1;
  let dataSource = 'unknown';
  let resumeCursorTimestamp: string | null = null;
  let consistencyWarnings: Array<Record<string, unknown>> = [];
  let lastNext: string | null = null;
  let lastPrevious: string | null = null;

  while (page <= maxPages) {
    const response = await fetchMetrics({
      ...fetchOpts,
      page,
      pageSize,
    });
    dataSource = response.data_source;
    resumeCursorTimestamp = response.resume_cursor_timestamp;
    consistencyWarnings = response.consistency_warnings;
    lastNext = response.next;
    lastPrevious = response.previous;
    results.push(...response.results);
    onProgress?.({
      page,
      pageResults: response.results,
      accumulatedResults: [...results],
      response,
      hasMore: Boolean(response.next),
    });
    if (!response.next) {
      return {
        count: results.length,
        count_is_exact: true,
        next: null,
        previous: null,
        data_source: dataSource,
        resume_cursor_timestamp: resumeCursorTimestamp,
        consistency_warnings: consistencyWarnings,
        results,
      };
    }
    page += 1;
  }
  return {
    count: results.length,
    count_is_exact: false,
    next: lastNext,
    previous: lastPrevious,
    data_source: dataSource,
    resume_cursor_timestamp: resumeCursorTimestamp,
    consistency_warnings: consistencyWarnings,
    results,
  };
}

/**
 * A single forced-liquidation (loss-cut) trade used to overlay vertical
 * reference lines on metric and strategy charts.
 */
export interface LossCutEvent {
  /** Trade id. */
  id: string;
  /** ISO 8601 timestamp of the loss-cut. */
  timestamp: string;
  /** Unix time (seconds). */
  time: number;
  /** Absolute units closed by this loss-cut. */
  units: number;
  /** Position direction before the close (long/short). */
  direction: string | null;
  /** Fill price of the close, if known. */
  price: number | null;
  /** Raw strategy description for tooltips. */
  description: string;
  /** Position id closed by this loss-cut, if linked. */
  position_id: string | null;
}

export interface LossCutEventsResponse {
  execution_id: string | null;
  strategy_type: string;
  instrument: string | null;
  count: number;
  results: LossCutEvent[];
}

/**
 * Fetch every loss-cut event for an execution.
 *
 * The backend returns ordered-by-timestamp-asc markers keyed off the
 * ``close_position`` trade log.  We keep this separate from the
 * paginated metrics stream so charts can overlay vertical reference
 * lines without paying the per-tick metric cost.
 */
export async function fetchLossCutEvents(opts: {
  taskId: string;
  taskType: TaskType;
  executionRunId?: string;
  since?: string;
  until?: string;
}): Promise<LossCutEventsResponse> {
  const params: Record<string, string> = {};
  if (opts.executionRunId != null)
    params.execution_id = String(opts.executionRunId);
  if (opts.since) params.since = opts.since;
  if (opts.until) params.until = opts.until;

  const body = await api.get<Partial<LossCutEventsResponse>>(
    `${buildTaskPrefix(opts.taskType)}/${opts.taskId}/strategy/loss-cut-events/`,
    params
  );

  const results: LossCutEvent[] = Array.isArray(body.results)
    ? body.results.map((event) => ({
        id: String(event?.id ?? ''),
        timestamp: String(event?.timestamp ?? ''),
        time: Number(event?.time ?? 0),
        units: Number(event?.units ?? 0),
        direction:
          typeof event?.direction === 'string' ? event.direction : null,
        price:
          event?.price != null && Number.isFinite(Number(event.price))
            ? Number(event.price)
            : null,
        description:
          typeof event?.description === 'string' ? event.description : '',
        position_id:
          typeof event?.position_id === 'string' ? event.position_id : null,
      }))
    : [];

  return {
    execution_id:
      typeof body.execution_id === 'string' ? body.execution_id : null,
    strategy_type:
      typeof body.strategy_type === 'string' ? body.strategy_type : '',
    instrument: typeof body.instrument === 'string' ? body.instrument : null,
    count: Number(body.count ?? results.length),
    results,
  };
}
