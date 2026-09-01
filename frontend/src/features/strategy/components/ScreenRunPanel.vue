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
  /** 技能是否真的还在后台跑（skillBusy 只覆盖请求在途那一瞬） */
  skillActive?: boolean
  /** 「已跑 2 分 13 秒」；起点未知时调用方给「已跟踪 …」 */
  elapsedText?: string
  canAbandon?: boolean
}>()

const emit = defineEmits<{
  'update:skillReply': [value: string]
  reply: []
  abandon: []
}>()

const route = useRoute()
/**
 * 有日志才默认展开：未跑过时展开只会显示一行「尚无日志」，
 * 和下方的空结果区叠成两块零信息空壳。跑起来时下面的 watch 会自动展开。
 */
const logOpen = ref(
  (props.kind === 'skill' ? props.skillLog : (props.snap?.log ?? [])).length > 0,
)
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
    if (props.skillBusy || props.skillActive) return '技能运行中'
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
    return props.skillBusy || props.skillActive || st === 'running' || st === 'waiting_user'
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
  { prop: 'code', label: '标的', minWidth: 120, align: 'center', headerAlign: 'center', slotName: 'code' },
  {
    prop: 'open',
    label: '开',
    align: 'center',
    headerAlign: 'center',
    width: 88,
    formatter: (row) => fmtNum(row.open as number | null),
  },
  {
    prop: 'close',
    label: '收',
    align: 'center',
    headerAlign: 'center',
    width: 88,
    formatter: (row) => fmtNum(row.close as number | null),
  },
])

const pickRows = computed(
  () => (props.lastResult?.picks ?? []) as unknown as Record<string, unknown>[],
)
const watchRows = computed(
  () => (props.lastResult?.watch_picks ?? []) as unknown as Record<string, unknown>[],
)

const picksBatch = computed(() => ({
  source: '选股结果',
  sourcePath: route.fullPath || route.path || '/screen-history',
  items: toBatchItems(props.lastResult?.picks ?? []),
}))
const watchBatch = computed(() => ({
  source: '低吸观察',
  sourcePath: route.fullPath || route.path || '/screen-history',
  items: toBatchItems(props.lastResult?.watch_picks ?? []),
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
        <span v-if="elapsedText" class="mono mist run-panel__elapsed">{{ elapsedText }}</span>
        <span v-if="showProgress" class="mono mist">{{ progressPct }}%</span>
      </div>
      <el-progress
        v-if="showProgress"
        :percentage="progressPct"
        :stroke-width="4"
        :show-text="false"
        :status="progressStatus"
      />
      <div v-if="canAbandon" class="run-panel__abandon">
        <el-button size="small" type="warning" plain native-type="button" @click="emit('abandon')">
          放弃跟踪
        </el-button>
        <span class="run-panel__abandon-note">停跟踪不等于停任务：后端没有中止接口，它会在后台跑完</span>
      </div>
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
        <span class="mist">
          正式 {{ lastResult.picks.length }} 只 · 观察 {{ lastResult.watch_picks?.length ?? 0 }} 只
        </span>
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
      <!-- 未跑过时不再顶一条「今日结果 —」的空标题栏，直接由下方空态说明下一步 -->
      <div class="picks-body">
        <section v-if="pickRows.length" class="result-section">
          <div class="result-section__title">
            <strong>正式精选</strong>
            <span class="mist">沿用原战法入场与胜率口径</span>
          </div>
          <BasicTable
            :columns="pickColumns"
            :data-source="pickRows"
            :pagination="false"
            row-key="code"
            stripe
            height="100%"
            empty-text="无正式精选"
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
        </section>
        <section v-if="watchRows.length" class="result-section">
          <div class="result-section__title">
            <strong>低吸观察</strong>
            <el-tag size="small" type="warning" effect="plain">不计正式胜率</el-tag>
          </div>
          <BasicTable
            :columns="pickColumns"
            :data-source="watchRows"
            :pagination="false"
            row-key="code"
            stripe
            height="100%"
            empty-text="无低吸观察"
          >
            <template #code="{ row }">
              <StockLink
                :code="String(row.code)"
                :name="String(row.name || row.code)"
                :date="lastResult?.trade_date"
                :batch="watchBatch"
              />
            </template>
          </BasicTable>
        </section>
        <EmptyState
          v-if="lastResult && !pickRows.length && !watchRows.length"
          class="picks-empty"
          description="该日无标的满足条件"
        />
        <EmptyState
          v-else-if="!lastResult"
          class="picks-empty"
          description="今天还没跑过选股"
          reason="选中左侧战法后点右上角「选股」；15:30 自动跑一遍"
        />
      </div>
    </div>

    <div v-else-if="kind === 'skill'" class="run-panel__skill">
      <pre v-if="skillRun?.result?.output" class="skill-out">{{ skillRun.result.output }}</pre>
      <EmptyState
        v-else-if="!skillLog.length"
        class="picks-empty"
        description="跑技能后显示事件流与产出"
      />
    </div>
  </section>
</template>

<style scoped src="./ScreenRunPanel.css"></style>
