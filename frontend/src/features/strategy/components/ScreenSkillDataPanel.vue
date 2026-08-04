<script setup lang="ts">
import { computed } from 'vue'

import Sheet from '@/shared/components/layout/Sheet.vue'
import type { UniversePreset, UniverseStats } from '@/shared/types/quant'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'

const props = defineProps<{
  draft: ScreenSkillDraftModel
  fieldOptions: Array<{ label: string; value: string }>
  requiredFields: string[]
  presets: UniversePreset[]
  stats: UniverseStats | null
}>()

const emit = defineEmits<{
  applyPreset: [presetId: string]
  mergeRequiredFields: []
}>()

const boardOptions = [
  { label: '主板', value: 'main' },
  { label: '创业板', value: 'chi_next' },
  { label: '科创板', value: 'star' },
  { label: '北交所', value: 'bse' },
] as const

const boardTags = computed(() =>
  Object.entries(props.stats?.by_board ?? {}).map(([key, value]) => `${key}:${String(value)}`),
)
</script>

<template>
  <Sheet title="数据选择" padded margin>
    <div class="section-head">
      <div>
        <strong>字段与复权</strong>
        <div class="dim">字段会直接写入 `manifest.data.fields`，不是只读展示。</div>
      </div>
      <el-button v-if="requiredFields.length" size="small" @click="emit('mergeRequiredFields')">
        补齐诊断字段
      </el-button>
    </div>

    <el-form-item label="数据字段" required>
      <el-select
        v-model="props.draft.dataFields"
        multiple
        filterable
        allow-create
        default-first-option
        placeholder="选择或录入字段"
        class="full"
      >
        <el-option v-for="item in fieldOptions" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
    </el-form-item>

    <div v-if="requiredFields.length" class="hint-row">
      <span class="dim">诊断要求：</span>
      <el-tag v-for="field in requiredFields" :key="field" size="small" effect="plain">{{ field }}</el-tag>
    </div>

    <el-form-item label="复权方式">
      <el-radio-group v-model="props.draft.adjust">
        <el-radio-button label="前复权" value="qfq" />
        <el-radio-button label="后复权" value="hfq" />
        <el-radio-button label="不复权" value="none" />
      </el-radio-group>
    </el-form-item>

    <div class="section-head">
      <div>
        <strong>股票池</strong>
        <div class="dim">预设、板块、ST、上市天数与代码/行业包含排除都会进 manifest。</div>
      </div>
      <el-button size="small" :disabled="!props.draft.universePreset" @click="emit('applyPreset', props.draft.universePreset)">
        应用预设
      </el-button>
    </div>

    <div class="meta-grid">
      <el-form-item label="股票池预设">
        <el-select v-model="props.draft.universePreset" clearable placeholder="不套预设" class="full">
          <el-option v-for="item in presets" :key="item.id" :label="item.label" :value="item.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="上市天数下限">
        <el-input-number v-model="props.draft.minListDays" :min="0" :controls="false" class="full" />
      </el-form-item>
    </div>

    <el-form-item label="板块范围">
      <el-checkbox-group v-model="props.draft.boards" class="board-group">
        <el-checkbox v-for="item in boardOptions" :key="item.value" :value="item.value">
          {{ item.label }}
        </el-checkbox>
      </el-checkbox-group>
    </el-form-item>

    <div class="toggle-grid">
      <el-switch v-model="props.draft.excludeSt" inline-prompt active-text="剔 ST" inactive-text="含 ST" />
      <el-switch v-model="props.draft.excludeDelisting" inline-prompt active-text="剔退市整理" inactive-text="含退市整理" />
      <el-switch v-model="props.draft.excludeSuspended" inline-prompt active-text="剔停牌" inactive-text="含停牌" />
    </div>

    <div class="meta-grid">
      <el-form-item label="代码包含">
        <el-input
          v-model="props.draft.codesIncludeText"
          type="textarea"
          :rows="3"
          placeholder="逗号/空格/换行分隔，例如 600519, 000001"
        />
      </el-form-item>
      <el-form-item label="代码排除">
        <el-input
          v-model="props.draft.codesExcludeText"
          type="textarea"
          :rows="3"
          placeholder="用于黑名单、临停票或风控排除"
        />
      </el-form-item>
      <el-form-item label="行业包含">
        <el-input
          v-model="props.draft.industriesIncludeText"
          type="textarea"
          :rows="3"
          placeholder="例如 半导体, 电力设备"
        />
      </el-form-item>
      <el-form-item label="行业排除">
        <el-input
          v-model="props.draft.industriesExcludeText"
          type="textarea"
          :rows="3"
          placeholder="例如 ST 概念, 退市整理"
        />
      </el-form-item>
    </div>

    <div v-if="stats" class="stats-panel">
      <div><span class="dim">统计日期</span><strong>{{ stats.as_of }}</strong></div>
      <div><span class="dim">全市场</span><strong>{{ stats.total }}</strong></div>
      <div><span class="dim">默认可选</span><strong>{{ stats.selectable_default }}</strong></div>
      <div><span class="dim">ST 数量</span><strong>{{ stats.st_count }}</strong></div>
      <div class="stats-tags">
        <el-tag v-for="tag in boardTags" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
      </div>
    </div>
  </Sheet>
</template>

<style scoped>
.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem 0.75rem;
}

.full {
  width: 100%;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
}

.board-group,
.toggle-grid,
.hint-row,
.stats-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.toggle-grid {
  margin-bottom: 0.75rem;
}

.stats-panel {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem 0.75rem;
  padding: 0.8rem;
  border: 1px solid var(--rule);
  border-radius: 8px;
  background: color-mix(in srgb, var(--panel) 90%, var(--paper));
}

.stats-panel > div {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.stats-tags {
  grid-column: 1 / -1;
}

.dim {
  color: var(--mist);
  font-size: 0.82rem;
}

@media (max-width: 640px) {
  .meta-grid,
  .stats-panel {
    grid-template-columns: 1fr;
  }
}
</style>
