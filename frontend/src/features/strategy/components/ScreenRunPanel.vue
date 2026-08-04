<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import type { SkillRun } from '@/shared/api/quant'
import type { ScreenResult, ScreenRunStatus } from '@/shared/types/quant'

const props = defineProps<{
  kind: 'engine' | 'skill' | null
  selectedName: string
  snap: ScreenRunStatus | null
  running: boolean
  percent: number
  lastResult: ScreenResult | null
  skillBusy: boolean
  skillLog: string[]
  skillRun: SkillRun | null
  skillReply: string
}>()

const emit = defineEmits<{
  'update:skillReply': [value: string]
  reply: []
}>()

const route = useRoute()
/** 日志默认展开；跑完自动收起；点待命/状态行可手动切换 */
const logOpen = ref(true)
const logEl = ref<HTMLElement | null>(null)
/** 用户上滚查看历史时暂停贴底；靠近底部再恢复 */
const stickToBottom = ref(true)

watch(
  () => [props.running, props.skillBusy, props.skillRun?.status] as const,
  ([busy, skillBusy, status], prev) => {
    const nowBusy =
      Boolean(busy) ||
      Boolean(skillBusy) ||
      status === 'running' ||
      status === 'waiting_user'
    const wasBusy =
      Boolean(prev?.[0]) ||
      Boolean(prev?.[1]) ||
      prev?.[2] === 'running' ||
      prev?.[2] === 'waiting_user'
    if (nowBusy) {
      logOpen.value = true
      stickToBottom.value = true
    } else if (wasBusy) {
      logOpen.value = false
    }
  },
)

const statusLabel = computed(() => {
  if (props.kind === 'skill') {
    if (props.skillBusy) return '技能运行中'
    const st = props.skillRun?.status
    if (st === 'done') return '技能已完成'
    if (st === 'error') return '技能失败'
    if (props.skillRun?.pending_ask) return '等待你的回复'
    return '待命'
  }
  if (props.running) return '选股中'
  if (props.snap?.status === 'done') return '已完成'
  if (props.snap?.status === 'error') return '失败'
  return '待命'
})

const showProgress = computed(
  () =>
    props.kind === 'engine' &&
    (props.running || props.snap?.status === 'done' || props.snap?.status === 'error'),
)

const progressPct = computed(() => {
  if (props.snap?.status === 'done') return 100
  if (props.snap?.status === 'error') return props.percent
  return props.percent
})

const progressStatus = computed(() => {
  if (props.snap?.status === 'error') return 'exception' as const
  if (props.snap?.status === 'done') return 'success' as const
  return undefined
})

const logs = computed(() =>
  props.kind === 'skill' ? props.skillLog : (props.snap?.log ?? []),
)

const liveRunning = computed(() => {
  if (props.kind === 'skill') {
    const st = props.skillRun?.status
    return props.skillBusy || st === 'running' || st === 'waiting_user'
  }
  return props.running
})

watch(
  () => [logs.value.length, logs.value[logs.value.length - 1], logOpen.value] as const,
  async () => {
    if (!logOpen.value || !stickToBottom.value) return
    await nextTick()
    const el = logEl.value
    if (!el) return
    el.scrollTop = el.scrollHeight
  },
)

function onLogScroll(): void {
  const el = logEl.value
  if (!el) return
  const gap = el.scrollHeight - el.scrollTop - el.clientHeight
  stickToBottom.value = gap < 36
}

const pickColumns = computed<BasicTableColumn[]>(() => [
  { prop: 'code', label: '标的', minWidth: 120, slotName: 'code' },
  {
    prop: 'open',
    label: '开',
    align: 'right',
    width: 88,
    formatter: (row) => fmtNum(row.open as number | null),
  },
  {
    prop: 'close',
    label: '收',
    align: 'right',
    width: 88,
    formatter: (row) => fmtNum(row.close as number | null),
  },
])

const pickRows = computed(
  () => (props.lastResult?.picks ?? []) as unknown as Record<string, unknown>[],
)

const picksBatch = computed(() => ({
  source: '选股结果',
  sourcePath: route.fullPath || route.path || '/screen-history',
  items: toBatchItems(props.lastResult?.picks ?? []),
}))

function fmtNum(value: number | null | undefined): string {
  if (value == null) return '—'
  return Number(value).toFixed(2)
}

function toggleLog(): void {
  logOpen.value = !logOpen.value
}
</script>

<template>
  <section class="run-panel" aria-label="选股跑道">
    <header class="run-panel__status">
      <div
        class="run-panel__status-row"
        role="button"
        tabindex="0"
        :aria-expanded="logOpen"
        aria-controls="run-panel-log"
        @click="toggleLog"
        @keydown.enter.prevent="toggleLog"
        @keydown.space.prevent="toggleLog"
      >
        <span class="run-panel__status-main">
          <el-icon class="run-panel__chevron" :class="{ open: logOpen }">
            <ArrowRight />
          </el-icon>
          <strong>{{ statusLabel }}</strong>
        </span>
        <span v-if="showProgress" class="mono mist">{{ progressPct }}%</span>
      </div>
      <el-progress
        v-if="showProgress"
        :percentage="progressPct"
        :stroke-width="4"
        :show-text="false"
        :status="progressStatus"
      />
    </header>

    <div
      v-show="logOpen"
      id="run-panel-log"
      class="run-panel__log"
      :class="{ 'run-panel__log--live': liveRunning }"
    >
      <ul ref="logEl" class="log mono" @scroll.passive="onLogScroll">
        <li
          v-for="(line, i) in logs"
          :key="`${i}-${line}`"
          :class="{
            'log-line--ok': line.startsWith('✓') || line.startsWith('■'),
            'log-line--err': line.startsWith('✗'),
            'log-line--wait': line.startsWith('⏸'),
            'log-line--fresh': liveRunning && i === logs.length - 1,
          }"
        >
          {{ line }}
        </li>
        <li v-if="!logs.length" class="mist">尚无日志</li>
      </ul>
    </div>

    <div v-if="kind === 'skill' && skillRun?.pending_ask" class="hitl">
      <p v-if="skillRun.pending_ask.prompt" class="hitl-prompt">
        {{ skillRun.pending_ask.prompt }}
      </p>
      <el-input
        :model-value="skillReply"
        type="textarea"
        :rows="2"
        placeholder="回复技能…"
        @update:model-value="emit('update:skillReply', String($event))"
      />
      <el-button type="primary" size="small" :loading="skillBusy" @click="emit('reply')">
        发送
      </el-button>
    </div>

    <div v-if="kind === 'engine'" class="run-panel__picks">
      <div v-if="lastResult" class="picks-head">
        <strong>
          {{ lastResult.range && lastResult.range.trading_days > 1 ? '区间末日' : '今日结果' }}
          · {{ lastResult.trade_date }}
        </strong>
        <span class="mist">{{ lastResult.picks.length }} 只</span>
        <span v-if="lastResult.range && lastResult.range.trading_days > 1" class="chip mist-chip">
          共 {{ lastResult.range.trading_days }} 日
        </span>
        <span v-if="lastResult.recorded" class="chip">
          已入库
          {{
            lastResult.recorded.written_total != null
              ? lastResult.recorded.written_total
              : lastResult.recorded.written
          }}
        </span>
      </div>
      <div v-else class="picks-head">
        <strong>今日结果</strong>
        <span class="mist">—</span>
      </div>
      <div class="picks-body">
        <BasicTable
          v-if="pickRows.length"
          :columns="pickColumns"
          :data-source="pickRows"
          :pagination="false"
          row-key="code"
          stripe
          height="100%"
          empty-text="无选股结果"
        >
          <template #code="{ row }">
            <StockLink
              :code="String(row.code)"
              :name="String(row.name || row.code)"
              :date="lastResult?.trade_date"
              :batch="picksBatch"
            />
          </template>
        </BasicTable>
        <EmptyState
          v-else-if="lastResult"
          class="picks-empty"
          description="该日无标的满足条件"
          :image-size="48"
        />
        <EmptyState
          v-else
          class="picks-empty"
          description="跑完后选票落在这里"
          :image-size="48"
        />
      </div>
    </div>

    <div v-else-if="kind === 'skill'" class="run-panel__skill">
      <pre v-if="skillRun?.result?.output" class="skill-out">{{ skillRun.result.output }}</pre>
      <EmptyState
        v-else-if="!skillLog.length"
        class="picks-empty"
        description="跑技能后显示事件流与产出"
        :image-size="48"
      />
    </div>
  </section>
</template>

<style scoped>
.run-panel {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  min-height: 0;
  height: 100%;
  padding: 0.65rem 0.75rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.run-panel__status {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  flex-shrink: 0;
}

.run-panel__status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  cursor: pointer;
  user-select: none;
  border-radius: 4px;
  margin: -0.15rem -0.25rem;
  padding: 0.15rem 0.25rem;
}

.run-panel__status-row:hover {
  background: color-mix(in srgb, var(--rule) 35%, transparent);
}

.run-panel__status-row:focus-visible {
  outline: 2px solid var(--accent, var(--up));
  outline-offset: 1px;
}

.run-panel__status-main {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
}

.run-panel__chevron {
  flex-shrink: 0;
  transition: transform 0.18s ease;
  color: var(--muted);
  font-size: 0.85rem;
}

.run-panel__chevron.open {
  transform: rotate(90deg);
}

.run-panel__status strong {
  font-family: var(--font-display);
  font-size: 1rem;
}

.run-panel__log {
  flex-shrink: 0;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--paper);
  padding: 0.35rem 0.55rem;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.run-panel__log--live {
  border-color: color-mix(in srgb, var(--accent, var(--up)) 42%, var(--rule));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent, var(--up)) 12%, transparent);
}

.log {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 11rem;
  overflow: auto;
  scroll-behavior: smooth;
  font-size: 0.74rem;
  line-height: 1.45;
  color: var(--mist);
}

.log li {
  padding: 0.16rem 0;
  border-bottom: 1px dashed color-mix(in srgb, var(--rule) 70%, transparent);
  transition: color 0.18s ease, background 0.18s ease;
}

.log li:last-child {
  border-bottom: 0;
}

.log-line--ok {
  color: color-mix(in srgb, var(--up) 78%, var(--ink));
}

.log-line--err {
  color: color-mix(in srgb, var(--down, #c44) 82%, var(--ink));
}

.log-line--wait {
  color: color-mix(in srgb, var(--accent, var(--up)) 70%, var(--ink));
}

.log-line--fresh {
  color: var(--ink);
  background: color-mix(in srgb, var(--accent, var(--up)) 10%, transparent);
  margin: 0 -0.35rem;
  padding-left: 0.35rem;
  padding-right: 0.35rem;
  border-radius: 3px;
}

.hitl {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.55rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--paper);
  flex-shrink: 0;
}

.hitl-prompt {
  margin: 0;
  font-size: 0.82rem;
  color: var(--muted);
  line-height: 1.4;
}

.picks-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.55rem;
  margin-bottom: 0.45rem;
  flex-shrink: 0;
}

.chip {
  font-size: 0.75rem;
  padding: 0.1rem 0.4rem;
  border-radius: 999px;
  background: color-mix(in srgb, var(--up) 14%, transparent);
  color: var(--up);
}

.mist-chip {
  background: color-mix(in srgb, var(--rule) 55%, transparent);
  color: var(--mist);
}

.mist {
  color: var(--mist);
}

.mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.skill-out {
  margin: 0;
  padding: 0.65rem;
  flex: 1;
  min-height: 0;
  overflow: auto;
  font-size: 0.75rem;
  white-space: pre-wrap;
  background: var(--paper);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
}

.run-panel__picks,
.run-panel__skill {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.picks-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.picks-body :deep(.basic-table) {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
}

.picks-empty {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.picks-empty :deep(.el-empty) {
  padding: 1rem 0;
}
</style>
