// Backtest Task types
import type { TaskActionPolicy, TaskStatus, DataSource } from './common';
import type { ExecutionSummary } from './execution';
import type { TaskInstrumentContext } from './instrument';
import type {
  CurrencyConversionContext,
  MoneyAmount,
  TaskMoneyContext,
} from './money';

export type BacktestInitialPositionStatus =
  | 'open'
  | 'closed'
  | 'closed_slot'
  | 'pending_rebuild';

export interface BacktestInitialPosition {
  layer_number: number | string;
  retracement_count: number | string;
  units?: number | string | null;
  entry_price?: number | string | null;
  planned_exit_price?: number | string | null;
  stop_loss_price?: number | string | null;
  status: BacktestInitialPositionStatus;
  exit_price?: number | string | null;
  close_reason?: string;
  oanda_trade_id?: string;
}

export interface BacktestInitialPositionCycle {
  direction: 'long' | 'short';
  positions: BacktestInitialPosition[];
}

export interface BacktestClosedWindow {
  start: string;
  end: string;
  timezone: string;
}

export type BacktestMarketClosure = string | BacktestClosedWindow;

export interface BacktestTask {
  id: string;
  user_id: number;
  config_id: string;
  config_name: string;
  config_revision?: number;
  config_hash?: string;
  strategy_type: string;
  name: string;
  description: string;
  data_source: DataSource;
  start_time: string;
  end_time: string;
  initial_balance: string;
  initial_balance_money?: MoneyAmount;
  account_currency?: string;
  display_currency?: string;
  money_context?: TaskMoneyContext;
  commission_per_trade: string;
  commission_per_trade_money?: MoneyAmount;
  pip_size?: string;
  instrument_context?: TaskInstrumentContext;
  instrument: string;
  tick_granularity: string;
  tick_window_value_mode: string;
  status: TaskStatus;
  sell_at_completion: boolean;
  sell_on_stop?: boolean;
  hedging_enabled: boolean;
  drain_duration_hours?: number;
  market_idle_pre_close_minutes?: number;
  market_idle_resume_delay_minutes?: number;
  market_close_enabled?: boolean;
  market_close_weekday?: number;
  market_close_hour_utc?: number;
  market_open_weekday?: number;
  market_open_hour_utc?: number;
  max_tick_gap_hours?: number;
  backtest_tick_batch_size?: number;
  spread_filter_enabled?: boolean;
  max_spread_pips?: string;
  oanda_candle_filter_enabled?: boolean;
  oanda_candle_filter_account?: number | null;
  oanda_candle_filter_account_name?: string | null;
  oanda_candle_filter_granularity?: string;
  oanda_candle_filter_tolerance_pips?: string;
  holidays_enabled?: boolean;
  excluded_dates?: BacktestMarketClosure[];
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
  in_memory_mode?: boolean;
  latest_execution?: ExecutionSummary;
  can_resume?: boolean;
  action_policy?: TaskActionPolicy;
  execution_id?: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  error_code?: string;
  status_reason_code?: string;
  status_reason_message?: string;
  created_at: string;
  updated_at: string;
  debug_options?: Record<string, unknown>;
}

export interface BacktestTaskCreateData {
  config: string;
  name: string;
  description?: string;
  data_source: DataSource;
  start_time: string;
  end_time: string;
  initial_balance: number | string;
  account_currency?: string;
  display_currency?: string;
  commission_per_trade?: number | string;
  pip_size?: number | string;
  instrument: string;
  tick_granularity?: string;
  tick_window_value_mode?: string;
  sell_on_stop?: boolean;
  hedging_enabled?: boolean;
  drain_duration_hours?: number;
  market_idle_pre_close_minutes?: number;
  market_idle_resume_delay_minutes?: number;
  market_close_enabled?: boolean;
  market_close_weekday?: number;
  market_close_hour_utc?: number;
  market_open_weekday?: number;
  market_open_hour_utc?: number;
  max_tick_gap_hours?: number;
  backtest_tick_batch_size?: number;
  spread_filter_enabled?: boolean;
  max_spread_pips?: number | string;
  oanda_candle_filter_enabled?: boolean;
  oanda_candle_filter_account?: number | null;
  oanda_candle_filter_granularity?: string;
  oanda_candle_filter_tolerance_pips?: number | string;
  holidays_enabled?: boolean;
  excluded_dates?: BacktestMarketClosure[];
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
  in_memory_mode?: boolean;
  debug_options?: Record<string, unknown>;
}

// Form data type - matches the validation schema (after transformation)
export interface BacktestTaskFormData {
  config_id: string;
  name: string;
  description?: string;
  data_source: DataSource;
  start_time: string;
  end_time: string;
  initial_balance: number;
  account_currency: string;
  display_currency?: string;
  commission_per_trade?: number;
  pip_size?: number;
  instrument: string;
  tick_granularity: string;
  tick_window_value_mode: string;
  sell_at_completion?: boolean;
  hedging_enabled?: boolean;
  drain_duration_hours?: number;
  market_idle_pre_close_minutes?: number;
  market_idle_resume_delay_minutes?: number;
  market_close_enabled?: boolean;
  market_close_weekday?: number;
  market_close_hour_utc?: number;
  market_open_weekday?: number;
  market_open_hour_utc?: number;
  max_tick_gap_hours?: number;
  backtest_tick_batch_size?: number;
  spread_filter_enabled?: boolean;
  max_spread_pips?: number;
  oanda_candle_filter_enabled?: boolean;
  oanda_candle_filter_account?: number | null;
  oanda_candle_filter_granularity?: string;
  oanda_candle_filter_tolerance_pips?: number;
  holidays_enabled?: boolean;
  excluded_dates?: BacktestMarketClosure[];
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
  in_memory_mode?: boolean;
}

export interface BacktestTaskUpdateData {
  config?: string;
  name?: string;
  description?: string;
  data_source?: DataSource;
  start_time?: string;
  end_time?: string;
  initial_balance?: number | string;
  account_currency?: string;
  display_currency?: string;
  commission_per_trade?: number | string;
  pip_size?: number | string;
  instrument?: string;
  tick_granularity?: string;
  tick_window_value_mode?: string;
  sell_on_stop?: boolean;
  hedging_enabled?: boolean;
  drain_duration_hours?: number;
  market_idle_pre_close_minutes?: number;
  market_idle_resume_delay_minutes?: number;
  market_close_enabled?: boolean;
  market_close_weekday?: number;
  market_close_hour_utc?: number;
  market_open_weekday?: number;
  market_open_hour_utc?: number;
  max_tick_gap_hours?: number;
  backtest_tick_batch_size?: number;
  spread_filter_enabled?: boolean;
  max_spread_pips?: number | string;
  oanda_candle_filter_enabled?: boolean;
  oanda_candle_filter_account?: number | null;
  oanda_candle_filter_granularity?: string;
  oanda_candle_filter_tolerance_pips?: number | string;
  holidays_enabled?: boolean;
  excluded_dates?: BacktestMarketClosure[];
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
  in_memory_mode?: boolean;
  debug_options?: Record<string, unknown>;
}

export interface BacktestBalanceAdjustmentData {
  current_balance: number | string;
  reason?: string;
}

export interface BacktestBalanceAdjustmentResult {
  task_id: string;
  execution_id: string;
  previous_balance: string;
  previous_balance_currency: string;
  previous_balance_money: MoneyAmount;
  previous_balance_display_money?: MoneyAmount | null;
  current_balance: string;
  current_balance_currency: string;
  current_balance_money: MoneyAmount;
  current_balance_display_money?: MoneyAmount | null;
  adjustment: string;
  adjustment_currency: string;
  adjustment_money: MoneyAmount;
  adjustment_display_money?: MoneyAmount | null;
  display_conversion_context?: CurrencyConversionContext | null;
  currency: string;
  state_version: number;
}

export interface BacktestTaskListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: TaskStatus;
  config_id?: string;
  strategy_type?: string;
  ordering?: string;
}

export interface BacktestTaskCopyData {
  new_name: string;
}

/**
 * Live/intermediate results during backtest execution
 */
export interface BacktestLiveResults {
  task_id: string;
  has_data: boolean;
  message?: string;
  day_date?: string;
  progress?: number;
  days_processed?: number;
  total_days?: number;
  ticks_processed?: number;
  balance?: number;
  total_trades?: number;
  metrics?: {
    total_pnl?: number;
    total_return?: number;
    win_rate?: number;
    winning_trades?: number;
    losing_trades?: number;
    average_win?: number;
    average_loss?: number;
    profit_factor?: number;
    max_drawdown?: number;
    sharpe_ratio?: number;
    [key: string]: number | string | undefined;
  };
  trade_log?: Array<{
    timestamp?: string;
    entry_time?: string;
    exit_time?: string;
    instrument?: string;
    direction?: string;
    entry_price?: number;
    exit_price?: number;
    units?: number;
    pnl?: number;
    duration?: number | string;
    layer_number?: number;
    is_first_lot?: boolean;
    retracement_count?: number;
    entry_retracement_count?: number;
    [key: string]: string | number | boolean | undefined;
  }>;
  strategy_events?: Array<{
    event_type: string;
    description: string;
    details: Record<string, string | number | boolean | null>;
    timestamp?: string;
  }>;
  equity_curve?: Array<{
    timestamp: string;
    balance: number;
    [key: string]: string | number | undefined;
  }>;
}
