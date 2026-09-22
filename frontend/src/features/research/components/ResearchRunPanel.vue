<script setup lang="ts">
import { computed, ref } from 'vue'
import { Download, LoaderCircle, RefreshCw, Search } from '@lucide/vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import type { ResearchRun } from '@/shared/types/quant'
const props = defineProps<{
  runs: ResearchRun[]
  activeRun: ResearchRun | null
  loading?: boolean
}>()

const emit = defineEmits<{
  load: [runId: string]
  resume: [runId: string]
}>()

const runId = ref('')
const runHref = computed(() => {
  const id = props.activeRun?.id
  return id ? `/api/research/runs/${encodeURIComponent(id)}` : ''
})

function runStatus(value: ResearchRun['status']): string {
  if (value === 'completed') return '已完成'
  if (value === 'running') return '运行中'
  if (value === 'stale') return '已过期'
  return '错误'
}

function runType(value: ResearchRun['status']): 'success' | 'warning' | 'info' | 'danger' {
  if (value === 'completed') return 'success'
  if (value === 'stale') return 'warning'
  if (value === 'error') return 'danger'
  return 'info'
}

/** 状态档 → 语义色：shadcn Badge 只有四档，状态色由令牌类补上（D1 状态色） */
const RUN_TONE: Record<'success' | 'warning' | 'info' | 'danger', string> = {
  success: 'border-transparent bg-ok-soft text-ok',
  warning: 'border-transparent bg-warn-soft text-warn-ink',
  info: 'border-line bg-sunken text-mist',
  danger: 'text-stamp border-[color-mix(in_oklab,var(--stamp)_38%,var(--rule))] bg-surface',
}

const tableRows = computed(() => props.runs as unknown as Record<string, unknown>[])

const columns: BasicTableColumn[] = [
  { prop: 'id', label: 'run id', minWidth: 190, showOverflowTooltip: true },
  { prop: 'status', label: '状态', width: 86, slotName: 'status' },
  { prop: 'code', label: '标的', width: 84 },
  { prop: 'as_of', label: '截止日', width: 116 },
  { prop: 'id', label: '动作', width: 172, fixed: 'right', slotName: 'actions' },
]

function submit(): void {
  emit('load', runId.value)
}
</script>

<template>
  <section class="run-panel research-surface" aria-label="研究 run">
    <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行（用户原话：一行能显示的话两行） -->
    <!-- 「只列本次会话的 run」这句口径进 tooltip：页面上不留介绍段 -->
    <header class="run-head">
      <Tooltip>
        <TooltipTrigger as-child>
          <h3 class="run-head__title" tabindex="0">
            <RefreshCw aria-hidden="true" />研究批次
          </h3>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="start">
          只列本次会话已创建或读取的 run；持久历史列表要等后端列表接口
        </TooltipContent>
      </Tooltip>
      <form class="run-query" @submit.prevent="submit">
        <Input
          v-model="runId"
          class="run-query__input"
          aria-label="研究 run id"
          placeholder="粘贴 run id"
        />
        <Button access="read" type="button" size="sm" @click="submit">
          <LoaderCircle v-if="props.loading" class="size-4 animate-spin" aria-hidden="true" />
          <Search v-else class="size-4" aria-hidden="true" />
          读取
        </Button>
      </form>
    </header>

    <BasicTable
      :columns="columns"
      :data-source="tableRows"
      :pagination="false"
      :loading="props.loading"
      row-key="id"
      stripe
      empty-text="还没有跑过任务"
      empty-reason="归档剖面或按编号读取"
    >
      <template #status="{ row }">
        <Badge variant="outline" :class="RUN_TONE[runType(row.status as ResearchRun['status'])]">
          {{ runStatus(row.status as ResearchRun['status']) }}
        </Badge>
      </template>
      <template #actions="{ row }">
        <Button access="read" variant="link" size="sm" :disabled="Boolean(props.loading && row.id === props.activeRun?.id)" @click="emit('load', String(row.id))">
          查看
        </Button>
        <Button
          v-if="row.status === 'error'"
          variant="link"
          size="sm"
          :disabled="Boolean(props.loading && row.id === props.activeRun?.id)"
          @click="emit('resume', String(row.id))"
        >
          <RefreshCw class="size-3.5" aria-hidden="true" />恢复
        </Button>
      </template>
    </BasicTable>

    <div v-if="props.activeRun" class="run-detail">
      <div class="run-detail-head">
        <span>当前 run <code>{{ props.activeRun.id }}</code></span>
        <Button access="read"
          v-if="runHref"
          as="a"
          variant="link"
          class="h-auto justify-start p-0 text-left"
          :href="runHref"
          target="_blank"
          rel="noopener noreferrer"
        >
          <Download class="size-3.5" aria-hidden="true" />
          查看 run JSON
        </Button>
      </div>
      <div class="run-facts">
        <span>策略输入 <strong>未提供</strong></span>
        <span>行情版本 <code>{{ props.activeRun.market_revision || '—' }}</code></span>
        <span>输入指纹 <code>{{ props.activeRun.input_sha256 || '—' }}</code></span>
      </div>
      <div class="stage-strip" aria-label="研究阶段">
        <Badge v-for="(stage, name) in props.activeRun.stages" :key="name" variant="outline" :class="RUN_TONE.info">
          {{ name }} · {{ stage.status }} · {{ stage.output_sha256.slice(0, 12) }}…
        </Badge>
      </div>
    </div>
  </section>
</template>

<style scoped>
.run-panel { border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); overflow: hidden; }
.run-head, .run-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; }
.run-head { padding: 0.82rem 0.9rem; border-bottom: 1px solid var(--rule); }
.run-head h3 { margin: 0; font-size: var(--fs-title); font-weight: 700; letter-spacing: .03em; cursor: help; }
.run-head__title { display: inline-flex; align-items: center; gap: 0.35rem; }
.run-query { display: flex; align-items: center; gap: 0.4rem; min-width: min(100%, 23rem); }
.run-query__input { flex: 1 1 auto; }
.run-detail { padding: 0.75rem 0.9rem; border-top: 1px solid var(--rule); }
.run-detail-head { align-items: center; color: var(--mist); font-size: var(--fs-aux); }
.run-detail-head code, .run-facts code { color: var(--ink); font-family: var(--mono); font-size: var(--fs-kicker); overflow-wrap: anywhere; }
.run-facts { display: flex; flex-wrap: wrap; gap: 0.4rem 1rem; margin-top: 0.52rem; color: var(--mist); font-size: 0.75rem; }
.run-facts strong { color: var(--seal-ink); font-weight: 600; }
.stage-strip { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.6rem; }
@media (max-width: 700px) { .run-head { flex-direction: column; } .run-query { min-width: 0; width: 100%; } }
</style>
<style scoped src="./ResearchSurfaces.css"></style>
