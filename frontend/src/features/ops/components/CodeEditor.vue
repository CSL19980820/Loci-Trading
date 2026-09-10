<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import type { editor as MonacoEditorNs } from 'monaco-editor'

import { APPEARANCE_OPTIONS } from '@/shared/lib/theme'
import { ensureMonacoEnv } from './monacoEnv'

const props = withDefaults(
  defineProps<{
    modelValue: string
    language?: 'json' | 'python' | string
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

/**
 * 只装配用得上的东西：裸 `monaco-editor` 解析到 `editor.main`，会连带 ~90 种
 * basic-languages 与 ts/css/html/json 四套语言服务——而 monacoEnv 只注册了
 * editor / json 两个 worker，那三套服务在运行时根本没有 worker 可用，纯属死重量。
 * `features/register.all.js` 是 monaco 自带的「全部编辑器功能、不含语言」入口，
 * 折叠、查找、右键菜单、撤销这些照旧。
 * 子路径按 0.56 exports 写 `monaco-editor/<path>.js`（见 monacoEnv.ts 注释）。
 *
 * **不要再 `import 'monaco-editor/min/vs/editor/editor.main.css'`**：那是 AMD 版
 * 全量样式（349 KB raw / 117 KB gz），而 ESM 侧每个 contrib 模块自带 CSS，已经随
 * 上面四个 import 进了异步分片。2026-09 实测过差集：把 min 全量 CSS 的 1242 条顶层
 * 规则拆成 1510 条单选择器逐条比对 contrib 分片，**独有选择器 0 条、独有声明 0 条**
 * （余下差异全是 minifier 归一化，如 `transparent` vs `#0000`、属性重排、`var()`
 * 回退值里的空格）；codicon 字体也只是从内联 base64 换成外链 `.ttf`。
 * 编辑器样式若出问题，先查 contrib 是否漏 import，别把全量 CSS 加回来。
 */
async function loadMonaco(): Promise<MonacoModule> {
  const [api] = await Promise.all([
    import('monaco-editor/editor/editor.api.js'),
    import('monaco-editor/features/register.all.js'),
    import('monaco-editor/languages/definitions/python/register.js'),
    import('monaco-editor/languages/features/json/register.js'),
  ])
  return api as unknown as MonacoModule
}

let monacoMod: MonacoModule | null = null
let themeObserver: MutationObserver | null = null
let suppressModelEmit = false
let mountGeneration = 0

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
  const generation = ++mountGeneration
  ensureMonacoEnv()
  monacoMod = await loadMonaco()
  if (generation !== mountGeneration || !host.value) return
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
  mountGeneration += 1
  themeObserver?.disconnect()
  themeObserver = null
  const model = editorRef.value?.getModel()
  editorRef.value?.dispose()
  model?.dispose()
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

function insertText(text: string): void {
  const editor = editorRef.value
  const monaco = monacoMod
  if (!editor || !monaco || !text) return
  const selection = editor.getSelection()
  const range = selection ?? new monaco.Range(1, 1, 1, 1)
  editor.executeEdits('catalog-insert', [{ range, text, forceMoveMarkers: true }])
  editor.focus()
}

function focusLine(line: number, column = 1): void {
  const editor = editorRef.value
  if (!editor) return
  const model = editor.getModel()
  const safeLine = Math.max(1, Math.min(Math.trunc(line), model?.getLineCount() ?? 1))
  const safeColumn = Math.max(1, Math.trunc(column))
  editor.setPosition({ lineNumber: safeLine, column: safeColumn })
  editor.revealLineInCenterIfOutsideViewport(safeLine)
  editor.focus()
}

defineExpose({ focusLine, insertText })
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
