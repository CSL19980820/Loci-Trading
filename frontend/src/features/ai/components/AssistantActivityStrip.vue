<script setup lang="ts">
import { computed } from 'vue'

import { agentRunning } from '../assistantAgentUi'
import type { AiAgentProgress } from '@/shared/types/ai_assistant'
import AssistantAgentCard from './AssistantAgentCard.vue'

const props = defineProps<{
  lines: string[]
  agents: AiAgentProgress[]
}>()

const emit = defineEmits<{
  open: [agentId: string]
}>()

const liveCount = computed(() => props.agents.filter((agent) => agentRunning(agent.status)).length)
const headline = computed(() => {
  if (liveCount.value) return `${liveCount.value} 路运行中`
  if (props.agents.length) return `${props.agents.length} 路证据`
  return '子进程'
})
</script>

<template>
  <section
    v-if="agents.length"
    class="assistant-activity"
    :class="{ 'is-live': liveCount > 0 }"
    data-testid="assistant-activity-strip"
    aria-label="子进程活动"
  >
    <svg
      v-if="liveCount > 0"
      class="assistant-activity__flow"
      viewBox="0 0 100 40"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <rect
        class="assistant-activity__chase"
        x="1"
        y="1"
        width="98"
        height="38"
        rx="7"
        ry="7"
        pathLength="100"
      />
    </svg>
    <header class="assistant-activity__head">
      <div class="assistant-activity__lead">
        <span class="assistant-activity__mark" aria-hidden="true" />
        <strong>{{ headline }}</strong>
      </div>
      <span class="assistant-activity__hint">仅证据 · 非终裁</span>
    </header>
    <div class="assistant-activity__lane">
      <AssistantAgentCard
        v-for="agent in agents"
        :key="agent.id"
        :agent="agent"
        variant="lane"
        @open="emit('open', $event)"
      />
    </div>
  </section>
</template>

<style scoped>
.assistant-activity {
  position: relative;
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
  margin: 0;
  padding: .4rem .55rem;
  border: 1px solid color-mix(in srgb, var(--lake) 18%, var(--rule));
  border-radius: var(--ai-r-card);
  background: color-mix(in srgb, var(--lake-soft) 28%, var(--panel));
  overflow: hidden;
}
.assistant-activity__flow {
  display: none;
}
.assistant-activity.is-live .assistant-activity__flow {
  display: block;
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
  overflow: visible;
}
.assistant-activity__chase {
  fill: none;
  stroke: var(--lake);
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-dasharray: 10 90;
  animation: activity-shell-chase 1.7s linear infinite;
}
.assistant-activity__head {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .75rem;
  margin-bottom: .35rem;
}
.assistant-activity__lead {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: .4rem;
  font-size: var(--ai-fs-body);
}
.assistant-activity__lead strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 650;
}
.assistant-activity__mark {
  flex: 0 0 auto;
  width: .4rem;
  height: .4rem;
  border-radius: var(--ai-r-pill);
  background: var(--lake);
}
.assistant-activity__hint {
  flex: 0 0 auto;
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  letter-spacing: .03em;
  white-space: nowrap;
}
.assistant-activity__lane {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: .3rem;
  width: 100%;
  min-width: 0;
}
@keyframes activity-shell-chase {
  to { stroke-dashoffset: -100; }
}
@media (prefers-reduced-motion: reduce) {
  .assistant-activity__chase { animation: none; opacity: 0; }
  .assistant-activity.is-live {
    border-color: color-mix(in srgb, var(--lake) 40%, var(--rule));
    box-shadow: inset 2px 0 0 0 var(--lake);
  }
}
</style>
