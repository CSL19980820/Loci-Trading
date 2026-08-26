/**
 * 盘面短线情报条：只读 GET /intel/brief（intel_snapshots）。
 * 无缓存诚实空态；不现场调 MCP。
 */
import { ref, watch, type Ref } from 'vue'

import { getIntelBrief, type IntelBrief } from '@/shared/api/quant_intel'
import { toErrorMessage } from '@/shared/lib/errors'

export function usePulseIntelBrief(tradeDate: Ref<string>) {
  const brief = ref<IntelBrief | null>(null)
  const briefError = ref('')
  const briefLoading = ref(false)
  let generation = 0

  async function loadBrief(): Promise<void> {
    const token = ++generation
    briefLoading.value = true
    briefError.value = ''
    try {
      const day = tradeDate.value.trim()
      const next = await getIntelBrief(day || undefined)
      if (token !== generation) return
      brief.value = next
    } catch (caught: unknown) {
      if (token !== generation) return
      // 可选能力：失败给空摘要，不打断盘面
      brief.value = {
        trade_date: tradeDate.value.trim(),
        available: false,
        fetched_at: null,
        emotion: null,
        themes: [],
        ladder: null,
        tools: {},
        source: 'intel_snapshots',
        optional: true,
        note: '情报暂不可用（已忽略）；不影响盘面主体',
      }
      briefError.value = toErrorMessage(caught, '短线情报加载失败')
    } finally {
      if (token === generation) briefLoading.value = false
    }
  }

  watch(
    tradeDate,
    () => {
      void loadBrief()
    },
    { immediate: true },
  )

  return { brief, briefError, briefLoading, loadBrief }
}
