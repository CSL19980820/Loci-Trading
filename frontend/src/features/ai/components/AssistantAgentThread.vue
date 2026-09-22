<script setup lang="ts">
import { X as Close } from '@lucide/vue'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { IconBox } from '@/shared/components/ui/app/presentation'

import { computed } from 'vue'


import {
  agentDisplayName,
  agentRunning,
  agentStatusLabel,
  agentStatusTone,
} from '../assistantAgentUi'
import { localizeAgentLine } from '../toolLabel'
import type { AiAgentProgress } from '@/shared/types/ai_assistant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import AssistantToolReceiptList from './AssistantToolReceiptList.vue'

const props = defineProps<{
  open: boolean
  agent: AiAgentProgress | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const visible = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})

const title = computed(() => (props.agent ? agentDisplayName(props.agent) : '子进程'))
const tone = computed(() => (props.agent ? agentStatusTone(props.agent.status) : 'queued'))
const live = computed(() => (props.agent ? agentRunning(props.agent.status) : false))
const steps = computed(() =>
  (props.agent?.timeline ?? [])
    .map((item) => localizeAgentLine(item))
    .filter(Boolean),
)
const finished = computed(() => props.agent?.status === 'done' || props.agent?.status === 'error')
const summary = computed(() => {
  if (!finished.value || !props.agent) return ''
  const text = localizeAgentLine(props.agent.detail)
  if (!text) return ''
  if (text === '已完成只读取证' || text === '无摘要') return ''
  return text
})
const detailLive = computed(() => {
  if (finished.value) return ''
  return localizeAgentLine(props.agent?.detail)
})

function close(): void {
  visible.value = false
}
</script>

<template>
  <DialogPanel
    v-model="visible"
    width="min(92vw, 52rem)"
    top="5vh"
    append-to-body
    :modal="false"
    :show-close="false"
    class="assistant-agent-thread-dialog"
    data-testid="assistant-agent-thread"
  >
    <template #header>
      <div class="assistant-agent-thread__header" :class="[`is-${tone}`, { 'is-live': live }]">
        <span class="assistant-agent-thread__dot" aria-hidden="true" />
        <h3 class="assistant-agent-thread__title">{{ title }}</h3>
        <span v-if="agent" class="assistant-agent-thread__badge">
          {{ agentStatusLabel(agent.status) }}
        </span>
        <span
          v-if="agent?.progress != null"
          class="assistant-agent-thread__pct"
        >{{ agent.progress }}%</span>
        <ActionButton access="read"
          class="assistant-agent-thread__close"
          variant="ghost"
          icon-only
          aria-label="关闭"
          @click="close"
        >
          <IconBox :size="16"><Close /></IconBox>
        </ActionButton>
      </div>
    </template>

    <template v-if="agent">
      <div
        v-if="agent.progress != null"
        class="assistant-agent-thread__meter"
        role="progressbar"
        :aria-valuenow="agent.progress"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <i
          class="assistant-agent-thread__meter-fill"
          :class="{ 'is-error': agent.status === 'error', 'is-done': agent.status === 'done' }"
          :style="{ width: `${agent.progress}%` }"
        />
      </div>

      <p v-if="detailLive" class="assistant-agent-thread__detail">{{ detailLive }}</p>

      <section v-if="steps.length" class="assistant-agent-thread__block">
        <header class="assistant-agent-thread__block-head">
          <h4>加载过程</h4>
          <span>{{ steps.length }} 步</span>
        </header>
        <ol class="assistant-agent-thread__steps">
          <li
            v-for="(item, index) in steps"
            :key="`${agent.id}-${index}`"
            :class="{ 'is-last': index === steps.length - 1 && live }"
          >
            <span class="assistant-agent-thread__step-index" aria-hidden="true">{{ index + 1 }}</span>
            <p>{{ item }}</p>
          </li>
        </ol>
      </section>

      <section
        v-if="agent.tool_receipts?.length"
        class="assistant-agent-thread__block"
        data-testid="assistant-agent-tools"
      >
        <header class="assistant-agent-thread__block-head">
          <h4>工具回执</h4>
          <span>{{ agent.tool_receipts.length }} 条</span>
        </header>
        <AssistantToolReceiptList :tools="agent.tool_receipts" />
      </section>

      <section v-if="summary" class="assistant-agent-thread__block">
        <div class="assistant-agent-thread__summary">
          <h4>摘要</h4>
          <p>{{ summary }}</p>
        </div>
      </section>
    </template>
    <EmptyState v-else description="未选择子进程" />
  </DialogPanel>
</template>

<style scoped>
.assistant-agent-thread__header {
  --dot: var(--mist);
  display: flex;
  align-items: center;
  gap: .55rem;
  min-width: 0;
  width: 100%;
}
.assistant-agent-thread__header.is-running,
.assistant-agent-thread__header.is-live { --dot: var(--ok); }
.assistant-agent-thread__header.is-done { --dot: var(--ok); }
.assistant-agent-thread__header.is-error { --dot: var(--warn); }
.assistant-agent-thread__header.is-cancelled { --dot: var(--mist); }
.assistant-agent-thread__header.is-queued { --dot: var(--info); }
.assistant-agent-thread__dot {
  flex: 0 0 auto;
  width: .55rem;
  height: .55rem;
  border-radius: var(--ai-r-pill);
  background: var(--dot);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--dot) 18%, transparent);
}
.assistant-agent-thread__header.is-live .assistant-agent-thread__dot {
  animation: thread-dot-pulse 1.4s ease-in-out infinite;
}
.assistant-agent-thread__title {
  margin: 0;
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font);
  font-size: var(--ai-fs-title);
  font-weight: 650;
  line-height: 1.2;
}
.assistant-agent-thread__badge {
  flex: 0 0 auto;
  color: var(--mist);
  font-size: var(--ai-fs-meta);
  font-weight: 600;
  white-space: nowrap;
}
.assistant-agent-thread__header.is-done .assistant-agent-thread__badge { color: var(--ok); }
.assistant-agent-thread__header.is-error .assistant-agent-thread__badge { color: var(--warn); }
.assistant-agent-thread__pct {
  flex: 0 0 auto;
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.assistant-agent-thread__close {
  flex: 0 0 auto;
  margin: 0 0 0 .15rem !important;
  width: 1.7rem !important;
  height: 1.7rem !important;
  padding: 0 !important;
  color: var(--mist) !important;
}
.assistant-agent-thread__close:hover,
.assistant-agent-thread__close:focus-visible {
  color: var(--ink) !important;
  background: color-mix(in oklab, var(--ink) 6%, transparent) !important;
}
.assistant-agent-thread__meter {
  height: 3px;
  overflow: hidden;
  border-radius: var(--ai-r-pill);
  background: color-mix(in oklab, var(--ink) 8%, transparent);
  margin-bottom: .75rem;
}
.assistant-agent-thread__meter-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--ok);
  transition: width .25s ease;
}
.assistant-agent-thread__meter-fill.is-done { background: var(--ok); }
.assistant-agent-thread__meter-fill.is-error { background: var(--warn); }
.assistant-agent-thread__detail {
  margin: 0 0 .75rem;
  padding: .55rem .65rem;
  border: 1px solid var(--rule);
  border-radius: var(--ai-r-card);
  background: color-mix(in oklab, var(--panel-2) 88%, transparent);
  font-size: var(--ai-fs-body);
  line-height: 1.45;
  white-space: pre-wrap;
}
.assistant-agent-thread__block {
  margin-bottom: .85rem;
}
.assistant-agent-thread__block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: .5rem;
  margin-bottom: .45rem;
}
.assistant-agent-thread__block-head h4 {
  margin: 0;
  font-size: var(--ai-fs-aux);
  font-weight: 650;
  color: var(--mist);
}
.assistant-agent-thread__block-head span {
  color: var(--mist);
  font-size: var(--ai-fs-meta);
}
.assistant-agent-thread__steps {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
}
.assistant-agent-thread__steps li {
  display: grid;
  grid-template-columns: 1.3rem minmax(0, 1fr);
  gap: .5rem;
  position: relative;
  padding: 0 0 .55rem;
}
.assistant-agent-thread__steps li:not(:last-child)::before {
  content: '';
  position: absolute;
  left: .55rem;
  top: 1.2rem;
  bottom: 0;
  width: 1px;
  background: color-mix(in oklab, var(--rule) 85%, var(--ink) 8%);
}
.assistant-agent-thread__step-index {
  display: grid;
  place-items: center;
  width: 1.1rem;
  height: 1.1rem;
  border-radius: var(--ai-r-pill);
  border: 1px solid var(--rule);
  background: var(--panel);
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  z-index: 1;
}
.assistant-agent-thread__steps li.is-last .assistant-agent-thread__step-index {
  border-color: color-mix(in oklab, var(--ok) 45%, var(--rule));
  background: var(--ok-soft);
  color: var(--ok);
}
.assistant-agent-thread__steps p {
  margin: .02rem 0 0;
  font-size: var(--ai-fs-body);
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.assistant-agent-thread__summary {
  display: flex;
  align-items: baseline;
  gap: .5rem;
  padding: .6rem .7rem;
  border: 1px solid color-mix(in oklab, var(--ok) 24%, var(--rule));
  border-radius: var(--ai-r-card);
  background: color-mix(in oklab, var(--ok-soft) 40%, var(--panel));
}
.assistant-agent-thread__summary h4 {
  flex: 0 0 auto;
  margin: 0;
  font-size: var(--ai-fs-aux);
  font-weight: 650;
  color: var(--mist);
}
.assistant-agent-thread__summary p {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  font-size: var(--ai-fs-body);
  line-height: 1.45;
  white-space: pre-wrap;
}
@keyframes thread-dot-pulse {
  0%, 100% { box-shadow: 0 0 0 3px color-mix(in oklab, var(--dot) 16%, transparent); }
  50% { box-shadow: 0 0 0 6px color-mix(in oklab, var(--dot) 10%, transparent); }
}
@media (prefers-reduced-motion: reduce) {
  .assistant-agent-thread__header.is-live .assistant-agent-thread__dot,
  .assistant-agent-thread__meter-fill { animation: none; transition: none; }
}
</style>

<style>
.assistant-agent-thread-dialog.dialog-panel {
  width: min(92vw, 52rem) !important;
  max-width: calc(100vw - 1.5rem);
  margin-top: 5vh !important;
  border-radius: var(--ai-r-card);
  overflow: hidden;
}
.assistant-agent-thread-dialog .dialog-panel__header {
  margin: 0;
  padding: .7rem .85rem;
  border-bottom: 1px solid var(--rule);
  background: color-mix(in oklab, var(--panel-2) 88%, transparent);
}
.assistant-agent-thread-dialog .dialog-panel__body {
  max-height: min(78dvh, 44rem);
  overflow: auto;
  padding: .85rem 1rem 1rem;
}
</style>
