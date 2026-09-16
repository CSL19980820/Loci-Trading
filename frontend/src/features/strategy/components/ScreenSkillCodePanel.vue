<script setup lang="ts">
import { computed } from 'vue'

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
    <div class="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-2">
      <UiField label="运行时">
        <el-select
          :model-value="props.draft.runtime"
          class="w-full"
          @update:model-value="requestRuntimeChange"
        >
          <el-option label="公式（通达信兼容）" value="formula" />
          <el-option label="脚本（高级）" value="python" />
        </el-select>
      </UiField>
      <UiField v-if="props.draft.runtime === 'python'" label="入口函数" required :error="err('entrypoint')">
        <el-input
          v-model.trim="props.draft.entrypoint"
          maxlength="80"
          placeholder="文件:函数名，例如 strategy.py:compute"
        />
      </UiField>
      <UiField v-else label="公式方言">
        <el-input model-value="通达信 / 同花顺兼容写法" readonly />
      </UiField>
    </div>

    <el-form-item
      v-if="showEditor !== false"
      :label="props.draft.runtime === 'python' ? '脚本源码' : '公式正文'"
      required
    >
      <CodeEditor v-model="editorContent" :language="editorLanguage" height="24rem" />
    </el-form-item>

    <div class="section-head">
      <!-- 标题旁那句常驻介绍收进 tooltip：页面上不留介绍段（AGENTS.md 4） -->
      <el-tooltip placement="bottom-start" content="编译、保存、试跑共用同一份参数定义">
        <strong class="section-head__title">参数表</strong>
      </el-tooltip>
      <el-button size="small" @click="emit('addParam')">新增参数</el-button>
    </div>
    <el-alert
      v-if="err('params')"
      :title="err('params')"
      type="error"
      show-icon
      :closable="false"
      class="params-alert"
    />

    <el-table :data="props.draft.params" size="small" border class="params-table">
      <el-table-column label="参数名" min-width="120">
        <template #default="{ row }">
          <el-input v-model.trim="row.key" maxlength="32" placeholder="N" />
        </template>
      </el-table-column>
      <el-table-column label="类型" width="112">
        <template #default="{ row }">
          <el-select v-model="row.type" class="full">
            <el-option label="整数" value="int" />
            <el-option label="小数" value="float" />
            <el-option label="开关" value="bool" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="默认值" min-width="110">
        <template #default="{ row }">
          <el-input
            v-model.trim="row.defaultValue"
            :placeholder="row.type === 'bool' ? '是 / 否' : '20'"
          />
        </template>
      </el-table-column>
      <el-table-column label="最小值" min-width="96">
        <template #default="{ row }">
          <el-input v-model.trim="row.min" :disabled="row.type === 'bool'" placeholder="5" />
        </template>
      </el-table-column>
      <el-table-column label="最大值" min-width="96">
        <template #default="{ row }">
          <el-input v-model.trim="row.max" :disabled="row.type === 'bool'" placeholder="120" />
        </template>
      </el-table-column>
      <el-table-column label="标签" min-width="120">
        <template #default="{ row }">
          <el-input v-model.trim="row.label" maxlength="32" placeholder="均线周期" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="76" align="center">
        <template #default="{ $index }">
          <el-button text type="danger" size="small" @click="emit('removeParam', $index)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </Sheet>
</template>

<style scoped>
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
