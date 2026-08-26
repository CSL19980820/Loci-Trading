import type { Ref } from 'vue'

import type { ScreenSkillPreviewResponse } from '@/shared/types/quant'

import type { DockTab } from '../components/ScreenWorkbenchDock.vue'
import type { ScreenSkillDraftModel } from './screenSkillDraft'

/** 试跑/保存前仅补齐技术 slug；名称/说明留给表单校验引导，避免 silently 填空。 */
export function ensureDraftIdentity(draft: ScreenSkillDraftModel): void {
  if (!draft.slug.trim()) {
    draft.slug = `f_${Date.now().toString(36)}`
  }
  if (draft.runtime === 'formula' && (draft.dialect === 'tdx' || draft.dialect === 'ths')) {
    draft.dialect = 'loci'
  }
}

export function applyTrialPreview(options: {
  result: ScreenSkillPreviewResponse
  draft: ScreenSkillDraftModel
  preview: Ref<ScreenSkillPreviewResponse | null>
  trialPassed: Ref<boolean>
  trialAt: Ref<string>
  dockOpen: Ref<boolean>
  dockTab: Ref<DockTab>
  clearTrial: () => void
}): boolean {
  const { result, draft, preview, trialPassed, trialAt, dockOpen, dockTab, clearTrial } = options
  preview.value = result
  if (result.strategy_revision) draft.strategyRevision = result.strategy_revision
  const failed = !result.ok || result.diagnostics.some((item) => item.severity === 'error')
  if (failed) {
    clearTrial()
    dockOpen.value = true
    dockTab.value = 'diag'
    return false
  }
  trialPassed.value = true
  trialAt.value = new Date().toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
  dockOpen.value = true
  dockTab.value = 'explain'
  return true
}

export function openGlobalAssistant(): void {
  window.dispatchEvent(new CustomEvent('loci:assistant-open'))
}
