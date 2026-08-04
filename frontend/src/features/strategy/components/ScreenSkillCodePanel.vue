<script setup lang="ts">
import { computed } from 'vue'

import CodeEditor from '@/features/ops/components/CodeEditor.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import type { ScreenSkillRuntime } from '@/shared/types/quant'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'

const props = defineProps<{
  draft: ScreenSkillDraftModel
  showEditor?: boolean
}>()

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

const dialectOptions = computed(() =>
  props.draft.runtime === 'python'
    ? [{ label: 'python', value: 'python' }]
    : [
        { label: 'loci', value: 'loci' },
        { label: 'tdx', value: 'tdx' },
        { label: 'ths', value: 'ths' },
      ],
)

const editorLanguage = computed(() => (props.draft.runtime === 'python' ? 'python' : 'plaintext'))
</script>

<template>
  <Sheet :title="showEditor === false ? '运行与参数' : '代码高级视图'" padded margin>
    <div class="meta-grid">
      <el-form-item label="运行时">
        <el-select
          :model-value="props.draft.runtime"
          class="full"
          @update:model-value="requestRuntimeChange"
        >
          <el-option label="公式" value="formula" />
          <el-option label="Python" value="python" />
        </el-select>
      </el-form-item>
      <el-form-item label="方言">
        <el-select v-model="props.draft.dialect" class="full">
          <el-option v-for="item in dialectOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="props.draft.runtime === 'python'" label="入口函数" required>
        <el-input v-model.trim="props.draft.entrypoint" maxlength="80" placeholder="strategy.py:compute" />
      </el-form-item>
      <el-form-item v-else label="公式源">
        <el-input :model-value="props.draft.dialect.toUpperCase()" readonly />
      </el-form-item>
    </div>

    <el-form-item
      v-if="showEditor !== false"
      :label="props.draft.runtime === 'python' ? 'Python 源码' : '公式正文'"
      required
    >
      <CodeEditor v-model="editorContent" :language="editorLanguage" height="24rem" />
    </el-form-item>

    <div class="section-head">
      <div>
        <strong>参数表</strong>
        <div class="dim">编译、保存、试跑共用同一份 manifest 参数定义。</div>
      </div>
      <el-button size="small" @click="emit('addParam')">新增参数</el-button>
    </div>

    <el-table :data="props.draft.params" size="small" border class="params-table">
      <el-table-column label="参数名" min-width="120">
        <template #default="{ row }">
          <el-input v-model.trim="row.key" maxlength="32" placeholder="N" />
        </template>
      </el-table-column>
      <el-table-column label="类型" width="112">
        <template #default="{ row }">
          <el-select v-model="row.type" class="full">
            <el-option label="int" value="int" />
            <el-option label="float" value="float" />
            <el-option label="bool" value="bool" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="默认值" min-width="110">
        <template #default="{ row }">
          <el-input v-model.trim="row.defaultValue" :placeholder="row.type === 'bool' ? 'true / false' : '20'" />
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

.dim {
  color: var(--mist);
  font-size: 0.82rem;
}

@media (max-width: 640px) {
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
