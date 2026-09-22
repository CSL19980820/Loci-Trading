<script setup lang="ts">
import { ChevronRight, Send } from '@lucide/vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useRoute } from 'vue-router'

import { Button } from '@/shared/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/components/ui/card'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Progress } from '@/shared/components/ui/progress'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import { Textarea } from '@/shared/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import type { SkillRun } from '@/shared/api/quant'
import type { Pick, ScreenResult, ScreenRunStatus } from '@/shared/types/quant'

const props = defineProps<{
  kind: 'engine' | 'skill' | null
  selectedName: string
  /** 「战法」/「技能」；页头已选中的类型，跑道状态卡上再点一次名 */
  kindLabel?: string
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
const isMobile = useMediaQuery('(max-width: 640px)')
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

const statusVariant = computed(() => {
  if (props.kind === 'skill') {
    if (props.skillBusy || props.skillActive) return 'info' as const
    const st = props.skillRun?.status
    if (st === 'done') return 'ok' as const
    if (st === 'error') return 'stamp' as const
    if (props.skillRun?.pending_ask) return 'warn' as const
    return 'secondary' as const
  }
  if (props.running) return 'info' as const
  if (props.snap?.status === 'done') return 'ok' as const
  if (props.snap?.status === 'error') return 'stamp' as const
  return 'secondary' as const
})

const showProgress = computed(
  () =>
    props.kind === 'engine' &&
    (props.running || props.snap?.status === 'done' || props.snap?.status === 'error'),
)

const progressPct = computed(() => {
  if (props.snap?.status === 'done') return 100
  return props.percent
})

const progressTone = computed(() => {
  if (props.snap?.status === 'error') return 'is-error'
  if (props.snap?.status === 'done') return 'is-done'
  return ''
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

const picks = computed<Pick[]>(() => props.lastResult?.picks ?? [])
const watchPicks = computed<Pick[]>(() => props.lastResult?.watch_picks ?? [])
const hasPctChg = computed(() =>
  [...picks.value, ...watchPicks.value].some((row) => typeof row.pct_chg === 'number'),
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

const resultTitle = computed(() => {
  const result = props.lastResult
  const base = result?.range && result.range.trading_days > 1 ? '区间末日' : '今日结果'
  return result ? `${base} · ${result.trade_date}` : base
})

const recordedCount = computed(() => {
  const rec = props.lastResult?.recorded
  if (!rec) return null
  return rec.written_total != null ? rec.written_total : rec.written ?? null
})

function fmtNum(value: number | null | undefined): string {
  if (value == null) return '—'
  return Number(value).toFixed(2)
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function pctTone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}

function toggleLog(): void {
  logOpen.value = !logOpen.value
}
</script>

<template>
  <section class="run-panel" aria-label="选股跑道">
    <!-- 状态卡：谁在跑 · 到几 % · 日志 -->
    <Card class="run-status" :class="{ 'run-status--live': liveRunning }">
      <div class="run-status__row">
        <div class="run-status__id">
          <UiBadge v-if="kindLabel" variant="secondary">{{ kindLabel }}</UiBadge>
          <strong class="run-status__name">{{ selectedName || '先在目录里选一个战法或技能' }}</strong>
          <UiBadge :variant="statusVariant" :dot="!liveRunning" class="run-status__state">
            <span v-if="liveRunning" class="run-status__pulse" aria-hidden="true" />
            {{ statusLabel }}
          </UiBadge>
          <span v-if="elapsedText" class="run-status__elapsed">{{ elapsedText }}</span>
        </div>
        <div class="run-status__actions">
          <span v-if="showProgress" class="run-status__pct">{{ progressPct }}%</span>
          <Tooltip v-if="canAbandon">
            <TooltipTrigger as-child>
              <Button size="xs" variant="outline" class="text-warn-ink" type="button" @click="emit('abandon')">
                放弃跟踪
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom" align="end">停跟踪不等于停任务：后端没有中止接口，它会在后台跑完</TooltipContent>
          </Tooltip>
          <Button access="read"
            size="xs"
            variant="ghost"
            type="button"
            :aria-expanded="logOpen"
            aria-controls="run-panel-log"
            @click="toggleLog"
          >
            <ChevronRight class="run-status__chevron" :class="{ 'is-open': logOpen }" aria-hidden="true" />
            日志<template v-if="logs.length"> {{ logs.length }}</template>
          </Button>
        </div>
      </div>
      <Progress
        v-if="showProgress"
        :model-value="progressPct"
        class="run-status__progress"
        :class="progressTone"
        aria-label="选股进度"
      />
      <div
        v-show="logOpen"
        id="run-panel-log"
        class="run-log"
        :class="{ 'run-log--live': liveRunning }"
      >
        <ul ref="logEl" class="run-log__list" @scroll.passive="onLogScroll">
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
          <li v-if="!logs.length" class="log-line--empty">尚无日志</li>
        </ul>
      </div>
    </Card>

    <!-- 技能等待回复 -->
    <Card v-if="kind === 'skill' && skillRun?.pending_ask" class="hitl">
      <CardHeader class="border-b">
        <CardTitle>技能在等你回复</CardTitle>
        <CardDescription v-if="skillRun.pending_ask.prompt">{{ skillRun.pending_ask.prompt }}</CardDescription>
      </CardHeader>
      <CardContent class="hitl__body">
        <Textarea
          :model-value="skillReply"
          :rows="2"
          placeholder="回复技能…"
          aria-label="回复技能"
          @update:model-value="emit('update:skillReply', String($event))"
        />
        <Button size="sm" class="self-end" :disabled="skillBusy" @click="emit('reply')">
          <Send aria-hidden="true" />
          发送
        </Button>
      </CardContent>
    </Card>

    <!-- 战法结果 -->
    <Card v-if="kind === 'engine'" class="run-results">
      <CardHeader class="run-results__head border-b">
        <CardTitle class="run-results__title">
          {{ resultTitle }}
          <UiBadge variant="default">正式 {{ picks.length }}</UiBadge>
          <UiBadge variant="warn">观察 {{ watchPicks.length }}</UiBadge>
          <UiBadge v-if="lastResult?.range && lastResult.range.trading_days > 1" variant="secondary">共 {{ lastResult.range.trading_days }} 日</UiBadge>
          <UiBadge v-if="recordedCount != null" variant="ok">已入库 {{ recordedCount }}</UiBadge>
        </CardTitle>
        <CardDescription v-if="lastResult" class="run-results__hint">
          <template v-if="lastResult">全市场 {{ lastResult.universe_size.toLocaleString() }} 只 · 用时 {{ Number(lastResult.elapsed_seconds).toFixed(1) }}s</template>
        </CardDescription>
      </CardHeader>

      <div class="run-results__body" :class="{ 'run-results__body--single': !lastResult }">
        <section class="result-section" aria-label="正式精选">
          <div v-if="lastResult" class="result-section__title">
            <strong>正式精选</strong>
          </div>
          <EmptyState
            v-if="!picks.length"
            compact
            :description="lastResult ? '该日无正式精选' : '尚未执行选股'"
            :reason="lastResult ? '未满足入场条件' : undefined"
          />
          <ul v-else-if="isMobile" class="pick-cards">
            <li v-for="row in picks" :key="row.code" class="pick-card">
              <StockLink :code="row.code" :name="row.name || row.code" :date="lastResult?.trade_date" :batch="picksBatch" class="pick-card__link" />
              <span class="pick-card__nums">
                <b>{{ fmtNum(row.close) }}</b>
                <small :class="pctTone(row.pct_chg)">{{ hasPctChg ? fmtPct(row.pct_chg) : `开 ${fmtNum(row.open)}` }}</small>
              </span>
            </li>
          </ul>
          <Table v-else class="pick-table">
            <TableHeader>
              <TableRow>
                <TableHead class="text-center">标的 · 编码</TableHead>
                <TableHead class="text-center">开 · 收 · 涨跌</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="row in picks" :key="row.code">
                <TableCell class="text-center">
                  <span class="pick-inline" :title="`${row.name || row.code} ${row.code}`">
                    <StockLink :code="row.code" :name="row.name || row.code" :date="lastResult?.trade_date" :batch="picksBatch" />
                    <span class="pick-code">{{ row.code }}</span>
                  </span>
                </TableCell>
                <TableCell class="num text-center">{{ fmtNum(row.open) }} · {{ fmtNum(row.close) }}<template v-if="hasPctChg"> · <span :class="pctTone(row.pct_chg)">{{ fmtPct(row.pct_chg) }}</span></template></TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </section>

        <section v-if="lastResult" class="result-section" aria-label="低吸观察">
          <div class="result-section__title">
            <strong>低吸观察</strong>
            <UiBadge variant="warn">不计正式胜率</UiBadge>
          </div>
          <EmptyState v-if="!watchPicks.length" compact description="无低吸观察" />
          <ul v-else-if="isMobile" class="pick-cards">
            <li v-for="row in watchPicks" :key="row.code" class="pick-card">
              <StockLink :code="row.code" :name="row.name || row.code" :date="lastResult?.trade_date" :batch="watchBatch" class="pick-card__link" />
              <span class="pick-card__nums">
                <b>{{ fmtNum(row.close) }}</b>
                <small :class="pctTone(row.pct_chg)">{{ hasPctChg ? fmtPct(row.pct_chg) : `开 ${fmtNum(row.open)}` }}</small>
              </span>
            </li>
          </ul>
          <Table v-else class="pick-table">
            <TableHeader>
              <TableRow>
                <TableHead class="text-center">标的 · 编码</TableHead>
                <TableHead class="text-center">开 · 收 · 涨跌</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="row in watchPicks" :key="row.code">
                <TableCell class="text-center">
                  <span class="pick-inline" :title="`${row.name || row.code} ${row.code}`">
                    <StockLink :code="row.code" :name="row.name || row.code" :date="lastResult?.trade_date" :batch="watchBatch" />
                    <span class="pick-code">{{ row.code }}</span>
                  </span>
                </TableCell>
                <TableCell class="num text-center">{{ fmtNum(row.open) }} · {{ fmtNum(row.close) }}<template v-if="hasPctChg"> · <span :class="pctTone(row.pct_chg)">{{ fmtPct(row.pct_chg) }}</span></template></TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </section>
      </div>
    </Card>

    <!-- 技能产出 -->
    <Card v-else-if="kind === 'skill'" class="run-results run-results--skill">
      <CardHeader class="border-b">
        <CardTitle>技能产出</CardTitle>
        
      </CardHeader>
      <pre v-if="skillRun?.result?.output" class="skill-out">{{ skillRun.result.output }}</pre>
      <EmptyState
        v-else
        description="跑技能后显示事件流与产出"
        reason="选好模型供应商后点右上角「跑技能」"
      />
    </Card>

    <Card v-else class="run-results run-results--idle">
      <EmptyState description="先选一个战法或技能" reason="左侧目录（手机端在页头「选目录」）里挑一个，再点「选股」" />
    </Card>
  </section>
</template>

<style scoped src="./ScreenRunPanel.css"></style>
