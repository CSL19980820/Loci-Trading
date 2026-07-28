import { computed, ref } from 'vue'

import { CapabilityUnavailableError, awaitJobResult, startAnalysis } from '@/shared/api/quant'
import type { CompareResult, OptimizeResult } from '@/shared/types/quant'

export function useQuantAnalysis(setUnavailable: (msg: string) => void) {
  const compareResult = ref<CompareResult | null>(null)
  const optimizeResult = ref<OptimizeResult | null>(null)
  const optimizeExpanded = ref(false)
  const analysisBusy = ref(false)
  const analysisLabel = ref('')
  const optimizeTarget = ref('')
  const analysisStart = ref('2025-01-01')

  const optimizeRowsShown = computed(() => {
    const rows = optimizeResult.value?.rows ?? []
    if (optimizeExpanded.value || rows.length <= 12) return rows
    return rows.slice(0, 12)
  })

  async function runAnalysis(kind: 'compare' | 'optimize', payload: Record<string, unknown>): Promise<unknown> {
    analysisBusy.value = true
    analysisLabel.value = kind === 'compare' ? '横向对比' : '退出扫描'
    setUnavailable('')
    compareResult.value = null
    optimizeResult.value = null
    try {
      const started = await startAnalysis(kind, payload)
      const run = await awaitJobResult(started.job_id)
      if (run.status === 'failed') {
        setUnavailable(run.error_text.split('\n')[0] || '分析失败')
        return null
      }
      return run.result
    } catch (caught: unknown) {
      setUnavailable(
        caught instanceof CapabilityUnavailableError
          ? caught.message
          : caught instanceof Error
            ? caught.message
            : '分析失败',
      )
      return null
    } finally {
      analysisBusy.value = false
      analysisLabel.value = ''
    }
  }

  async function runCompare(): Promise<void> {
    const result = await runAnalysis('compare', { start: analysisStart.value, holds: [1, 3] })
    if (result) {
      compareResult.value = result as CompareResult
      try {
        sessionStorage.setItem('quant-compare', JSON.stringify(result))
      } catch {
        /* ignore quota */
      }
    }
  }

  async function runOptimize(): Promise<void> {
    if (!optimizeTarget.value) return
    const result = await runAnalysis('optimize', {
      strategy: optimizeTarget.value,
      start: analysisStart.value,
      holds: [1, 2, 3, 5],
      targets: [0, 3, 5, 8],
      stops: [0, -5, -8],
    })
    if (result) {
      optimizeResult.value = result as OptimizeResult
      try {
        sessionStorage.setItem('quant-optimize', JSON.stringify(result))
      } catch {
        /* ignore quota */
      }
    }
  }

  function restoreAnalysisResults(): void {
    try {
      const raw = sessionStorage.getItem('quant-compare')
      if (raw) compareResult.value = JSON.parse(raw) as CompareResult
    } catch {
      sessionStorage.removeItem('quant-compare')
    }
    try {
      const raw = sessionStorage.getItem('quant-optimize')
      if (raw) optimizeResult.value = JSON.parse(raw) as OptimizeResult
    } catch {
      sessionStorage.removeItem('quant-optimize')
    }
  }

  function clearAnalysisResults(): void {
    compareResult.value = null
    optimizeResult.value = null
    sessionStorage.removeItem('quant-compare')
    sessionStorage.removeItem('quant-optimize')
  }

  return {
    compareResult,
    optimizeResult,
    optimizeExpanded,
    optimizeRowsShown,
    analysisBusy,
    analysisLabel,
    optimizeTarget,
    analysisStart,
    runCompare,
    runOptimize,
    restoreAnalysisResults,
    clearAnalysisResults,
  }
}
