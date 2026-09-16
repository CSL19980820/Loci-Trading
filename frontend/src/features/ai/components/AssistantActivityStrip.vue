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
.assistant-activity { width: 100%; max-width: 100%; min-width: 0; box-sizing: border-box; margin: 0; padding: var(--gap-2); border: 1px solid var(--rule); border-radius: var(--ai-r-card); background: var(--surface-sunken); overflow: hidden; }
.assistant-activity.is-live { border-color: var(--seal-border); }
.assistant-activity__head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--gap-2); margin-bottom: var(--gap-2); }
.assistant-activity__lead { display: flex; min-width: 0; align-items: center; gap: var(--gap-2); font-size: var(--ai-fs-body); }
.assistant-activity__lead strong { font-weight: 600; }
.assistant-activity__mark { flex: 0 0 auto; width: var(--gap-1); height: var(--gap-1); border-radius: var(--ai-r-pill); background: var(--mist); }
.assistant-activity.is-live .assistant-activity__mark { background: var(--seal); }
.assistant-activity__hint { color: var(--mist); font-size: var(--ai-fs-meta); }
.assistant-activity__lane { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr)); gap: var(--gap-2); width: 100%; min-width: 0; }
</style>
