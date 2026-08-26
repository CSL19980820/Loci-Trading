import { computed, onScopeDispose, ref } from 'vue'

import {
  createResearchRun,
  getResearchCatalog,
  getResearchProfile,
  getResearchRun,
  resumeResearchRun,
} from '@/shared/api/quant'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  ResearchBudget,
  ResearchCatalog,
  ResearchProfile,
  ResearchRun,
} from '@/shared/types/quant'

export function useResearchProfile() {
  const catalog = ref<ResearchCatalog | null>(null)
  const profile = ref<ResearchProfile | null>(null)
  const loading = ref(false)
  const archiveLoading = ref(false)
  const runLoading = ref(false)
  const catalogLoading = ref(false)
  const error = ref('')
  const archivedRun = ref<ResearchRun | null>(null)
  const activeRun = ref<ResearchRun | null>(null)
  const runs = ref<ResearchRun[]>([])
  let requestSeq = 0

  onScopeDispose(() => {
    requestSeq += 1
  })

  const dimensionsCount = computed(() => catalog.value?.dimensions.length ?? 0)

  async function loadCatalog(): Promise<void> {
    if (catalog.value || catalogLoading.value) return
    catalogLoading.value = true
    try {
      catalog.value = await getResearchCatalog()
    } catch (caught: unknown) {
      error.value = toErrorMessage(caught, '研究目录加载失败')
    } finally {
      catalogLoading.value = false
    }
  }

  async function loadProfile(code: string, budget: ResearchBudget): Promise<boolean> {
    const seq = ++requestSeq
    loading.value = true
    error.value = ''
    try {
      if (!catalog.value) await loadCatalog()
      const next = await getResearchProfile(code, budget)
      if (seq !== requestSeq) return false
      profile.value = next
      archivedRun.value = null
      activeRun.value = null
      return true
    } catch (caught: unknown) {
      if (seq !== requestSeq) return false
      profile.value = null
      error.value = toErrorMessage(caught, '研究剖面加载失败')
      return false
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }

  async function archiveProfile(code: string, budget: ResearchBudget): Promise<boolean> {
    if (archiveLoading.value) return false
    const seq = ++requestSeq
    archiveLoading.value = true
    error.value = ''
    try {
      const result = await createResearchRun({ code, budget })
      if (seq !== requestSeq) return false
      profile.value = result.profile
      archivedRun.value = result.run
      activeRun.value = result.run
      runs.value = [result.run, ...runs.value.filter((item) => item.id !== result.run.id)]
      return true
    } catch (caught: unknown) {
      if (seq !== requestSeq) return false
      error.value = toErrorMessage(caught, '研究快照归档失败')
      return false
    } finally {
      archiveLoading.value = false
    }
  }

  async function loadRun(runId: string): Promise<boolean> {
    const id = runId.trim()
    if (!id) {
      error.value = '请输入研究 run id'
      return false
    }
    const seq = ++requestSeq
    runLoading.value = true
    error.value = ''
    try {
      const result = await getResearchRun(id)
      if (seq !== requestSeq) return false
      profile.value = result.profile
      activeRun.value = result.run
      runs.value = [result.run, ...runs.value.filter((item) => item.id !== result.run.id)]
      return true
    } catch (caught: unknown) {
      if (seq !== requestSeq) return false
      error.value = toErrorMessage(caught, '研究 run 读取失败')
      return false
    } finally {
      if (seq === requestSeq) runLoading.value = false
    }
  }

  async function resumeRun(runId: string): Promise<boolean> {
    const id = runId.trim()
    if (!id || runLoading.value) return false
    const seq = ++requestSeq
    runLoading.value = true
    error.value = ''
    try {
      const result = await resumeResearchRun(id)
      if (seq !== requestSeq) return false
      profile.value = result.profile
      activeRun.value = result.run
      runs.value = [result.run, ...runs.value.filter((item) => item.id !== result.run.id)]
      return true
    } catch (caught: unknown) {
      if (seq !== requestSeq) return false
      error.value = toErrorMessage(caught, '研究 run 恢复失败')
      return false
    } finally {
      if (seq === requestSeq) runLoading.value = false
    }
  }

  return {
    catalog,
    profile,
    loading,
    archiveLoading,
    runLoading,
    catalogLoading,
    error,
    archivedRun,
    activeRun,
    runs,
    dimensionsCount,
    loadCatalog,
    loadProfile,
    archiveProfile,
    loadRun,
    resumeRun,
  }
}
