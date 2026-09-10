/**
 * 纸面舱的状态与写口。
 *
 * 这些 ref 必须同源：`GET /api/skills/{slug}/paper-cabin` 一枪就把持仓、成交、
 * 盯盘快照、次日预案、风格记忆与记忆图全带回来，拆成几个 composable 只会变成
 * 互相回灌同一份响应。舱配置 / 盯盘 / 日终 / 风格 / 记忆图的写口跟着这份 state
 * 放，是因为它们写完都要重读同一个接口（loadCabin）。
 *
 * 派生闸门也在这里算：交易日闸与龙空龙闸门读的都是 monitor_runs[0].snapshot
 * 的形状，组件只该拿到「标题 / 备注 / tag 类型」这种能直接摆上去的结论。
 *
 * 通知策略与价格提醒不在这里：它们走各自的接口，与纸面舱没有共享字段。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  absorbPaperStyle,
  explorePaperMemory,
  getPaperCabin,
  rebuildPaperMemory,
  runPaperEod,
  runPaperMonitor,
  savePaperCabinConfig,
  savePaperStyle,
  type UnifiedMonitorPool,
} from '@/shared/api/quant_ops_paper'
import { getLeaderRoles } from '@/shared/api/quant_ops'
import type { LeaderRoleHistoryResponse } from '@/shared/types/quant'

export function usePaperCabin() {
  const slug = ref('demo')
  const cabinBusy = ref(false)
  const cabin = ref<Record<string, unknown> | null>(null)
  const positions = ref<Array<Record<string, unknown>>>([])
  const fills = ref<Array<Record<string, unknown>>>([])
  const monitorRuns = ref<Array<Record<string, unknown>>>([])
  const plan = ref<Record<string, unknown> | null>(null)
  const unifiedPool = ref<UnifiedMonitorPool | null>(null)
  const styleMd = ref('')
  const styleRevision = ref(0)
  const lessons = ref<Array<Record<string, unknown>>>([])
  const leaderRoles = ref<LeaderRoleHistoryResponse | null>(null)
  const watchHintsText = ref('')
  const memorySummary = ref('')
  const memoryNodes = ref<Array<Record<string, unknown>>>([])
  const memoryEdges = ref<Array<Record<string, unknown>>>([])
  const memoryQuery = ref('高开 教训')
  const memoryStats = ref('')
  const followWecom = ref(false)
  const model = ref('')
  const thinking = ref('medium')
  const maxLayers = ref(4)
  const gapUpChase = ref(false)

  const planItems = computed(() => {
    const items = (unifiedPool.value as { items?: Array<Record<string, unknown>> } | null)?.items
    return Array.isArray(items) ? items : []
  })

  const latestMarketGate = computed(() => {
    const snapshot = monitorRuns.value[0]?.snapshot
    const gate = (snapshot as { market_gate?: unknown } | undefined)?.market_gate
    return gate && typeof gate === 'object' ? (gate as Record<string, unknown>) : null
  })

  const latestMarketGateType = computed<'success' | 'warning' | 'info'>(() => {
    if (latestMarketGate.value?.state === 'dragon') return 'success'
    if (latestMarketGate.value?.state === 'empty') return 'warning'
    return 'info'
  })

  /** 最近盯盘快照中的交易日闸（日历缺失 fail-closed 须可见）。 */
  const latestTradingDayGate = computed(() => {
    const snapshot = monitorRuns.value[0]?.snapshot
    const gate = (snapshot as { trading_day_gate?: unknown } | undefined)?.trading_day_gate
    return gate && typeof gate === 'object' ? (gate as Record<string, unknown>) : null
  })

  const tradingDayGateAlert = computed(() => {
    const gate = latestTradingDayGate.value
    if (!gate) return null
    const buyOk = gate.buy_execution_allowed === true
    const isTrading = gate.is_trading_day === true
    const source = String(gate.calendar_source || '')
    if (buyOk && isTrading) return null
    const type: 'warning' | 'error' | 'info' =
      source === 'weekday_fallback' || (!buyOk && isTrading) ? 'warning' : 'info'
    const title =
      source === 'weekday_fallback'
        ? '交易日历缺失：买入 fail-closed'
        : isTrading
          ? '纸面买入暂不可执行'
          : '今日非交易日'
    return {
      type,
      title,
      // el-alert 禁 description：闸门备注改挂 tooltip，页面上只留 ≤20 字的标题
      note: String(gate.note || '请同步 market.db 交易日历后再开仓'),
    }
  })

  const roleAlertLessons = computed(() =>
    lessons.value.filter((row) => String(row.kind || '') === 'role_alert'),
  )

  const regularLessons = computed(() =>
    lessons.value.filter((row) => String(row.kind || '') !== 'role_alert'),
  )

  function scenarioLabel(row: Record<string, unknown>, key: string): string {
    const scenarios = row.scenarios as Record<string, Record<string, unknown>> | undefined
    const sc = scenarios?.[key]
    if (!sc) return '—'
    const buy = sc.buy ? '买' : '不买'
    return `${buy} ${sc.entry_pct_min}~${sc.entry_pct_max}% · ${sc.layers ?? 0}层`
  }

  async function loadLeaderRoles(slugValue: string): Promise<void> {
    try {
      leaderRoles.value = await getLeaderRoles(slugValue)
    } catch {
      leaderRoles.value = null
    }
  }

  async function loadCabin(): Promise<void> {
    cabinBusy.value = true
    try {
      const slugValue = slug.value.trim() || 'demo'
      const [data] = await Promise.all([getPaperCabin(slugValue), loadLeaderRoles(slugValue)])
      cabin.value = data.cabin
      positions.value = data.positions
      fills.value = data.fills
      monitorRuns.value = data.monitor_runs
      plan.value = data.nextday_plan
      unifiedPool.value = data.unified_pool ?? null
      const style = data.style as
        | { style_md?: string; revision?: number; watch_hints?: string[] }
        | undefined
      styleMd.value = String(style?.style_md || '')
      styleRevision.value = Number(style?.revision || 0)
      watchHintsText.value = Array.isArray(style?.watch_hints)
        ? style.watch_hints.join('\n')
        : ''
      lessons.value = Array.isArray(data.lessons) ? data.lessons : []
      const graph = data.memory_graph
      memorySummary.value = String(graph?.summary || '')
      memoryNodes.value = Array.isArray(graph?.nodes) ? graph.nodes : []
      memoryEdges.value = Array.isArray(graph?.edges) ? graph.edges : []
      const stats = graph?.stats as { nodes?: number; edges?: number; by_kind?: Record<string, number> } | undefined
      memoryStats.value = stats
        ? `节点 ${stats.nodes ?? 0} · 边 ${stats.edges ?? 0}`
        : ''
      const cfg = (data.cabin.config as { paper_quant?: Record<string, unknown> } | undefined)
        ?.paper_quant
      if (cfg) {
        followWecom.value = Boolean(cfg.follow_wecom)
        model.value = String(cfg.model || '')
        thinking.value = String(cfg.thinking || 'medium')
        gapUpChase.value = Boolean(cfg.gap_up_chase)
      }
      maxLayers.value = Number(data.cabin.max_layers || 4)
    } finally {
      cabinBusy.value = false
    }
  }

  async function saveStyle(): Promise<void> {
    const hints = watchHintsText.value
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    await savePaperStyle(slug.value.trim() || 'demo', {
      style_md: styleMd.value,
      watch_hints: hints,
    })
    ElMessage.success('战法风格记忆已保存')
    await loadCabin()
  }

  async function absorbStyle(): Promise<void> {
    cabinBusy.value = true
    try {
      const result = await absorbPaperStyle(slug.value.trim() || 'demo')
      ElMessage.success(`已吸入 ${String(result.absorbed ?? 0)} 条教训`)
      await loadCabin()
    } finally {
      cabinBusy.value = false
    }
  }

  async function exploreMemory(): Promise<void> {
    cabinBusy.value = true
    try {
      const result = await explorePaperMemory(slug.value.trim() || 'demo', memoryQuery.value)
      memorySummary.value = String(result.summary || '')
      memoryNodes.value = Array.isArray(result.nodes) ? result.nodes : []
      memoryEdges.value = Array.isArray(result.edges) ? result.edges : []
      const stats = result.stats as { nodes?: number; edges?: number } | undefined
      memoryStats.value = stats ? `节点 ${stats.nodes ?? 0} · 边 ${stats.edges ?? 0}` : ''
    } finally {
      cabinBusy.value = false
    }
  }

  async function rebuildMemory(): Promise<void> {
    cabinBusy.value = true
    try {
      await rebuildPaperMemory(slug.value.trim() || 'demo')
      ElMessage.success('记忆图已重建')
      await loadCabin()
    } finally {
      cabinBusy.value = false
    }
  }

  async function saveCabin(): Promise<void> {
    await savePaperCabinConfig(slug.value.trim() || 'demo', {
      enabled: true,
      follow_wecom: followWecom.value,
      model: model.value,
      thinking: thinking.value,
      max_layers: maxLayers.value,
      gap_up_chase: gapUpChase.value,
      ai_apply_paper: true,
      ai_mode: model.value ? 'suggest' : 'rules',
    })
    ElMessage.success('纸面舱配置已保存')
    await loadCabin()
  }

  async function monitorNow(): Promise<void> {
    cabinBusy.value = true
    try {
      await runPaperMonitor(slug.value.trim() || 'demo')
      ElMessage.success('盯盘已执行')
      await loadCabin()
    } finally {
      cabinBusy.value = false
    }
  }

  async function eodNow(): Promise<void> {
    cabinBusy.value = true
    try {
      const result = await runPaperEod(slug.value.trim() || 'demo')
      const lb = result.lookback as
        | { days?: string[]; missed?: unknown[]; bought?: unknown[] }
        | undefined
      const miss = Array.isArray(lb?.missed) ? lb.missed.length : 0
      const bought = Array.isArray(lb?.bought) ? lb.bought.length : 0
      ElMessage.success(
        lb?.days?.length
          ? `日终完成：回看 ${lb.days.length} 日 · 买过 ${bought} · 错过 ${miss}`
          : '日终总结已执行',
      )
      await loadCabin()
    } finally {
      cabinBusy.value = false
    }
  }

  return {
    slug,
    cabinBusy,
    positions,
    fills,
    plan,
    unifiedPool,
    styleMd,
    styleRevision,
    leaderRoles,
    watchHintsText,
    memorySummary,
    memoryNodes,
    memoryEdges,
    memoryQuery,
    memoryStats,
    followWecom,
    model,
    thinking,
    maxLayers,
    gapUpChase,
    planItems,
    latestMarketGate,
    latestMarketGateType,
    tradingDayGateAlert,
    roleAlertLessons,
    regularLessons,
    scenarioLabel,
    loadCabin,
    saveCabin,
    monitorNow,
    eodNow,
    saveStyle,
    absorbStyle,
    exploreMemory,
    rebuildMemory,
  }
}

/** 面板与两张卡共享同一个实例，按 prop 显式传递（不做模块级单例）。 */
export type PaperCabinStore = ReturnType<typeof usePaperCabin>
