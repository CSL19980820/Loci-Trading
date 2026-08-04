<script setup lang="ts">
import { Close, Clock, Plus, Promotion, Stopwatch } from '@element-plus/icons-vue'
import type { InputInstance } from 'element-plus'
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import AssistantAgentsRail from './AssistantAgentsRail.vue'
import AssistantConversation from './AssistantConversation.vue'
import AssistantSessionRail from './AssistantSessionRail.vue'
import type { AiAgentProgress, AiMessage, AiProviderProfile, AiSessionSummary } from '@/shared/types/ai_assistant'

const WIDTH_KEY = 'loci.assistant.panel.width'
const WIDTH_OPTIONS = [
  { label: '窄', value: 440 },
  { label: '标准', value: 560 },
  { label: '宽', value: 720 },
] as const

const props = defineProps<{
  open: boolean
  title?: string
  sessions: AiSessionSummary[]
  activeId?: string
  messages: AiMessage[]
  agents: AiAgentProgress[]
  loading?: boolean
  busy?: boolean
  waitingUser?: boolean
  providerReady: boolean
  providers: AiProviderProfile[]
  provider: string
  model: string
  models: string[]
  error?: string
}>()
const emit = defineEmits<{
  close: []
  create: []
  select: [id: string]
  remove: [id: string]
  send: [content: string]
  cancel: []
  provider: [name: string]
  model: [name: string]
  configure: []
}>()

const historyOpen = ref(false)
const sender = ref<InputInstance | null>(null)
const draft = ref('')
const preferredWidth = ref(560)

const drawerSize = computed(() => `min(${preferredWidth.value}px, 100dvw)`)
const compactBody = computed(() => preferredWidth.value < 520 || (historyOpen.value && props.agents.length > 0))
const headerTight = computed(() => preferredWidth.value < 480 || compactBody.value)
const sessionLocked = computed(() => Boolean(props.busy || props.waitingUser))
const showAgents = computed(() => props.agents.length > 0)

watch(() => props.open, async (open) => {
  if (!open || !props.providerReady) return
  await nextTick()
  sender.value?.focus()
})

onMounted(() => {
  const saved = Number(localStorage.getItem(WIDTH_KEY))
  if (WIDTH_OPTIONS.some((item) => item.value === saved)) preferredWidth.value = saved
})

function chooseWidth(next: number): void {
  preferredWidth.value = next
  localStorage.setItem(WIDTH_KEY, String(next))
}

function submit(): void {
  const content = draft.value.trim()
  if (!content || props.busy || !props.providerReady) return
  draft.value = ''
  emit('send', content)
}
</script>

<template>
  <el-drawer
    :model-value="open"
    direction="rtl"
    :size="drawerSize"
    :destroy-on-close="false"
    :with-header="false"
    aria-label="Loci 助手"
    class="assistant-drawer"
    @update:model-value="(value: boolean) => !value && emit('close')"
  >
    <section class="assistant-panel" :class="{ 'is-compact': compactBody }" aria-label="Loci 助手">
      <header class="assistant-panel__header" :class="{ 'is-tight': headerTight }">
        <div class="assistant-panel__title">
          <h2>{{ title || '新对话' }}</h2>
          <el-tag size="small" type="info">本机工具</el-tag>
        </div>
        <div class="assistant-panel__actions" :class="{ 'is-tight': headerTight }">
          <el-segmented
            :model-value="preferredWidth"
            size="small"
            :options="WIDTH_OPTIONS.map((item) => ({ label: item.label, value: item.value }))"
            aria-label="助手面板宽度"
            @change="chooseWidth(Number($event))"
          />
          <el-tooltip content="新建对话">
            <el-button
              :icon="Plus"
              circle
              text
              aria-label="新建对话"
              :disabled="sessionLocked"
              @click="emit('create')"
            />
          </el-tooltip>
          <el-tooltip content="历史对话">
            <el-button :icon="Clock" circle text aria-label="历史对话" :aria-pressed="historyOpen" @click="historyOpen = !historyOpen" />
          </el-tooltip>
          <el-tooltip v-if="busy || waitingUser" :content="waitingUser ? '取消等待' : '中止运行'">
            <el-button :icon="Stopwatch" circle text type="warning" aria-label="中止运行" @click="emit('cancel')" />
          </el-tooltip>
          <el-tooltip content="关闭助手">
            <el-button :icon="Close" circle text aria-label="关闭助手" @click="emit('close')" />
          </el-tooltip>
        </div>
        <div class="assistant-panel__runtime">
          <el-select
            :model-value="provider"
            size="small"
            aria-label="选择模型厂商"
            :disabled="sessionLocked || !providers.length"
            @update:model-value="emit('provider', String($event))"
          >
            <el-option v-for="item in providers" :key="item.name" :label="item.name" :value="item.name" />
          </el-select>
          <el-select
            :model-value="model"
            size="small"
            aria-label="选择模型"
            :disabled="sessionLocked || !models.length"
            @update:model-value="emit('model', String($event))"
          >
            <el-option v-for="item in models" :key="item" :label="item" :value="item" />
          </el-select>
        </div>
      </header>
      <el-alert v-if="error" class="assistant-panel__alert" type="error" :closable="false" :title="error" show-icon />
      <div v-if="!providerReady" class="assistant-panel__provider-empty">
        <el-alert class="assistant-panel__alert" type="warning" :closable="false" title="尚未配置可用模型，请先到运维完成供应商配置。" show-icon />
        <el-button data-testid="assistant-configure-provider" type="primary" plain size="small" @click="emit('configure')">配置 LLM 厂商</el-button>
      </div>
      <div class="assistant-panel__body">
        <AssistantSessionRail
          v-if="historyOpen"
          :sessions="sessions"
          :active-id="activeId"
          :loading="loading"
          :disabled="sessionLocked"
          @create="emit('create')"
          @select="emit('select', $event)"
          @remove="emit('remove', $event)"
        />
        <main class="assistant-panel__conversation">
          <div v-if="!messages.length && providerReady" class="assistant-empty">
            <p>问持仓、调配置、跑选股。数字都来自本机工具。</p>
            <div class="assistant-empty__actions">
              <el-button plain size="small" @click="emit('send', '今天持仓怎么样？')">查看持仓</el-button>
              <el-button plain size="small" @click="emit('send', '用当前默认策略跑一遍选股')">运行选股</el-button>
            </div>
          </div>
          <AssistantConversation
            v-else
            :messages="messages"
            :busy="busy"
            :waiting-user="waitingUser"
          />
        </main>
        <AssistantAgentsRail v-if="showAgents" :agents="agents" :overlay="compactBody" />
      </div>
      <footer class="assistant-panel__composer">
        <div class="assistant-panel__input-row">
          <el-input
            ref="sender"
            v-model="draft"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            resize="none"
            :disabled="busy || !providerReady"
            :placeholder="waitingUser ? '回复助手以继续…' : providerReady ? '输入问题，Enter 发送，Shift+Enter 换行' : '配置模型后即可开始对话'"
            aria-label="向 Loci 助手发送消息"
            @keydown.enter.exact.prevent="submit"
          />
          <el-tooltip :content="waitingUser ? '回复并继续' : '发送'">
            <el-button
              type="primary"
              circle
              :icon="Promotion"
              :loading="busy"
              :disabled="busy || !providerReady || !draft.trim()"
              aria-label="发送消息"
              @click="submit"
            />
          </el-tooltip>
        </div>
        <span aria-live="polite">
          {{ busy ? '正在运行，可关闭面板后继续等待。' : waitingUser ? '等待你的确认，直接回复即可。' : providerReady ? 'Enter 发送' : '模型未配置' }}
        </span>
      </footer>
    </section>
  </el-drawer>
</template>

<style scoped>
.assistant-panel { display: flex; height: 100%; min-height: 0; flex-direction: column; background: var(--sheet); color: var(--ink); }
.assistant-panel__header { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .45rem; padding: .45rem .7rem; border-bottom: 1px solid var(--rule); }
.assistant-panel__title { display: flex; min-width: 0; align-items: center; gap: .4rem; }
.assistant-panel__title h2 { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .9rem; }
.assistant-panel__runtime { display: grid; grid-column: 1 / -1; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .3rem; }
.assistant-panel__runtime :deep(.el-select) { min-width: 0; width: 100%; }
.assistant-panel__actions { display: flex; grid-column: 2; grid-row: 1; flex: 0 0 auto; flex-wrap: wrap; align-items: center; justify-content: end; gap: .15rem; }
.assistant-panel__actions :deep(.el-segmented) { margin-right: .15rem; }
.assistant-panel__header.is-tight { grid-template-columns: minmax(0, 1fr) auto; }
.assistant-panel__actions.is-tight { max-width: 100%; }
.assistant-panel__actions.is-tight :deep(.el-segmented) {
  flex: 1 1 100%;
  order: 5;
  margin: .15rem 0 0;
  min-width: 0;
}
.assistant-panel__actions.is-tight :deep(.el-segmented__item) {
  padding-inline: .35rem;
  font-size: .7rem;
}
.assistant-panel__alert { margin: .45rem .6rem 0; }
.assistant-panel__provider-empty { display: flex; align-items: center; gap: .45rem; margin: .45rem .6rem 0; }
.assistant-panel__provider-empty .assistant-panel__alert { margin: 0; flex: 1; }
.assistant-panel__body { position: relative; display: flex; min-height: 0; flex: 1; }
.assistant-panel__conversation { display: flex; min-width: 0; flex: 1; flex-direction: column; }
.assistant-empty {
  display: flex; min-height: 0; flex: 1; flex-direction: column; align-items: center; justify-content: center;
  gap: .65rem; padding: 1rem; text-align: center;
}
.assistant-empty p { margin: 0; max-width: 18rem; color: var(--muted); font-size: .86rem; line-height: 1.5; }
.assistant-empty__actions { display: flex; flex-wrap: wrap; justify-content: center; gap: .45rem; }
.assistant-panel__composer { padding: .6rem; border-top: 1px solid var(--rule); background: var(--sheet); }
.assistant-panel__input-row { display: flex; align-items: end; gap: .45rem; }
.assistant-panel__input-row :deep(.el-textarea) { flex: 1; }
.assistant-panel__input-row :deep(.el-button) { flex: 0 0 auto; }
.assistant-panel__composer > span { display: block; margin-top: .3rem; color: var(--mist); font-size: .7rem; }
.assistant-panel.is-compact :deep(.assistant-session-rail) {
  position: absolute; z-index: 5; inset: 0 auto 0 0; width: min(86%, 19rem); box-shadow: var(--shadow);
}
@media (max-width: 639px) {
  .assistant-panel :deep(.assistant-session-rail) {
    position: absolute; z-index: 5; inset: 0 auto 0 0; width: min(86%, 19rem); height: 100%; box-shadow: var(--shadow);
  }
}
</style>

<style>
/* Teleported drawer: fill height so .assistant-panel can stretch (see MobileBottomNav). */
.assistant-drawer.el-drawer .el-drawer__body {
  height: 100%;
  padding: 0;
  overflow: hidden;
}
</style>
