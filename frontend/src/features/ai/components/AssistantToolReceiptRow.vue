<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import { Button } from '@/shared/components/ui/button'
import { computed, onUnmounted, ref, watch } from 'vue'
import { ChevronRight, CircleCheck, CircleX } from '@lucide/vue'

import { toolLabel } from '../toolLabel'
import { formatToolPreview } from '../toolPreview'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import type { AiToolReceipt } from '@/shared/types/ai_assistant'

/**
 * 一条工具回执：状态图标 + 工具名 + 一行摘要（截断）+ 耗时，点开看入参 JSON。
 * 外层只显示状态；长跑（>1.5s）自动展开便于盯进度，出错也自动展开。
 */
const props = defineProps<{
  tool: AiToolReceipt
  /** Open argument panel when true (e.g. errors). */
  preferOpen?: boolean
}>()

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
const statusText = computed(() => {
  const status = props.tool.status
  if (status === 'running') return '运行中'
  if (status === 'error') return '失败'
  if (status === 'done') return '完成'
  return '未知'
})
const elapsedText = computed(() => {
  if (props.tool.elapsed_ms == null) return ''
  const ms = props.tool.elapsed_ms
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
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
    return JSON.stringify(props.tool.arguments ?? Object.create(null), null, 2)
  } catch {
    return String(props.tool.arguments ?? '')
  }
})

</script>

<template>
  <Collapsible as="div" v-model:open="open"
    class="assistant-receipt-row"
    :class="{
      'is-running': tool.status === 'running',
      'is-error': tool.status === 'error',
      'is-open': open,
      'is-done': tool.status === 'done',
    }"
    data-testid="assistant-receipt-row"
  >
    <CollapsibleTrigger as-child><Button access="read" variant="ghost"
      type="button"
      class="assistant-receipt-row__head"
      :aria-expanded="open"
    >
      <span class="assistant-receipt-row__status" aria-hidden="true">
        <Spinner v-if="tool.status === 'running'" class="assistant-receipt-row__spin" />
        <CircleX v-else-if="tool.status === 'error'" />
        <CircleCheck v-else />
      </span>
      <span class="assistant-receipt-row__title">{{ title }}</span>
      <span v-if="detail" class="assistant-receipt-row__summary" :title="detail">{{ detail }}</span>
      <span class="sr-only">{{ statusText }}</span>
      <small v-if="elapsedText" class="assistant-receipt-row__ms">{{ elapsedText }}</small>
      <ChevronRight class="assistant-receipt-row__chevron" :class="{ 'is-open': open }" aria-hidden="true" />
    </Button></CollapsibleTrigger>
    <CollapsibleContent class="assistant-receipt-row__body">
      <p v-if="tool.risk" class="assistant-receipt-row__meta">
        <UiBadge variant="warn">风险：{{ tool.risk }}</UiBadge>
      </p>
      <p v-if="detail" class="assistant-receipt-row__detail">{{ detail }}</p>
      <pre v-if="hasArgs" class="assistant-receipt-row__args">{{ argsText }}</pre>
      <p v-else-if="!detail" class="assistant-receipt-row__empty">无入参详情</p>
    </CollapsibleContent>
  </Collapsible>
</template>

<style scoped>
.assistant-receipt-row {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  border-top: 1px solid var(--border-subtle);
}

.assistant-receipt-row:first-child {
  border-top: 0;
}

.assistant-receipt-row__head {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  height: auto;
  justify-content: flex-start;
  min-height: 34px;
  padding: 0 var(--gap-3);
  border: 0;
  background: transparent;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}

.assistant-receipt-row__head:hover {
  background: var(--surface-hover);
}

.assistant-receipt-row__head:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

.assistant-receipt-row__status {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  color: var(--ok);
}

.assistant-receipt-row.is-running .assistant-receipt-row__status {
  color: var(--seal);
}

.assistant-receipt-row.is-error .assistant-receipt-row__status {
  color: var(--warn);
}

.assistant-receipt-row__status :deep(svg) {
  width: 14px;
  height: 14px;
}

.assistant-receipt-row__spin {
  animation: assistant-receipt-spin 1s linear infinite;
}

.assistant-receipt-row__title {
  flex: 0 0 auto;
  max-width: 45%;
  overflow: hidden;
  font-size: var(--fs-aux);
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.assistant-receipt-row__summary {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.assistant-receipt-row__ms {
  flex: 0 0 auto;
  margin-left: auto;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
}

.assistant-receipt-row__chevron {
  flex: 0 0 auto;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  transition: transform var(--dur-fast) var(--ease);
}

.assistant-receipt-row__chevron.is-open {
  transform: rotate(90deg);
}

.assistant-receipt-row__body {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3) var(--gap-3) 34px;
  background: var(--surface-sunken);
}

.assistant-receipt-row__meta {
  margin: 0;
}

.assistant-receipt-row__detail {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.assistant-receipt-row__args {
  margin: 0;
  max-height: 10rem;
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow: auto;
  overflow-wrap: anywhere;
  scrollbar-width: thin;
}

.assistant-receipt-row__empty {
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

@keyframes assistant-receipt-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 640px) {
  .assistant-receipt-row__summary {
    display: none;
  }

  .assistant-receipt-row__title {
    flex: 1 1 auto;
    max-width: none;
  }

  .assistant-receipt-row__body {
    padding-left: var(--gap-3);
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-receipt-row__spin {
    animation: none;
  }

  .assistant-receipt-row__chevron {
    transition: none;
  }
}
</style>
