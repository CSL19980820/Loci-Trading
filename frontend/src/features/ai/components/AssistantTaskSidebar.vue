<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import type {
  AiAssistantProfile,
  AiChartArtifact,
  AiMemoryItem,
  AiToolReceipt,
} from '@/shared/types/ai_assistant'
import { agentRunning } from '../assistantAgentUi'
import type { AssistantTaskModel, TaskPlanStep } from '../assistantTaskModel'
import AssistantAgentCard from './AssistantAgentCard.vue'

type InspectorTab = 'plan' | 'agents' | 'sources' | 'artifacts' | 'cabin'

const props = defineProps<{
  model: AssistantTaskModel
  open?: boolean
  tools?: AiToolReceipt[]
  artifacts?: AiChartArtifact[]
  /** 由 Host 统一加载下发。侧栏自己再拉一份会在改完设置后显示旧值。 */
  profile?: AiAssistantProfile | null
  memories?: AiMemoryItem[]
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'open-agent': [agentId: string]
  settings: []
}>()

const visible = computed({
  get: () => props.open !== false,
  set: (value: boolean) => emit('update:open', value),
})

const activeTab = ref<InspectorTab>('plan')

const memories = computed(() => props.memories ?? [])
const usage = computed(() => props.profile?.memory_usage || { user: 0, memory: 0 })
const rules = computed(() => props.profile?.rules || [])
const tools = computed(() => props.tools ?? [])
const cabinArtifacts = computed(() => props.artifacts ?? props.model.artifacts)
const liveAgents = computed(() => props.model.agents.filter((agent) => agentRunning(agent.status)).length)

const tabs = computed(() => {
  const rows: Array<{ value: InspectorTab; label: string; count?: number }> = [
    { value: 'plan', label: '计划', count: props.model.plan.length || undefined },
    { value: 'agents', label: '子进程', count: props.model.agents.length || undefined },
    { value: 'sources', label: '来源', count: props.model.sources.length || undefined },
    { value: 'artifacts', label: '产物', count: props.model.artifacts.length || undefined },
    { value: 'cabin', label: '上下文' },
  ]
  return rows
})

watch(
  () => props.model.agents.length,
  (count, prev) => {
    if (count > 0 && count !== prev) activeTab.value = 'agents'
  },
)

onMounted(() => {
  if (props.model.agents.length) activeTab.value = 'agents'
  else if (props.model.plan.length) activeTab.value = 'plan'
})

function planLabel(status: TaskPlanStep['status']): string {
  return { queued: '排队', running: '进行中', done: '完成', error: '失败' }[status]
}

function artifactLabel(status: AiChartArtifact['status'] | undefined): string {
  if (status === 'loading') return '渲染中'
  if (status === 'error') return '失败'
  return '就绪'
}
</script>

<template>
  <aside
    class="assistant-task-sidebar"
    :class="{ 'is-collapsed': !visible }"
    data-testid="assistant-task-sidebar"
    aria-label="任务侧栏"
  >
    <div v-if="!visible" class="assistant-task-sidebar__rail">
      <el-tooltip content="展开侧栏" placement="left">
        <el-button
          class="assistant-task-sidebar__toggle"
          text
          circle
          aria-label="展开任务侧栏"
          data-testid="task-sidebar-expand"
          @click="visible = true"
        >
          <span class="assistant-panel-toggle-icon is-right" aria-hidden="true" />
        </el-button>
      </el-tooltip>
      <span v-if="liveAgents" class="assistant-task-sidebar__live-dot" :title="`${liveAgents} 路运行中`" />
    </div>

    <template v-else>
      <header class="assistant-task-sidebar__head">
        <span class="assistant-task-sidebar__title">本轮</span>
        <div
          class="assistant-task-sidebar__toggle"
          role="button"
          tabindex="0"
          aria-label="收起任务侧栏"
          data-testid="task-sidebar-collapse"
          title="收起侧栏"
          @click="visible = false"
          @keydown.enter.prevent="visible = false"
          @keydown.space.prevent="visible = false"
        >
          <span class="assistant-panel-toggle-icon is-right is-open" aria-hidden="true" />
        </div>
      </header>

      <nav class="assistant-task-sidebar__tabs" aria-label="任务分区">
        <el-button
          v-for="tab in tabs"
          :key="tab.value"
          class="assistant-task-sidebar__tab"
          :class="{ 'is-active': activeTab === tab.value }"
          size="small"
          text
          @click="activeTab = tab.value"
        >
          {{ tab.label }}
          <em v-if="tab.count">{{ tab.count }}</em>
        </el-button>
      </nav>

      <div class="assistant-task-sidebar__pane" data-testid="task-sidebar-pane">
        <section v-if="activeTab === 'plan'" class="assistant-task-sidebar__section">
          <p v-if="!model.plan.length" class="assistant-task-sidebar__empty">还没有计划步骤</p>
          <ol v-else class="assistant-task-sidebar__plan">
            <li
              v-for="(step, index) in model.plan"
              :key="step.id"
              class="assistant-task-sidebar__plan-step"
              :class="[`is-${step.status}`, { 'is-active': step.status === 'running' }]"
            >
              <span class="assistant-task-sidebar__plan-index" aria-hidden="true">{{ index + 1 }}</span>
              <div class="assistant-task-sidebar__plan-body">
                <strong>{{ step.label }}</strong>
                <span>{{ planLabel(step.status) }}</span>
              </div>
            </li>
          </ol>
        </section>

        <section v-else-if="activeTab === 'agents'" class="assistant-task-sidebar__section">
          <p v-if="!model.agents.length" class="assistant-task-sidebar__empty">
            暂无子进程。主助手需要并行取证时会在这里出现。
          </p>
          <div v-else class="assistant-task-sidebar__agents">
            <AssistantAgentCard
              v-for="agent in model.agents"
              :key="agent.id"
              :agent="agent"
              variant="rail"
              @open="emit('open-agent', $event)"
            />
          </div>
        </section>

        <section v-else-if="activeTab === 'sources'" class="assistant-task-sidebar__section">
          <p v-if="!model.sources.length" class="assistant-task-sidebar__empty">本轮还没查数据</p>
          <ul v-else class="assistant-task-sidebar__list">
            <li v-for="source in model.sources" :key="source.id">
              <span class="assistant-task-sidebar__chip">
                {{ source.kind === 'tool' ? '工具' : source.kind === 'artifact' ? '图/表' : '规则' }}
              </span>
              <div>
                <strong>{{ source.label }}</strong>
                <p v-if="source.detail" :title="source.detail">{{ source.detail }}</p>
              </div>
            </li>
          </ul>
        </section>

        <section v-else-if="activeTab === 'artifacts'" class="assistant-task-sidebar__section">
          <p v-if="!model.artifacts.length" class="assistant-task-sidebar__empty">暂无产物</p>
          <ul v-else class="assistant-task-sidebar__list">
            <li v-for="item in model.artifacts" :key="item.id">
              <span class="assistant-task-sidebar__chip">{{ artifactLabel(item.status) }}</span>
              <div>
                <strong>{{ item.title || item.kind }}</strong>
              </div>
            </li>
          </ul>
        </section>

        <section v-else class="assistant-task-sidebar__section">
          <div class="assistant-task-sidebar__cabin">
            <div class="assistant-task-sidebar__cabin-card">
              <span>安全</span>
              <p>不造数 · 不下单 · 子进程只做证据</p>
            </div>
            <div class="assistant-task-sidebar__cabin-card">
              <span>关于你</span>
              <p>{{ profile?.about_user || '未设置' }}</p>
            </div>
            <div class="assistant-task-sidebar__cabin-card">
              <span>回答偏好</span>
              <p>{{ profile?.response_style || '默认' }}</p>
            </div>
            <div class="assistant-task-sidebar__cabin-card">
              <span>记忆</span>
              <p>用户 {{ usage.user }}/2200 · 工作 {{ usage.memory }}/4000 · 共 {{ memories.length }} 条 · 规则 {{ rules.length }}</p>
            </div>
            <div class="assistant-task-sidebar__cabin-card">
              <span>本轮</span>
              <p>
                <template v-if="tools.length || cabinArtifacts.length">
                  {{ tools.length }} 次查询
                  <template v-if="cabinArtifacts.length"> · {{ cabinArtifacts.length }} 个图/表</template>
                </template>
                <template v-else>还没查</template>
                · 子进程 {{ model.agents.length || '无' }}
              </p>
            </div>
            <el-button size="small" plain @click="emit('settings')">改设置</el-button>
          </div>
        </section>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.assistant-task-sidebar {
  display: flex;
  flex-direction: column;
  gap: var(--ai-gap-md);
  /*
   * shrink 因子必须 > 0：原来写 0 0 300px，旁边的 min-width 对不可收缩的 flex 项无效，
   * 窄屏下正文区被压到 0 还溢出弹窗。980px 以下由 AssistantPanel 的断点直接折成 44px
   * rail（折叠态是 v-if 切 DOM 的，纯 CSS 收窄只会把展开态内容裁掉），
   * 这里的可收缩只兜中间地带；min-width 是「任务列表还读得出来」的下限。
   * width 删掉：flex-basis 已经给了宽度，两处写宽度只会打架。
   */
  flex: 0 1 300px;
  min-width: 240px;
  min-height: 0;
  overflow: hidden;
  border-left: 1px solid var(--rule);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--panel-2) 92%, var(--ink) 3%), var(--panel-2));
  padding: .7rem .75rem .85rem;
  transition: flex-basis .18s ease, width .18s ease, padding .18s ease;
}
.assistant-task-sidebar.is-collapsed {
  flex: 0 0 44px;
  /* 展开态的 min-width 会把 44px 的 rail 撑回 240px，折叠时必须清掉 */
  min-width: 0;
  width: 44px;
  padding: .45rem 0;
  overflow: hidden;
  align-items: center;
}
.assistant-task-sidebar__rail {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  gap: .45rem;
  padding-top: .2rem;
}
.assistant-task-sidebar__live-dot {
  width: .45rem;
  height: .45rem;
  border-radius: var(--ai-r-pill);
  background: var(--lake);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--lake) 22%, transparent);
  animation: task-live-pulse 1.4s ease-in-out infinite;
}
.assistant-task-sidebar__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  min-height: 1.6rem;
}
.assistant-task-sidebar__title {
  margin: 0;
  color: var(--mist);
  font-size: var(--ai-fs-meta);
  font-weight: 650;
  letter-spacing: .04em;
  line-height: 1;
}
.assistant-task-sidebar__toggle {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: var(--ai-r-card);
  background: transparent;
  color: var(--mist);
  cursor: pointer;
}
.assistant-task-sidebar__toggle:hover,
.assistant-task-sidebar__toggle:focus-visible {
  color: var(--ink);
  background: color-mix(in srgb, var(--ink) 6%, transparent);
  outline: none;
}
.assistant-panel-toggle-icon {
  display: block;
  width: .9rem;
  height: .8rem;
  border: 1.5px solid currentColor;
  border-radius: var(--ai-r-chip);
  opacity: .9;
}
.assistant-panel-toggle-icon.is-right {
  box-shadow: inset -4px 0 0 currentColor;
}
.assistant-panel-toggle-icon.is-right.is-open {
  box-shadow: inset -5px 0 0 currentColor;
}
.assistant-task-sidebar__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: .25rem;
  width: 100%;
  min-width: 0;
  padding: .2rem;
  border-radius: var(--ai-r-card);
  background: color-mix(in srgb, var(--ink) 4.5%, transparent);
}
.assistant-task-sidebar__tab {
  margin: 0 !important;
  height: 1.7rem !important;
  padding: 0 .45rem !important;
  border-radius: var(--ai-r-chip) !important;
  color: var(--mist) !important;
  font-size: var(--ai-fs-aux) !important;
}
.assistant-task-sidebar__tab em {
  margin-left: .2rem;
  font-style: normal;
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  opacity: .85;
}
.assistant-task-sidebar__tab.is-active {
  background: var(--panel) !important;
  color: var(--ink) !important;
  box-shadow: 0 1px 1px color-mix(in srgb, var(--ink) 8%, transparent);
}
.assistant-task-sidebar__pane {
  min-height: 0;
  flex: 1;
  overflow: auto;
  scrollbar-width: thin;
  padding-right: .1rem;
}
.assistant-task-sidebar__pane::-webkit-scrollbar {
  width: 8px;
}
.assistant-task-sidebar__pane::-webkit-scrollbar-track {
  background: transparent;
}
.assistant-task-sidebar__pane::-webkit-scrollbar-thumb {
  border: 2px solid transparent;
  border-radius: var(--ai-r-pill);
  background: color-mix(in srgb, var(--ink) 18%, transparent);
  background-clip: padding-box;
}
.assistant-task-sidebar__section {
  display: flex;
  flex-direction: column;
  gap: .45rem;
  min-height: 0;
}
.assistant-task-sidebar__empty {
  margin: .35rem 0 0;
  padding: .75rem .7rem;
  border: 1px dashed var(--rule);
  border-radius: var(--ai-r-card);
  color: var(--mist);
  font-size: var(--ai-fs-aux);
  line-height: 1.45;
  background: color-mix(in srgb, var(--panel) 70%, transparent);
}
.assistant-task-sidebar__plan {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.assistant-task-sidebar__plan-step {
  display: grid;
  grid-template-columns: 1.35rem minmax(0, 1fr);
  gap: .55rem;
  position: relative;
  padding: .28rem 0 .6rem;
}
.assistant-task-sidebar__plan-step:not(:last-child)::before {
  content: '';
  position: absolute;
  left: .55rem;
  top: 1.35rem;
  bottom: 0;
  width: 1px;
  background: color-mix(in srgb, var(--rule) 80%, var(--ink) 10%);
}
.assistant-task-sidebar__plan-index {
  display: grid;
  place-items: center;
  width: 1.15rem;
  height: 1.15rem;
  border-radius: var(--ai-r-pill);
  border: 1px solid var(--rule);
  background: var(--panel);
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  z-index: 1;
}
.assistant-task-sidebar__plan-step.is-running .assistant-task-sidebar__plan-index,
.assistant-task-sidebar__plan-step.is-active .assistant-task-sidebar__plan-index {
  border-color: color-mix(in srgb, var(--lake) 50%, var(--rule));
  background: var(--lake-soft);
  color: var(--lake);
}
.assistant-task-sidebar__plan-step.is-done .assistant-task-sidebar__plan-index {
  border-color: color-mix(in srgb, var(--lake) 40%, var(--rule));
  background: color-mix(in srgb, var(--lake) 14%, var(--panel));
  color: var(--lake);
}
.assistant-task-sidebar__plan-step.is-error .assistant-task-sidebar__plan-index {
  border-color: color-mix(in srgb, var(--loss) 45%, var(--rule));
  background: var(--seal-soft);
  color: var(--seal-ink);
}
.assistant-task-sidebar__plan-body {
  display: flex;
  flex-direction: column;
  gap: .12rem;
  min-width: 0;
  padding-top: .05rem;
}
.assistant-task-sidebar__plan-body strong {
  font-size: var(--ai-fs-body);
  font-weight: 650;
}
.assistant-task-sidebar__plan-body span {
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  letter-spacing: .03em;
  text-transform: uppercase;
}
.assistant-task-sidebar__agents {
  display: flex;
  flex-direction: column;
  gap: var(--ai-gap-sm);
}
.assistant-task-sidebar__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--ai-gap-sm);
}
.assistant-task-sidebar__list li {
  display: flex;
  gap: .45rem;
  align-items: center;
  padding: var(--ai-pad-y) var(--ai-pad-x);
  border: 1px solid var(--rule);
  border-radius: var(--ai-r-card);
  background: var(--panel);
  font-size: var(--ai-fs-aux);
  min-height: var(--ai-row-min);
}
.assistant-task-sidebar__chip {
  flex: 0 0 auto;
  padding: .06rem .3rem;
  border-radius: var(--ai-r-pill);
  background: color-mix(in srgb, var(--ink) 6%, transparent);
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  letter-spacing: .03em;
  text-transform: uppercase;
}
.assistant-task-sidebar__list strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--ai-fs-body);
  line-height: 1.2;
}
.assistant-task-sidebar__list p {
  margin: .08rem 0 0;
  color: var(--mist);
  font-size: var(--ai-fs-aux);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 13rem;
}
.assistant-task-sidebar__cabin {
  display: flex;
  flex-direction: column;
  gap: .4rem;
}
.assistant-task-sidebar__cabin-card {
  padding: .5rem .55rem;
  border: 1px solid var(--rule);
  border-radius: var(--ai-r-card);
  background: var(--panel);
}
.assistant-task-sidebar__cabin-card span {
  display: block;
  margin-bottom: .15rem;
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--ai-fs-meta);
  letter-spacing: .04em;
  text-transform: uppercase;
}
.assistant-task-sidebar__cabin-card p {
  margin: 0;
  color: var(--ink);
  font-size: var(--ai-fs-aux);
  line-height: 1.45;
}
@keyframes task-live-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .45; }
}
@media (prefers-reduced-motion: reduce) {
  .assistant-task-sidebar,
  .assistant-task-sidebar__live-dot { transition: none; animation: none; }
}
</style>
