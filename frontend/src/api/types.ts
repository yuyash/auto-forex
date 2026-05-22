/**
 * API types — hand-maintained replacements for the previously generated models.
 */

// --- Enums ---

export enum StatusEnum {
  CREATED = 'created',
  STARTING = 'starting',
  RUNNING = 'running',
  PAUSED = 'paused',
  STOPPING = 'stopping',
  STOPPED = 'stopped',
  COMPLETED = 'completed',
  FAILED = 'failed',
}

export enum DataSourceEnum {
  POSTGRESQL = 'postgresql',
  ATHENA = 'athena',
  S3 = 's3',
}

export enum ApiTypeEnum {
  PRACTICE = 'practice',
  LIVE = 'live',
}

export enum JurisdictionEnum {
  US = 'US',
  JP = 'JP',
  OTHER = 'OTHER',
}

export type BacktestInitialPositionStatus =
  | 'open'
  | 'closed'
  | 'closed_slot'
  | 'pending_rebuild';

export interface BacktestInitialPositionRequest {
  layer_number: number;
  retracement_count: number;
  units?: number | string | null;
  entry_price?: number | string | null;
  planned_exit_price?: number | string | null;
  stop_loss_price?: number | string | null;
  status?: BacktestInitialPositionStatus;
  exit_price?: number | string | null;
  close_reason?: string;
  oanda_trade_id?: string;
}

export interface BacktestInitialPositionCycleRequest {
  direction: 'long' | 'short';
  positions: BacktestInitialPositionRequest[];
}

export interface BacktestClosedWindowRequest {
  start: string;
  end: string;
  timezone: string;
}

export type BacktestMarketClosureRequest = string | BacktestClosedWindowRequest;

// --- OANDA Account types ---

export interface OandaAccounts {
  readonly id?: number;
  account_id: string;
  api_type?: ApiTypeEnum;
  jurisdiction?: JurisdictionEnum;
  currency?: string;
  readonly balance?: string;
  readonly margin_used?: string;
  readonly margin_available?: string;
  readonly unrealized_pnl?: string;
  live_max_exposure_guard_enabled?: boolean;
  live_max_estimated_exposure_units?: number;
  live_max_initial_order_guard_enabled?: boolean;
  live_max_initial_order_units?: number;
  live_max_order_guard_enabled?: boolean;
  live_max_order_units?: number;
  is_active?: boolean;
  is_default?: boolean;
  readonly created_at?: string;
  readonly updated_at?: string;
}

export interface OandaAccountsRequest {
  account_id: string;
  api_token: string;
  api_type?: ApiTypeEnum;
  jurisdiction?: JurisdictionEnum;
  currency?: string;
  live_max_exposure_guard_enabled?: boolean;
  live_max_estimated_exposure_units?: number;
  live_max_initial_order_guard_enabled?: boolean;
  live_max_initial_order_units?: number;
  live_max_order_guard_enabled?: boolean;
  live_max_order_units?: number;
  is_active?: boolean;
  is_default?: boolean;
}

// --- Trading Task types ---

export interface TradingTaskRequest {
  name: string;
  config: number | string;
  oanda_account: number | string;
  description?: string;
  sell_on_stop?: boolean;
  tick_granularity?: string;
}

export interface PatchedTradingTaskCreateRequest {
  name?: string;
  config?: number | string;
  oanda_account?: number | string;
  description?: string;
  sell_on_stop?: boolean;
  tick_granularity?: string;
}

// --- Backtest Task types ---

export interface BacktestTaskRequest {
  name: string;
  config: number | string;
  start_time: string;
  end_time: string;
  description?: string;
  data_source?: DataSourceEnum;
  initial_balance?: string;
  account_currency?: string;
  display_currency?: string;
  commission_per_trade?: string;
  instrument?: string;
  spread_filter_enabled?: boolean;
  max_spread_pips?: string;
  oanda_candle_filter_enabled?: boolean;
  oanda_candle_filter_account?: number | null;
  oanda_candle_filter_granularity?: string;
  oanda_candle_filter_tolerance_pips?: string;
  backtest_tick_batch_size?: number;
  excluded_dates?: BacktestMarketClosureRequest[];
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycleRequest[];
  in_memory_mode?: boolean;
}

export interface PatchedBacktestTaskCreateRequest {
  name?: string;
  config?: number | string;
  start_time?: string;
  end_time?: string;
  description?: string;
  data_source?: DataSourceEnum;
  initial_balance?: string;
  account_currency?: string;
  display_currency?: string;
  commission_per_trade?: string;
  instrument?: string;
  spread_filter_enabled?: boolean;
  max_spread_pips?: string;
  oanda_candle_filter_enabled?: boolean;
  oanda_candle_filter_account?: number | null;
  oanda_candle_filter_granularity?: string;
  oanda_candle_filter_tolerance_pips?: string;
  backtest_tick_batch_size?: number;
  excluded_dates?: BacktestMarketClosureRequest[];
  initial_positions_enabled?: boolean;
  initial_position_cycles?: BacktestInitialPositionCycleRequest[];
  in_memory_mode?: boolean;
}

// --- Strategy Config types ---

export interface StrategyConfigCreateRequest {
  name: string;
  strategy_id: string;
  parameters?: Record<string, unknown>;
  description?: string;
}

// --- Paginated response (generic) ---

export interface PaginatedApiResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
