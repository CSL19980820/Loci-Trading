import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { getGuardianSummary, getStockAgents } from '@/shared/api/stock_agents'
import type { AgentSummary, GuardianSummary } from '@/shared/types/stock_agents'

/** 两组卡片独立出数；刷新保留旧卡片，不等待慢接口，也不共享跨租户缓存。 */
export function useAgentOverview(paused: () => boolean) {
  const guardian = shallowRef<GuardianSummary | null>(null)
  const agents = shallowRef<AgentSummary[] | null>(null)
  const guardianLoading = ref(false), agentsLoading = ref(false)
  const guardianError = ref(''), agentsError = ref(''), lastLoaded = ref('')
  const loading = computed(() => guardianLoading.value || agentsLoading.value)
  const controller = new AbortController()
  let disposed = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const message = (error: unknown) => error instanceof Error ? error.message : String(error)
  async function loadGuardian() {
    if (disposed || guardianLoading.value) return
    guardianLoading.value = true
    try {
      const result = await getGuardianSummary(controller.signal)
      if (!disposed) { guardian.value = result; guardianError.value = '' }
    } catch (error) { if (!disposed) guardianError.value = message(error) }
    finally { if (!disposed) guardianLoading.value = false }
  }
  async function loadAgents() {
    if (disposed || agentsLoading.value) return
    agentsLoading.value = true
    try {
      const result = await getStockAgents(controller.signal)
      if (!disposed) { agents.value = result.items; lastLoaded.value = result.as_of; agentsError.value = '' }
    } catch (error) { if (!disposed) agentsError.value = message(error) }
    finally { if (!disposed) agentsLoading.value = false }
  }
  function reload() { return Promise.all([loadGuardian(), loadAgents()]) }
  async function poll() {
    if (disposed) return
    if (!document.hidden && !paused()) await reload()
    if (!disposed) timer = setTimeout(poll, agents.value?.some(agent => agent.running) ? 5000 : 15000)
  }
  onMounted(() => { void poll() })
  onUnmounted(() => { disposed = true; controller.abort(); clearTimeout(timer) })
  return { guardian, agents, guardianLoading, agentsLoading, loading, guardianError, agentsError, lastLoaded, reload }
}
