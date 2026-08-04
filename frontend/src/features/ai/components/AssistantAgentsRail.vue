<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { AiAgentProgress } from '@/shared/types/ai_assistant'

const props = defineProps<{ agents: AiAgentProgress[]; overlay?: boolean }>()

const expanded = ref<string[]>([])
const knownIds = ref<string[]>([])
const dismissed = ref(false)
const agentIds = computed(() => props.agents.map((agent) => agent.id))
const visible = computed(() => props.agents.length > 0 && !(props.overlay && dismissed.value))

watch(agentIds, (ids) => {
  dismissed.value = false
  const next = ids.filter((id) => !knownIds.value.includes(id))
  expanded.value = [...expanded.value.filter((id) => ids.includes(id)), ...next]
  knownIds.value = ids
}, { immediate: true })

function statusType(status: AiAgentProgress['status']): 'success' | 'danger' | 'warning' | 'info' {
  return status === 'done' ? 'success' : status === 'error' ? 'danger' : status === 'running' ? 'warning' : 'info'
}

function statusText(status: AiAgentProgress['status']): string {
  return { queued: '等待中', running: '运行中', done: '完成', error: '失败' }[status]
}
</script>

<template>
  <template v-if="visible">
    <div
      v-if="overlay"
      class="assistant-agents__backdrop"
      data-testid="assistant-agents-backdrop"
      role="button"
      tabindex="0"
      aria-label="收起子 Agent 面板"
      @click="dismissed = true"
      @keydown.enter.prevent="dismissed = true"
      @keydown.space.prevent="dismissed = true"
    />
    <aside class="assistant-agents" :class="{ 'is-overlay': overlay }" aria-label="子 Agent 状态">
      <h3>子 Agent</h3>
      <el-collapse v-model="expanded" class="assistant-agents__collapse">
        <el-collapse-item v-for="agent in agents" :key="agent.id" :name="agent.id">
          <template #title>
            <span class="assistant-agent-row__title">
              <strong>{{ agent.name || agent.id }}</strong>
              <el-tag size="small" :type="statusType(agent.status)">{{ statusText(agent.status) }}</el-tag>
            </span>
          </template>
          <div class="assistant-agent-row">
            <el-progress v-if="agent.progress != null" :percentage="agent.progress" :stroke-width="4" />
            <p v-if="agent.detail">{{ agent.detail }}</p>
            <el-timeline v-if="agent.timeline?.length" class="assistant-agent-row__timeline">
              <el-timeline-item v-for="(item, index) in agent.timeline" :key="`${agent.id}-${index}`" :type="statusType(agent.status)" hollow>
                {{ item }}
              </el-timeline-item>
            </el-timeline>
          </div>
        </el-collapse-item>
      </el-collapse>
    </aside>
  </template>
</template>

<style scoped>
.assistant-agents__backdrop {
  position: absolute;
  inset: 0;
  z-index: 2;
  background: color-mix(in srgb, var(--ink) 28%, transparent);
  cursor: pointer;
}
.assistant-agents { flex: 0 0 168px; overflow: auto; border-left: 1px solid var(--rule); background: var(--panel-2); }
.assistant-agents.is-overlay {
  position: absolute; z-index: 3; inset: 0 0 0 auto; width: min(72%, 15.5rem); box-shadow: var(--shadow);
}
.assistant-agents h3 { margin: 0; padding: .65rem .7rem; border-bottom: 1px solid var(--rule); font-size: .8rem; }
.assistant-agents__collapse { border: 0; }
.assistant-agents__collapse :deep(.el-collapse-item__header) { min-height: 2.45rem; padding: .35rem .7rem; border-color: var(--rule); background: transparent; color: var(--ink); line-height: 1.2; }
.assistant-agents__collapse :deep(.el-collapse-item__wrap) { border-color: var(--rule); background: transparent; }
.assistant-agents__collapse :deep(.el-collapse-item__content) { padding-bottom: 0; }
.assistant-agent-row__title { display: flex; min-width: 0; flex: 1; align-items: center; gap: .35rem; padding-right: .35rem; }
.assistant-agent-row__title strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .76rem; }
.assistant-agent-row__title :deep(.el-tag) { margin-left: auto; }
.assistant-agent-row { padding: .1rem .7rem .55rem; }
.assistant-agent-row p { margin: .35rem 0 0; color: var(--mist); font-size: .72rem; line-height: 1.4; white-space: pre-wrap; overflow-wrap: anywhere; }
.assistant-agent-row__timeline { margin: .5rem 0 0; padding-left: .15rem; }
.assistant-agent-row__timeline :deep(.el-timeline-item) { padding-bottom: .3rem; }
.assistant-agent-row__timeline :deep(.el-timeline-item__content) { color: var(--mist); font-size: .7rem; line-height: 1.35; overflow-wrap: anywhere; }
</style>
