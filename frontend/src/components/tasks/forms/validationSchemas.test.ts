import { describe, expect, it } from 'vitest';
import { DataSource } from '../../../types/common';
import { backtestTaskSchema } from './validationSchemas';

const baseBacktestTask = {
  config_id: '9f2d791a-9f31-4f8e-ae7a-c49f3cc8a915',
  name: 'Backtest',
  data_source: DataSource.POSTGRESQL,
  start_time: '2026-01-01T00:00:00.000Z',
  end_time: '2026-01-02T00:00:00.000Z',
  initial_balance: 10000,
  account_currency: 'JPY',
  display_currency: 'USD',
  instrument: 'USD_JPY',
  tick_granularity: 'tick',
  tick_window_value_mode: 'last',
};

describe('backtestTaskSchema', () => {
  it('accepts recurring MM-DD holiday exclusions', () => {
    const result = backtestTaskSchema.safeParse({
      ...baseBacktestTask,
      excluded_dates: ['12-25', '01-01', '2026-02-11'],
    });

    expect(result.success).toBe(true);
    expect(result.data?.excluded_dates).toEqual([
      '12-25',
      '01-01',
      '2026-02-11',
    ]);
  });

  it('rejects malformed holiday exclusions', () => {
    const result = backtestTaskSchema.safeParse({
      ...baseBacktestTask,
      excluded_dates: ['2026/12/25'],
    });

    expect(result.success).toBe(false);
  });

  it('accepts closed datetime windows with timezone', () => {
    const result = backtestTaskSchema.safeParse({
      ...baseBacktestTask,
      excluded_dates: [
        {
          start: '2024-12-24T21:59:00.000Z',
          end: '2024-12-25T22:05:00.000Z',
          timezone: 'America/New_York',
        },
      ],
    });

    expect(result.success).toBe(true);
    expect(result.data?.excluded_dates).toEqual([
      {
        start: '2024-12-24T21:59:00.000Z',
        end: '2024-12-25T22:05:00.000Z',
        timezone: 'America/New_York',
      },
    ]);
  });

  it('rejects closed datetime windows with end before start', () => {
    const result = backtestTaskSchema.safeParse({
      ...baseBacktestTask,
      excluded_dates: [
        {
          start: '2024-12-25T22:05:00.000Z',
          end: '2024-12-24T21:59:00.000Z',
          timezone: 'America/New_York',
        },
      ],
    });

    expect(result.success).toBe(false);
  });

  it('allows in-memory mode without initial-position cycles', () => {
    const result = backtestTaskSchema.safeParse({
      ...baseBacktestTask,
      in_memory_mode: true,
      initial_positions_enabled: true,
      initial_position_cycles: [],
    });

    expect(result.success).toBe(true);
  });

  it('requires a max spread when the spread filter is enabled', () => {
    const result = backtestTaskSchema.safeParse({
      ...baseBacktestTask,
      spread_filter_enabled: true,
      max_spread_pips: undefined,
    });

    expect(result.success).toBe(false);
  });

  it('requires an account when OANDA candle validation is enabled', () => {
    const result = backtestTaskSchema.safeParse({
      ...baseBacktestTask,
      oanda_candle_filter_enabled: true,
      oanda_candle_filter_granularity: 'M1',
      oanda_candle_filter_tolerance_pips: 5,
    });

    expect(result.success).toBe(false);
  });
});
