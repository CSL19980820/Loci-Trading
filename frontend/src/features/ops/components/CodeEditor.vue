<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import type { editor as MonacoEditorNs } from 'monaco-editor'

import { APPEARANCE_OPTIONS } from '@/shared/lib/theme'
import { ensureMonacoEnv } from './monacoEnv'

const props = withDefaults(
  defineProps<{
    modelValue: string
    language?: 'yaml' | 'markdown' | 'json' | 'python' | string
    readOnly?: boolean
    /** CSS height，如 10rem / 240px */
    height?: string
  }>(),
  {
    language: 'plaintext',
    readOnly: false,
    height: '10rem',
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const host = ref<HTMLDivElement | null>(null)
const editorRef = shallowRef<MonacoEditorNs.IStandaloneCodeEditor | null>(null)

type MonacoModule = typeof import('monaco-editor')

let monacoMod: MonacoModule | null = null
let themeObserver: MutationObserver | null = null
let suppressModelEmit = false

function isDarkAppearance(): boolean {
  const id = document.documentElement.getAttribute('data-appearance')
  return APPEARANCE_OPTIONS.find((o) => o.id === id)?.mode === 'dark'
}

function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

function applyLociTheme(monaco: MonacoModule): void {
  const dark = isDarkAppearance()
  const themeName = dark ? 'loci-dark' : 'loci-light'
  monaco.editor.defineTheme(themeName, {
    base: dark ? 'vs-dark' : 'vs',
    inherit: true,
    rules: [],
    colors: {
      'editor.background': cssVar('--sheet', dark ? '#1a222d' : '#f7f9fc'),
      'editor.foreground': cssVar('--ink', dark ? '#e8eef5' : '#142033'),
      'editorLineNumber.foreground': cssVar('--mist', dark ? '#8b9aab' : '#5b6b7c'),
      'editor.selectionBackground': cssVar('--accent-soft', dark ? '#3a1a22' : '#fce8ec'),
      'editorCursor.foreground': cssVar('--accent', dark ? '#e0576f' : '#c41e3a'),
      'editorWidget.background': cssVar('--panel', dark ? '#141b24' : '#f7f9fc'),
      'editorWidget.border': cssVar('--rule', dark ? '#2a3544' : '#d5dce6'),
      'focusBorder': cssVar('--rule', dark ? '#2a3544' : '#d5dce6'),
    },
  })
  monaco.editor.setTheme(themeName)
}

async function mountEditor(): Promise<void> {
  if (!host.value || editorRef.value) return
  ensureMonacoEnv()
  await import('monaco-editor-css')
  monacoMod = await import('monaco-editor')
  applyLociTheme(monacoMod)

  const ed = monacoMod.editor.create(host.value, {
    value: props.modelValue ?? '',
    language: props.language || 'plaintext',
    readOnly: props.readOnly,
    automaticLayout: true,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    wordWrap: 'on',
    fontSize: 13,
    fontFamily: 'var(--mono)',
    lineNumbers: 'on',
    renderLineHighlight: 'line',
    tabSize: 2,
    padding: { top: 8, bottom: 8 },
    overviewRulerLanes: 0,
    scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 },
  })
  editorRef.value = ed

  ed.onDidChangeModelContent(() => {
    if (suppressModelEmit) return
    emit('update:modelValue', ed.getValue())
  })

  themeObserver = new MutationObserver(() => {
    if (monacoMod) applyLociTheme(monacoMod)
  })
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-appearance', 'data-theme', 'data-primary'],
  })
}

onMounted(() => {
  void mountEditor()
})

onBeforeUnmount(() => {
  themeObserver?.disconnect()
  themeObserver = null
  editorRef.value?.dispose()
  editorRef.value = null
  monacoMod = null
})

watch(
  () => props.modelValue,
  (next) => {
    const ed = editorRef.value
    if (!ed || ed.getValue() === next) return
    suppressModelEmit = true
    ed.setValue(next ?? '')
    suppressModelEmit = false
  },
)

watch(
  () => props.language,
  (lang) => {
    const ed = editorRef.value
    const monaco = monacoMod
    if (!ed || !monaco) return
    const model = ed.getModel()
    if (model) monaco.editor.setModelLanguage(model, lang || 'plaintext')
  },
)

watch(
  () => props.readOnly,
  (ro) => {
    editorRef.value?.updateOptions({ readOnly: Boolean(ro) })
  },
)
</script>

<template>
  <div class="code-editor" :style="{ height }" data-testid="code-editor">
    <div ref="host" class="code-editor__host" />
  </div>
</template>

<style scoped>
.code-editor {
  width: 100%;
  min-height: 6rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  overflow: hidden;
  background: var(--sheet);
}

.code-editor__host {
  width: 100%;
  height: 100%;
}
</style>
