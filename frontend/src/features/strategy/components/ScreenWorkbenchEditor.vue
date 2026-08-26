<script setup lang="ts">
import { computed, ref } from 'vue'

import CodeEditor from '@/features/ops/components/CodeEditor.vue'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'

interface EditorHandle {
  focusLine: (line: number, column?: number) => void
  insertText: (text: string) => void
}

const ENTRY_TIMING_LABELS: Record<string, string> = {
  open: '当日开盘',
  close: '当日收盘',
  next_open: '次日开盘',
  next_dip: '次日低吸',
}

const props = defineProps<{
  draft: ScreenSkillDraftModel
  statusLeft?: string
  statusRight?: string
  statusTone?: 'neutral' | 'ok' | 'error'
}>()

const editor = ref<EditorHandle | null>(null)

const editorContent = computed({
  get: () => (props.draft.runtime === 'python' ? props.draft.code : props.draft.formula),
  set: (value: string) => {
    if (props.draft.runtime === 'python') props.draft.code = value
    else props.draft.formula = value
  },
})

const editorLanguage = computed(() => (props.draft.runtime === 'python' ? 'python' : 'plaintext'))
const entryTimingLabel = computed(
  () => ENTRY_TIMING_LABELS[props.draft.entryTiming] || props.draft.entryTiming,
)

function insertText(text: string): void {
  editor.value?.insertText(text)
}

function focusLine(line: number, column?: number): void {
  editor.value?.focusLine(line, column)
}

defineExpose({ focusLine, insertText })
</script>

<template>
  <section class="editor-stage" aria-label="策略执行源编辑器">
    <div class="editor-stage__body">
      <CodeEditor
        ref="editor"
        v-model="editorContent"
        :language="editorLanguage"
        height="100%"
      />
    </div>
    <footer
      class="editor-stage__status"
      :class="{
        'editor-stage__status--ok': statusTone === 'ok',
        'editor-stage__status--error': statusTone === 'error',
      }"
    >
      <span class="editor-stage__status-left">{{ statusLeft || '尚未编译' }}</span>
      <span>主信号 {{ draft.signal }}</span>
      <span>最少 {{ draft.minBars }} 根</span>
      <span>{{ entryTimingLabel }}</span>
      <span class="editor-stage__status-right">{{ statusRight || '尚未试跑' }}</span>
    </footer>
  </section>
</template>

<style scoped>
.editor-stage {
  display: grid;
  grid-template-rows: minmax(12rem, 1fr) 1.75rem;
  min-width: 0;
  min-height: 0;
  background: var(--sheet);
}

.editor-stage__status {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 0.75rem;
  padding: 0 0.75rem;
  border-top: 1px solid var(--rule);
  background: var(--panel-2);
  overflow: hidden;
  color: var(--mist);
  font: 0.72rem var(--mono);
  white-space: nowrap;
}

.editor-stage__body {
  min-height: 0;
  padding: 0;
}

.editor-stage__body :deep(.code-editor) {
  min-height: 100%;
  border-radius: 0;
  border: 0;
}

.editor-stage__status-left {
  margin-right: auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.editor-stage__status--ok .editor-stage__status-left {
  color: var(--lake);
}

.editor-stage__status--error .editor-stage__status-left {
  color: var(--loss);
}

@media (max-width: 640px) {
  .editor-stage__status span:nth-child(2),
  .editor-stage__status span:nth-child(3) {
    display: none;
  }
}
</style>
