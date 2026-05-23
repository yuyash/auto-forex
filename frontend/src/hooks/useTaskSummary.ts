/**
 * Hook for fetching task summary from the backend API.
 *
 * Returns comprehensive task summary grouped into logical sections:
 * - pnl: realized/unrealized PnL
 * - counts: trade/position counts
 * - execution: balance, ticks processed
 * - tick: last tick prices (bid, ask, mid) with timestamp
 * - task: status, timing, progress
 *
 * Supports optional polling for real-time updates.
 */

import type { TaskType } from '../types/common';
import type { CurrencyConversionContext } from '../types/money';
import { refreshTaskSummary } from './taskResourceCache';
import { createTaskSummaryQuery } from './taskResourceQueries';
import { usePollingPolicy } from './usePollingPolicy';
import { usePolledTaskResource } from './useTaskCollections';

export interface TickInfo {
  timestamp: string | null;
  bid: number | null;
  ask: number | null;
  mid: number | null;
}

export interface TickDeliveryInfo {
  status: string | null;
  tickTimestamp: string | null;
  observedAt: string | null;
  ageSeconds: number | null;
  maxAgeSeconds: number | null;
  message: string | null;
}

export interface PnlInfo {
  realized: number;
  unrealized: number;
  currency: string | null;
  realizedMoney: MoneyInfo | null;
  unrealizedMoney: MoneyInfo | null;
  totalMoney: MoneyInfo | null;
  realizedDisplayMoney: MoneyInfo | null;
  unrealizedDisplayMoney: MoneyInfo | null;
  totalDisplayMoney: MoneyInfo | null;
  displayConversionContext: CurrencyConversionContext | null;
}

export interface MoneyInfo {
  amount: string;
  currency: string;
}

export interface CountsInfo {
  totalTrades: number;
  openPositions: number;
  closedPositions: number;
  openLongUnits: number;
  openShortUnits: number;
  winningTrades: number;
  losingTrades: number;
}

export interface ExecutionInfo {
  currentBalance: number | null;
  currentBalanceMoney: MoneyInfo | null;
  ticksProcessed: number;
  accountCurrency: string | null;
  currentBalanceCurrency: string | null;
  currentBalanceDisplay: number | null;
  currentBalanceDisplayMoney: MoneyInfo | null;
  currentBalanceDisplayConversionContext: CurrencyConversionContext | null;
  displayCurrency: string | null;
  resumeCursorTimestamp: string | null;
  marginRatio: number | null;
  currentAtr: number | null;
  recoveryStatus: string | null;
  recoveryWarnings: string[];
  recoveryBlockers: string[];
  reconciledAt: string | null;
  tickDelivery: TickDeliveryInfo | null;
}

export interface TaskInfo {
  status: string;
  startedAt: string | null;
  completedAt: string | null;
  errorMessage: string | null;
  errorCode: string | null;
  statusReasonCode: string | null;
  statusReasonMessage: string | null;
  stopReason: string | null;
  progress: number;
}

export interface WatermarkInfo {
  value: number | null;
  timestamp: string | null;
  sourceMetric?: string | null;
}

export interface ExecutionWatermarks {
  marginRatioMax: WatermarkInfo;
  baseUnitsMax: WatermarkInfo;
  openLongUnitsMax: WatermarkInfo;
  openShortUnitsMax: WatermarkInfo;
  realizedPnlMax: WatermarkInfo;
  unrealizedPnlMin: WatermarkInfo;
  openPositionsMax: WatermarkInfo;
  activeCyclesMax: WatermarkInfo;
}

export interface TaskSummary {
  timestamp: string | null;
  pnl: PnlInfo;
  counts: CountsInfo;
  execution: ExecutionInfo;
  tick: TickInfo;
  task: TaskInfo;
  watermarks?: ExecutionWatermarks;
}

export interface UseTaskSummaryOptions {
  polling?: boolean;
  interval?: number;
}

export interface UseTaskSummaryResult {
  data: TaskSummary;
  summary: TaskSummary;
  isLoading: boolean;
  error: Error | null;
  refresh: () => Promise<unknown>;
}

const INITIAL_SUMMARY: TaskSummary = {
  timestamp: null,
  pnl: {
    realized: 0,
    unrealized: 0,
    currency: null,
    realizedMoney: null,
    unrealizedMoney: null,
    totalMoney: null,
    realizedDisplayMoney: null,
    unrealizedDisplayMoney: null,
    totalDisplayMoney: null,
    displayConversionContext: null,
  },
  counts: {
    totalTrades: 0,
    openPositions: 0,
    closedPositions: 0,
    openLongUnits: 0,
    openShortUnits: 0,
    winningTrades: 0,
    losingTrades: 0,
  },
  execution: {
    currentBalance: null,
    currentBalanceMoney: null,
    ticksProcessed: 0,
    accountCurrency: null,
    currentBalanceCurrency: null,
    currentBalanceDisplay: null,
    currentBalanceDisplayMoney: null,
    currentBalanceDisplayConversionContext: null,
    displayCurrency: null,
    resumeCursorTimestamp: null,
    marginRatio: null,
    currentAtr: null,
    recoveryStatus: null,
    recoveryWarnings: [],
    recoveryBlockers: [],
    reconciledAt: null,
    tickDelivery: null,
  },
  tick: { timestamp: null, bid: null, ask: null, mid: null },
  task: {
    status: '',
    startedAt: null,
    completedAt: null,
    errorMessage: null,
    errorCode: null,
    statusReasonCode: null,
    statusReasonMessage: null,
    stopReason: null,
    progress: 0,
  },
  watermarks: {
    marginRatioMax: { value: null, timestamp: null },
    baseUnitsMax: { value: null, timestamp: null },
    openLongUnitsMax: { value: null, timestamp: null },
    openShortUnitsMax: { value: null, timestamp: null },
    realizedPnlMax: { value: null, timestamp: null },
    unrealizedPnlMin: { value: null, timestamp: null },
    openPositionsMax: { value: null, timestamp: null },
    activeCyclesMax: { value: null, timestamp: null },
  },
};

export function useTaskSummary(
  taskId: string,
  taskType: TaskType,
  executionRunId?: string,
  options: UseTaskSummaryOptions = {}
): UseTaskSummaryResult {
  const { polling = false, interval = 10_000 } = options;
  const pollingPolicy = usePollingPolicy({
    enabled: polling && Boolean(taskId),
    baseIntervalMs: interval,
  });
  const refresh = () => refreshTaskSummary(taskId, taskType, executionRunId);
  const resource = usePolledTaskResource(
    createTaskSummaryQuery(taskId, taskType, executionRunId, INITIAL_SUMMARY),
    refresh,
    {
      pollingEnabled: pollingPolicy.isActive,
      intervalMs: pollingPolicy.intervalMs,
    }
  );

  return {
    ...resource,
    data: resource.data ?? INITIAL_SUMMARY,
    summary: resource.data ?? INITIAL_SUMMARY,
  };
}
