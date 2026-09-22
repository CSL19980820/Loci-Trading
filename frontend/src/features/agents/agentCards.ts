import type { AgentAction, AgentSummary, GuardianCard, GuardianSummary } from '@/shared/types/stock_agents'
import { phaseName, statusName } from './agentFormat'

export interface AgentCardData {
  id: string; name: string; kind: 'guardian' | 'leader' | 'custom'; subtitle: string
  enabled: boolean; running: boolean; failed: boolean; status: string; model: string
  summary: string; at: string | null; phase: string; actions: AgentAction[]
  equity: number; pnl: number; positions: number; watchCount?: number; totalRuns?: number
  /** 投入本金（分）；有它才能算「收益率」chip */
  initialCapital?: number
  /** 可用现金 / 持仓市值（分）；卡片上的仓位条用 */
  cash?: number
  marketValue?: number
}

/** 收益率 % = 累计盈亏 / 投入本金；本金未知或为 0 时给 null，卡片不画 chip。 */
export function cardReturnPct(card: Pick<AgentCardData, 'pnl' | 'initialCapital'>): number | null {
  const base = card.initialCapital
  if (!base || !Number.isFinite(base) || base <= 0) return null
  return (card.pnl / base) * 100
}

/** 仓位 % = 持仓市值 / 净资产；净资产为 0 时给 null。 */
export function cardAllocationPct(card: Pick<AgentCardData, 'equity' | 'marketValue' | 'cash'>): number | null {
  if (!card.equity || card.equity <= 0) return null
  const mv = typeof card.marketValue === 'number'
    ? card.marketValue
    : typeof card.cash === 'number'
      ? card.equity - card.cash
      : null
  if (mv == null || !Number.isFinite(mv)) return null
  return Math.max(0, Math.min(100, (mv / card.equity) * 100))
}

export function guardianCard(value: GuardianSummary | GuardianCard): AgentCardData {
  const run = value.runs[0]
  const running = run?.status === 'running'
  const failed = !!run?.result.error || run?.status === 'failed'
  const state = value.state as GuardianCard['state'] & Partial<GuardianSummary['state']>
  const positions = 'position_count' in value
    ? value.position_count
    : Array.isArray(state.positions) ? state.positions.length : 0
  return {
    id: 'guardian', name: '自主交易员', kind: 'guardian', subtitle: '工坊战法 · 持仓管理',
    enabled: value.config.enabled, running, failed,
    status: running ? '正在研究' : failed ? '运行异常' : value.config.enabled ? '运行中' : '已暂停',
    model: value.config.model || '', summary: run?.result.error || run?.result.analysis || '等待首次工作',
    at: run?.result.as_of || (run?.started ? new Date(run.started * 1000).toISOString() : null),
    phase: '自主研判', actions: (run?.result.fills ?? []).slice(0, 3).map(fill => ({
      code: fill.code, name: fill.name || fill.code, action: fill.action || fill.side || 'hold', quantity: fill.quantity ?? 0, status: 'filled',
    })), equity: state.equity_cents, pnl: state.total_pnl_cents, positions,
    initialCapital: typeof state.initial_capital_cents === 'number' ? state.initial_capital_cents : undefined,
    cash: typeof state.cash_cents === 'number' ? state.cash_cents : undefined,
    marketValue: typeof state.market_value_cents === 'number' ? state.market_value_cents : undefined,
  }
}

export function stockAgentCard(value: AgentSummary): AgentCardData {
  const failed = ['failed', 'interrupted'].includes(value.latest_status || '')
  return {
    id: value.id, name: value.config.name, kind: value.config.kind,
    subtitle: value.config.kind === 'leader' ? (value.config.description || '龙头选手 · 接力研究') : (value.config.description || '自定义研判 · 独立账户'),
    enabled: value.config.enabled,
    running: value.running, failed, status: value.running ? '正在研究' : failed ? statusName(value.latest_status) : value.config.enabled ? '运行中' : '已暂停',
    model: value.config.model, summary: value.latest_summary || '暂无工作记录，启用后将按日程自动研判。', at: value.latest_at,
    phase: value.latest_phase ? phaseName(value.latest_phase) : '最近动态', actions: value.latest_actions,
    equity: value.state.equity_cents, pnl: value.state.total_pnl_cents,
    positions: value.state.position_count, watchCount: value.state.watchlist.length, totalRuns: value.total_runs,
    initialCapital: value.state.initial_capital_cents, cash: value.state.cash_cents,
  }
}
