<script setup lang="ts">
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { Notice } from '@/shared/components/ui/app/presentation'
import { default as DataGrid } from '@/shared/components/ui/app/DataGrid.vue'
import { default as DataColumn } from '@/shared/components/ui/app/DataColumn.vue'

import { computed } from 'vue'
import { useMediaQuery } from '@vueuse/core'
const narrow = useMediaQuery('(max-width: 640px)')

import CodeEditor from '@/features/ops/components/CodeEditor.vue'
import UiField from '@/shared/components/ui/UiField.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import type { ScreenSkillRuntime } from '@/shared/types/quant'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'

const props = withDefaults(
  defineProps<{
    draft: ScreenSkillDraftModel
    showEditor?: boolean
    fieldErrors?: Record<string, string>
  }>(),
  { fieldErrors: () => ({}) },
)

function err(field: string): string {
  return props.fieldErrors[field] || ''
}

const emit = defineEmits<{
  addParam: []
  removeParam: [index: number]
  'runtime-change': [runtime: ScreenSkillRuntime]
}>()

function requestRuntimeChange(runtime: ScreenSkillRuntime): void {
  emit('runtime-change', runtime)
}

const editorContent = computed({
  get: () => (props.draft.runtime === 'python' ? props.draft.code : props.draft.formula),
  set: (value: string) => {
    if (props.draft.runtime === 'python') props.draft.code = value
    else props.draft.formula = value
  },
})

const editorLanguage = computed(() => (props.draft.runtime === 'python' ? 'python' : 'plaintext'))
</script>

<template>
  <!--
    不留块标题：这块在策稿台是 PageTabs 的「参数」分区（showEditor=false），
    高亮的 tab 已经交代了身份；带编辑器的另一形态里，下面的「脚本源码 / 公式正文」
    form-item label 也已经说清楚了。两种取值都属于白占一行。
  -->
  <Sheet padded margin>
    <div class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,260px),1fr))] gap-2">
      <UiField label="运行时">
        <ChoiceField
          :model-value="props.draft.runtime"
          class="w-full"
          @update:model-value="requestRuntimeChange"
        >
          <ChoiceOption label="公式（通达信兼容）" value="formula" />
          <ChoiceOption label="脚本（高级）" value="python" />
        </ChoiceField>
      </UiField>
      <UiField v-if="props.draft.runtime === 'python'" label="入口函数" required :error="err('entrypoint')">
        <TextField
          v-model.trim="props.draft.entrypoint"
          maxlength="80"
          placeholder="文件:函数名，例如 strategy.py:compute"
        />
      </UiField>
      <UiField v-else label="公式方言">
        <TextField model-value="通达信 / 同花顺兼容写法" readonly />
      </UiField>
    </div>

    <FormField
      v-if="showEditor !== false"
      :label="props.draft.runtime === 'python' ? '脚本源码' : '公式正文'"
      required
    >
      <CodeEditor v-model="editorContent" :language="editorLanguage" height="24rem" />
    </FormField>

    <div class="section-head">
      <!-- 标题旁那句常驻介绍收进 tooltip：页面上不留介绍段（AGENTS.md 4） -->
      <HintTooltip placement="bottom-start" content="编译、保存、试跑共用同一份参数定义">
        <strong class="section-head__title">参数表</strong>
      </HintTooltip>
      <ActionButton size="small" @click="emit('addParam')">新增参数</ActionButton>
    </div>
    <Notice
      v-if="err('params')"
      :title="err('params')"
      tone="error"
      show-icon
      :closable="false"
      class="params-alert"
    />

    <div v-if="narrow" class="param-cards">
      <fieldset v-for="(row, index) in props.draft.params" :key="index" class="param-card">
        <legend>参数 {{ index + 1 }}</legend>
        <UiField label="参数名"><TextField v-model.trim="row.key" maxlength="32" placeholder="N" aria-label="参数名" /></UiField>
        <UiField label="类型"><ChoiceField v-model="row.type" aria-label="参数类型"><ChoiceOption label="整数" value="int" /><ChoiceOption label="小数" value="float" /><ChoiceOption label="开关" value="bool" /></ChoiceField></UiField>
        <UiField label="默认值"><TextField v-model.trim="row.defaultValue" :placeholder="row.type === 'bool' ? '是 / 否' : '20'" aria-label="默认值" /></UiField>
        <UiField label="标签"><TextField v-model.trim="row.label" maxlength="32" placeholder="均线周期" aria-label="参数标签" /></UiField>
        <UiField label="最小值"><TextField v-model.trim="row.min" :disabled="row.type === 'bool'" placeholder="5" aria-label="最小值" /></UiField>
        <UiField label="最大值"><TextField v-model.trim="row.max" :disabled="row.type === 'bool'" placeholder="120" aria-label="最大值" /></UiField>
        <ActionButton class="param-card__remove" variant="ghost" tone="danger" size="small" :aria-label="'删除参数 ' + (index + 1)" @click="emit('removeParam', index)">删除</ActionButton>
      </fieldset>
    </div>
    <DataGrid v-else :data="props.draft.params" size="small" border class="params-table">
      <DataColumn label="参数名" min-width="120">
        <template #default="{ row }">
          <TextField v-model.trim="row.key" maxlength="32" placeholder="N" />
        </template>
      </DataColumn>
      <DataColumn label="类型" width="112">
        <template #default="{ row }">
          <ChoiceField v-model="row.type" class="full">
            <ChoiceOption label="整数" value="int" />
            <ChoiceOption label="小数" value="float" />
            <ChoiceOption label="开关" value="bool" />
          </ChoiceField>
        </template>
      </DataColumn>
      <DataColumn label="默认值" min-width="110">
        <template #default="{ row }">
          <TextField
            v-model.trim="row.defaultValue"
            :placeholder="row.type === 'bool' ? '是 / 否' : '20'"
          />
        </template>
      </DataColumn>
      <DataColumn label="最小值" min-width="96">
        <template #default="{ row }">
          <TextField v-model.trim="row.min" :disabled="row.type === 'bool'" placeholder="5" />
        </template>
      </DataColumn>
      <DataColumn label="最大值" min-width="96">
        <template #default="{ row }">
          <TextField v-model.trim="row.max" :disabled="row.type === 'bool'" placeholder="120" />
        </template>
      </DataColumn>
      <DataColumn label="标签" min-width="120">
        <template #default="{ row }">
          <TextField v-model.trim="row.label" maxlength="32" placeholder="均线周期" />
        </template>
      </DataColumn>
      <DataColumn label="操作" width="76" align="center">
        <template #default="{ $index }">
          <ActionButton variant="ghost" tone="danger" size="small" @click="emit('removeParam', $index)">删除</ActionButton>
        </template>
      </DataColumn>
    </DataGrid>
  </Sheet>
</template>

<style scoped>
.param-cards { display: grid; gap: 10px; }
.param-card { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; min-width: 0; padding: 10px; border: 1px solid var(--border-subtle); border-radius: 6px; }
.param-card legend { padding: 0 4px; color: var(--text-secondary); font-size: 12px; }
.param-card__remove { grid-column: 1 / -1; justify-self: end; }
.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.55rem 0.75rem;
}

.full,
.params-table {
  width: 100%;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
}

.params-alert {
  margin-bottom: 0.55rem;
}

/* 小节标题压成一行：标题与它的操作按钮同高同行，不再是标题一行、介绍一行 */
.section-head__title {
  font-size: var(--fs-title);
  font-weight: 700;
  letter-spacing: 0.03em;
  cursor: help;
}

@media (max-width: 640px) {
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
