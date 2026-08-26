<script setup lang="ts">
import {
  ArrowLeft,
  ChatDotRound,
  Collection,
  DataLine,
  Delete,
  DocumentChecked,
  FolderOpened,
  Search,
  VideoPlay,
} from '@element-plus/icons-vue'
import { computed } from 'vue'

import PageBusy from '@/shared/components/ui/PageBusy.vue'
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
import ScreenWorkbenchDock from './components/ScreenWorkbenchDock.vue'
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

function toggleAssist(): void {
  if (assistOpen.value) {
    assistOpen.value = false
    return
  }
  workbenchTab.value = 'formula'
  assistOpen.value = true
}
</script>

<template>
  <div class="page-fill workbench-page">
    <header class="workbench-bar">
      <div class="workbench-identity">
        <el-tooltip content="返回工坊" placement="bottom">
          <el-button
            text
            circle
            :icon="ArrowLeft"
            aria-label="返回工坊"
            @click="router.push('/quant')"
          />
        </el-tooltip>
        <el-input
          v-model="draft.name"
          class="workbench-name-input"
          maxlength="64"
          placeholder="未命名公式"
          aria-label="公式名称"
        />
      </div>

      <div class="workbench-actions">
        <el-button :icon="Collection" aria-label="打开函数词典" @click="catalogOpen = true">
          函数
        </el-button>
        <el-tooltip :content="hasBody ? '' : '先写点公式'" :disabled="hasBody">
          <el-button
            :icon="VideoPlay"
            :loading="previewBusy"
            :disabled="!hasBody || previewBusy"
            aria-label="试跑"
            @click="handleTrial"
          >
            试跑
          </el-button>
        </el-tooltip>
        <el-tooltip content="先试跑通过再选股" :disabled="trialPassed">
          <el-button
            :icon="Search"
            :disabled="!trialPassed || screenBusy"
            aria-label="选股"
            @click="selectOpen = true"
          >
            选股
          </el-button>
        </el-tooltip>
        <el-button
          :icon="DataLine"
          :disabled="!trialPassed && !currentSlug"
          aria-label="回测"
          @click="openBacktest"
        >
          回测
        </el-button>
        <el-button
          class="workbench-secondary"
          :icon="FolderOpened"
          aria-label="导入"
          @click="importOpen = true"
        >
          导入
        </el-button>
        <el-button
          v-if="isEditing && draft.packageRevision"
          class="workbench-secondary"
          type="danger"
          plain
          :icon="Delete"
          aria-label="删除当前公式"
          @click="handleDelete"
        >
          删除
        </el-button>
        <el-button
          type="primary"
          :icon="DocumentChecked"
          :loading="busy"
          aria-label="保存"
          @click="handleSave"
        >
          保存
        </el-button>
        <el-button
          :type="assistOpen ? 'primary' : 'default'"
          :plain="assistOpen"
          :icon="ChatDotRound"
          :aria-label="assistOpen ? '收起助手' : '展开助手'"
          @click="toggleAssist"
        >
          助手
        </el-button>
      </div>
    </header>

    <PageTabs
      v-model="workbenchTab"
      :items="workbenchTabs"
      :sticky="false"
      dense
      aria-label="策稿分区"
    >
      <template #trailing>
        <span>{{ editorLineCount }} 行</span>
        <span>{{ fieldCount }} 字段</span>
        <span>{{ paramCount }} 参数</span>
      </template>
    </PageTabs>

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
          <el-button size="small" type="primary" @click="loadCurrentSkill(currentSlug)">
            重新加载
          </el-button>
        </template>
      </el-alert>
    </div>

    <main
      v-show="workbenchTab === 'formula'"
      class="workbench-shell"
      :class="{ 'workbench-shell--assist': assistOpen }"
    >
      <ScreenWorkbenchEditor
        ref="editor"
        :draft="draft"
        :status-left="statusLeft"
        :status-right="statusRight"
        :status-tone="statusTone"
      />

      <aside v-if="assistOpen" class="copilot-pane">
        <div class="copilot-pane__head">
          <strong>助手</strong>
          <el-button text size="small" @click="assistOpen = false">收起</el-button>
        </div>
        <ScreenAiCopilot
          v-model:instruction="generationForm.source"
          v-model:provider="generationForm.provider"
          v-model:model="generationForm.model"
          v-model:thinking="generationForm.thinking"
          compact
          :providers="providers"
          :provider-models="providerModels"
          :references-ready="referencesReady"
          :busy="busy"
          @generate="handleGenerate"
          @manage-references="openSettings('references')"
          @open-assistant="openAssistant"
        />
      </aside>
    </main>

    <div v-show="workbenchTab !== 'formula'" class="page-scroll workbench-settings">
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
    </div>

    <ScreenWorkbenchDock
      v-show="workbenchTab === 'formula'"
      v-model:active-tab="dockTab"
      :open="dockOpen"
      :preview="preview"
      :screen-result="screenResult"
      :screen-busy="screenBusy || previewBusy"
      backtest-slot
      @focus-line="editor?.focusLine($event)"
    >
      <template #backtest>
        <QuantBacktestPanel
          v-if="backtestOpen || dockTab === 'bt'"
          :strategies="strategies"
          :locked-slug="currentSlug || undefined"
          :locked-name="draft.name || undefined"
        />
      </template>
    </ScreenWorkbenchDock>

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
