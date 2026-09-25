<script setup lang="ts">
import { useId } from 'vue'
const strategyPanelId = useId()
const strategyPaneId = useId()
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/shared/components/ui/resizable'
import { Spinner } from '@/shared/components/ui/spinner'
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import {
  ArrowLeft,
  ChartLine,
  CircleAlert,
  Ellipsis,
  FileCheck,
  FolderOpen,
  Library,
  PanelRight,
  Play,
  Search,
  Sparkles,
  TriangleAlert,
  Trash2,
  X,
} from '@lucide/vue'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
const mobile = useMobileLayout()

import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { Input } from '@/shared/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'

import QuantBacktestPanel from './components/QuantBacktestPanel.vue'
import ScreenAiCopilot from './components/ScreenAiCopilot.vue'
import ScreenCatalogDialog from './components/ScreenCatalogDialog.vue'
import ScreenSelectDialog from './components/ScreenSelectDialog.vue'
import ScreenSkillCodePanel from './components/ScreenSkillCodePanel.vue'
import ScreenSkillDataPanel from './components/ScreenSkillDataPanel.vue'
import ScreenSkillImportDialog from './components/ScreenSkillImportDialog.vue'
import ScreenSkillLogicPanel from './components/ScreenSkillLogicPanel.vue'
import ScreenSkillReferencesPanel from './components/ScreenSkillReferencesPanel.vue'
import ScreenWorkbenchDock, { type DockTab } from './components/ScreenWorkbenchDock.vue'
import ScreenWorkbenchEditor from './components/ScreenWorkbenchEditor.vue'
import { useScreenSkillWorkbenchPage } from './composables/useScreenSkillWorkbenchPage'

const {
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
  referenceCount,
  freshDraft,
  generationSeq,
  generating,
  fieldOptions,
  requiredFields,
  statusTone,
  statusLeft,
  statusRight,
  openSettings,
  setRuntime,
  loadCurrentSkill,
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
  applyImportedSource,
  blankLogicRow,
  blankParamRow,
  blankReferenceRow,
} = useScreenSkillWorkbenchPage()

const narrow = useMediaQuery('(max-width: 980px)')
const route = useRoute()

const workbenchTabs = computed<PageTabItem[]>(() => [
  { name: 'formula', label: '公式', badge: tabErrors.value.formula || undefined },
  { name: 'strategy', label: '策略', badge: tabErrors.value.strategy || undefined },
  { name: 'data', label: '数据', badge: tabErrors.value.data || undefined },
  { name: 'params', label: '参数', badge: tabErrors.value.params || undefined },
  { name: 'references', label: '资料', badge: tabErrors.value.references || undefined },
])

const editorLineCount = computed(() => {
  const body = draft.runtime === 'python' ? draft.code : draft.formula
  return Math.max(1, body.split('\n').length)
})
const fieldCount = computed(() => draft.dataFields.length)
const paramCount = computed(() => draft.params.filter((item) => item.key.trim()).length)
const runtimeLabel = computed(() => (draft.runtime === 'python' ? 'Python 脚本' : 'Loci 公式'))

/**
 * 右侧输出栏（结果坞）的显隐：桌面默认常开成双栏；用户可收起，一旦试跑 / 选股
 * 有了新结果（composable 把 dockOpen 拨成 true）就自动再展开。
 * ≤980 没有并排的空间，改成「编辑器 / 结果」两页药片切换。
 */
const sideCollapsed = ref(false)
const mobilePane = ref<'editor' | 'side'>('editor')
const sideVisible = computed(() => (narrow.value ? mobilePane.value === 'side' : !sideCollapsed.value))

const paneItems: PageTabItem[] = [
  { name: 'editor', label: '编辑器' },
  { name: 'side', label: '结果' },
]
const paneModel = computed({
  get: () => mobilePane.value,
  set: (value: string) => {
    mobilePane.value = value === 'side' ? 'side' : 'editor'
  },
})

/** 助手是输出栏里的一枚 tab：`assistOpen` 与 `dockTab` 二选一映射 */
const sideTab = computed<DockTab>({
  get: () => (assistOpen.value ? 'assist' : dockTab.value),
  set: (value) => {
    if (value === 'assist') {
      assistOpen.value = true
      return
    }
    assistOpen.value = false
    dockTab.value = value
  },
})

watch(dockOpen, (open) => {
  if (!open) return
  sideCollapsed.value = false
  assistOpen.value = false
  mobilePane.value = 'side'
})

watch(dockTab, () => {
  if (dockOpen.value) assistOpen.value = false
})

/* 新建策稿默认把「AI 编写」摆在右栏；从工坊「AI 草稿」进来同理 */
onMounted(() => {
  if (visitor.value) return
  if (route.query.source === 'description' || !route.query.slug) {
    assistOpen.value = true
    sideCollapsed.value = false
    if (route.query.source === 'description') mobilePane.value = 'side'
  }
})

/* 生成完成：输出栏切到解释 / 诊断，让结果先被看见 */
watch(generationSeq, () => {
  assistOpen.value = false
  sideCollapsed.value = false
  mobilePane.value = narrow.value ? 'editor' : 'side'
})

function toggleAssist(): void {
  if (assistOpen.value) {
    assistOpen.value = false
    return
  }
  workbenchTab.value = 'formula'
  assistOpen.value = true
  sideCollapsed.value = false
  mobilePane.value = 'side'
}

function toggleSide(): void {
  if (narrow.value) {
    mobilePane.value = mobilePane.value === 'side' ? 'editor' : 'side'
    return
  }
  sideCollapsed.value = !sideCollapsed.value
}

function closeSide(): void {
  if (narrow.value) mobilePane.value = 'editor'
  else sideCollapsed.value = true
}
</script>

<template>
  <div class="workbench-page page-fill flex h-full min-h-0 flex-1 flex-col overflow-hidden">
    <header v-if="mobile" class="formula-phone-header">
      <Button access="read" as-child variant="ghost" size="icon"><RouterLink to="/quant" aria-label="返回工坊"><ArrowLeft /></RouterLink></Button>
      <Input v-model="draft.name" :readonly="visitor" maxlength="64" placeholder="未命名公式" aria-label="公式名称" />
      <Button variant="ghost" size="icon" aria-label="试跑" :disabled="!hasBody || previewBusy" @click="handleTrial"><Spinner v-if="previewBusy" class="animate-spin" /><Play v-else /></Button>
      <Button size="sm" aria-label="保存" :disabled="busy" @click="handleSave">保存</Button>
      <DropdownMenu><DropdownMenuTrigger as-child><Button access="read" variant="ghost" size="icon" aria-label="策稿操作"><Ellipsis /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
        <DropdownMenuItem :disabled="!trialPassed || screenBusy" @select="selectOpen = true"><Search />选股</DropdownMenuItem>
        <DropdownMenuItem @select="toggleAssist"><Sparkles />{{ assistOpen ? '收起 AI 编写' : 'AI 编写' }}</DropdownMenuItem>
        <DropdownMenuItem access="read" @select="catalogOpen = true"><Library />函数词典</DropdownMenuItem>
        <DropdownMenuItem :disabled="!trialPassed && !currentSlug" @select="openBacktest"><ChartLine />回测</DropdownMenuItem>
        <DropdownMenuItem @select="importOpen = true"><FolderOpen />导入</DropdownMenuItem>
        <DropdownMenuItem v-if="isEditing && draft.packageRevision" variant="destructive" @select="handleDelete"><Trash2 />删除公式</DropdownMenuItem>
      </DropdownMenuContent></DropdownMenu>
    </header>
    <div v-if="mobile" class="formula-phone-navigation"><Select v-model="workbenchTab"><SelectTrigger aria-label="策稿分区"><SelectValue /></SelectTrigger><SelectContent><SelectItem v-for="item in workbenchTabs" :key="item.name" :value="item.name">{{ item.label }}</SelectItem></SelectContent></Select><PageTabs :panel-id="strategyPaneId" v-if="workbenchTab === 'formula'" v-model="paneModel" :items="paneItems" variant="pill" :sticky="false" aria-label="编辑器与结果切换" /><span v-else>{{ paramCount }} 参数 · {{ fieldCount }} 字段</span></div>
    <PageHeader v-else compact :panel-id="strategyPanelId" :tabs="workbenchTabs" v-model:tab="workbenchTab">
      <template #leading><Button access="read" as-child variant="ghost" size="icon-sm"><RouterLink to="/quant" aria-label="返回工坊"><ArrowLeft aria-hidden="true" /></RouterLink></Button></template>
      <template #title>
        <span class="sr-only">策稿台 · {{ draft.name || '未命名公式' }}</span>
        <Input
          v-model="draft.name"
          :readonly="visitor"
          class="workbench-name-input"
          maxlength="64"
          placeholder="未命名公式"
          aria-label="公式名称"
        />
      </template>
      <template #actions>
        <Button
          variant="outline"
          size="sm"
          class="workbench-ai-btn"
          :class="{ 'is-on': assistOpen }"
          :aria-expanded="assistOpen"
          aria-controls="strategy-copilot"
          @click="toggleAssist"
        >
          <Spinner v-if="generating" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <Sparkles v-else aria-hidden="true" />
          AI 编写
        </Button>
        <span class="workbench-actions-sep" aria-hidden="true" />
        <Tooltip :disabled="hasBody">
          <TooltipTrigger as-child>
            <Button variant="outline" size="sm" :disabled="!hasBody || previewBusy" aria-label="试跑" @click="handleTrial">
              <Spinner v-if="previewBusy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              <Play v-else aria-hidden="true" />
              试跑
            </Button>
          </TooltipTrigger>
          <TooltipContent v-if="!hasBody" side="bottom">先写点公式</TooltipContent>
        </Tooltip>
        <Tooltip :disabled="trialPassed">
          <TooltipTrigger as-child>
            <Button variant="outline" size="sm" :disabled="!trialPassed || screenBusy" aria-label="选股" @click="selectOpen = true">
              <Search aria-hidden="true" />
              选股
            </Button>
          </TooltipTrigger>
          <TooltipContent v-if="!trialPassed" side="bottom">先试跑通过再选股</TooltipContent>
        </Tooltip>
        <Button size="sm" aria-label="保存" :disabled="busy" @click="handleSave">
          <Spinner v-if="busy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <FileCheck v-else aria-hidden="true" />
          保存
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="outline" size="icon-sm" aria-label="更多操作">
              <Ellipsis aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem access="read" @select="catalogOpen = true">
              <Library aria-hidden="true" />
              函数词典
            </DropdownMenuItem>
            <DropdownMenuItem :disabled="!trialPassed && !currentSlug" @select="openBacktest">
              <ChartLine aria-hidden="true" />
              回测
            </DropdownMenuItem>
            <DropdownMenuItem @select="importOpen = true">
              <FolderOpen aria-hidden="true" />
              导入
            </DropdownMenuItem>
            <DropdownMenuItem access="read" @select="toggleSide">
              <PanelRight aria-hidden="true" />
              {{ sideVisible ? '收起结果栏' : '展开结果栏' }}
            </DropdownMenuItem>
            <template v-if="isEditing && draft.packageRevision">
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" @select="handleDelete">
                <Trash2 aria-hidden="true" />
                删除当前公式
              </DropdownMenuItem>
            </template>
          </DropdownMenuContent>
        </DropdownMenu>
      </template>
      <template #default>
        <span class="workbench-stat"><b>{{ editorLineCount }}</b> 行</span>
        <span class="workbench-stat"><b>{{ fieldCount }}</b> 字段</span>
        <span class="workbench-stat"><b>{{ paramCount }}</b> 参数</span>
        <span class="workbench-trial" :class="{ 'is-ok': trialPassed }"><i aria-hidden="true" />{{ trialPassed ? '试跑通过' : '未试跑' }}</span>
      </template>
    </PageHeader>

    <div v-if="error || conflict" class="workbench-alerts">
      <Alert v-if="error" variant="destructive">
        <CircleAlert />
        <div class="flex w-full min-w-0 items-start justify-between gap-2">
          <AlertTitle class="line-clamp-none min-w-0">{{ error }}</AlertTitle>
          <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="error = ''">
            <X class="size-3.5" />
          </Button>
        </div>
      </Alert>
      <Alert v-if="conflict">
        <TriangleAlert />
        <div class="flex w-full min-w-0 items-center justify-between gap-2">
          <AlertTitle class="min-w-0">{{ conflict }}</AlertTitle>
          <Button variant="outline" size="sm" class="shrink-0" @click="loadCurrentSkill(currentSlug)">
            重新加载
          </Button>
        </div>
      </Alert>
    </div>

    <div :id="strategyPanelId" :role="!mobile ? 'tabpanel' : undefined" tabindex="0" :aria-labelledby="!mobile ? `${strategyPanelId}-tab-${workbenchTab}` : undefined" class="flex min-h-0 flex-1 flex-col">
    <PageTabs
      :panel-id="strategyPaneId"
      v-if="!mobile && narrow && workbenchTab === 'formula'"
      v-model="paneModel"
      :items="paneItems"
      variant="pill"
      dense
      :sticky="false"
      aria-label="编辑器与结果切换"
      class="workbench-pane-switch"
    />

    <ResizablePanelGroup
      as="main"
      :id="strategyPaneId"
      :role="narrow ? 'tabpanel' : undefined"
      :tabindex="narrow ? 0 : undefined"
      :aria-labelledby="narrow ? `${strategyPaneId}-tab-${paneModel}` : undefined"
      direction="horizontal"
      :auto-save-id="narrow ? null : 'loci-strategy-workbench-v1'"
      v-show="workbenchTab === 'formula'"
      class="workbench-shell"
      :class="{ 'workbench-shell--side': sideVisible, 'workbench-shell--narrow': narrow, 'workbench-shell--bt': sideVisible && sideTab === 'bt' }"
    >
      <ResizablePanel id="strategy-editor" :order="0" :default-size="62" :min-size="30" v-show="!narrow || mobilePane === 'editor'" class="workbench-editor-pane">
      <ScreenWorkbenchEditor
        ref="editor"
        class="workbench-editor"
        :draft="draft"
        :status-left="statusLeft"
        :status-right="statusRight"
        :status-tone="statusTone"
        :generating="generating"
      />

      </ResizablePanel>
      <ResizableHandle v-if="sideVisible && !narrow" aria-label="调整编辑器与结果区宽度" class="workbench-resize-handle" />
      <ResizablePanel v-if="sideVisible" id="strategy-results" :order="1" :default-size="38" :min-size="30" class="workbench-result-pane">
      <ScreenWorkbenchDock
        v-model:active-tab="sideTab"
        class="workbench-side"
        :open="sideVisible"
        :preview="preview"
        :screen-result="screenResult"
        :screen-busy="screenBusy || previewBusy"
        backtest-slot
        assist-slot
        @close="closeSide"
        @focus-line="editor?.focusLine($event)"
      >
        <template #assist>
          <div id="strategy-copilot" class="copilot-pane" aria-label="公式助手">
            <ScreenAiCopilot v-if="!visitor"
              v-model:instruction="generationForm.source"
              v-model:provider="generationForm.provider"
              v-model:model="generationForm.model"
              v-model:thinking="generationForm.thinking"
              compact
              :providers="providers"
              :provider-models="providerModels"
              :references-ready="referencesReady"
              :reference-count="referenceCount"
              :fresh="freshDraft"
              :busy="generating || busy"
              :generating="generating"
              @generate="handleGenerate"
              @manage-references="openSettings('references')"
              @open-assistant="openAssistant"
            />
          </div>
        </template>
        <template #backtest>
          <QuantBacktestPanel
            v-if="backtestOpen || sideTab === 'bt'"
            :strategies="strategies"
            :locked-slug="currentSlug || undefined"
            :locked-name="draft.name || undefined"
          />
        </template>
      </ScreenWorkbenchDock>
      </ResizablePanel>
    </ResizablePanelGroup>

    <fieldset :disabled="visitor" v-show="workbenchTab !== 'formula'" class="page-scroll workbench-settings">
      <ScreenSkillLogicPanel
        v-show="workbenchTab === 'strategy'"
        :draft="draft"
        :field-errors="fieldErrors"
        @add-logic="draft.logic.push(blankLogicRow())"
        @remove-logic="
        draft.logic.length === 1
        ? (draft.logic[0] = blankLogicRow())
        : draft.logic.splice($event, 1)
        "
      />
      <ScreenSkillDataPanel
        v-show="workbenchTab === 'data'"
        :draft="draft"
        :field-options="fieldOptions"
        :required-fields="requiredFields"
        :presets="universePresets"
        :stats="universeStats"
        :field-errors="fieldErrors"
        @apply-preset="applyPreset"
        @merge-required-fields="mergeRequiredFields"
      />
      <ScreenSkillCodePanel
        v-show="workbenchTab === 'params'"
        :draft="draft"
        :show-editor="false"
        :field-errors="fieldErrors"
        @add-param="draft.params.push(blankParamRow())"
        @remove-param="
        draft.params.length === 1
        ? (draft.params[0] = blankParamRow())
        : draft.params.splice($event, 1)
        "
        @runtime-change="setRuntime"
      />
      <ScreenSkillReferencesPanel
        v-show="workbenchTab === 'references'"
        :draft="draft"
        :field-errors="fieldErrors"
        @add-reference="draft.references.push(blankReferenceRow())"
        @remove-reference="
        draft.references.length === 1
        ? (draft.references[0] = blankReferenceRow())
        : draft.references.splice($event, 1)
        "
      />
    </fieldset>
    </div>

    <PageBusy overlay :busy="loading" label="加载量化技能…" />

    <ScreenSkillImportDialog v-model="importOpen" @apply="applyImportedSource" />

    <ScreenCatalogDialog
      v-model="catalogOpen"
      :catalog="catalog"
      :runtime="draft.runtime"
      :loading="catalogLoading"
      @insert-text="insertCatalogText"
      @apply-snippet="applySnippet"
    />

    <ScreenSelectDialog
      v-model="selectOpen"
      :formula-name="draft.name"
      :presets="universePresets"
      :default-preset-id="draft.universePreset"
      :busy="screenBusy"
      @confirm="runSelect"
    />
  </div>
</template>

<!--
  样式此前用 `import './StrategyConverterView.css'` 全局注入，144 行类名对全站生效。
  改用 scoped src：既满足样式隔离，又不把这个文件撑过 600 行。
-->
<style scoped src="./StrategyConverterView.css"></style>
