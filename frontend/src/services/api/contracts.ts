import type { PaginatedApiResponse } from './pagination';
import type { TaskActionPolicy } from '../../types/common';
import type {
  CurrencyConversionContext,
  MoneyAmount,
  TaskMoneyContext,
} from '../../types/money';
import type { StrategyCapabilities } from '../../types/strategy';
import type {
  BacktestInitialPositionCycle,
  BacktestMarketClosure,
} from '../../types/backtestTask';
import type { TaskInstrumentContext } from '../../types/instrument';

export type BackendMoneyAmount = MoneyAmount;

export interface BackendExecutionMetrics {
  total_return?: string;
  total_pnl?: string;
  realized_pnl?: string;
  unrealized_pnl?: string;
  total_pnl_quote?: string;
  realized_pnl_quote?: string;
  unrealized_pnl_quote?: string;
  total_trades?: number;
  winning_trades?: number;
  losing_trades?: number;
  win_rate?: string;
  pnl_currency?: string;
  account_currency?: string;
  quote_currency?: string;
  display_currency?: string;
  current_balance?: string;
  initial_balance?: string;
  current_balance_currency?: string;
  initial_balance_currency?: string;
  total_pnl_money?: BackendMoneyAmount;
  realized_pnl_money?: BackendMoneyAmount;
  unrealized_pnl_money?: BackendMoneyAmount;
  total_pnl_quote_money?: BackendMoneyAmount;
  realized_pnl_quote_money?: BackendMoneyAmount;
  unrealized_pnl_quote_money?: BackendMoneyAmount;
  total_pnl_display_money?: BackendMoneyAmount;
  realized_pnl_display_money?: BackendMoneyAmount;
  unrealized_pnl_display_money?: BackendMoneyAmount;
  current_balance_money?: BackendMoneyAmount;
  current_balance_display_money?: BackendMoneyAmount;
  initial_balance_money?: BackendMoneyAmount;
  display_conversion_context?: CurrencyConversionContext;
  quote_to_account_rate?: string;
  quote_to_account_rate_source?: string;
  quote_to_account_rate_as_of?: string | null;
  quote_to_account_rate_path?: string[];
}

export interface BackendTaskExecutionSummary extends BackendExecutionMetrics {
  id: string;
  task_type: 'backtest' | 'trading';
  task_id: string;
  execution_number: string;
  segment_index?: number;
  config_revision_count?: number;
  configuration_revision?: number | null;
  configuration_hash?: string | null;
  status: string;
  progress: number;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  error_code?: string | null;
  duration?: number | null;
  created_at: string;
}

export interface BackendTaskStopResponse {
  message: string;
  command?: 'stop';
  task_id: string;
  previous_status?: string;
  next_status?: string;
  status: string;
  accepted?: boolean;
  mode?: string;
}

export interface BackendBacktestTask {
  id: string;
  user_id: number;
  config_id: string;
  config_name: string;
  config_revision?: number;
  config_hash?: string;
  strategy_type: string;
  name: string;
  description: string;
  data_source: string;
  start_time: string;
  end_time: string;
  initial_balance: string;
  initial_balance_money?: BackendMoneyAmount;
  account_currency?: string;
  display_currency?: string;
  money_context?: TaskMoneyContext;
  commission_per_trade: string;
  commission_per_trade_money?: BackendMoneyAmount;
  pip_size?: string | null;
  instrument_context?: TaskInstrumentContext;
  instrument: string;
  hedging_enabled: boolean;
  sell_on_stop: boolean;
  tick_granularity: string;
  tick_window_value_mode: string;
  status: string;
  execution_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  error_code?: string | null;
  latest_execution?: BackendTaskExecutionSummary | null;
  can_resume?: boolean;
  action_policy?: TaskActionPolicy;
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
  created_at: string;
  updated_at: string;
  debug_options?: Record<string, unknown>;
}

export interface BackendTradingTask {
  id: string;
  user_id: number;
  config_id: string;
  config_name: string;
  config_revision?: number;
  config_hash?: string;
  strategy_type: string;
  instrument: string;
  account_id: number;
  account_name: string;
  account_type: 'live' | 'practice';
  account_currency: string;
  display_currency: string;
  money_context?: TaskMoneyContext;
  name: string;
  description: string;
  sell_on_stop: boolean;
  dry_run: boolean;
  hedging_enabled: boolean;
  tick_granularity: string;
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
  pip_size?: string | null;
  instrument_context?: TaskInstrumentContext;
  status: string;
  execution_id?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  error_code?: string | null;
  latest_execution?: BackendTaskExecutionSummary | null;
  has_strategy_state: boolean;
  can_resume: boolean;
  action_policy?: TaskActionPolicy;
  api_retry_max_attempts?: number;
  api_retry_backoff_base_seconds?: string;
  api_retry_backoff_max_seconds?: string;
  drain_duration_hours?: number;
  market_idle_pre_close_minutes?: number;
  market_idle_resume_delay_minutes?: number;
  live_tick_stale_guard_enabled?: boolean;
  live_tick_max_age_seconds?: number;
  live_tick_status_log_interval_seconds?: number;
  broker_drift_check_interval_seconds?: number;
  created_at: string;
  updated_at: string;
  debug_options?: Record<string, unknown>;
}

export interface BackendConfigurationTask {
  id: string;
  task_type: 'backtest' | 'trading';
  name: string;
  status: string;
}

export interface BackendConfigurationTaskList {
  results: BackendConfigurationTask[];
}

export interface BackendStrategyConfig {
  id: string;
  user_id: number;
  name: string;
  strategy_type: string;
  parameters?: Record<string, unknown> | null;
  revision: number;
  config_hash: string;
  description: string;
  is_in_use: boolean;
  has_running_tasks: boolean;
  created_at: string;
  updated_at: string;
}

export interface BackendStrategyListResponse {
  strategies: Array<{
    id: string;
    name: string;
    class_name?: string;
    description: string;
    capabilities?: StrategyCapabilities;
    config_schema: Record<string, unknown>;
  }>;
  count: number;
}

export interface BackendStrategyDefaultsResponse {
  strategy_id: string;
  defaults: Record<string, unknown>;
}

export interface BackendAccount {
  id?: number;
  account_id: string;
  api_type?: 'practice' | 'live';
  jurisdiction?: string;
  currency?: string;
  balance?: string;
  margin_used?: string;
  margin_available?: string;
  unrealized_pnl?: string;
  is_active?: boolean;
  is_default?: boolean;
  created_at?: string;
  updated_at?: string;
  nav?: string;
  open_trade_count?: number;
  open_position_count?: number;
  pending_order_count?: number;
  live_data?: boolean;
  live_data_error?: string;
  snapshot_refreshed_at?: string | null;
  snapshot_stale?: boolean;
  snapshot_refresh_error?: string;
  snapshot_refresh_task_id?: string;
  snapshot_refresh_status?: BackendAccountSnapshotRefreshStatus;
  snapshot_refresh_status_updated_at?: string | null;
  hedging_enabled?: boolean;
  position_mode?: 'hedging' | 'netting';
  oanda_account?: Record<string, unknown>;
  live_max_exposure_guard_enabled?: boolean;
  live_max_estimated_exposure_units?: number;
  live_max_initial_order_guard_enabled?: boolean;
  live_max_initial_order_units?: number;
  live_max_order_guard_enabled?: boolean;
  live_max_order_units?: number;
  live_tick_latency_metric_interval_seconds?: number;
}

export type BackendAccountSnapshotRefreshStatus =
  | 'idle'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed';

export interface BackendAccountSnapshotRefreshResponse {
  id: number;
  account_id: string;
  task_id: string;
  status: BackendAccountSnapshotRefreshStatus;
  snapshot_refreshed_at: string | null;
  snapshot_stale: boolean;
  snapshot_refresh_error: string;
  snapshot_refresh_status_updated_at: string | null;
}

export type BackendPaginatedBacktestTasks =
  PaginatedApiResponse<BackendBacktestTask>;
export type BackendPaginatedTradingTasks =
  PaginatedApiResponse<BackendTradingTask>;
export type BackendPaginatedConfigurations =
  PaginatedApiResponse<BackendStrategyConfig>;
