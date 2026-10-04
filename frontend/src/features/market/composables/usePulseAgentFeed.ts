/** Home feed merges intraday cycles, pre/post/weekly reports and every stock agent. */
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import { getAgentActivity } from '@/shared/api/stock_agents'
import { toErrorMessage } from '@/shared/lib/errors'
import { latestAgentFeed, type AgentFeedRow } from './pulseAgentFeedModel'
export type { AgentFeedRow } from './pulseAgentFeedModel'
export { feedEpoch } from './pulseAgentFeedModel'

const MAX_ROWS = 16
const REFRESH_MS = 60_000
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
    try {
      const activity = await getAgentActivity(ac.signal, MAX_ROWS)
      if (token !== generation) return
      rows.value = latestAgentFeed(activity.items ?? [], MAX_ROWS)
      partialError.value = (activity.partial_errors ?? []).join('；')
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
