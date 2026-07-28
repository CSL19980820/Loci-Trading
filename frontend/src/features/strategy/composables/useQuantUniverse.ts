import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { getUniversePresets, getUniverseStats, previewUniverse } from '@/shared/api/quant'
import type { BoardBucket, UniversePreset, UniverseSpec, UniverseStats } from '@/shared/types/quant'

import { formatFunnel } from './quantFormat'

export function useQuantUniverse() {
  const universePresets = ref<UniversePreset[]>([])
  const universeStats = ref<UniverseStats | null>(null)
  const universePreset = ref('default_a_share')
  const universeBoards = ref<BoardBucket[]>(['main', 'chi_next', 'star'])
  const excludeSt = ref(true)
  const previewCount = ref<number | null>(null)
  const previewFunnel = ref<Record<string, number> | null>(null)

  const previewFunnelText = computed(() => formatFunnel(previewFunnel.value))

  function currentUniverse(): UniverseSpec {
    return {
      preset: universePreset.value === 'custom' ? 'custom' : universePreset.value,
      boards: [...universeBoards.value],
      exclude_st: excludeSt.value,
    }
  }

  function applyPreset(id: string): void {
    const found = universePresets.value.find((item) => item.id === id)
    if (!found) return
    universeBoards.value = [...found.boards]
    excludeSt.value = found.exclude_st
    previewCount.value = null
    previewFunnel.value = null
  }

  function onBoardsChange(values: string[] | BoardBucket[]): void {
    if (!values.length) {
      ElMessage.warning('至少保留一个板块')
      universeBoards.value = ['main']
    }
    universePreset.value = 'custom'
    previewCount.value = null
    previewFunnel.value = null
  }

  function onExcludeStChange(): void {
    universePreset.value = 'custom'
    previewCount.value = null
    previewFunnel.value = null
  }

  async function previewPool(): Promise<void> {
    const result = await previewUniverse(currentUniverse())
    previewCount.value = result.code_count
    previewFunnel.value = result.universe_funnel as unknown as Record<string, number>
  }

  async function loadUniverseMeta(): Promise<void> {
    const [presets, stats] = await Promise.all([getUniversePresets(), getUniverseStats()])
    universePresets.value = presets
    universeStats.value = stats
    if (!presets.some((item) => item.id === universePreset.value)) {
      universePreset.value = 'default_a_share'
    }
    applyPreset(universePreset.value)
  }

  return {
    universePresets,
    universeStats,
    universePreset,
    universeBoards,
    excludeSt,
    previewCount,
    previewFunnelText,
    currentUniverse,
    applyPreset,
    onBoardsChange,
    onExcludeStChange,
    previewPool,
    loadUniverseMeta,
  }
}
