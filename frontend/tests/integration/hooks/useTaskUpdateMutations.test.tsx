import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryClient } from '../../../src/config/reactQuery';
import { queryKeys } from '../../../src/config/reactQuery';
import { useUpdateBacktestTask } from '../../../src/hooks/useBacktestTaskMutations';
import { useUpdateTradingTask } from '../../../src/hooks/useTradingTaskMutations';
import { backtestTasksApi, tradingTasksApi } from '../../../src/services/api';
import { TaskStatus } from '../../../src/types/common';
import type { BacktestTask, TradingTask } from '../../../src/types';

vi.mock('../../../src/services/api', () => ({
  backtestTasksApi: {
    partialUpdate: vi.fn(),
    get: vi.fn(),
  },
  tradingTasksApi: {
    partialUpdate: vi.fn(),
    get: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function buildTradingTask(overrides?: Partial<TradingTask>): TradingTask {
  return {
    id: 'task-1',
    user_id: 1,
    config_id: 'config-1',
    config_name: 'Original Config',
    strategy_type: 'snowball',
    instrument: 'USD_JPY',
    account_id: 'account-1',
    account_name: 'Practice',
    account_type: 'practice',
    name: 'Task',
    description: 'desc',
    status: TaskStatus.CREATED,
    sell_on_stop: false,
    dry_run: false,
    hedging_enabled: false,
    created_at: '2026-03-22T00:00:00Z',
    updated_at: '2026-03-22T00:00:00Z',
    ...overrides,
  };
}

function buildBacktestTask(overrides?: Partial<BacktestTask>): BacktestTask {
  return {
    id: 'task-2',
    user_id: 1,
    config_id: 'config-1',
    config_name: 'Original Config',
    strategy_type: 'snowball',
    name: 'Backtest Task',
    description: 'desc',
    data_source: 'postgresql',
    start_time: '2026-03-22T00:00:00Z',
    end_time: '2026-03-22T01:00:00Z',
    initial_balance: '10000',
    commission_per_trade: '0',
    instrument: 'USD_JPY',
    status: TaskStatus.CREATED,
    sell_at_completion: false,
    hedging_enabled: false,
    created_at: '2026-03-22T00:00:00Z',
    updated_at: '2026-03-22T00:00:00Z',
    ...overrides,
  };
}

describe('task update mutations', () => {
  beforeEach(() => {
    queryClient.clear();
    vi.clearAllMocks();
  });

  it('refreshes trading task cache from the full task detail after update', async () => {
    vi.mocked(tradingTasksApi.partialUpdate).mockResolvedValueOnce(
      buildTradingTask({
        config_id: 'config-2',
        config_name: 'Original Config',
      }) as never
    );
    vi.mocked(tradingTasksApi.get).mockResolvedValueOnce(
      buildTradingTask({
        config_id: 'config-2',
        config_name: 'Updated Config',
      }) as never
    );

    const { result } = renderHook(() => useUpdateTradingTask(), { wrapper });

    await act(async () => {
      await result.current.mutate({
        id: 'task-1',
        data: { config: 'config-2' },
      });
    });

    await waitFor(() => {
      expect(tradingTasksApi.get).toHaveBeenCalledWith('task-1');
      expect(
        queryClient.getQueryData<TradingTask>(
          queryKeys.tradingTasks.detail('task-1')
        )
      ).toEqual(expect.objectContaining({ config_name: 'Updated Config' }));
    });
  });

  it('refreshes backtest task cache from the full task detail after update', async () => {
    vi.mocked(backtestTasksApi.partialUpdate).mockResolvedValueOnce(
      buildBacktestTask({
        config_id: 'config-2',
        config_name: 'Original Config',
        tick_granularity: 'tick',
      }) as never
    );
    vi.mocked(backtestTasksApi.get).mockResolvedValueOnce(
      buildBacktestTask({
        config_id: 'config-2',
        config_name: 'Updated Config',
        tick_granularity: 'tick',
      }) as never
    );

    const { result } = renderHook(() => useUpdateBacktestTask(), { wrapper });

    await act(async () => {
      await result.current.mutate({
        id: 'task-2',
        data: { config: 'config-2', tick_granularity: 'tick' },
      });
    });

    await waitFor(() => {
      expect(backtestTasksApi.get).toHaveBeenCalledWith('task-2');
      expect(
        queryClient.getQueryData<BacktestTask>(
          queryKeys.backtestTasks.detail('task-2')
        )
      ).toEqual(
        expect.objectContaining({
          config_name: 'Updated Config',
          tick_granularity: 'tick',
        })
      );
    });
  });
});
