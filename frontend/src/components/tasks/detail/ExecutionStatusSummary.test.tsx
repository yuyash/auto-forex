import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { TaskSummary } from '../../../hooks/useTaskSummary';
import { ExecutionStatusSummary } from './ExecutionStatusSummary';
import { ExecutionWatermarkSummary } from './ExecutionWatermarkSummary';

vi.mock('../../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { timezone: 'UTC', language: 'en' },
  }),
}));

const baseSummary: TaskSummary = {
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
    currentBalance: 10000,
    currentBalanceMoney: { amount: '10000', currency: 'JPY' },
    ticksProcessed: 0,
    accountCurrency: 'JPY',
    currentBalanceCurrency: 'JPY',
    currentBalanceDisplay: 67.89,
    currentBalanceDisplayMoney: { amount: '67.89', currency: 'USD' },
    currentBalanceDisplayConversionContext: null,
    displayCurrency: 'USD',
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

describe('ExecutionStatusSummary', () => {
  it('shows current balance only in the configured display currency', () => {
    render(
      <ExecutionStatusSummary
        taskNamespace="backtest"
        summary={baseSummary}
        pnlCurrency="USD"
      />
    );

    expect(screen.getByText('$ 67.89')).toBeInTheDocument();
    expect(screen.queryByText(/¥ 10,000/)).not.toBeInTheDocument();
  });

  it('shows the public status reason when one is available', () => {
    render(
      <ExecutionStatusSummary
        taskNamespace="backtest"
        summary={{
          ...baseSummary,
          task: {
            ...baseSummary.task,
            status: 'failed',
            statusReasonCode: 'snowball_net_emergency_margin',
            statusReasonMessage:
              'Emergency stop: margin closeout ratio reached 95%.',
          },
        }}
        pnlCurrency="JPY"
      />
    );

    expect(screen.getByText('Stop Reason')).toBeInTheDocument();
    expect(
      screen.getByText('Emergency stop: margin closeout ratio reached 95%.')
    ).toBeInTheDocument();
  });
});

describe('ExecutionWatermarkSummary', () => {
  it('shows configured watermark values', () => {
    const emptyWatermarks = baseSummary.watermarks ?? {
      marginRatioMax: { value: null, timestamp: null },
      baseUnitsMax: { value: null, timestamp: null },
      openLongUnitsMax: { value: null, timestamp: null },
      openShortUnitsMax: { value: null, timestamp: null },
      realizedPnlMax: { value: null, timestamp: null },
      unrealizedPnlMin: { value: null, timestamp: null },
      openPositionsMax: { value: null, timestamp: null },
      activeCyclesMax: { value: null, timestamp: null },
    };

    render(
      <ExecutionWatermarkSummary
        summary={{
          ...baseSummary,
          watermarks: {
            ...emptyWatermarks,
            marginRatioMax: {
              value: 0.08,
              timestamp: '2024-06-01T12:01:00Z',
            },
            openShortUnitsMax: {
              value: 1600,
              timestamp: '2024-06-01T12:01:00Z',
            },
            unrealizedPnlMin: {
              value: -35,
              timestamp: '2024-06-01T12:01:00Z',
            },
          },
        }}
        pnlCurrency="JPY"
      />
    );

    expect(screen.getByText('Watermarks')).toBeInTheDocument();
    expect(screen.getByText('Max Margin Closeout Ratio')).toBeInTheDocument();
    expect(screen.getByText('8.00%')).toBeInTheDocument();
    expect(screen.getByText('Max Open Short Size')).toBeInTheDocument();
    expect(screen.getByText('1,600')).toBeInTheDocument();
    expect(screen.getByText('Min Unrealized PnL')).toBeInTheDocument();
    expect(screen.getByText('-¥ 35')).toBeInTheDocument();
  });
});
