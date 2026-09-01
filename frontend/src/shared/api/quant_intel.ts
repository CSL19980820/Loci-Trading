/** 外部情报只读投影（intel_snapshots），不触发 MCP。 */
import { quantRequest, query } from '@/shared/api/quant_client'

export type IntelBriefEmotion = {
  limit_up_count: number | null
  limit_down_count: number | null
  /** 已是 0–100 百分数（后端 brief 统一） */
  promotion_rate: number | null
  /** 已是 0–100 百分数 */
  broken_rate: number | null
  temperature: number | null
  advancers?: number | null
  decliners?: number | null
  /** 如「1进2」 */
  promotion_rate_basis?: string | null
}

export type IntelBriefTheme = {
  code: string
  name: string
  /** 开盘啦内部量纲，展示优先用 pct_chg / main_net_amount_text */
  strength: number | null
  pct_chg?: number | null
  main_net_amount?: number | null
  main_net_amount_text?: string
}

export type IntelBriefLadder = {
  count: number | null
  height: number | null
}

/** 断板分析（悟道 board_break_analysis）：昨涨停 × 今日。 */
export type IntelBriefBoardBreak = {
  prev_limit_ups: number | null
  sealed_again: number | null
  broken: number | null
  /** 已是 0–100 百分数 */
  break_rate: number | null
  avg_broken_pct_chg: number | null
  /** cooling / neutral / warming */
  sentiment_signal: string | null
  /** 退潮 / 中性 / 修复（后端翻译，前端不再自己映射） */
  sentiment_zh?: string | null
  high_board_broken: Array<{
    code: string
    name: string
    prev_streak: number | null
    pct_chg: number | null
  }>
}

/** 跌停池（悟道 limit_down）：家数 + 今日封板率/炸板数。 */
export type IntelBriefLimitDown = {
  count: number | null
  /** 已是 0–100 百分数 */
  sealed_rate: number | null
  reopened: number | null
  rows: Array<{ code: string; name: string; reason: string }>
}

/** 竞价题材强度（悟道 auction_theme_strength）。 */
export type IntelBriefAuctionTheme = {
  name: string
  member_count: number | null
  hit_count: number | null
  bid_amount_text: string
  avg_change_pct: number | null
  /** 已是 0–100 百分数 */
  consistency: number | null
  limit_up_open: number | null
  leaders: Array<{ code: string; name: string; change_pct: number | null }>
}

/** 短线催化日历（悟道 market_catalyst_calendar），已按「今天及以后 + 中国」筛过。 */
export type IntelBriefCatalyst = {
  date: string
  time: string
  title: string
  type: string
  star: number | null
}

/** 两融汇总（悟道 margin_trading），余额是交易所三行之和。 */
export type IntelBriefMargin = {
  trade_date: string
  balance: number | null
  net_buy: number | null
  exchange_count: number
  exchanges: Array<{ exchange: string; balance: number | null; net_buy: number | null }>
}

/** 限售解禁（悟道 unlock_events），按解禁比例降序。 */
export type IntelBriefUnlock = {
  code: string
  float_date: string
  float_ratio: number | null
  share_type: string
  holder: string
}

export type IntelBrief = {
  trade_date: string
  available: boolean
  fetched_at: string | null
  emotion: IntelBriefEmotion | null
  themes: IntelBriefTheme[]
  ladder: IntelBriefLadder | null
  /** 以下六段来自「配了悟道才有」的复盘/排雷工具；缺采集时为 null / 空数组 */
  board_break?: IntelBriefBoardBreak | null
  limit_down?: IntelBriefLimitDown | null
  auction_themes?: IntelBriefAuctionTheme[]
  catalysts?: IntelBriefCatalyst[]
  margin?: IntelBriefMargin | null
  unlocks?: IntelBriefUnlock[]
  tools: Record<string, { present: boolean; fetched_at: string | null; server: string }>
  source: string
  note: string
  /** 可选情报：无悟道/无缓存不影响主体功能 */
  optional?: boolean
}

export function getIntelBrief(tradeDate?: string): Promise<IntelBrief> {
  return quantRequest<IntelBrief>(
    `/intel/brief${query({ trade_date: tradeDate || undefined })}`,
  )
}
