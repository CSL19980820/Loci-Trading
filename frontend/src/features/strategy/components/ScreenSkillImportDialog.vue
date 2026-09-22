<script setup lang="ts">
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as SegmentedControl } from '@/shared/components/ui/app/SegmentedControl.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

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
  <DialogPanel
    v-model="visible"
    title="导入执行源"
    width="min(50rem, 94vw)"
    destroy-on-close
  >
    <div class="mb-3 flex items-center justify-between gap-3">
      <SegmentedControl v-model="kind" :options="kindOptions" />
    </div>
    <CodeEditor v-model="source" :language="language" height="26rem" />
    <template #footer>
      <ActionButton access="read" @click="visible = false">取消</ActionButton>
      <ActionButton tone="primary" :disabled="!source.trim()" @click="applyImport">应用到当前草稿</ActionButton>
    </template>
  </DialogPanel>
</template>

<style scoped>
/* 工具条版式已上移到模板工具类 */
</style>
