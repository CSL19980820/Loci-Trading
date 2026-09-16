/** 回测执行参数；账户与区间模板单独分层，避免混入后端执行配置。 */
export interface BacktestExecutionConfig {
  hold_days?: number
  stop_loss_pct?: number | null
  take_profit_pct?: number | null
  commission_bps?: number
  stamp_duty_bps?: number
  slippage_bps?: number
  allow_limit_up_entry?: boolean
  benchmark?: string | null
  strict_limit_prices?: boolean
  economic_returns?: boolean
  signal_dataset?: string | null
  valuation_end?: string | null
}

export interface StrategyBacktestTemplate extends BacktestExecutionConfig {
  start?: string
  end?: string
  account_model?: 'daily_close'
  initial_capital?: number
  max_positions?: number
  lot_size?: number
  split?: {
    train_start: string
    train_end: string
    oos_start: string
    oos_end: string
  }
}
