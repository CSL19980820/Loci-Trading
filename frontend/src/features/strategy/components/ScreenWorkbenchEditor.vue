<script setup lang="ts">
import { computed, ref } from 'vue'

import CodeEditor from '@/features/ops/components/CodeEditor.vue'

import type { ScreenSkillDraftModel } from '../composables/screenSkillDraft'

interface EditorHandle {
  focusLine: (line: number, column?: number) => void
  insertText: (text: string) => void
}

const props = defineProps<{
  draft: ScreenSkillDraftModel
}>()

const editor = ref<EditorHandle | null>(null)

const editorContent = computed({
  get: () => (props.draft.runtime === 'python' ? props.draft.code : props.draft.formula),
  set: (value: string) => {
    if (props.draft.runtime === 'python') props.draft.code = value
    else props.draft.formula = value
  },
})

const filename = computed(() => (props.draft.runtime === 'python' ? 'strategy.py' : 'formula.tdx'))
const editorLanguage = computed(() => (props.draft.runtime === 'python' ? 'python' : 'plaintext'))
const lineCount = computed(() => Math.max(1, editorContent.value.split('\n').length))

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
    <header class="editor-stage__head">
      <div class="editor-file">
        <span class="editor-file__dot" aria-hidden="true" />
        <strong>{{ filename }}</strong>
        <el-tag size="small" effect="plain">{{ draft.dialect.toUpperCase() }}</el-tag>
      </div>
      <div class="editor-meta">
        <span>{{ lineCount }} 行</span>
        <span>{{ draft.dataFields.length }} 字段</span>
        <span>{{ draft.params.filter((item) => item.key.trim()).length }} 参数</span>
      </div>
    </header>
    <div class="editor-stage__body">
      <CodeEditor
        ref="editor"
        v-model="editorContent"
        :language="editorLanguage"
        height="100%"
      />
    </div>
    <footer class="editor-stage__status">
      <span>{{ draft.runtime === 'python' ? draft.entrypoint : `主信号 ${draft.signal}` }}</span>
      <span>最少 {{ draft.minBars }} 根 K 线</span>
      <span>{{ draft.entryTiming }}</span>
    </footer>
  </section>
</template>

<style scoped>
.editor-stage {
  display: grid;
  grid-template-rows: 2.5rem minmax(15rem, 1fr) 1.9rem;
  min-width: 0;
  min-height: 0;
  border-inline: 1px solid var(--rule);
  background: var(--sheet);
}

.editor-stage__head,
.editor-stage__status,
.editor-file,
.editor-meta {
  display: flex;
  align-items: center;
}

.editor-stage__head {
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0 0.75rem;
  border-bottom: 1px solid var(--rule);
}

.editor-file,
.editor-meta,
.editor-stage__status {
  gap: 0.55rem;
}

.editor-file {
  min-width: 0;
  font: 600 0.8rem var(--mono);
}

.editor-file__dot {
  width: 0.5rem;
  height: 0.5rem;
  border-radius: 50%;
  background: var(--lake);
}

.editor-meta,
.editor-stage__status {
  color: var(--mist);
  font: 0.72rem var(--mono);
  white-space: nowrap;
}

.editor-stage__body {
  min-height: 0;
  padding: 0.55rem;
}

.editor-stage__body :deep(.code-editor) {
  min-height: 100%;
  border-radius: 3px;
}

.editor-stage__status {
  justify-content: flex-end;
  padding: 0 0.75rem;
  border-top: 1px solid var(--rule);
  background: var(--panel-2);
}

@media (max-width: 640px) {
  .editor-meta span:not(:first-child),
  .editor-stage__status span:nth-child(2) {
    display: none;
  }
}
</style>
