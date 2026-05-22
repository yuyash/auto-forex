// Trading Task types
import type { TaskActionPolicy, TaskStatus } from './common';
import type { ExecutionSummary } from './execution';
import type { TaskInstrumentContext } from './instrument';
import type { TaskMoneyContext } from './money';
import type { BacktestInitialPositionCycle } from './backtestTask';

export interface TradingTask {
  id: string;
  user_id: number;
  config_id: string;
  config_name: string;
  config_revision?: number;
  config_hash?: string;
  strategy_type: string;
  instrument: string;
  account_id: string;
  account_name: string;
  account_type: 'live' | 'practice';
  account_currency: string;
  display_currency: string;
  money_context?: TaskMoneyContext;
  name: string;
  description: string;
  status: TaskStatus;
  sell_on_stop: boolean;
  dry_run: boolean;
  hedging_enabled: boolean;
  tick_granularity: string;
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
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
  latest_execution?: ExecutionSummary;
  has_strategy_state?: boolean;
  can_resume?: boolean;
  action_policy?: TaskActionPolicy;
  execution_id?: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  error_code?: string;
  pip_size?: string;
  instrument_context?: TaskInstrumentContext;
  created_at: string;
  updated_at: string;
  debug_options?: Record<string, unknown>;
}

export interface TradingTaskCreateData {
  config_id: string;
  account_id: string;
  name: string;
  description?: string;
  instrument?: string;
  display_currency?: string;
  sell_on_stop?: boolean;
  dry_run?: boolean;
  hedging_enabled?: boolean;
  tick_granularity?: string;
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
  api_retry_max_attempts?: number;
  api_retry_backoff_base_seconds?: number;
  api_retry_backoff_max_seconds?: number;
  drain_duration_hours?: number;
  market_idle_pre_close_minutes?: number;
  market_idle_resume_delay_minutes?: number;
  live_tick_stale_guard_enabled?: boolean;
  live_tick_max_age_seconds?: number;
  live_tick_status_log_interval_seconds?: number;
  broker_drift_check_interval_seconds?: number;
  debug_options?: Record<string, unknown>;
}

export interface TradingTaskUpdateData {
  config?: string;
  name?: string;
  description?: string;
  account_id?: string;
  display_currency?: string;
  sell_on_stop?: boolean;
  dry_run?: boolean;
  hedging_enabled?: boolean;
  tick_granularity?: string;
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycle[];
  api_retry_max_attempts?: number;
  api_retry_backoff_base_seconds?: number;
  api_retry_backoff_max_seconds?: number;
  drain_duration_hours?: number;
  market_idle_pre_close_minutes?: number;
  market_idle_resume_delay_minutes?: number;
  live_tick_stale_guard_enabled?: boolean;
  live_tick_max_age_seconds?: number;
  live_tick_status_log_interval_seconds?: number;
  broker_drift_check_interval_seconds?: number;
  debug_options?: Record<string, unknown>;
}

export interface TradingTaskListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: TaskStatus;
  config_id?: string;
  account_id?: string;
  strategy_type?: string;
  ordering?: string;
}

export interface TradingTaskCopyData {
  new_name: string;
}
