<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

import { toolLabel } from '../toolLabel'
import { formatToolPreview } from '../toolPreview'
import type { AiToolReceipt } from '@/shared/types/ai_assistant'

const props = defineProps<{
  tool: AiToolReceipt
  /** Open argument panel when true (e.g. errors). */
  preferOpen?: boolean
}>()

/** 外层只显示状态；展开后才见内容。长跑时自动展开便于盯进度。 */
const LONG_RUN_OPEN_MS = 1500
const open = ref(Boolean(props.preferOpen))
let longRunTimer: ReturnType<typeof setTimeout> | null = null

function clearLongRunTimer(): void {
  if (longRunTimer == null) return
  clearTimeout(longRunTimer)
  longRunTimer = null
}

watch(
  () => props.preferOpen,
  (value) => {
    if (value) open.value = true
  },
)

watch(
  () => props.tool.status,
  (status) => {
    clearLongRunTimer()
    if (props.preferOpen) {
      open.value = true
      return
    }
    if (status === 'running') {
      longRunTimer = setTimeout(() => {
        open.value = true
        longRunTimer = null
      }, LONG_RUN_OPEN_MS)
      return
    }
    open.value = false
  },
  { immediate: true },
)

onUnmounted(clearLongRunTimer)

const title = computed(() => toolLabel(props.tool.name))
const statusType = computed((): 'primary' | 'warning' | 'info' => {
  const status = props.tool.status
  if (status === 'done') return 'primary'
  if (status === 'error') return 'warning'
  return 'info'
})
const statusText = computed(() => {
  const status = props.tool.status
  if (status === 'running') return '运行中'
  if (status === 'error') return '失败'
  if (status === 'done') return '完成'
  return '未知'
})
const elapsedText = computed(() => {
  if (props.tool.elapsed_ms == null) return '—'
  return `${props.tool.elapsed_ms}ms`
})
const detail = computed(() =>
  formatToolPreview(props.tool.name, props.tool.summary || props.tool.preview || ''),
)
const hasArgs = computed(() => {
  const args = props.tool.arguments
  return Boolean(args && Object.keys(args).length)
})
const argsText = computed(() => {
  try {
    return JSON.stringify(props.tool.arguments ?? {}, null, 2)
  } catch {
    return String(props.tool.arguments ?? '')
  }
})

function toggle(): void {
  open.value = !open.value
}

</script>

<template>
  <div
    class="assistant-receipt-row"
    :class="{
      'is-running': tool.status === 'running',
      'is-error': tool.status === 'error',
      'is-open': open,
      'is-done': tool.status === 'done',
    }"
    data-testid="assistant-receipt-row"
  >
    <el-button
      text
      class="assistant-receipt-row__head"
      :aria-expanded="open"
      @click="toggle"
    >
      <span class="assistant-receipt-row__left">
        <span class="assistant-receipt-row__dot" aria-hidden="true" />
        <span class="assistant-receipt-row__title">{{ title }}</span>
        <el-tag size="small" :type="statusType" effect="plain">{{ statusText }}</el-tag>
      </span>
      <span class="assistant-receipt-row__right">
        <small class="assistant-receipt-row__ms">{{ elapsedText }}</small>
        <span class="assistant-receipt-row__detail">{{ open ? '收起' : '详情' }}</span>
      </span>
    </el-button>
    <div v-if="open" class="assistant-receipt-row__body">
      <p v-if="tool.risk" class="assistant-receipt-row__meta">
        <el-tag size="small" type="warning" effect="plain">风险：{{ tool.risk }}</el-tag>
      </p>
      <p v-if="detail" class="assistant-receipt-row__summary">{{ detail }}</p>
      <pre v-if="hasArgs" class="assistant-receipt-row__args">{{ argsText }}</pre>
      <p v-else-if="!detail" class="assistant-receipt-row__empty">无入参详情</p>
    </div>
  </div>
</template>

<style scoped>
.assistant-receipt-row { width: 100%; min-width: 0; border: 1px solid var(--rule); border-radius: var(--ai-r-chip); background: var(--surface); overflow: hidden; box-sizing: border-box; }
.assistant-receipt-row.is-running { border-color: var(--seal-border); }
.assistant-receipt-row.is-error { border-color: color-mix(in oklab, var(--warn) 45%, var(--rule)); }
.assistant-receipt-row__head { width: 100%; min-height: var(--ai-row-min); height: auto; margin: 0; padding: var(--gap-2); color: var(--ink); text-align: left; white-space: normal; }
.assistant-receipt-row__head :deep(> span) { display: flex; align-items: center; justify-content: space-between; gap: var(--gap-2); width: 100%; min-width: 0; }
.assistant-receipt-row__head:focus-visible { outline: 2px solid var(--seal); outline-offset: -2px; }
.assistant-receipt-row__left, .assistant-receipt-row__right { display: inline-flex; align-items: center; gap: var(--gap-2); min-width: 0; }
.assistant-receipt-row__left { flex: 1; }
.assistant-receipt-row__right { flex: 0 0 auto; margin-left: auto; }
.assistant-receipt-row__dot { flex: 0 0 auto; width: var(--gap-1); height: var(--gap-1); border-radius: var(--ai-r-pill); background: var(--mist); }
.assistant-receipt-row.is-running .assistant-receipt-row__dot { background: var(--seal); }
.assistant-receipt-row.is-error .assistant-receipt-row__dot { background: var(--warn); }
.assistant-receipt-row.is-done .assistant-receipt-row__dot { background: var(--info); }
.assistant-receipt-row__title { min-width: 0; font-size: var(--ai-fs-body); font-weight: 600; overflow-wrap: anywhere; }
.assistant-receipt-row__ms, .assistant-receipt-row__detail { color: var(--mist); font-size: var(--ai-fs-meta); }
.assistant-receipt-row__ms { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.assistant-receipt-row__body { padding: var(--gap-2); border-top: 1px solid var(--rule-soft); }
.assistant-receipt-row__meta { display: flex; flex-wrap: wrap; gap: var(--gap-2); margin: 0 0 var(--gap-2); }
.assistant-receipt-row__summary { margin: 0 0 var(--gap-2); font-size: var(--ai-fs-body); line-height: 1.5; color: var(--ink); overflow-wrap: anywhere; }
.assistant-receipt-row__args { margin: 0; padding: var(--gap-2); max-height: 10rem; overflow: auto; scrollbar-width: thin; border: 1px solid var(--rule-soft); border-radius: var(--ai-r-chip); background: var(--surface-sunken); font: var(--ai-fs-meta)/1.55 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.assistant-receipt-row__empty { margin: 0; color: var(--mist); font-size: var(--ai-fs-aux); }
@container (max-width: 400px) { .assistant-receipt-row__head :deep(> span), .assistant-receipt-row__left { flex-wrap: wrap; } }
</style>
