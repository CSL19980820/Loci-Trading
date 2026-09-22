<script setup lang="ts">
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/shared/components/ui/collapsible'
/**
 * 智能体研判：各智能体最近几轮判断的汇总表，按时间倒排。
 * 桌面用密度表（智能体 / 时间 / 阶段 / 状态 / 研判），手机端卡片列表；
 * 空态与「部分读不到」都不许说成「今天没有研判」。
 */
import { computed } from 'vue'
import { Cpu } from '@lucide/vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { useRouter } from 'vue-router'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { Button } from '@/shared/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { agentTime } from '@/features/agents/agentFormat'

import type { AgentFeedRow } from '../composables/usePulseAgentFeed'

import './pulseSkin.css'

const props = defineProps<{
  rows: AgentFeedRow[]
  compact?: boolean
  loading?: boolean
  /** 整体读不到（一条都没有） */
  error?: string
  /** 部分智能体读不到；不影响已读到的行 */
  partialError?: string
}>()

const emit = defineEmits<{ retry: [] }>()

const router = useRouter()
const isMobile = useMobileLayout()

const columns: BasicTableColumn[] = [
  { prop: 'agentName', label: '智能体', minWidth: 116, align: 'center', headerAlign: 'center', slotName: 'agent' },
  { prop: 'at', label: '时间', width: 104, align: 'center', headerAlign: 'center', slotName: 'at' },
  { prop: 'phaseLabel', label: '阶段', width: 88, align: 'center', headerAlign: 'center', slotName: 'phase' },
  { prop: 'statusLabel', label: '状态', width: 84, align: 'center', headerAlign: 'center', slotName: 'status' },
  { prop: 'summary', label: '研判', minWidth: 220, align: 'center', headerAlign: 'center', slotName: 'summary' },
]

const tableRows = computed(() => props.rows as unknown as Record<string, unknown>[])

const note = computed(() => {
  if (props.error) return '读取失败'
  if (!props.rows.length) return '暂无研判'
  return `按时间倒序 · 最近 ${props.rows.length} 条 · ${new Set(props.rows.map((row) => row.agentId)).size} 个智能体`
})

const emptyHint = computed(() =>
  props.error
    ? props.error
    : '盘前、盘中、盘后和周复盘统一按时间倒序展示。',
)

function open(row: AgentFeedRow): void {
  void router.push(row.to)
}

function statusVariant(row: AgentFeedRow): 'ok' | 'warn' | 'secondary' {
  if (row.failed) return 'warn'
  if (row.statusLabel === '研判中' || row.statusLabel === '正在研究') return 'secondary'
  return 'ok'
}
</script>

<template>
  <section class="pulse-panel">
    <header v-if="!compact" class="pulse-panel__head">
      <div class="pulse-panel__lead">
        <span class="pulse-panel__icon-box"><Cpu class="pulse-panel__icon" aria-hidden="true" /></span>
        <div class="pulse-panel__titles">
          <h2 class="pulse-panel__title">智能体研判</h2>
          <Tooltip :disabled="!partialError">
            <TooltipTrigger as-child>
              <span class="pulse-panel__meta">{{ note }}</span>
            </TooltipTrigger>
            <TooltipContent>{{ partialError }}</TooltipContent>
          </Tooltip>
        </div>
      </div>
      <span v-if="rows.length" class="pulse-panel__count">{{ rows.length }}</span>
    </header>

    <p v-if="partialError && rows.length" class="agent-feed-warning" role="status">部分研判未能读取：{{ partialError }}</p>
    <!-- 手机：卡片列表 -->
    <template v-if="isMobile">
      <ul v-if="rows.length" class="agent-feed-list">
        <li v-for="row in rows" :key="row.key" class="agent-feed-item">
          <div class="agent-feed-item__head">
            <Button access="read" variant="ghost" type="button" class="pulse-agent__link" @click="open(row)">{{ row.agentName }}</Button>
            <time>{{ agentTime(row.at) }}</time>
          </div>
          <div class="agent-feed-item__state">{{ row.phaseLabel }} · {{ row.statusLabel }}</div>
          <Collapsible class="agent-feed-item__summary">
            <CollapsibleTrigger><span class="agent-feed-preview">{{ row.summary || '本轮没有留下研判正文' }}</span><span class="agent-feed-collapse">收起正文</span></CollapsibleTrigger>
            <CollapsibleContent as="p">{{ row.summary || '本轮没有留下研判正文' }}</CollapsibleContent>
          </Collapsible>
        </li>
      </ul>
      <EmptyState
        v-else
        class="pulse-panel__empty"
        :description="error ? '智能体研判读不到' : '还没有智能体研判'"
        :reason="emptyHint"
        :icon="Cpu"
      >
        <Button access="read" v-if="error" size="sm" variant="outline" @click="emit('retry')">重试</Button>
        <Button access="read" v-else size="sm" variant="outline" @click="open({ to: '/agents' } as AgentFeedRow)">去智能体</Button>
      </EmptyState>
    </template>

    <BasicTable
      v-else
      class="pulse-table"
      :columns="columns"
      :data-source="tableRows"
      :pagination="false"
      height="100%"
    >
      <template #agent="{ row }">
        <Button access="read" variant="ghost" type="button" class="pulse-agent__link" :title="String(row.agentName)" @click="open(row as unknown as AgentFeedRow)">
          {{ row.agentName }}
        </Button>
      </template>
      <template #at="{ row }">
        <span class="pulse-num pulse-dim">{{ agentTime(row.at as string) }}</span>
      </template>
      <template #phase="{ row }">
        <span class="pulse-dim">{{ row.phaseLabel }}</span>
      </template>
      <template #status="{ row }">
        <UiBadge :variant="statusVariant(row as unknown as AgentFeedRow)" class="pulse-agent__state">
          {{ row.statusLabel }}
        </UiBadge>
      </template>
      <template #summary="{ row }">
        <Tooltip>
          <TooltipTrigger as-child>
            <span class="pulse-agent__text">{{ row.summary || '—' }}</span>
          </TooltipTrigger>
          <TooltipContent class="max-w-[min(560px,calc(100vw-32px))] whitespace-pre-line">
            {{ row.summary || '这一轮没有留下研判正文' }}
          </TooltipContent>
        </Tooltip>
      </template>
      <template #empty>
        <EmptyState
          class="pulse-panel__empty"
          :description="error ? '智能体研判读不到' : '还没有智能体研判'"
          :reason="emptyHint"
          :icon="Cpu"
        >
          <Button access="read" v-if="error" size="sm" variant="outline" @click="emit('retry')">重试</Button>
          <Button access="read" v-else size="sm" variant="outline" @click="open({ to: '/agents' } as AgentFeedRow)">去智能体</Button>
        </EmptyState>
      </template>
    </BasicTable>
  </section>
</template>

<style scoped>
/* 智能体名是个可点进详情的按钮，外观与正文一致（表格里别长成链接） */
.pulse-agent__link {
  height: auto;
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.pulse-agent__link:hover {
  color: var(--seal);
}

.pulse-agent__link:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
  border-radius: var(--radius-xs);
}

.pulse-agent__state {
  font-weight: 500;
}
.agent-feed-list { list-style:none; padding:0; margin:0; }
.agent-feed-warning { margin:0; padding:8px 12px; color:var(--warn-ink); font-size:12px; line-height:1.5; flex:none; }
.agent-feed-item { padding:12px; border-bottom:1px solid var(--border-subtle); min-width:0; }
.agent-feed-item:last-child { border-bottom:0; }
.agent-feed-item__head { display:flex; align-items:baseline; justify-content:space-between; gap:8px; min-width:0; }
.agent-feed-item__head button { font-size:13px; }
.agent-feed-item__head time { flex:none; font:11px var(--mono); color:var(--text-tertiary); white-space:nowrap; }
.agent-feed-item__state { color:var(--text-tertiary); font-size:11px; margin-top:3px; }
.agent-feed-item__summary { color:var(--text-secondary); font-size:12px; line-height:1.65; margin-top:5px; overflow-wrap:anywhere; }
.agent-feed-item__summary :deep([data-slot="collapsible-trigger"]) { width:100%; text-align:left; cursor:pointer; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; list-style:none; }
.agent-feed-collapse { display:none; }
.agent-feed-item__summary[data-state="open"] .agent-feed-preview { display:none; }
.agent-feed-item__summary[data-state="open"] .agent-feed-collapse { display:inline; color:var(--seal); }
.agent-feed-item__summary p { margin:0; white-space:pre-wrap; }

/* 研判正文单行截断，全文进 tooltip */
.pulse-agent__text {
  display: block;
  max-width: 100%;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--text-secondary);
  text-align: left;
}
</style>
