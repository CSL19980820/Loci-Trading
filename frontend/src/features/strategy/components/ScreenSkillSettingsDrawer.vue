<script setup lang="ts">
import type { ScreenSkillRuntime, UniversePreset, UniverseStats } from '@/shared/types/quant'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'
import ScreenSkillCodePanel from './ScreenSkillCodePanel.vue'
import ScreenSkillDataPanel from './ScreenSkillDataPanel.vue'
import ScreenSkillLogicPanel from './ScreenSkillLogicPanel.vue'
import ScreenSkillReferencesPanel from './ScreenSkillReferencesPanel.vue'

const visible = defineModel<boolean>({ default: false })
const activeTab = defineModel<string>('activeTab', { default: 'strategy' })

defineProps<{
  draft: ScreenSkillDraftModel
  fieldOptions: Array<{ label: string; value: string }>
  requiredFields: string[]
  presets: UniversePreset[]
  stats: UniverseStats | null
}>()

const emit = defineEmits<{
  addLogic: []
  removeLogic: [index: number]
  addReference: []
  removeReference: [index: number]
  addParam: []
  removeParam: [index: number]
  applyPreset: [presetId: string]
  mergeRequiredFields: []
  'runtime-change': [runtime: ScreenSkillRuntime]
}>()
</script>

<template>
  <el-drawer
    v-model="visible"
    title="策略设置"
    direction="rtl"
    size="min(46rem, 94vw)"
    class="skill-settings-drawer"
  >
    <el-tabs v-model="activeTab" class="settings-tabs">
      <el-tab-pane label="策略与逻辑" name="strategy">
        <ScreenSkillLogicPanel
          :draft="draft"
          @add-logic="emit('addLogic')"
          @remove-logic="emit('removeLogic', $event)"
        />
      </el-tab-pane>
      <el-tab-pane label="数据与股票池" name="data">
        <ScreenSkillDataPanel
          :draft="draft"
          :field-options="fieldOptions"
          :required-fields="requiredFields"
          :presets="presets"
          :stats="stats"
          @apply-preset="emit('applyPreset', $event)"
          @merge-required-fields="emit('mergeRequiredFields')"
        />
      </el-tab-pane>
      <el-tab-pane label="参数" name="params">
        <ScreenSkillCodePanel
          :draft="draft"
          :show-editor="false"
          @add-param="emit('addParam')"
          @remove-param="emit('removeParam', $event)"
          @runtime-change="emit('runtime-change', $event)"
        />
      </el-tab-pane>
      <el-tab-pane label="资料来源" name="references">
        <ScreenSkillReferencesPanel
          :draft="draft"
          @add-reference="emit('addReference')"
          @remove-reference="emit('removeReference', $event)"
        />
      </el-tab-pane>
    </el-tabs>
  </el-drawer>
</template>

<style scoped>
.settings-tabs {
  height: 100%;
}

.settings-tabs :deep(.el-tabs__content) {
  height: calc(100% - 3rem);
  overflow: auto;
  padding-right: 0.25rem;
}

.settings-tabs :deep(.sheet) {
  margin: 0 0 0.75rem;
  box-shadow: none;
}
</style>
