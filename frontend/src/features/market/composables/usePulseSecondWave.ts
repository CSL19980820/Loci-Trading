/**
 * 盘面二波监测：读上一轮扫描快照，盘中轮询叠当日现价。
 */
import { ref } from 'vue'

import { getSecondWaveLatest, type SecondWaveLatest } from '@/shared/api/quant_ops'
import { useLivePolling } from '@/shared/composables/useLivePolling'
import { toErrorMessage } from '@/shared/lib/errors'

import { SECOND_WAVE_SLUG } from './pulseSecondWaveLogic'

export function usePulseSecondWave() {
  const wave = ref<SecondWaveLatest | null>(null)
  const waveError = ref('')
  const waveLoading = ref(false)
  let generation = 0

  async function loadWave(silent = false): Promise<void> {
    const token = ++generation
    if (!silent) {
      waveLoading.value = true
      waveError.value = ''
    }
    try {
      const next = await getSecondWaveLatest(SECOND_WAVE_SLUG)
      if (token !== generation) return
      wave.value = next
      waveError.value = ''
    } catch (caught: unknown) {
      if (token !== generation) return
      if (!silent) wave.value = null
      waveError.value = toErrorMessage(caught, '二波监测加载失败')
    } finally {
      if (token === generation && !silent) waveLoading.value = false
    }
  }

  useLivePolling({
    intervalMs: 30_000,
    tick: () => loadWave(wave.value != null),
  })

  return { wave, waveError, waveLoading, loadWave }
}
