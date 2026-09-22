/** Home feed merges intraday cycles, pre/post/weekly reports and every stock agent. */
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import { getAgentHistory, getStockAgents } from '@/shared/api/stock_agents'
import { getGuardianActivity } from '@/shared/api/guardian'
import { statusName } from '@/features/agents/agentFormat'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AgentSummary, GuardianSummary } from '@/shared/types/stock_agents'
import { feedEpoch, feedPhase, guardianReportRows, guardianRunRows, latestAgentFeed, type AgentFeedRow } from './pulseAgentFeedModel'
export type { AgentFeedRow } from './pulseAgentFeedModel'
export { feedEpoch } from './pulseAgentFeedModel'

const MAX_ROWS = 16
const CONCURRENCY = 4
const REFRESH_MS = 60_000
export function guardianFeedRows(summary: GuardianSummary | null): AgentFeedRow[] {
  return summary ? latestAgentFeed(guardianRunRows(summary.runs ?? []), MAX_ROWS) : []
}
export async function stockAgentFeedRows(agent: AgentSummary, signal?: AbortSignal): Promise<AgentFeedRow[]> {
  // Fetch enough from each source to make the final global top-N exact.
  const page = await getAgentHistory(agent.id, 'runs', 0, undefined, undefined, signal, MAX_ROWS)
  return (page.items ?? []).map(item => ({
    key:`${agent.id}:${item.id ?? item.request_id ?? item.started_at ?? ''}`, agentId:agent.id,
    agentName:agent.config.name || agent.id, to:`/agents/${encodeURIComponent(agent.id)}?tab=diary`,
    at:item.started_at || item.finished_at || item.at || '', phaseLabel:feedPhase(item.phase),
    statusLabel:statusName(item.status), summary:(item.summary || '').trim(),
    failed:['failed','interrupted'].includes(item.status ?? ''),
  }))
}

export function usePulseAgentFeed() {
  const rows = ref<AgentFeedRow[]>([]), loading = ref(false), error = ref(''), partialError = ref('')
  let generation = 0, active = false
  let controller: AbortController | null = null
  let timer: ReturnType<typeof setInterval> | null = null
  const agentCount = computed(() => new Set(rows.value.map(row => row.agentId)).size)
  async function load(): Promise<void> {
    const token = ++generation
    controller?.abort()
    const ac = new AbortController(); controller = ac
    loading.value = true; error.value = ''; partialError.value = ''
    const items: AgentFeedRow[] = [], failures: string[] = []
    try {
      const [activity, agents] = await Promise.allSettled([
        getGuardianActivity(MAX_ROWS, ac.signal), getStockAgents(ac.signal),
      ])
      if (token !== generation) return
      if (activity.status === 'fulfilled') {
        items.push(...guardianRunRows(activity.value.runs ?? []), ...guardianReportRows(activity.value.reports ?? []))
      } else failures.push(`自主交易员各阶段研判：${toErrorMessage(activity.reason, '读取失败')}`)
      if (agents.status === 'rejected') failures.push(`智能体列表：${toErrorMessage(agents.reason, '读取失败')}`)
      const pending = agents.status === 'fulfilled' ? [...(agents.value.items ?? [])].sort((a,b) => feedEpoch(b.latest_at) - feedEpoch(a.latest_at)) : []
      let cursor = 0
      await Promise.all(Array.from({length:Math.min(CONCURRENCY, pending.length)}, async () => {
        while (cursor < pending.length && !ac.signal.aborted) {
          const agent = pending[cursor++]!
          try { items.push(...await stockAgentFeedRows(agent, ac.signal)) }
          catch (caught) { failures.push(`${agent.config.name || agent.id}：${toErrorMessage(caught, '研判读取失败')}`) }
        }
      }))
      if (token !== generation) return
      rows.value = latestAgentFeed(items, MAX_ROWS)
      if (failures.length) {
        if (!items.length) error.value = failures.join('；')
        else partialError.value = failures.join('；')
      }
    } catch (caught) {
      if (token === generation) error.value = toErrorMessage(caught, '智能体研判加载失败')
    } finally { if (token === generation) loading.value = false }
  }
  function start(): void {
    if (active) return
    active = true; void load()
    timer = setInterval(() => { if (!document.hidden) void load() }, REFRESH_MS)
  }
  function stop(): void {
    active = false
    if (timer) clearInterval(timer)
    timer = null; generation++; controller?.abort(); loading.value = false
  }
  onMounted(start); onActivated(start); onDeactivated(stop); onUnmounted(stop)
  return { rows, loading, error, partialError, agentCount, load }
}
