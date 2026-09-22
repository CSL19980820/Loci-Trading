<script setup lang="ts">
import { Sidebar, SidebarHeader } from '@/shared/components/ui/sidebar'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/shared/components/ui/tabs'
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
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Button } from '@/shared/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

type InspectorTab = 'plan' | 'agents' | 'sources' | 'artifacts' | 'cabin'

const props = defineProps<{
  model: AssistantTaskModel
  open?: boolean
  tools?: AiToolReceipt[]
  artifacts?: AiChartArtifact[]
  /** 由 Host 统一加载下发。侧栏自己再拉一份会在改完设置后显示旧值。 */
  profile?: AiAssistantProfile | null
  memories?: AiMemoryItem[]
  /** 抽屉模式：父级贴右 / 窄屏时传 true，样式换成浮层底 */
  drawer?: boolean
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
  if (status === 'loading') return '读取中'
  if (status === 'error') return '失败'
  return '就绪'
}
</script>

<template>
  <Sidebar side="right" collapsible="none" role="complementary"
    class="assistant-task-sidebar"
    :class="{ 'is-collapsed': !visible, 'is-drawer': drawer }"
    data-testid="assistant-task-sidebar"
    aria-label="任务侧栏"
  >
    <div v-if="!visible" class="assistant-task-sidebar__rail">
      <Tooltip>
        <TooltipTrigger as-child>
          <Button
            variant="ghost"
            size="icon-sm"
            class="assistant-task-sidebar__toggle"
            access="read" aria-label="展开任务侧栏"
            data-testid="task-sidebar-expand"
            @click="visible = true"
          >
            <span class="assistant-panel-toggle-icon is-right" aria-hidden="true" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="left">展开侧栏</TooltipContent>
      </Tooltip>
      <span v-if="liveAgents" class="assistant-task-sidebar__live-dot" :title="`${liveAgents} 路运行中`" />
    </div>

    <template v-else>
      <SidebarHeader class="assistant-task-sidebar__head flex-row p-0">
        <span class="assistant-task-sidebar__title">本轮</span>
        <Button access="read"
          variant="ghost"
          size="icon-sm"
          class="assistant-task-sidebar__toggle"
          aria-label="收起任务侧栏"
          data-testid="task-sidebar-collapse"
          title="收起侧栏"
          @click="visible = false"
        >
          <span class="assistant-panel-toggle-icon is-right is-open" aria-hidden="true" />
        </Button>
      </SidebarHeader>

      <Tabs v-model="activeTab" class="min-h-0 flex-1 flex-col"><TabsList class="assistant-task-sidebar__tabs h-auto" aria-label="任务分区">
        <TabsTrigger :value="tab.value"
          v-for="tab in tabs"
          :key="tab.value"
          variant="ghost"
          size="sm"
          class="assistant-task-sidebar__tab"
          :class="{ 'is-active': activeTab === tab.value }"

        >
          {{ tab.label }}
          <em v-if="tab.count">{{ tab.count }}</em>
        </TabsTrigger>
      </TabsList>

      <TabsContent :value="activeTab" class="assistant-task-sidebar__pane" data-testid="task-sidebar-pane">
        <section v-if="activeTab === 'plan'" class="assistant-task-sidebar__section">
          <EmptyState v-if="!model.plan.length" description="暂无计划步骤" />
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
          <EmptyState v-if="!model.agents.length" description="暂无子进程" />
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
          <EmptyState v-if="!model.sources.length" description="暂无数据来源" />
          <ul v-else class="assistant-task-sidebar__list">
            <li v-for="source in model.sources" :key="source.id">
              <span class="assistant-task-sidebar__chip">
                {{ source.kind === 'tool' ? '工具' : source.kind === 'artifact' ? '图/表' : '规则' }}
              </span>
              <div>
                <strong :title="source.label">{{ source.label }}</strong>
                <p v-if="source.detail" :title="source.detail">{{ source.detail }}</p>
              </div>
            </li>
          </ul>
        </section>

        <section v-else-if="activeTab === 'artifacts'" class="assistant-task-sidebar__section">
          <EmptyState v-if="!model.artifacts.length" description="暂无产物" />
          <ul v-else class="assistant-task-sidebar__list">
            <li v-for="item in model.artifacts" :key="item.id">
              <span class="assistant-task-sidebar__chip">{{ artifactLabel(item.status) }}</span>
              <div>
                <strong :title="item.title || item.kind">{{ item.title || item.kind }}</strong>
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
            <Button variant="outline" size="sm" @click="emit('settings')">助手设置</Button>
          </div>
        </section>
      </TabsContent></Tabs>
    </template>
  </Sidebar>
</template>

<style scoped>
/* 300/44px 与 Panel 的展开、折叠契约一致。 */
.assistant-task-sidebar { display: flex; flex-direction: column; gap: var(--gap-2); flex: 0 1 300px; min-width: 240px; min-height: 0; overflow: hidden; border-left: 1px solid var(--border-subtle); background: var(--surface-canvas); padding: var(--gap-3); }
.assistant-task-sidebar.is-drawer { background: var(--surface); min-width: 0; }
.assistant-task-sidebar.is-collapsed { flex: 0 0 44px; min-width: 0; width: 44px; padding: var(--gap-2) 0; align-items: center; }
.assistant-task-sidebar__rail { display: flex; flex: 1; flex-direction: column; align-items: center; gap: var(--gap-2); }
.assistant-task-sidebar__live-dot { width: var(--gap-1); height: var(--gap-1); border-radius: var(--ai-r-pill); background: var(--seal); }
.assistant-task-sidebar__head { display: flex; align-items: center; justify-content: space-between; gap: var(--gap-2); min-height: var(--ctl-h); }
.assistant-task-sidebar__title { margin: 0; color: var(--ink); font-size: var(--ai-fs-body); font-weight: 600; }
.assistant-task-sidebar__toggle { display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; width: var(--ctl-h); height: var(--ctl-h); margin: 0; padding: 0; color: var(--mist); }
.assistant-task-sidebar :deep(button:focus-visible) { outline: 2px solid var(--seal); outline-offset: -2px; }
.assistant-panel-toggle-icon { display: block; width: 1em; height: .9em; border: 1.5px solid currentColor; border-radius: var(--ai-r-chip); }
.assistant-panel-toggle-icon.is-right { box-shadow: inset -4px 0 0 currentColor; }
.assistant-task-sidebar__tabs { display: flex; flex-wrap: wrap; gap: var(--gap-1); width: 100%; min-width: 0; }
.assistant-task-sidebar__tabs { padding: 3px; border-radius: var(--radius); background: var(--surface-sunken); gap: 2px; }
.assistant-task-sidebar__tab { flex: 1 1 auto; margin: 0; height: 28px; padding: 0 var(--gap-2); border: 0; border-radius: var(--radius-sm); color: var(--text-tertiary); font-size: var(--fs-aux); font-weight: 500; }
.assistant-task-sidebar__tab em { margin-left: var(--gap-1); font: var(--ai-fs-meta) var(--mono); color: var(--mist); }
.assistant-task-sidebar__tab.is-active { background: var(--surface); color: var(--text-primary); font-weight: 600; box-shadow: var(--shadow-xs); }
.assistant-task-sidebar__pane { min-height: 0; min-width: 0; flex: 1; overflow: auto; overscroll-behavior: contain; scrollbar-width: thin; }
.assistant-task-sidebar__section, .assistant-task-sidebar__agents, .assistant-task-sidebar__cabin { display: flex; flex-direction: column; gap: var(--gap-2); min-height: 0; min-width: 0; }
.assistant-task-sidebar__plan, .assistant-task-sidebar__list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: var(--gap-1); }
.assistant-task-sidebar__plan-step { display: grid; grid-template-columns: var(--row-h-sm) minmax(0, 1fr); gap: var(--gap-2); padding: var(--gap-2); border: 1px solid var(--border-subtle); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow-xs); }
.assistant-task-sidebar__plan-step.is-running { background: var(--seal-soft); border-color: var(--seal-border); }
.assistant-task-sidebar__plan-index { display: grid; place-items: center; width: var(--row-h-sm); height: var(--row-h-sm); color: var(--mist); font: var(--ai-fs-meta) var(--mono); }
.assistant-task-sidebar__plan-step.is-running .assistant-task-sidebar__plan-index, .assistant-task-sidebar__plan-step.is-done .assistant-task-sidebar__plan-index { color: var(--info-ink); }
.assistant-task-sidebar__plan-step.is-error .assistant-task-sidebar__plan-index { color: var(--warn-ink); }
.assistant-task-sidebar__plan-body { display: flex; flex-direction: column; gap: var(--gap-1); min-width: 0; }
.assistant-task-sidebar__plan-body strong { font-size: var(--ai-fs-body); font-weight: 600; overflow-wrap: anywhere; }
.assistant-task-sidebar__plan-body span { color: var(--mist); font-size: var(--ai-fs-meta); }
.assistant-task-sidebar__list li { display: flex; gap: var(--gap-2); align-items: flex-start; padding: var(--gap-2); border: 1px solid var(--border-subtle); border-radius: var(--radius); background: var(--surface); min-height: var(--ai-row-min); box-shadow: var(--shadow-xs); }
.assistant-task-sidebar__list li > div { min-width: 0; flex: 1; }
.assistant-task-sidebar__chip { flex: 0 0 auto; padding: var(--gap-1); border-radius: var(--ai-r-chip); background: var(--surface-sunken); color: var(--mist); font-size: var(--ai-fs-meta); }
.assistant-task-sidebar__list strong { display: block; font-size: var(--ai-fs-body); line-height: 1.5; overflow-wrap: anywhere; }
.assistant-task-sidebar__list p { margin: var(--gap-1) 0 0; color: var(--mist); font-size: var(--ai-fs-aux); line-height: 1.5; overflow-wrap: anywhere; }
.assistant-task-sidebar__cabin-card { padding: var(--gap-2) var(--gap-3); border: 1px solid var(--border-subtle); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow-xs); }
.assistant-task-sidebar__cabin-card span { display: block; margin-bottom: var(--gap-1); color: var(--mist); font-size: var(--ai-fs-meta); }
.assistant-task-sidebar__cabin-card p { margin: 0; color: var(--ink); font-size: var(--ai-fs-body); line-height: 1.5; overflow-wrap: anywhere; }
</style>
