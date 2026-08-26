<script setup lang="ts">
import {
  agentDisplayName,
  agentRunning,
  agentStatusLabel,
  agentStatusTone,
} from '../assistantAgentUi'
import { localizeAgentLine } from '../toolLabel'
import type { AiAgentProgress } from '@/shared/types/ai_assistant'

const props = withDefaults(defineProps<{
  agent: AiAgentProgress
  /** lane = chat activity; rail = task sidebar */
  variant?: 'lane' | 'rail'
}>(), {
  variant: 'rail',
})

const emit = defineEmits<{
  open: [agentId: string]
}>()

const tone = () => agentStatusTone(props.agent.status)
const name = () => agentDisplayName(props.agent)
const live = () => agentRunning(props.agent.status)

/** 过滤空话 / 占位 detail；完成态不占中间位 */
function detailText(): string {
  if (!live()) return ''
  const raw = localizeAgentLine(props.agent.detail)
  if (!raw || raw === '未取得可用证据' || raw === '查看证据摘要') return '执行中…'
  return raw
}

function open(): void {
  emit('open', props.agent.id)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    open()
  }
}
</script>

<template>
  <div
    class="agent-card"
    :class="[`is-${variant}`, `is-${tone()}`, { 'is-live': live() }]"
    role="button"
    tabindex="0"
    data-testid="assistant-agent-card"
    :aria-label="`${name()}，${agentStatusLabel(agent.status)}`"
    @click="open"
    @keydown="onKeydown"
  >
    <!-- 方案 A：SVG 边框追光（短 dash 沿周界跑），避免 conic 在 WebView 崩成斜线 -->
    <svg
      v-if="live()"
      class="agent-card__flow"
      viewBox="0 0 100 36"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <rect
        class="agent-card__chase"
        x="1"
        y="1"
        width="98"
        height="34"
        rx="6"
        ry="6"
        pathLength="100"
      />
    </svg>
    <span class="agent-card__name">{{ name() }}</span>
    <span
      v-if="detailText()"
      class="agent-card__detail"
      :title="detailText()"
    >{{ detailText() }}</span>
    <span class="agent-card__status">{{ agentStatusLabel(agent.status) }}</span>
    <span
      v-if="agent.progress != null && live()"
      class="agent-card__pct"
    >{{ agent.progress }}%</span>
  </div>
</template>

<style scoped>
.agent-card {
  --dot: var(--mist);
  position: relative;
  display: flex;
  align-items: center;
  gap: .55rem;
  width: 100%;
  min-height: var(--ai-row-min);
  margin: 0;
  padding: .32rem .6rem;
  border: 1px solid color-mix(in srgb, var(--rule) 88%, var(--ink) 12%);
  border-radius: var(--ai-r-card);
  background: var(--panel);
  color: var(--ink);
  box-sizing: border-box;
  cursor: pointer;
  overflow: hidden;
  transition: border-color .16s ease, background .16s ease;
}
.agent-card:hover,
.agent-card:focus-visible {
  border-color: color-mix(in srgb, var(--seal) 35%, var(--rule));
  background: color-mix(in srgb, var(--seal-soft) 40%, var(--panel));
  outline: none;
}
.agent-card:focus-visible {
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--seal) 28%, transparent);
}
.agent-card.is-live {
  border-color: color-mix(in srgb, var(--lake) 30%, var(--rule));
  background: var(--panel);
}
.agent-card.is-error {
  border-color: color-mix(in srgb, var(--loss) 40%, var(--rule));
}
.agent-card.is-cancelled {
  --dot: var(--mist);
  border-color: var(--rule);
  opacity: .88;
}
.agent-card.is-done { --dot: var(--lake); }
.agent-card.is-running,
.agent-card.is-queued { --dot: var(--lake); }
.agent-card__flow {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
  overflow: visible;
}
.agent-card__chase {
  fill: none;
  stroke: var(--lake);
  stroke-width: 1.75;
  stroke-linecap: round;
  stroke-dasharray: 12 88;
  animation: agent-card-chase 1.6s linear infinite;
}
.agent-card__name,
.agent-card__detail,
.agent-card__status,
.agent-card__pct {
  position: relative;
  z-index: 1;
}
.agent-card__name {
  flex: 0 0 auto;
  font-size: var(--ai-fs-body);
  font-weight: 650;
  letter-spacing: .01em;
  white-space: nowrap;
}
.agent-card__detail {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--mist);
  font-size: var(--ai-fs-aux);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-card__status {
  flex: 0 0 auto;
  margin-left: auto;
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  letter-spacing: .02em;
  white-space: nowrap;
}
.agent-card.is-done .agent-card__status {
  color: var(--success);
}
.agent-card.is-error .agent-card__status {
  color: var(--loss);
}
.agent-card.is-cancelled .agent-card__status {
  color: var(--mist);
}
.agent-card__pct {
  flex: 0 0 auto;
  color: var(--ink);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
@keyframes agent-card-chase {
  to { stroke-dashoffset: -100; }
}
@media (prefers-reduced-motion: reduce) {
  .agent-card__chase { animation: none; stroke-dasharray: none; opacity: 0; }
  .agent-card.is-live {
    border-color: color-mix(in srgb, var(--lake) 45%, var(--rule));
    box-shadow: inset 2px 0 0 0 var(--lake);
  }
}
</style>
