<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { toolLabel } from '../toolLabel'
import type { AiToolReceipt } from '@/shared/types/ai_assistant'
import AssistantToolReceiptRow from './AssistantToolReceiptRow.vue'

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
      ? `本机回执 · ${ok} 成功 · ${errorCount.value} 失败`
      : '本机回执 · 含失败'
  }
  return `本机回执 · ${props.tools.length} 步`
})

const overviewMs = computed(() => {
  if (totalMs.value == null) return ''
  return `${totalMs.value}ms`
})

const railClass = computed(() => ({
  'is-featured': !props.hasActivity,
  'is-quiet': Boolean(props.hasActivity),
  'is-running': Boolean(runningTool.value),
  'is-open': expanded.value,
}))

function toggle(): void {
  expanded.value = !expanded.value
}

</script>

<template>
  <section
    v-if="tools.length"
    class="assistant-receipts"
    :class="railClass"
    aria-label="本机回执"
    data-testid="assistant-receipts"
  >
    <el-button
      text
      class="assistant-receipts__toggle"
      :aria-expanded="expanded"
      @click="toggle"
    >
      <span class="assistant-receipts__left">
        <span class="assistant-receipts__pulse" aria-hidden="true" />
        <strong class="assistant-receipts__overview" :title="overview">{{ overview }}</strong>
      </span>
      <span class="assistant-receipts__right">
        <small v-if="overviewMs" class="assistant-receipts__ms">{{ overviewMs }}</small>
        <span class="assistant-receipts__chevron">{{ expanded ? '收起' : '展开' }}</span>
      </span>
    </el-button>
    <div v-if="expanded" class="assistant-receipts__list">
      <AssistantToolReceiptRow
        v-for="tool in tools"
        :key="tool.call_id"
        :tool="tool"
        :prefer-open="tool.status === 'error'"
      />
    </div>
  </section>
</template>

<style scoped>
.assistant-receipts { display: grid; gap: var(--gap-1); width: 100%; max-width: 100%; min-width: 0; box-sizing: border-box; padding: var(--gap-1); border: 1px solid var(--rule); border-radius: var(--ai-r-card); background: var(--surface-sunken); overflow: hidden; }
.assistant-receipts.is-running { border-color: var(--seal-border); }
.assistant-receipts__toggle { width: 100%; max-width: 100%; height: auto; min-height: var(--ai-row-min); padding: var(--gap-2); margin: 0; color: var(--ink); white-space: normal; }
.assistant-receipts__toggle :deep(> span) { display: flex; align-items: center; justify-content: space-between; gap: var(--gap-2); width: 100%; min-width: 0; }
.assistant-receipts__toggle:focus-visible { outline: 2px solid var(--seal); outline-offset: -2px; }
.assistant-receipts__left, .assistant-receipts__right { display: inline-flex; align-items: center; gap: var(--gap-2); min-width: 0; }
.assistant-receipts__left { flex: 1; }
.assistant-receipts__right { flex: 0 0 auto; margin-left: auto; }
.assistant-receipts__pulse { flex: 0 0 auto; width: var(--gap-1); height: var(--gap-1); border-radius: var(--ai-r-pill); background: var(--mist); }
.assistant-receipts.is-running .assistant-receipts__pulse { background: var(--seal); }
.assistant-receipts__overview { min-width: 0; font-size: var(--ai-fs-body); font-weight: 600; text-align: left; overflow-wrap: anywhere; }
.assistant-receipts__ms, .assistant-receipts__chevron { color: var(--mist); font-size: var(--ai-fs-meta); }
.assistant-receipts__ms { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.assistant-receipts__list { display: grid; gap: var(--gap-1); width: 100%; min-width: 0; }
@container (max-width: 400px) { .assistant-receipts__toggle :deep(> span) { flex-wrap: wrap; } }
</style>
