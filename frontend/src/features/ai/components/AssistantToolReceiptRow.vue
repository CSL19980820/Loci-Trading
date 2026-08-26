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
const statusType = computed((): 'success' | 'danger' | 'warning' | 'info' => {
  const status = props.tool.status
  if (status === 'done') return 'success'
  if (status === 'error') return 'danger'
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

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    toggle()
  }
}
</script>

<template>
  <div
    class="assistant-receipt-row"
    :class="{
      'is-running': tool.status === 'running',
      'is-error': tool.status === 'error',
      'is-open': open,
    }"
    data-testid="assistant-receipt-row"
  >
    <div
      class="assistant-receipt-row__head"
      role="button"
      tabindex="0"
      :aria-expanded="open"
      @click="toggle"
      @keydown="onKeydown"
    >
      <span class="assistant-receipt-row__flow" aria-hidden="true" />
      <span class="assistant-receipt-row__left">
        <span class="assistant-receipt-row__dot" aria-hidden="true" />
        <span class="assistant-receipt-row__title">{{ title }}</span>
        <el-tag size="small" :type="statusType" effect="plain">{{ statusText }}</el-tag>
      </span>
      <span class="assistant-receipt-row__right">
        <small class="assistant-receipt-row__ms">{{ elapsedText }}</small>
        <span class="assistant-receipt-row__detail">{{ open ? '收起' : '详情' }}</span>
      </span>
    </div>
    <div v-if="open" class="assistant-receipt-row__body">
      <p v-if="tool.risk" class="assistant-receipt-row__meta">
        <el-tag size="small" type="danger" effect="plain">风险：{{ tool.risk }}</el-tag>
      </p>
      <p v-if="detail" class="assistant-receipt-row__summary">{{ detail }}</p>
      <pre v-if="hasArgs" class="assistant-receipt-row__args">{{ argsText }}</pre>
      <p v-else-if="!detail" class="assistant-receipt-row__empty">无入参详情</p>
    </div>
  </div>
</template>

<style scoped>
.assistant-receipt-row {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--rule);
  border-radius: var(--ai-r-card);
  background: var(--panel);
  overflow: hidden;
}
.assistant-receipt-row.is-running {
  border-color: color-mix(in srgb, var(--el-color-primary) 40%, var(--rule));
}
.assistant-receipt-row.is-error {
  border-color: color-mix(in srgb, var(--el-color-danger) 40%, var(--rule));
}
.assistant-receipt-row__head {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  width: 100%;
  min-height: var(--ai-row-min);
  margin: 0;
  padding: .28rem .55rem;
  color: inherit;
  text-align: left;
  box-sizing: border-box;
  cursor: pointer;
  overflow: hidden;
}
.assistant-receipt-row__head:hover,
.assistant-receipt-row__head:focus-visible {
  background: color-mix(in srgb, var(--ink) 3.5%, transparent);
  outline: none;
}
.assistant-receipt-row__head:focus-visible {
  box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--seal) 28%, transparent);
}
.assistant-receipt-row__flow {
  display: none;
}
.assistant-receipt-row.is-running .assistant-receipt-row__flow {
  display: block;
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(
    110deg,
    transparent 0%,
    transparent 38%,
    color-mix(in srgb, var(--el-color-primary) 16%, transparent) 50%,
    transparent 62%,
    transparent 100%
  );
  background-size: 220% 100%;
  animation: receipt-flow 1.45s linear infinite;
}
.assistant-receipt-row__left,
.assistant-receipt-row__right {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: .5rem;
  min-width: 0;
}
.assistant-receipt-row__left {
  flex: 1 1 auto;
}
.assistant-receipt-row__right {
  flex: 0 0 auto;
  margin-left: auto;
  gap: .65rem;
}
.assistant-receipt-row__dot {
  flex: 0 0 auto;
  display: block;
  width: .4rem;
  height: .4rem;
  border-radius: var(--ai-r-pill);
  background: var(--mist);
}
.assistant-receipt-row.is-running .assistant-receipt-row__dot {
  background: var(--el-color-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 22%, transparent);
  animation: receipt-dot-pulse 1.2s ease-in-out infinite;
}
.assistant-receipt-row.is-error .assistant-receipt-row__dot {
  background: var(--el-color-danger);
}
.assistant-receipt-row:not(.is-running):not(.is-error) .assistant-receipt-row__dot {
  background: var(--el-color-success);
}
.assistant-receipt-row__title {
  flex: 0 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ai-fs-body);
  font-weight: 650;
  color: var(--ink);
}
.assistant-receipt-row__ms {
  flex: 0 0 auto;
  min-width: 2.8rem;
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.assistant-receipt-row__detail {
  flex: 0 0 auto;
  color: var(--mist);
  font-size: var(--ai-fs-meta);
  font-weight: 500;
  opacity: .85;
}
.assistant-receipt-row__head:hover .assistant-receipt-row__detail {
  color: var(--ink);
  opacity: 1;
}
.assistant-receipt-row__body {
  position: relative;
  z-index: 1;
  padding: .4rem .55rem .5rem;
  border-top: 1px solid var(--rule);
}
.assistant-receipt-row__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: .4rem;
  margin: 0 0 .35rem;
  font-size: var(--ai-fs-aux);
  color: var(--mist);
}
.assistant-receipt-row__meta code {
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
}
.assistant-receipt-row__summary {
  margin: 0 0 .3rem;
  font-size: var(--ai-fs-aux);
  line-height: 1.4;
  color: var(--ink);
  word-break: break-word;
}
.assistant-receipt-row__args {
  margin: 0;
  padding: .4rem .45rem;
  max-height: 10rem;
  overflow: auto;
  border-radius: var(--ai-r-chip);
  background: color-mix(in srgb, var(--ink) 6%, transparent);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
}
.assistant-receipt-row__empty {
  margin: 0;
  font-size: var(--ai-fs-aux);
  color: var(--mist);
}
@keyframes receipt-flow {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}
@keyframes receipt-dot-pulse {
  0%, 100% { box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 18%, transparent); }
  50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--el-color-primary) 8%, transparent); }
}
@media (prefers-reduced-motion: reduce) {
  .assistant-receipt-row.is-running .assistant-receipt-row__flow,
  .assistant-receipt-row.is-running .assistant-receipt-row__dot {
    animation: none;
  }
  .assistant-receipt-row.is-running .assistant-receipt-row__flow {
    display: none;
  }
}
</style>
