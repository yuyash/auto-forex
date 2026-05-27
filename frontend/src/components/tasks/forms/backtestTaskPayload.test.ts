import { describe, expect, it } from 'vitest';
import {
  buildBacktestTaskCreatePayload,
  buildBacktestTaskUpdatePayload,
} from './backtestTaskPayload';
import { DataSource } from '../../../types/common';

const baseFormData = {
  config_id: '9f2d791a-9f31-4f8e-ae7a-c49f3cc8a915',
  name: 'Backtest',
  description: 'Regression run',
  start_time: '2026-01-01T00:00:00.000Z',
  end_time: '2026-01-02T00:00:00.000Z',
  initial_balance: 10000,
  account_currency: 'JPY',
  display_currency: 'USD',
  commission_per_trade: 1.25,
  pip_size: 0.01,
  instrument: 'USD_JPY',
  tick_granularity: 'tick',
  tick_window_value_mode: 'last',
  sell_at_completion: true,
  hedging_enabled: false,
  drain_duration_hours: 4,
  market_idle_pre_close_minutes: 30,
  market_idle_resume_delay_minutes: 15,
  market_close_enabled: true,
  market_close_weekday: 4,
  market_close_hour_utc: 21,
  market_open_weekday: 6,
  market_open_hour_utc: 21,
  max_tick_gap_hours: 120,
  backtest_tick_batch_size: 5000,
  spread_filter_enabled: true,
  max_spread_pips: 12.5,
  oanda_candle_filter_enabled: true,
  oanda_candle_filter_account: 7,
  oanda_candle_filter_granularity: 'M1',
  oanda_candle_filter_tolerance_pips: 5,
};

function omitSellAtCompletion(data: typeof baseFormData) {
  const copy: Partial<typeof baseFormData> = { ...data };
  delete copy.sell_at_completion;
  return copy as Omit<typeof baseFormData, 'sell_at_completion'>;
}

describe('backtest task payload builders', () => {
  it('maps create form data to the backend payload', () => {
    expect(buildBacktestTaskCreatePayload(baseFormData)).toMatchObject({
      config: baseFormData.config_id,
      name: baseFormData.name,
      description: baseFormData.description,
      data_source: DataSource.POSTGRESQL,
      initial_balance: 10000,
      account_currency: 'JPY',
      display_currency: 'USD',
      commission_per_trade: 1.25,
      pip_size: 0.01,
      sell_on_stop: true,
      hedging_enabled: false,
      in_memory_mode: false,
      market_close_enabled: true,
      max_tick_gap_hours: 120,
      backtest_tick_batch_size: 5000,
      spread_filter_enabled: true,
      max_spread_pips: 12.5,
      oanda_candle_filter_enabled: true,
      oanda_candle_filter_account: 7,
      oanda_candle_filter_granularity: 'M1',
      oanda_candle_filter_tolerance_pips: 5,
    });
  });

  it('defaults close-at-completion to disabled when omitted', () => {
    const formData = omitSellAtCompletion(baseFormData);

    expect(buildBacktestTaskCreatePayload(formData)).toMatchObject({
      sell_on_stop: false,
    });
    expect(buildBacktestTaskUpdatePayload(formData)).toMatchObject({
      sell_on_stop: false,
    });
  });

  it('preserves an explicit disabled close-at-completion value', () => {
    const formData = { ...baseFormData, sell_at_completion: false };

    expect(buildBacktestTaskCreatePayload(formData)).toMatchObject({
      sell_on_stop: false,
    });
    expect(buildBacktestTaskUpdatePayload(formData)).toMatchObject({
      sell_on_stop: false,
    });
  });

  it('preserves debug options for creates when provided', () => {
    expect(
      buildBacktestTaskCreatePayload(baseFormData, { tracemalloc: true })
    ).toMatchObject({
      debug_options: { tracemalloc: true },
    });
  });

  it('maps initial Snowball positions when enabled', () => {
    const initial_position_cycles = [
      {
        direction: 'long' as const,
        positions: [
          {
            layer_number: 1,
            retracement_count: 0,
            units: 1000,
            entry_price: '150.1',
            planned_exit_price: '150.6',
            stop_loss_price: '149.8',
            status: 'open' as const,
          },
        ],
      },
    ];

    expect(
      buildBacktestTaskCreatePayload({
        ...baseFormData,
        initial_positions_enabled: true,
        initial_position_cycles,
      })
    ).toMatchObject({
      initial_positions_enabled: true,
      initial_position_cycles,
    });
  });

  it('clears initial positions when in-memory mode is enabled', () => {
    const initial_position_cycles = [
      {
        direction: 'long' as const,
        positions: [
          {
            layer_number: 1,
            retracement_count: 0,
            units: 1000,
            entry_price: '150.1',
            status: 'open' as const,
          },
        ],
      },
    ];

    expect(
      buildBacktestTaskCreatePayload({
        ...baseFormData,
        in_memory_mode: true,
        initial_positions_enabled: true,
        initial_position_cycles,
      })
    ).toMatchObject({
      in_memory_mode: true,
      initial_positions_enabled: false,
      initial_position_cycles: [],
    });
  });

  it('stringifies decimal fields and preserves debug options for updates', () => {
    expect(
      buildBacktestTaskUpdatePayload(baseFormData, { tracemalloc: true })
    ).toMatchObject({
      config: baseFormData.config_id,
      data_source: DataSource.POSTGRESQL,
      initial_balance: '10000',
      account_currency: 'JPY',
      display_currency: 'USD',
      commission_per_trade: '1.25',
      pip_size: '0.01',
      max_spread_pips: '12.5',
      oanda_candle_filter_tolerance_pips: '5',
      sell_on_stop: true,
      debug_options: { tracemalloc: true },
    });
  });

  it('clears the candle account when OANDA candle validation is disabled', () => {
    expect(
      buildBacktestTaskCreatePayload({
        ...baseFormData,
        oanda_candle_filter_enabled: false,
        oanda_candle_filter_account: 7,
      })
    ).toMatchObject({
      oanda_candle_filter_enabled: false,
      oanda_candle_filter_account: null,
    });
  });
});
