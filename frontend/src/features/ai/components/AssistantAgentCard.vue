<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
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

</script>

<template>
  <Button
    variant="ghost"
    class="agent-card"
    :class="[`is-${variant}`, `is-${tone()}`, { 'is-live': live() }]"
    data-testid="assistant-agent-card"
    :aria-label="`${name()}，${agentStatusLabel(agent.status)}`"
    @click="open"
  >
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
  </Button>
</template>

<style scoped>
.agent-card { --agent-tone: var(--mist); display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-start; gap: var(--gap-1) var(--gap-2); width: 100%; height: auto; min-height: var(--ai-row-min); margin: 0; padding: var(--gap-2); border: 1px solid var(--rule); border-radius: var(--ai-r-card); background: var(--surface); color: var(--ink); white-space: normal; text-align: left; font-weight: 400; }
.agent-card:hover { border-color: var(--seal-border); background: var(--surface-hover); }
.agent-card:focus-visible { outline: 2px solid var(--seal); outline-offset: -2px; }
.agent-card.is-live { --agent-tone: var(--info-ink); border-color: var(--seal-border); }
.agent-card.is-error { --agent-tone: var(--warn-ink); border-color: color-mix(in oklab, var(--warn) 40%, var(--rule)); }
.agent-card.is-done { --agent-tone: var(--info-ink); }
.agent-card__name { flex: 1; min-width: 0; font-size: var(--ai-fs-body); font-weight: 600; overflow-wrap: anywhere; }
.agent-card__detail { order: 4; flex: 1 0 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--mist); font-size: var(--ai-fs-aux); }
.agent-card__status { flex: 0 0 auto; color: var(--agent-tone); font-size: var(--ai-fs-meta); }
.agent-card__pct { flex: 0 0 auto; color: var(--ink); font: var(--ai-fs-meta) var(--mono); font-variant-numeric: tabular-nums; }
</style>
