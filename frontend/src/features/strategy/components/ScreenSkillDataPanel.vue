<script setup lang="ts">
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as RadioChoices } from '@/shared/components/ui/app/RadioChoices.vue'
import { default as RadioButton } from '@/shared/components/ui/app/RadioButton.vue'
import { default as NumberInput } from '@/shared/components/ui/app/NumberInput.vue'
import { default as CheckboxChoices } from '@/shared/components/ui/app/CheckboxChoices.vue'
import { default as CheckboxField } from '@/shared/components/ui/app/CheckboxField.vue'
import { default as ToggleSwitch } from '@/shared/components/ui/app/ToggleSwitch.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'

import { computed } from 'vue'

import Sheet from '@/shared/components/layout/Sheet.vue'
import type { UniversePreset, UniverseStats } from '@/shared/types/quant'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'

const props = withDefaults(
  defineProps<{
    draft: ScreenSkillDraftModel
    fieldOptions: Array<{ label: string; value: string }>
    requiredFields: string[]
    presets: UniversePreset[]
    stats: UniverseStats | null
    fieldErrors?: Record<string, string>
  }>(),
  { fieldErrors: () => ({}) },
)

function err(field: string): string {
  return props.fieldErrors[field] || ''
}

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
  <!--
    不留块标题：策略 / 数据 / 参数 / 资料这四块是 PageTabs 的互斥分区，
    高亮的那枚 tab 已经把「你在哪一块」交代完了，Sheet 再印一遍标题只是白占
    一行（用户原话：毫无意义的标题还丑）。Sheet 只留边框与内边距。
  -->
  <Sheet padded margin>
    <div class="section-head">
      <!-- 标题旁那句常驻介绍收进 tooltip：页面上不留介绍段（AGENTS.md 4） -->
      <HintTooltip placement="bottom-start" content="字段会直接写入 manifest.data.fields，不是只读展示">
        <strong class="section-head__title">字段与复权</strong>
      </HintTooltip>
      <ActionButton v-if="requiredFields.length" size="small" @click="emit('mergeRequiredFields')">
        补齐诊断字段
      </ActionButton>
    </div>

    <FormField label="数据字段" required :error="err('dataFields')">
      <ChoiceField
        v-model="props.draft.dataFields"
        multiple
        filterable
        allow-create
        default-first-option
        placeholder="选择或录入字段"
        class="full"
      >
        <ChoiceOption v-for="item in fieldOptions" :key="item.value" :label="item.label" :value="item.value" />
      </ChoiceField>
    </FormField>

    <div v-if="requiredFields.length" class="hint-row">
      <span class="dim">诊断要求：</span>
      <StatusBadge v-for="field in requiredFields" :key="field" size="small" effect="plain">{{ field }}</StatusBadge>
    </div>

    <FormField label="复权方式">
      <RadioChoices v-model="props.draft.adjust">
        <RadioButton label="前复权" value="qfq" />
        <RadioButton label="后复权" value="hfq" />
        <RadioButton label="不复权" value="none" />
      </RadioChoices>
    </FormField>

    <div class="section-head">
      <!-- 标题旁那句常驻介绍收进 tooltip：页面上不留介绍段（AGENTS.md 4） -->
      <HintTooltip placement="bottom-start" content="预设、板块、ST、上市天数与代码 / 行业包含排除都会进 manifest">
        <strong class="section-head__title">股票池</strong>
      </HintTooltip>
      <ActionButton
        size="small"
        :disabled="!props.draft.universePreset"
        @click="emit('applyPreset', props.draft.universePreset)"
      >
        应用预设
      </ActionButton>
    </div>

    <div class="meta-grid">
      <FormField label="股票池预设">
        <ChoiceField v-model="props.draft.universePreset" clearable placeholder="不套预设" class="full">
          <ChoiceOption v-for="item in presets" :key="item.id" :label="item.label" :value="item.id" />
        </ChoiceField>
      </FormField>
      <FormField label="上市天数下限" :error="err('minListDays')">
        <NumberInput v-model="props.draft.minListDays" :min="0" :controls="false" class="full" />
      </FormField>
    </div>

    <FormField label="板块范围">
      <CheckboxChoices v-model="props.draft.boards" class="board-group">
        <CheckboxField v-for="item in boardOptions" :key="item.value" :value="item.value">
          {{ item.label }}
        </CheckboxField>
      </CheckboxChoices>
    </FormField>

    <div class="toggle-grid">
      <ToggleSwitch v-model="props.draft.excludeSt" inline-prompt active-text="剔 ST" inactive-text="含 ST" />
      <ToggleSwitch v-model="props.draft.excludeDelisting" inline-prompt active-text="剔退市整理" inactive-text="含退市整理" />
      <ToggleSwitch v-model="props.draft.excludeSuspended" inline-prompt active-text="剔停牌" inactive-text="含停牌" />
    </div>

    <div class="meta-grid">
      <FormField label="代码包含">
        <TextField
          v-model="props.draft.codesIncludeText"
          type="textarea"
          :rows="3"
          placeholder="逗号/空格/换行分隔，例如 600519, 000001"
        />
      </FormField>
      <FormField label="代码排除">
        <TextField
          v-model="props.draft.codesExcludeText"
          type="textarea"
          :rows="3"
          placeholder="用于黑名单、临停票或风控排除"
        />
      </FormField>
      <FormField label="行业包含">
        <TextField
          v-model="props.draft.industriesIncludeText"
          type="textarea"
          :rows="3"
          placeholder="例如 半导体, 电力设备"
        />
      </FormField>
      <FormField label="行业排除">
        <TextField
          v-model="props.draft.industriesExcludeText"
          type="textarea"
          :rows="3"
          placeholder="例如 ST 概念, 退市整理"
        />
      </FormField>
    </div>

    <div v-if="stats" class="stats-panel">
      <div><span class="dim">统计日期</span><strong>{{ stats.as_of }}</strong></div>
      <div><span class="dim">全市场</span><strong>{{ stats.total }}</strong></div>
      <div><span class="dim">默认可选</span><strong>{{ stats.selectable_default }}</strong></div>
      <div><span class="dim">ST 数量</span><strong>{{ stats.st_count }}</strong></div>
      <div class="stats-tags">
        <StatusBadge v-for="tag in boardTags" :key="tag" size="small" effect="plain">{{ tag }}</StatusBadge>
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
  background: color-mix(in oklab, var(--panel) 90%, var(--paper));
}

.stats-panel > div {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.stats-tags {
  grid-column: 1 / -1;
}

/* 小节标题压成一行：标题与它的操作按钮同高同行，不再是标题一行、介绍一行 */
.section-head__title {
  font-size: var(--fs-title);
  font-weight: 700;
  letter-spacing: 0.03em;
  cursor: help;
}
.dim {
  color: var(--mist);
  font-size: var(--fs-aux);
}

@media (max-width: 640px) {
  .meta-grid,
  .stats-panel {
    grid-template-columns: 1fr;
  }
}
</style>
