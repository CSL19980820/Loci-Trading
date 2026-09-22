import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import {
  CapabilityUnavailableError,
  createScreenSkill,
  deleteScreenSkill,
  generateScreenSkill,
  getProviders,
  getScreenSkill,
  getScreenSkillCatalog,
  getScreenSkills,
  getUniversePresets,
  getUniverseStats,
  previewScreenSkill,
  updateScreenSkill,
} from '@/shared/api/quant'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import { enabledModelOptions } from '@/shared/lib/llm'
import { useScreenRunStore } from '@/shared/stores/screenRun'
import type {
  LlmProvider,
  ScreenResult,
  ScreenSkillCatalog,
  ScreenSkillCatalogSnippet,
  ScreenSkillGenerateRequest,
  ScreenSkillPreviewResponse,
  ScreenSkillRuntime,
  StrategyInfo,
  UniversePreset,
  UniverseStats,
} from '@/shared/types/quant'

import type { DockTab } from '../components/ScreenWorkbenchDock.vue'
import {
  blankLogicRow,
  blankParamRow,
  blankReferenceRow,
  buildScreenSkillPayload,
  buildScreenSkillReferences,
  createEmptyScreenSkillDraft,
  draftFromGeneratedSkill,
  draftFromScreenSkill,
  isCurrentSkillLoad,
  type ScreenSkillDraftModel,
  type ScreenSkillDraftSource,
} from './screenSkillDraft'
import { createCegaoSelectActions } from './screenSkillCegaoSelect'
import {
  applyTrialPreview,
  ensureDraftIdentity,
  openGlobalAssistant,
} from './screenSkillCegaoTrial'
import {
  fieldErrorMap,
  firstIssueTab,
  issuesFromMessages,
  tabIssueCounts,
  type WorkbenchPane,
} from './screenSkillDraftIssues'
import {
  applyCatalogSnippet,
  applyImportedSource,
  buildAiRevisionInstruction,
  SCREEN_FALLBACK_FIELDS,
  switchScreenSkillRuntime,
} from './screenSkillWorkbench'

import { useVisitorMode } from '@/shared/composables/useAccess'

export function useScreenSkillWorkbenchPage() {
  const visitor = useVisitorMode()
  const route = useRoute()
  const router = useRouter()
  const screenRun = useScreenRunStore()

  const editor = ref<{ insertText: (text: string) => void; focusLine: (line: number) => void } | null>(null)
  const providers = ref<LlmProvider[]>([])
  const catalog = ref<ScreenSkillCatalog | null>(null)
  const universePresets = ref<UniversePreset[]>([])
  const universeStats = ref<UniverseStats | null>(null)
  const strategies = ref<StrategyInfo[]>([])
  const loading = ref(false)
  const catalogLoading = ref(false)
  const busy = ref(false)
  const previewBusy = ref(false)
  const screenBusy = ref(false)
  const error = ref('')
  const conflict = ref('')
  const preview = ref<ScreenSkillPreviewResponse | null>(null)
  const screenResult = ref<ScreenResult | null>(null)
  const trialPassed = ref(false)
  const trialAt = ref('')
  const workbenchTab = ref<WorkbenchPane>('formula')
  const fieldErrors = ref<Record<string, string>>({})
  const tabErrors = ref<Partial<Record<WorkbenchPane, number>>>({})
  const importOpen = ref(false)
  const catalogOpen = ref(false)
  const selectOpen = ref(false)
  const assistOpen = ref(false)
  const dockOpen = ref(false)
  const dockTab = ref<DockTab>('explain')
  const backtestOpen = ref(false)
  let latestSkillLoadToken = 0

  const draft = reactive(createEmptyScreenSkillDraft())
  const generationForm = reactive({ source: '', provider: '', model: '', thinking: '' })
  const isEditing = computed(() => Boolean(route.query.slug))
  const currentSlug = computed(() => String(route.query.slug ?? draft.slug).trim())
  const hasBody = computed(() =>
    draft.runtime === 'python' ? Boolean(draft.code.trim()) : Boolean(draft.formula.trim()),
  )
  const providerModels = computed(() =>
    enabledModelOptions(providers.value.find((item) => item.name === generationForm.provider)),
  )
  const referenceBuild = computed(() => buildScreenSkillReferences(draft))
  const referencesReady = computed(
    () => referenceBuild.value.references.length > 0 && referenceBuild.value.errors.length === 0,
  )
  const fieldOptions = computed(() => {
    if (!catalog.value?.fields.length) return SCREEN_FALLBACK_FIELDS
    return catalog.value.fields.map((item) => ({
      label: `${item.label} · ${item.name}`,
      value: item.name,
    }))
  })
  const requiredFields = computed(() =>
    (preview.value?.derived?.required_fields ?? []).filter(
      (field) => !draft.dataFields.includes(field),
    ),
  )

  const statusTone = computed<'neutral' | 'ok' | 'error'>(() => {
    if (!preview.value) return 'neutral'
    if (!preview.value.ok || preview.value.diagnostics.some((d) => d.severity === 'error')) return 'error'
    if (trialPassed.value) return 'ok'
    return 'neutral'
  })
  const statusLeft = computed(() => {
    if (previewBusy.value) return '试跑中…'
    if (!preview.value) return '尚未编译'
    if (!preview.value.ok) {
      const first = preview.value.diagnostics.find((d) => d.severity === 'error')
      return first ? `试跑失败 · ${first.message}` : '试跑失败'
    }
    return trialPassed.value ? '试跑通过' : '已编译'
  })
  const statusRight = computed(() => {
    if (trialPassed.value && trialAt.value) return trialAt.value
    return '尚未试跑'
  })

  function cloneDraft(source: ScreenSkillDraftModel): ScreenSkillDraftModel {
    return {
      ...source,
      params: source.params.map((row) => ({ ...row })),
      logic: source.logic.map((row) => ({ ...row })),
      references: source.references.map((row) => ({ ...row })),
      dataFields: [...source.dataFields],
      boards: [...source.boards],
    }
  }

  function applyDraft(source: ScreenSkillDraftModel): void {
    const next = cloneDraft(source)
    Object.assign(draft, next)
    draft.params = next.params
    draft.logic = next.logic
    draft.references = next.references
    draft.dataFields = next.dataFields
    draft.boards = next.boards
  }

  function parseLegacySource(raw: unknown): ScreenSkillDraftSource {
    if (raw === 'description' || raw === 'tdx' || raw === 'ths' || raw === 'python') return raw
    return 'blank'
  }

  function clearTrial(): void {
    trialPassed.value = false
    trialAt.value = ''
  }

  function resetDraft(source: ScreenSkillDraftSource = 'blank'): void {
    applyDraft(createEmptyScreenSkillDraft(source))
    preview.value = null
    screenResult.value = null
    clearTrial()
    dockOpen.value = false
    error.value = ''
    conflict.value = ''
    generationForm.source = ''
  }

  function openSettings(tab: WorkbenchPane = 'strategy'): void {
    workbenchTab.value = tab
  }

  function clearFieldErrors(): void {
    fieldErrors.value = {}
    tabErrors.value = {}
  }

  function applyDraftIssues(messages: string[]): void {
    const issues = issuesFromMessages(messages)
    fieldErrors.value = fieldErrorMap(issues)
    tabErrors.value = tabIssueCounts(issues)
    workbenchTab.value = firstIssueTab(issues)
    error.value = messages[0] ?? '草稿不完整'
  }

  function setRuntime(runtime: ScreenSkillRuntime): void {
    switchScreenSkillRuntime(draft, runtime)
    preview.value = null
    clearTrial()
  }

  async function loadProviders(): Promise<void> {
    providers.value = visitor.value ? [] : await getProviders().catch(() => [])
    if (!generationForm.provider && providers.value.length) {
      generationForm.provider =
        providers.value.find((item) => item.is_default)?.name || providers.value[0]!.name
    }
  }

  async function loadCatalog(): Promise<void> {
    catalogLoading.value = true
    catalog.value = await getScreenSkillCatalog().catch(() => null)
    catalogLoading.value = false
  }

  async function loadUniverseMeta(): Promise<void> {
    universePresets.value = await getUniversePresets().catch(() => [])
    universeStats.value = await getUniverseStats().catch(() => null)
  }

  async function loadStrategies(): Promise<void> {
    strategies.value = await getScreenSkills().catch(() => [])
  }

  async function loadCurrentSkill(slug: string): Promise<void> {
    const token = ++latestSkillLoadToken
    loading.value = true
    error.value = ''
    conflict.value = ''
    try {
      const detail = await getScreenSkill(slug)
      if (!isCurrentSkillLoad(token, latestSkillLoadToken, slug, String(route.query.slug ?? '').trim())) return
      applyDraft(draftFromScreenSkill(detail))
      preview.value = null
      screenResult.value = null
      clearTrial()
    } catch (caught: unknown) {
      if (!isCurrentSkillLoad(token, latestSkillLoadToken, slug, String(route.query.slug ?? '').trim())) return
      error.value = toErrorMessage(caught, `加载战法 ${slug} 失败`)
    } finally {
      if (token === latestSkillLoadToken) loading.value = false
    }
  }

  async function syncFromRoute(): Promise<void> {
    const slug = String(route.query.slug ?? '').trim()
    if (slug) {
      await loadCurrentSkill(slug)
      return
    }
    latestSkillLoadToken += 1
    loading.value = false
    resetDraft(parseLegacySource(route.query.source))
  }

  async function startNew(): Promise<void> {
    if (route.query.slug || route.query.source) await router.replace({ query: {} })
    else resetDraft()
  }

  async function guard<T>(task: () => Promise<T>, previewTask = false): Promise<T | null> {
    if (previewTask) previewBusy.value = true
    else busy.value = true
    error.value = ''
    conflict.value = ''
    try {
      return await task()
    } catch (caught: unknown) {
      if ((caught as { status?: number }).status === 409) {
        conflict.value = toErrorMessage(caught, '服务器版本已变化，请重新加载后再保存。')
        return null
      }
      error.value =
        caught instanceof CapabilityUnavailableError
          ? caught.message
          : toErrorMessage(caught, previewTask ? '试跑失败' : '操作失败')
      return null
    } finally {
      if (previewTask) previewBusy.value = false
      else busy.value = false
    }
  }

  function builtPayload() {
    ensureDraftIdentity(draft)
    const built = buildScreenSkillPayload(draft)
    if (built.payload) {
      clearFieldErrors()
      return built.payload
    }
    preview.value = {
      ok: false,
      diagnostics: built.errors.map((message, index) => ({
        code: `LOCAL_${index + 1}`,
        severity: 'error',
        message,
      })),
    }
    trialPassed.value = false
    applyDraftIssues(built.errors)
    if (workbenchTab.value === 'formula') {
      dockOpen.value = true
      dockTab.value = 'diag'
    }
    return null
  }

  function markTrialFromPreview(result: ScreenSkillPreviewResponse): boolean {
    return applyTrialPreview({
      result,
      draft,
      preview,
      trialPassed,
      trialAt,
      dockOpen,
      dockTab,
      clearTrial,
    })
  }

  async function handleTrial(): Promise<void> {
    if (!hasBody.value) {
      toast.warning('先写点公式')
      return
    }
    const payload = builtPayload()
    if (!payload) return
    const result = await guard(() => previewScreenSkill(payload), true)
    if (!result) return
    const ok = markTrialFromPreview(result)
    toast.success(ok ? '试跑通过' : '试跑未通过，请看诊断')
  }

  async function handleGenerate(): Promise<void> {
    if (!generationForm.source.trim()) {
      error.value = '请先填写要生成或修改的策略要求。'
      return
    }
    if (!referencesReady.value) {
      const messages = referenceBuild.value.errors.length
        ? referenceBuild.value.errors
        : ['AI 编写前至少需要一条可追溯资料来源']
      applyDraftIssues(messages)
      return
    }
    const payload: ScreenSkillGenerateRequest = {
      source_type: 'description',
      source: buildAiRevisionInstruction(draft, generationForm.source),
      slug: draft.slug || undefined,
      name: draft.name || undefined,
      description: draft.description || undefined,
      entry_timing: draft.entryTiming,
      runtime: draft.runtime,
      dialect: draft.runtime === 'formula' ? 'loci' : draft.dialect,
      entrypoint: draft.runtime === 'python' ? draft.entrypoint : undefined,
      references: referenceBuild.value.references,
      provider: generationForm.provider || undefined,
      model: generationForm.model || undefined,
      thinking: generationForm.thinking || undefined,
    }
    const result = await guard(() => generateScreenSkill(payload))
    if (!result) return
    applyDraft(draftFromGeneratedSkill(result, cloneDraft(draft)))
    clearTrial()
    preview.value = {
      ok: result.ok,
      diagnostics: result.diagnostics,
      derived: result.derived,
      strategy_revision: result.strategy_revision,
    }
    generationForm.source = ''
    toast.success('AI 建议已应用到当前草稿')
  }

  async function handleSave(): Promise<string | null> {
    const payload = builtPayload()
    if (!payload) return null
    const result =
      isEditing.value && draft.packageRevision
        ? await guard(() =>
            updateScreenSkill(currentSlug.value, {
              ...payload,
              expected_revision: draft.packageRevision,
            }),
          )
        : await guard(() => createScreenSkill(payload))
    if (!result) return null
    applyDraft(draftFromScreenSkill(result))
    toast.success(isEditing.value ? '量化技能已更新' : '量化技能已保存')
    await router.replace({ query: { slug: result.slug } })
    await loadStrategies()
    return result.slug
  }

  async function handleDelete(): Promise<void> {
    if (!currentSlug.value || !draft.packageRevision) return
    const confirmed = await confirmDangerous(
      `确定删除战法「${draft.name || currentSlug.value}」？会进入历史归档。`,
      '删除战法',
      '删除',
    )
    if (!confirmed) return
    const removed = await guard(() => deleteScreenSkill(currentSlug.value, draft.packageRevision))
    if (!removed) return
    toast.success('量化技能已删除')
    await router.replace({ query: {} })
  }

  function insertCatalogText(text: string): void {
    editor.value?.insertText(text)
  }

  function applySnippet(snippet: ScreenSkillCatalogSnippet): void {
    applyCatalogSnippet(draft, snippet)
    preview.value = null
    clearTrial()
    toast.success(`已应用片段：${snippet.title}`)
  }

  function applyPreset(presetId: string): void {
    const preset = universePresets.value.find((item) => item.id === presetId)
    if (!preset) return
    draft.universePreset = preset.id
    draft.boards = [...preset.boards]
    draft.excludeSt = preset.exclude_st
    draft.excludeDelisting = preset.exclude_delisting
    draft.excludeSuspended = preset.exclude_suspended
    draft.minListDays = preset.min_list_days
  }

  function mergeRequiredFields(): void {
    const missing = [...requiredFields.value]
    draft.dataFields = [...new Set([...draft.dataFields, ...missing])]
    if (missing.length) toast.success('已补齐编译所需字段')
  }

  function openAssistant(): void {
    openGlobalAssistant()
  }

  const { runSelect, openBacktest } = createCegaoSelectActions({
    draft,
    trialPassed,
    currentSlug,
    selectOpen,
    screenBusy,
    dockOpen,
    dockTab,
    error,
    screenResult,
    backtestOpen,
    screenRun,
    builtPayload,
    applyPreset,
    markTrialFromPreview,
    handleSave,
    loadStrategies,
  })

  watch(
    () => [draft.formula, draft.code, draft.runtime] as const,
    () => {
      if (trialPassed.value) clearTrial()
    },
  )

  // 进度槽按「租户 × 战法」分片：只认自己这一个，别的战法并行跑着与本页无关
  watch(
    () => screenRun.resultFor(currentSlug.value),
    (result) => {
      if (!result) return
      screenResult.value = result
      dockOpen.value = true
      dockTab.value = 'picks'
      screenBusy.value = false
    },
  )

  watch(
    () => screenRun.isRunning(currentSlug.value),
    (isRunning) => {
      screenBusy.value = isRunning
    },
  )

  watch(
    () => route.fullPath,
    () => void syncFromRoute(),
  )

  onMounted(async () => {
    await Promise.all([loadProviders(), loadCatalog(), loadUniverseMeta(), loadStrategies()])
    await screenRun.hydrate()
    await syncFromRoute()
  })

  return {
    router,
    editor,
    providers,
    catalog,
    universePresets,
    universeStats,
    strategies,
    loading,
    catalogLoading,
    busy,
    previewBusy,
    screenBusy,
    error,
    conflict,
    preview,
    screenResult,
    trialPassed,
    workbenchTab,
    fieldErrors,
    tabErrors,
    importOpen,
    catalogOpen,
    selectOpen,
    assistOpen,
    dockOpen,
    dockTab,
    backtestOpen,
    draft,
    generationForm,
    isEditing,
    currentSlug,
    hasBody,
    providerModels,
    referencesReady,
    fieldOptions,
    requiredFields,
    statusTone,
    statusLeft,
    statusRight,
    openSettings,
    setRuntime,
    loadCurrentSkill,
    startNew,
    handleTrial,
    handleGenerate,
    handleSave,
    handleDelete,
    insertCatalogText,
    applySnippet,
    applyPreset,
    mergeRequiredFields,
    openAssistant,
    runSelect,
    openBacktest,
    applyImportedSource: (source: Parameters<typeof applyImportedSource>[1]) => {
      applyImportedSource(draft, source)
      preview.value = null
      clearTrial()
    },
    blankLogicRow,
    blankParamRow,
    blankReferenceRow,
  }
}
