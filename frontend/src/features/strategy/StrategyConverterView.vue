<script setup lang="ts">
import {
  ArrowLeft,
  Check,
  Delete,
  FolderOpened,
  Operation,
  Setting,
  VideoPlay,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  CapabilityUnavailableError,
  createScreenSkill,
  deleteScreenSkill,
  generateScreenSkill,
  getProviders,
  getScreenSkill,
  getScreenSkillCatalog,
  getUniversePresets,
  getUniverseStats,
  previewScreenSkill,
  updateScreenSkill,
} from '@/shared/api/quant'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import { enabledModelOptions } from '@/shared/lib/llm'
import type {
  LlmProvider,
  ScreenSkillCatalog,
  ScreenSkillCatalogSnippet,
  ScreenSkillGenerateRequest,
  ScreenSkillPreviewResponse,
  ScreenSkillRuntime,
  UniversePreset,
  UniverseStats,
} from '@/shared/types/quant'

import './StrategyConverterView.css'
import ScreenAiCopilot from './components/ScreenAiCopilot.vue'
import ScreenSkillImportDialog from './components/ScreenSkillImportDialog.vue'
import ScreenSkillSettingsDrawer from './components/ScreenSkillSettingsDrawer.vue'
import ScreenSkillTestReport from './components/ScreenSkillTestReport.vue'
import ScreenWorkbenchCatalog from './components/ScreenWorkbenchCatalog.vue'
import ScreenWorkbenchEditor from './components/ScreenWorkbenchEditor.vue'
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
} from './composables/screenSkillDraft'
import {
  applyCatalogSnippet,
  applyImportedSource,
  buildAiRevisionInstruction,
  SCREEN_FALLBACK_FIELDS,
  SCREEN_RUNTIME_OPTIONS,
  switchScreenSkillRuntime,
} from './composables/screenSkillWorkbench'

const route = useRoute()
const router = useRouter()
const editor = ref<{ insertText: (text: string) => void } | null>(null)
const providers = ref<LlmProvider[]>([])
const catalog = ref<ScreenSkillCatalog | null>(null)
const universePresets = ref<UniversePreset[]>([])
const universeStats = ref<UniverseStats | null>(null)
const loading = ref(false)
const catalogLoading = ref(false)
const busy = ref(false)
const previewBusy = ref(false)
const error = ref('')
const conflict = ref('')
const preview = ref<ScreenSkillPreviewResponse | null>(null)
const settingsOpen = ref(false)
const settingsTab = ref('strategy')
const importOpen = ref(false)
const mobileToolsOpen = ref(false)
const mobileToolTab = ref('catalog')
let latestSkillLoadToken = 0

const draft = reactive(createEmptyScreenSkillDraft())
const generationForm = reactive({ source: '', provider: '', model: '', thinking: '' })
const previewForm = reactive({ tradeDate: '', codesText: '' })
const isEditing = computed(() => Boolean(route.query.slug))
const currentSlug = computed(() => String(route.query.slug ?? draft.slug).trim())
const revisionChip = computed(() => draft.strategyRevision.slice(0, 12))
const pageTitle = computed(() => draft.name.trim() || '未命名量化技能')
const runtimeModel = computed<ScreenSkillRuntime>({
  get: () => draft.runtime,
  set: (runtime) => {
    switchScreenSkillRuntime(draft, runtime)
    preview.value = null
  },
})
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
const formulaDialects = computed(() =>
  (catalog.value?.dialects ?? [])
    .filter((item) => item.runtime === 'formula')
    .map((item) => ({ label: item.label, value: item.id })),
)

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

function resetDraft(source: ScreenSkillDraftSource = 'blank'): void {
  applyDraft(createEmptyScreenSkillDraft(source))
  preview.value = null
  error.value = ''
  conflict.value = ''
  generationForm.source = ''
  previewForm.tradeDate = ''
  previewForm.codesText = ''
}

function parseCodes(): string[] | undefined {
  const values = previewForm.codesText
    .split(/[\n,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
  return values.length ? [...new Set(values)] : undefined
}

function openSettings(tab = 'strategy'): void {
  settingsTab.value = tab
  settingsOpen.value = true
}

function openMobileTools(tab: 'catalog' | 'ai' | 'report'): void {
  mobileToolTab.value = tab
  mobileToolsOpen.value = true
}

async function loadProviders(): Promise<void> {
  providers.value = await getProviders().catch(() => [])
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
        : toErrorMessage(caught, previewTask ? '预览失败' : '操作失败')
    return null
  } finally {
    if (previewTask) previewBusy.value = false
    else busy.value = false
  }
}

function builtPayload() {
  const built = buildScreenSkillPayload(draft)
  if (built.payload) return built.payload
  preview.value = {
    ok: false,
    diagnostics: built.errors.map((message, index) => ({
      code: `LOCAL_${index + 1}`,
      severity: 'error',
      message,
    })),
  }
  error.value = built.errors[0] ?? '草稿不完整'
  return null
}

async function handlePreview(withRun: boolean): Promise<void> {
  const payload = builtPayload()
  if (!payload) return
  const result = await guard(
    () =>
      previewScreenSkill({
        ...payload,
        ...(withRun
          ? { run: { trade_date: previewForm.tradeDate || undefined, codes: parseCodes() } }
          : {}),
      }),
    true,
  )
  if (!result) return
  preview.value = result
  if (result.strategy_revision) draft.strategyRevision = result.strategy_revision
  ElMessage.success(withRun ? '试跑完成' : '编译完成')
  if (window.matchMedia('(max-width: 820px)').matches) openMobileTools('report')
}

async function handleGenerate(): Promise<void> {
  if (!generationForm.source.trim()) {
    error.value = '请先填写要生成或修改的策略要求。'
    return
  }
  if (!referencesReady.value) {
    error.value = referenceBuild.value.errors[0] ?? 'AI 编写前至少需要一条可追溯资料来源。'
    openSettings('references')
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
    dialect: draft.dialect,
    entrypoint: draft.runtime === 'python' ? draft.entrypoint : undefined,
    references: referenceBuild.value.references,
    provider: generationForm.provider || undefined,
    model: generationForm.model || undefined,
    thinking: generationForm.thinking || undefined,
  }
  const result = await guard(() => generateScreenSkill(payload))
  if (!result) return
  applyDraft(draftFromGeneratedSkill(result, cloneDraft(draft)))
  preview.value = {
    ok: result.ok,
    diagnostics: result.diagnostics,
    derived: result.derived,
    strategy_revision: result.strategy_revision,
  }
  generationForm.source = ''
  ElMessage.success('AI 建议已应用到当前草稿')
  await handlePreview(false)
}

async function handleSave(): Promise<void> {
  const payload = builtPayload()
  if (!payload) return
  const result =
    isEditing.value && draft.packageRevision
      ? await guard(() =>
          updateScreenSkill(currentSlug.value, {
            ...payload,
            expected_revision: draft.packageRevision,
          }),
        )
      : await guard(() => createScreenSkill(payload))
  if (!result) return
  applyDraft(draftFromScreenSkill(result))
  preview.value = null
  ElMessage.success(isEditing.value ? '量化技能已更新' : '量化技能已保存')
  await router.replace({ query: { slug: result.slug } })
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
  ElMessage.success('量化技能已删除')
  await router.replace({ query: {} })
}

function insertCatalogText(text: string): void {
  editor.value?.insertText(text)
  mobileToolsOpen.value = false
}

function applySnippet(snippet: ScreenSkillCatalogSnippet): void {
  applyCatalogSnippet(draft, snippet)
  preview.value = null
  mobileToolsOpen.value = false
  ElMessage.success(`已应用片段：${snippet.title}`)
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
  if (missing.length) ElMessage.success('已补齐编译所需字段')
}

watch(
  () => route.fullPath,
  () => void syncFromRoute(),
)

onMounted(async () => {
  await Promise.all([loadProviders(), loadCatalog(), loadUniverseMeta()])
  await syncFromRoute()
})
</script>

<template>
  <div class="page-fill workbench-page">
    <header class="workbench-bar">
      <div class="workbench-identity">
        <el-tooltip content="返回量化中心" placement="bottom">
          <el-button text circle :icon="ArrowLeft" aria-label="返回量化中心" @click="router.push('/quant')" />
        </el-tooltip>
        <div class="workbench-name">
          <strong>{{ pageTitle }}</strong>
          <span>{{ draft.slug || '尚未命名 slug' }}</span>
        </div>
        <el-tag v-if="revisionChip" size="small" effect="plain">rev {{ revisionChip }}</el-tag>
      </div>

      <div class="workbench-runtime">
        <el-segmented v-model="runtimeModel" :options="SCREEN_RUNTIME_OPTIONS" size="small" />
        <el-select v-if="draft.runtime === 'formula'" v-model="draft.dialect" size="small" aria-label="公式方言">
          <el-option
            v-for="item in formulaDialects.length ? formulaDialects : [{ label: 'Loci', value: 'loci' }, { label: '通达信', value: 'tdx' }, { label: '同花顺', value: 'ths' }]"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <el-tag v-else size="small" type="success" effect="plain">完整 Python</el-tag>
      </div>

      <div class="workbench-actions">
        <el-button :icon="FolderOpened" aria-label="导入量化技能" @click="importOpen = true">导入</el-button>
        <el-button class="catalog-trigger" :icon="Operation" aria-label="打开函数库" @click="openMobileTools('catalog')">函数库</el-button>
        <el-button class="ai-trigger" aria-label="打开 AI 助手" @click="openMobileTools('ai')">AI</el-button>
        <el-button class="report-trigger" aria-label="打开测试报告" @click="openMobileTools('report')">报告</el-button>
        <el-button :icon="Setting" aria-label="打开策略设置" @click="openSettings()">设置</el-button>
        <el-button :icon="Check" :loading="previewBusy" aria-label="编译量化技能" @click="handlePreview(false)">编译</el-button>
        <el-button :icon="VideoPlay" :loading="previewBusy" aria-label="试跑量化技能" @click="handlePreview(true)">试跑</el-button>
        <el-button type="primary" :loading="busy" aria-label="保存量化技能" @click="handleSave">保存</el-button>
        <el-dropdown trigger="click">
          <el-button text circle :icon="Operation" aria-label="更多操作" />
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="startNew">新建技能</el-dropdown-item>
              <el-dropdown-item
                v-if="isEditing && draft.packageRevision"
                divided
                :icon="Delete"
                @click="handleDelete"
              >
                删除当前技能
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <div v-if="error || conflict" class="workbench-flash">
      <el-alert
        v-if="error"
        :title="error"
        type="error"
        show-icon
        closable
        @close="error = ''"
      />
      <el-alert v-if="conflict" :title="conflict" type="warning" show-icon :closable="false">
        <template #default>
          <el-button size="small" type="primary" @click="loadCurrentSkill(currentSlug)">重新加载</el-button>
        </template>
      </el-alert>
    </div>

    <main class="workbench-shell">
      <aside class="workbench-pane catalog-pane">
        <ScreenWorkbenchCatalog
          :catalog="catalog"
          :runtime="draft.runtime"
          :loading="catalogLoading"
          @insert-text="insertCatalogText"
          @apply-snippet="applySnippet"
        />
      </aside>

      <ScreenWorkbenchEditor ref="editor" :draft="draft" />

      <aside class="workbench-pane copilot-pane">
        <ScreenAiCopilot
          v-model:instruction="generationForm.source"
          v-model:provider="generationForm.provider"
          v-model:model="generationForm.model"
          v-model:thinking="generationForm.thinking"
          :providers="providers"
          :provider-models="providerModels"
          :references-ready="referencesReady"
          :busy="busy"
          @generate="handleGenerate"
        />
        <el-button v-if="!referencesReady" text type="primary" @click="openSettings('references')">
          管理资料来源
        </el-button>
      </aside>
    </main>

    <section class="report-dock">
      <div class="report-dock__toolbar">
        <strong>测试报告</strong>
        <el-date-picker
          v-model="previewForm.tradeDate"
          type="date"
          value-format="YYYY-MM-DD"
          size="small"
          placeholder="最新交易日"
        />
        <el-input
          v-model="previewForm.codesText"
          size="small"
          clearable
          placeholder="限定代码，逗号分隔"
        />
        <el-button class="report-trigger" size="small" @click="openMobileTools('report')">查看报告</el-button>
      </div>
      <div class="report-dock__body">
        <ScreenSkillTestReport :preview="preview" />
      </div>
    </section>

    <PageBusy overlay :busy="loading" label="加载量化技能…" />

    <ScreenSkillSettingsDrawer
      v-model="settingsOpen"
      v-model:active-tab="settingsTab"
      :draft="draft"
      :field-options="fieldOptions"
      :required-fields="requiredFields"
      :presets="universePresets"
      :stats="universeStats"
      @add-logic="draft.logic.push(blankLogicRow())"
      @remove-logic="draft.logic.length === 1 ? (draft.logic[0] = blankLogicRow()) : draft.logic.splice($event, 1)"
      @add-reference="draft.references.push(blankReferenceRow())"
      @remove-reference="draft.references.length === 1 ? (draft.references[0] = blankReferenceRow()) : draft.references.splice($event, 1)"
      @add-param="draft.params.push(blankParamRow())"
      @remove-param="draft.params.length === 1 ? (draft.params[0] = blankParamRow()) : draft.params.splice($event, 1)"
      @apply-preset="applyPreset"
      @merge-required-fields="mergeRequiredFields"
      @runtime-change="runtimeModel = $event"
    />

    <ScreenSkillImportDialog
      v-model="importOpen"
      @apply="applyImportedSource(draft, $event); preview = null"
    />

    <el-drawer
      v-model="mobileToolsOpen"
      title="工作台工具"
      direction="btt"
      size="min(42rem, 86vh)"
      class="mobile-tools"
    >
      <el-tabs v-model="mobileToolTab" class="mobile-tools__tabs">
        <el-tab-pane label="函数与片段" name="catalog">
          <ScreenWorkbenchCatalog
            :catalog="catalog"
            :runtime="draft.runtime"
            :loading="catalogLoading"
            @insert-text="insertCatalogText"
            @apply-snippet="applySnippet"
          />
        </el-tab-pane>
        <el-tab-pane label="AI 助手" name="ai">
          <ScreenAiCopilot
            v-model:instruction="generationForm.source"
            v-model:provider="generationForm.provider"
            v-model:model="generationForm.model"
            v-model:thinking="generationForm.thinking"
            :providers="providers"
            :provider-models="providerModels"
            :references-ready="referencesReady"
            :busy="busy"
            @generate="handleGenerate"
          />
        </el-tab-pane>
        <el-tab-pane label="测试报告" name="report">
          <ScreenSkillTestReport :preview="preview" />
        </el-tab-pane>
      </el-tabs>
    </el-drawer>
  </div>
</template>
