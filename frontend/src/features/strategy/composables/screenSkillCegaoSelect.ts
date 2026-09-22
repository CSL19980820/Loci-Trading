import type { Ref } from 'vue'
import { toast } from 'vue-sonner'

import { previewScreenSkill } from '@/shared/api/quant'
import { confirmAction } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import type { useScreenRunStore } from '@/shared/stores/screenRun'
import type {
  ScreenResult,
  ScreenSkillPreviewResponse,
  ScreenSkillUpsertPayload,
} from '@/shared/types/quant'

import type { DockTab } from '../components/ScreenWorkbenchDock.vue'
import { buildUniverseSpec, type ScreenSkillDraftModel } from './screenSkillDraft'

type ScreenRunStore = ReturnType<typeof useScreenRunStore>

export function createCegaoSelectActions(deps: {
  draft: ScreenSkillDraftModel
  trialPassed: Ref<boolean>
  currentSlug: Ref<string>
  selectOpen: Ref<boolean>
  screenBusy: Ref<boolean>
  dockOpen: Ref<boolean>
  dockTab: Ref<DockTab>
  error: Ref<string>
  screenResult: Ref<ScreenResult | null>
  backtestOpen: Ref<boolean>
  screenRun: ScreenRunStore
  builtPayload: () => ScreenSkillUpsertPayload | null
  applyPreset: (presetId: string) => void
  markTrialFromPreview: (result: ScreenSkillPreviewResponse) => boolean
  handleSave: () => Promise<string | null>
  loadStrategies: () => Promise<void>
}): {
  runSelect: (payload: {
    mode: 'single' | 'range'
    tradeDate: string
    start: string
    end: string
    presetId: string
  }) => Promise<void>
  openBacktest: () => Promise<void>
} {
  async function ensureSavedForScreen(): Promise<string | null> {
    if (deps.currentSlug.value && deps.draft.packageRevision) return deps.currentSlug.value
    const confirmed = await confirmAction({
      message: '选股需要先保存当前公式，是否现在保存？',
      title: '保存后选股',
      confirmText: '保存并选股',
      cancelText: '取消',
    })
    if (!confirmed) return null
    return deps.handleSave()
  }

  async function runSelect(payload: {
    mode: 'single' | 'range'
    tradeDate: string
    start: string
    end: string
    presetId: string
  }): Promise<void> {
    if (!deps.trialPassed.value) {
      toast.warning('先试跑通过再选股')
      return
    }
    if (payload.presetId) deps.applyPreset(payload.presetId)
    const skillPayload = deps.builtPayload()
    if (!skillPayload) return

    deps.selectOpen.value = false
    deps.screenBusy.value = true
    deps.dockOpen.value = true
    deps.dockTab.value = 'picks'
    deps.error.value = ''

    try {
      if (payload.mode === 'single') {
        const result = await previewScreenSkill({
          ...skillPayload,
          run: {
            trade_date: payload.tradeDate || undefined,
            universe: buildUniverseSpec(deps.draft),
          },
        })
        deps.markTrialFromPreview(result)
        deps.screenResult.value = result.run_result ?? null
        const formalCount = result.run_result?.picks?.length ?? 0
        const watchCount = result.run_result?.watch_picks?.length ?? 0
        if (!formalCount && !watchCount) toast.info('这个范围没有选出股票')
        else toast.success(`正式 ${formalCount} 只，低吸观察 ${watchCount} 只`)
        return
      }

      const slug = await ensureSavedForScreen()
      if (!slug) return
      const outcome = await deps.screenRun.start({
        strategy: slug,
        start: payload.start,
        end: payload.end,
        record_candidates: false,
      })
      if (outcome === 'busy') {
        toast.warning(deps.screenRun.lastError || '已有选股任务在跑')
        return
      }
      if (outcome === 'error') {
        toast.error(deps.screenRun.lastError || '选股启动失败')
        return
      }
      toast.success('区间选股已开始')
    } catch (caught: unknown) {
      deps.error.value = toErrorMessage(caught, '选股失败')
      toast.error(deps.error.value)
    } finally {
      deps.screenBusy.value = false
    }
  }

  async function openBacktest(): Promise<void> {
    if (!deps.trialPassed.value && !deps.currentSlug.value) {
      toast.warning('先试跑或保存后再回测')
      return
    }
    if (!deps.currentSlug.value || !deps.draft.packageRevision) {
      const slug = await ensureSavedForScreen()
      if (!slug) return
    }
    await deps.loadStrategies()
    deps.backtestOpen.value = true
    deps.dockOpen.value = true
    deps.dockTab.value = 'bt'
  }

  return { runSelect, openBacktest }
}
