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

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    toggle()
  }
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
    <div
      class="assistant-receipts__toggle"
      role="button"
      tabindex="0"
      :aria-expanded="expanded"
      @click="toggle"
      @keydown="onKeydown"
    >
      <span class="assistant-receipts__flow" aria-hidden="true" />
      <span class="assistant-receipts__left">
        <span class="assistant-receipts__pulse" aria-hidden="true" />
        <strong class="assistant-receipts__overview">{{ overview }}</strong>
      </span>
      <span class="assistant-receipts__right">
        <small v-if="overviewMs" class="assistant-receipts__ms">{{ overviewMs }}</small>
        <span class="assistant-receipts__chevron">{{ expanded ? '收起' : '展开' }}</span>
      </span>
    </div>
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
.assistant-receipts {
  position: relative;
  display: grid;
  gap: .3rem;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: .35rem .5rem;
  border: 1px solid var(--rule);
  border-radius: var(--ai-r-card);
  background: var(--panel-2);
  overflow: hidden;
}
.assistant-receipts.is-featured {
  border-color: color-mix(in srgb, var(--el-color-primary) 35%, var(--rule));
}
.assistant-receipts.is-quiet {
  border-color: var(--rule);
  background: color-mix(in srgb, var(--panel-2) 88%, transparent);
}
.assistant-receipts.is-running {
  border-style: dashed;
  border-color: color-mix(in srgb, var(--el-color-primary) 40%, var(--rule));
}
.assistant-receipts__toggle {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  width: 100%;
  max-width: 100%;
  min-height: var(--ai-row-min);
  padding: .22rem .15rem;
  margin: 0;
  box-sizing: border-box;
  cursor: pointer;
  overflow: hidden;
}
.assistant-receipts__toggle:hover,
.assistant-receipts__toggle:focus-visible {
  background: color-mix(in srgb, var(--ink) 3.5%, transparent);
  outline: none;
  border-radius: var(--ai-r-chip);
}
.assistant-receipts__toggle:focus-visible {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--seal) 28%, transparent);
}
.assistant-receipts__flow {
  display: none;
}
.assistant-receipts.is-running .assistant-receipts__flow {
  display: block;
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(
    110deg,
    transparent 0%,
    transparent 38%,
    color-mix(in srgb, var(--el-color-primary) 14%, transparent) 50%,
    transparent 62%,
    transparent 100%
  );
  background-size: 220% 100%;
  animation: receipts-shell-flow 1.5s linear infinite;
}
.assistant-receipts__left,
.assistant-receipts__right {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: .45rem;
  min-width: 0;
}
.assistant-receipts__left {
  flex: 1 1 auto;
}
.assistant-receipts__right {
  flex: 0 0 auto;
  margin-left: auto;
  gap: .65rem;
}
.assistant-receipts__pulse {
  flex: 0 0 auto;
  display: block;
  width: .4rem;
  height: .4rem;
  border-radius: var(--ai-r-pill);
  background: var(--mist);
}
.assistant-receipts.is-running .assistant-receipts__pulse {
  background: var(--el-color-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 22%, transparent);
  animation: assistant-receipts-pulse 1.2s ease-in-out infinite;
}
.assistant-receipts.is-featured:not(.is-quiet) .assistant-receipts__pulse {
  background: var(--el-color-primary);
}
.assistant-receipts__overview {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ai-fs-body);
  font-weight: 650;
  color: var(--ink);
  text-align: left;
}
.assistant-receipts__ms {
  flex: 0 0 auto;
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  font-variant-numeric: tabular-nums;
}
.assistant-receipts__chevron {
  flex: 0 0 auto;
  font-size: var(--ai-fs-meta);
  color: var(--mist);
  font-weight: 500;
  opacity: .85;
}
.assistant-receipts__toggle:hover .assistant-receipts__chevron {
  color: var(--ink);
  opacity: 1;
}
.assistant-receipts__list {
  position: relative;
  z-index: 1;
  display: grid;
  gap: .28rem;
  width: 100%;
  min-width: 0;
}
@keyframes assistant-receipts-pulse {
  0%, 100% {
    opacity: 1;
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--el-color-primary) 18%, transparent);
  }
  50% {
    opacity: .7;
    box-shadow: 0 0 0 5px color-mix(in srgb, var(--el-color-primary) 8%, transparent);
  }
}
@keyframes receipts-shell-flow {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}
@media (prefers-reduced-motion: reduce) {
  .assistant-receipts.is-running .assistant-receipts__pulse,
  .assistant-receipts.is-running .assistant-receipts__flow {
    animation: none;
  }
  .assistant-receipts.is-running .assistant-receipts__flow {
    display: none;
  }
}
</style>
