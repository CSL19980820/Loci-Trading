export interface HoldingCurvePoint {
  at: string
  nav: number | null
  pnl_cents: number | null
  drawdown_pct: number | null
  equity_cents?: number | null
  quantity?: number
  market_value_cents?: number | null
  price_cents?: number | null
  kind: 'baseline' | 'buy' | 'sell' | 'valuation' | 'unavailable'
  quality: 'verified' | 'unavailable'
  trade_quantity?: number
  fees_cents?: number
  quote_at?: string
  source?: string
}
export interface HoldingProtection {
  code: string; name: string; quantity: number; available_quantity: number
  locked_quantity: number; protected_quantity: number; unprotected_quantity: number
  stale: boolean; invalid_plans: number
  stops: { price: number; quantity: number; valid_until: string; reached: boolean }[]
}
export interface HoldingCurve {
  code: string; name: string; scope: 'account' | 'holding'; as_of: string
  start: string; end: string; opened_at: string | null
  method: 'holding_unit_nav_net_fees_v1' | 'account_equity_v1'
  points: HoldingCurvePoint[]; protection: HoldingProtection[]
  excluded_points: number
  coverage: { sampled: true; missing_snapshots?: number; truncated?: boolean }
  summary: {
    current_drawdown_pct: number | null; max_drawdown_pct: number | null
    last_valid_drawdown_pct: number | null; last_valid_at: string | null
    last_valid_pnl_cents: number | null
    peak_at: string | null; max_drawdown_peak_at: string | null; max_drawdown_at: string | null
    valid_points: number; latest_nav: number | null; latest_pnl_cents: number | null
    recovery_pct: number | null
  }
}
