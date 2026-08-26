<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import CodeEditor from '@/features/ops/components/CodeEditor.vue'

import type { ScreenSkillDialect, ScreenSkillRuntime } from '@/shared/types/quant'

type ImportKind = 'tdx' | 'ths' | 'python'

const visible = defineModel<boolean>({ default: false })

const emit = defineEmits<{
  apply: [payload: { runtime: ScreenSkillRuntime; dialect: ScreenSkillDialect; source: string }]
}>()

const kind = ref<ImportKind>('tdx')
const source = ref('')

const kindOptions = [
  { label: '通达信', value: 'tdx' },
  { label: '同花顺', value: 'ths' },
  { label: '脚本', value: 'python' },
]

const language = computed(() => (kind.value === 'python' ? 'python' : 'plaintext'))

function applyImport(): void {
  const code = source.value.trim()
  if (!code) return
  emit('apply', {
    runtime: kind.value === 'python' ? 'python' : 'formula',
    dialect: kind.value,
    source: `${code}\n`,
  })
  visible.value = false
}

watch(visible, (open) => {
  if (open) source.value = ''
})
</script>

<template>
  <el-dialog
    v-model="visible"
    title="导入执行源"
    width="min(50rem, 94vw)"
    destroy-on-close
  >
    <div class="import-toolbar">
      <el-segmented v-model="kind" :options="kindOptions" />
    </div>
    <CodeEditor v-model="source" :language="language" height="26rem" />
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!source.trim()" @click="applyImport">应用到当前草稿</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.import-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}
</style>
