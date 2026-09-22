<script setup lang="ts">
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import { computed, ref, watch } from 'vue'
import { ChevronDown, Wrench } from '@lucide/vue'

import { toolLabel } from '../toolLabel'
import type { AiToolReceipt } from '@/shared/types/ai_assistant'
import AssistantToolReceiptRow from './AssistantToolReceiptRow.vue'

/**
 * 本轮工具回执（Claude / Cursor 的 tool-call 列一路）：一行折叠头（扳手图标 + 概览 + 总耗时），
 * 展开后是一列紧凑的回执行。运行中折叠头上的状态点闪烁；有失败时自动展开。
 */
const props = defineProps<{
  tools: AiToolReceipt[]
  /** When sub-agent activity is visible, keep the rail quiet and collapsed. */
  hasActivity?: boolean
}>()

const expanded = ref(false)

const needsAttention = computed(() =>
  props.tools.some((tool) => tool.status === 'error'),
)

watch(
  () => [needsAttention.value, props.hasActivity, props.tools.map((tool) => tool.call_id).join('|')] as const,
  () => {
    if (needsAttention.value) expanded.value = true
    else if (props.hasActivity) expanded.value = false
  },
  { immediate: true },
)

const runningTool = computed(() => props.tools.find((tool) => tool.status === 'running'))
const totalMs = computed(() => {
  let sum = 0
  let any = false
  for (const tool of props.tools) {
    if (tool.elapsed_ms == null) continue
    sum += tool.elapsed_ms
    any = true
  }
  return any ? sum : null
})
const errorCount = computed(() => props.tools.filter((tool) => tool.status === 'error').length)

const overview = computed(() => {
  const running = runningTool.value
  if (running) return `正在${toolLabel(running.name)}…`
  if (errorCount.value) {
    const ok = props.tools.length - errorCount.value
    return ok > 0
      ? `调用了 ${props.tools.length} 个工具 · ${errorCount.value} 个失败`
      : `调用了 ${props.tools.length} 个工具 · 含失败`
  }
  return `调用了 ${props.tools.length} 个工具`
})

const overviewMs = computed(() => {
  if (totalMs.value == null) return ''
  const ms = totalMs.value
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
})

const railClass = computed(() => ({
  'is-featured': !props.hasActivity,
  'is-quiet': Boolean(props.hasActivity),
  'is-running': Boolean(runningTool.value),
  'is-error': errorCount.value > 0,
  'is-open': expanded.value,
}))

</script>

<template>
  <Collapsible as="section" v-model:open="expanded"
    v-if="tools.length"
    class="assistant-receipts"
    :class="railClass"
    aria-label="本机回执"
    data-testid="assistant-receipts"
  >
    <CollapsibleTrigger
      type="button"
      class="assistant-receipts__toggle"
      :aria-expanded="expanded"
    >
      <span class="assistant-receipts__pulse" aria-hidden="true" />
      <Wrench class="assistant-receipts__icon" aria-hidden="true" />
      <strong class="assistant-receipts__overview" :title="overview">{{ overview }}</strong>
      <small v-if="overviewMs" class="assistant-receipts__ms">{{ overviewMs }}</small>
      <ChevronDown class="assistant-receipts__chevron" :class="{ 'is-open': expanded }" aria-hidden="true" />
    </CollapsibleTrigger>
    <CollapsibleContent class="assistant-receipts__list">
      <AssistantToolReceiptRow
        v-for="tool in tools"
        :key="tool.call_id"
        :tool="tool"
        :prefer-open="tool.status === 'error'"
      />
    </CollapsibleContent>
  </Collapsible>
</template>

<style scoped>
.assistant-receipts {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease);
}

.assistant-receipts.is-running {
  border-color: var(--seal-border);
}

.assistant-receipts.is-error {
  border-color: color-mix(in oklab, var(--warn) 45%, var(--border-subtle));
}

.assistant-receipts__toggle {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  max-width: 100%;
  min-height: 36px;
  padding: 0 var(--gap-3);
  border: 0;
  background: transparent;
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease);
}

.assistant-receipts__toggle:hover {
  background: var(--surface-hover);
}

.assistant-receipts__toggle:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

.assistant-receipts__pulse {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ok);
}

.assistant-receipts.is-running .assistant-receipts__pulse {
  background: var(--seal);
  animation: assistant-receipts-blink 1.2s ease-in-out infinite;
}

.assistant-receipts.is-error .assistant-receipts__pulse {
  background: var(--warn);
}

.assistant-receipts__icon {
  flex: 0 0 auto;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
}

.assistant-receipts__overview {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  font-size: var(--fs-aux);
  font-weight: 500;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.assistant-receipts__ms {
  flex: 0 0 auto;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
}

.assistant-receipts__chevron {
  flex: 0 0 auto;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  transition: transform var(--dur-fast) var(--ease);
}

.assistant-receipts__chevron.is-open {
  transform: rotate(180deg);
}

.assistant-receipts__list {
  display: flex;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  border-top: 1px solid var(--border-subtle);
}

@keyframes assistant-receipts-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-receipts.is-running .assistant-receipts__pulse {
    animation: none;
  }

  .assistant-receipts__chevron {
    transition: none;
  }
}
</style>
