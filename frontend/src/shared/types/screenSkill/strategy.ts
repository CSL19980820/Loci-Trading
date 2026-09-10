/**
 * 战法（strategy）在货架与详情页上的形态：一条目录项 + 它的版本链 + 每个版本
 * 附带的回测摘要。与 `authoring.ts` 的区别是这里描述「已注册、可运行」的战法，
 * 那边描述「正在编辑、还没落地」的策稿。
 */

import type { EntryTiming, ScreenSkillSourceKind } from './enums'
import type { UniverseSpec } from './universe'

export interface StrategyInfo {
  slug: string
  name: string
  description: string
  entry_instructions?: string
  entry_timing: EntryTiming
  required_fields: string[]
  min_bars: number
  params: Record<string, number | string | boolean>
  default_universe?: UniverseSpec | null
  source_kind?: ScreenSkillSourceKind
  editable?: boolean
  strategy_revision?: string
  version?: string
  version_history?: StrategyVersion[]
  backtest_metrics?: StrategyBacktestMetrics | null
  backtest_config?: Record<string, unknown> | null
}

/** 可编辑战法的已保存版本快照。 */
export interface StrategyVersion {
  version: string
  id?: string
  status?: string
  created_at?: string
  is_active?: boolean
  backtest_metrics?: StrategyBacktestMetrics | null
  backtest_config?: Record<string, unknown> | null
}

/** 回滚接口只返回恢复后的运行时标识，不返回完整战法详情。 */
export interface StrategyVersionRollbackResult {
  slug: string
  version: string
  file: string
  registered: boolean
}

/** 版本快照来自持久化记录，未执行过回测的字段允许为 null。 */
export interface StrategyBacktestMetrics {
  trades?: number | null
  win_rate?: number | null
  avg_net_return?: number | null
  profit_factor?: number | null
}
