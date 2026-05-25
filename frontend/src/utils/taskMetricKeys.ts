const BASE_METRIC_KEYS = [
  'current_balance',
  'total_pnl',
  'realized_pnl',
  'unrealized_pnl',
  'total_return',
  'margin_ratio',
  'live_tick_latency_seconds',
  'oanda_tick_publish_latency_seconds',
  'trading_tick_receive_latency_seconds',
  'oanda_order_response_ms',
  'oanda_order_response_avg_ms',
  'oanda_order_response_max_ms',
  'open_positions',
  'closed_positions',
  'total_trades',
  'win_rate',
  'winning_trades',
  'losing_trades',
  'ticks_processed',
  'ticks_per_second',
  'current_base_units',
] as const;

const SNOWBALL_METRIC_KEYS = [
  ...BASE_METRIC_KEYS,
  'snowball_allow_new_positions',
  'snowball_allow_rebuilds',
  'snowball_add_block_reason',
  'snowball_rebuild_block_reason',
  'snowball_trend_blocked_directions',
  'snowball_adaptive_counter_interval_multiplier',
  'snowball_adaptive_trend_interval_multiplier',
  'snowball_volatility_guard_current_pips',
  'snowball_volatility_guard_baseline_current_pips',
  'snowball_volatility_guard_cooldown_remaining_minutes',
  'snowball_trend_guard_deviation_pips',
  'snowball_trend_guard_slope_pips',
  'snowball_volatility_guard_source',
  'snowball_volatility_guard_candle_granularity',
  'snowball_adaptive_counter_interval_source',
  'snowball_adaptive_counter_interval_candle_granularity',
  'snowball_adaptive_trend_interval_source',
  'snowball_adaptive_trend_interval_candle_granularity',
  'snowball_trend_guard_candle_granularity',
] as const;

const SNOWBALL_NET_METRIC_KEYS = [
  ...BASE_METRIC_KEYS,
  'snowball_net_net_units',
  'snowball_net_average_price',
  'snowball_net_next_add_price',
  'snowball_net_current_price',
  'snowball_net_target_price',
  'snowball_net_pips_from_average',
  'snowball_net_loss_cut_threshold_pips',
  'snowball_net_margin_ratio_pct',
  'snowball_net_margin_reduce_threshold_pct',
  'snowball_net_margin_reduce_target_pct',
  'snowball_net_emergency_threshold_pct',
  'snowball_net_add_count',
  'snowball_net_exposure_pct',
] as const;

function uniqueMetricKeys(keys: readonly string[]): string[] {
  return Array.from(new Set(keys));
}

const BASE_METRIC_KEY_LIST = uniqueMetricKeys(BASE_METRIC_KEYS);
const SNOWBALL_METRIC_KEY_LIST = uniqueMetricKeys(SNOWBALL_METRIC_KEYS);
const SNOWBALL_NET_METRIC_KEY_LIST = uniqueMetricKeys(SNOWBALL_NET_METRIC_KEYS);

export function metricKeysForStrategy(strategyType?: string | null): string[] {
  if (strategyType === 'snowball') {
    return SNOWBALL_METRIC_KEY_LIST;
  }
  if (strategyType === 'snowball_net') {
    return SNOWBALL_NET_METRIC_KEY_LIST;
  }
  return BASE_METRIC_KEY_LIST;
}
