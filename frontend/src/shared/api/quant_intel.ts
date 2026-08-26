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

export type IntelBrief = {
  trade_date: string
  available: boolean
  fetched_at: string | null
  emotion: IntelBriefEmotion | null
  themes: IntelBriefTheme[]
  ladder: IntelBriefLadder | null
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
