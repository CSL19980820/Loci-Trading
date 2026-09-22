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
  /* 结果坞与助手展开时仍把状态栏留在可视范围，编辑器自己滚动。 */
  grid-template-rows: minmax(0, 1fr) var(--ctl-h);
  overflow: hidden;
  min-width: 0;
  min-height: 0;
  background: var(--surface);
}

.editor-stage__status {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--gap-3);
  padding: 0 var(--gap-3);
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-sunken);
  overflow: hidden;
  color: var(--text-tertiary);
  font: var(--fs-kicker) / 1 var(--mono);
  font-variant-numeric: tabular-nums;
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
  color: var(--ok);
}

.editor-stage__status--error .editor-stage__status-left {
  color: var(--warn-ink);
}

@media (max-width: 640px) {
  .editor-stage__status span:nth-child(2),
  .editor-stage__status span:nth-child(3) {
    display: none;
  }
}
</style>
