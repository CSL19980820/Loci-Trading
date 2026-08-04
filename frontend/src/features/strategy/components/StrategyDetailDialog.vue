<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  deleteStrategyVersion,
  getStrategyJob,
  getStrategyVersions,
  rollbackStrategyVersion,
  upsertStrategyJob,
} from '@/shared/api/quant_strategy'
import { confirmDangerous } from '@/shared/lib/confirm'
import { dialogWidth } from '@/shared/lib/format'
import { toErrorMessage } from '@/shared/lib/errors'
import type { StrategyInfo, StrategyJob, StrategyVersion, UniverseSpec } from '@/shared/types/quant'
type DetailTab = 'basics' | 'config'
type ScheduleMode = 'off' | 'once' | 'interval'
type BoardId = 'main' | 'chi_next' | 'star' | 'bse'
const FIELD_LABELS: Record<string, string> = {
  open: '开盘价',
  high: '最高价',
  low: '最低价',
  close: '收盘价',
  volume: '成交量',
  turnover: '换手率',
}
const PARAM_LABELS: Record<string, string> = {
  concentration: '集中度',
  low_ratio: '低位比例',
  volume_boost: '放量倍数',
  chip_bins: '筹码档位',
  death_lookback: '死叉回看',
  below_window: '白线下窗口',
  below_min: '白下最少天',
  price_min: '最低价',
  vol_boost: '放量倍数',
  hold_ratio: '站稳比例',
  turnover_min: '换手下限',
  turnover_max: '换手上限',
}
const BOARD_OPTIONS: { id: BoardId; label: string }[] = [
  { id: 'main', label: '主板' },
  { id: 'chi_next', label: '创业板' },
  { id: 'star', label: '科创板' },
  { id: 'bse', label: '北交所' },
]
const HOUR_OPTS = Array.from({ length: 24 }, (_, i) => i)
const MINUTE_OPTS = Array.from({ length: 12 }, (_, i) => i * 5)
const INTERVAL_OPTS = [5, 10, 15, 30, 60]
const props = defineProps<{
  modelValue: boolean
  strategy: StrategyInfo | null
}>()
const emit = defineEmits<{
  'update:modelValue': [boolean]
  saved: [job: StrategyJob]
}>()
const tab = ref<DetailTab>('basics')
const saving = ref(false)
const loadingJob = ref(false)
const loadingVersions = ref(false)
const versionActing = ref('')
const strategySnapshot = ref<StrategyInfo | null>(null)
const versionHistory = ref<StrategyVersion[]>([])
let versionRequestSeq = 0
let versionActionSeq = 0
const boards = reactive<Record<BoardId, boolean>>({
  main: true,
  chi_next: true,
  star: true,
  bse: false,
})
const includeSt = ref(false)
const scheduleEnabled = ref(false)
const scheduleMode = ref<'once' | 'interval'>('once')
const pushWecom = ref(true)
const runHour = ref(15)
const runMinute = ref(30)
const intervalMinutes = ref(10)
const windowStartHour = ref(9)
const windowStartMinute = ref(30)
const windowEndHour = ref(14)
const windowEndMinute = ref(50)
const nextRuns = ref<string[]>([])
const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})
const displayedStrategy = computed(() => strategySnapshot.value ?? props.strategy)
const title = computed(() => displayedStrategy.value?.name || '战法详情')
const sourceLabel = computed(() => {
  const kind = displayedStrategy.value?.source_kind
  if (kind === 'builtin') return '内置'
  if (kind === 'formula') return '公式'
  return kind || '—'
})
const entryLabel = computed(() => {
  const v = displayedStrategy.value?.entry_timing
  if (v === 'open') return '当日开盘'
  if (v === 'next_dip') return '次日低吸'
  if (v === 'close') return '当日收盘'
  return '次日开盘'
})
const revisionLabel = computed(() => {
  const raw = String(displayedStrategy.value?.strategy_revision || '').trim()
  const kind = displayedStrategy.value?.source_kind
  if (!raw) return '—'
  if (kind === 'builtin' || raw.startsWith('builtin:')) return '内置'
  if (/^[0-9a-f]{8,}$/i.test(raw)) return `公式 · ${raw.slice(0, 8)}`
  return raw.slice(0, 12)
})
const paramRows = computed(() =>
  Object.entries(displayedStrategy.value?.params ?? {}).map(([key, value]) => ({
    key,
    label: PARAM_LABELS[key] || key,
    value: String(value),
  })),
)
const fieldRows = computed(() =>
  (displayedStrategy.value?.required_fields ?? []).map((key) => ({
    key,
    label: FIELD_LABELS[key] || key,
  })),
)
const canManageVersions = computed(() => {
  const strategy = displayedStrategy.value
  return Boolean(
    strategy
    && (strategy.editable === true || strategy.source_kind === 'formula' || strategy.source_kind === 'python'),
  )
})
const versionRows = computed(() => versionHistory.value)
const backtestMetrics = computed(() => displayedStrategy.value?.backtest_metrics ?? null)
const backtestConfigLabel = computed(() => formatBacktestConfig(displayedStrategy.value?.backtest_config))
const previewRuns = computed(() => {
  if (!scheduleEnabled.value) return [] as string[]
  return buildPreview(
    scheduleMode.value,
    runHour.value,
    runMinute.value,
    intervalMinutes.value,
    windowStartHour.value,
    windowStartMinute.value,
    windowEndHour.value,
    windowEndMinute.value,
  )
})
/** 保存/拉取后用服务端；改表单时回落到本地预览 */
const displayRuns = computed(() =>
  nextRuns.value.length ? nextRuns.value : previewRuns.value,
)
let seedingSchedule = false
watch(
  [
    scheduleEnabled,
    scheduleMode,
    runHour,
    runMinute,
    intervalMinutes,
    windowStartHour,
    windowStartMinute,
    windowEndHour,
    windowEndMinute,
  ],
  () => {
    if (seedingSchedule) return
    nextRuns.value = []
  },
)
watch(
  () => [props.modelValue, props.strategy?.slug] as const,
  async ([opened, slug]) => {
    if (!opened || !slug || !props.strategy) {
      versionRequestSeq += 1
      versionActionSeq += 1
      versionActing.value = ''
      return
    }
    versionActionSeq += 1
    versionActing.value = ''
    strategySnapshot.value = props.strategy
    versionHistory.value = props.strategy.version_history ?? []
    tab.value = 'basics'
    if (canManageVersions.value) void refreshVersions(slug)
    seedingSchedule = true
    applyUniverse(props.strategy.default_universe ?? null)
    resetSchedule()
    loadingJob.value = true
    try {
      const job = await getStrategyJob(slug)
      hydrateFromJob(job)
    } catch {
      /* 无绑定用默认 */
    } finally {
      loadingJob.value = false
      seedingSchedule = false
    }
  },
  { immediate: true },
)
async function refreshVersions(slug: string): Promise<void> {
  const requestSeq = ++versionRequestSeq
  loadingVersions.value = true
  try {
    const versions = await getStrategyVersions(slug)
    if (requestSeq !== versionRequestSeq || displayedStrategy.value?.slug !== slug) return
    versionHistory.value = versions
  } catch (caught: unknown) {
    if (requestSeq === versionRequestSeq) {
      ElMessage.error(toErrorMessage(caught, '读取版本历史失败'))
    }
  } finally {
    if (requestSeq === versionRequestSeq) loadingVersions.value = false
  }
}
function versionKey(version: string): string {
  return version
}
function isVersionActionCurrent(actionSeq: number, slug: string): boolean {
  return actionSeq === versionActionSeq && displayedStrategy.value?.slug === slug
}
async function rollback(version: string): Promise<void> {
  const strategy = displayedStrategy.value
  if (!strategy || versionActing.value || !await confirmDangerous(`回滚到 ${version} 后将覆盖当前战法定义。`, '确认回滚', '回滚')) return
  const actionSeq = ++versionActionSeq
  versionActing.value = versionKey(version)
  try {
    const restored = await rollbackStrategyVersion(strategy.slug, version)
    if (!isVersionActionCurrent(actionSeq, strategy.slug)) return
    strategySnapshot.value = { ...strategy, version: restored.version }
    ElMessage.success(`已回滚到 ${version}`)
    await refreshVersions(strategy.slug)
  } catch (caught: unknown) {
    if (isVersionActionCurrent(actionSeq, strategy.slug)) {
      ElMessage.error(toErrorMessage(caught, '回滚版本失败'))
    }
  } finally {
    if (actionSeq === versionActionSeq) versionActing.value = ''
  }
}
async function removeVersion(version: string): Promise<void> {
  const strategy = displayedStrategy.value
  if (!strategy || versionActing.value || !await confirmDangerous(`删除版本 ${version} 后无法恢复。`, '确认删除版本', '删除')) return
  const actionSeq = ++versionActionSeq
  versionActing.value = versionKey(version)
  try {
    await deleteStrategyVersion(strategy.slug, version)
    if (!isVersionActionCurrent(actionSeq, strategy.slug)) return
    ElMessage.success(`已删除版本 ${version}`)
    await refreshVersions(strategy.slug)
  } catch (caught: unknown) {
    if (isVersionActionCurrent(actionSeq, strategy.slug)) {
      ElMessage.error(toErrorMessage(caught, '删除版本失败'))
    }
  } finally {
    if (actionSeq === versionActionSeq) versionActing.value = ''
  }
}
function resetSchedule(): void {
  scheduleEnabled.value = false
  scheduleMode.value = 'once'
  pushWecom.value = true
  runHour.value = 15
  runMinute.value = 47
  intervalMinutes.value = 10
  windowStartHour.value = 9
  windowStartMinute.value = 30
  windowEndHour.value = 14
  windowEndMinute.value = 50
  nextRuns.value = []
}
function applyUniverse(spec: UniverseSpec | null | undefined): void {
  const list = spec?.boards?.length
    ? spec.boards
    : (['main', 'chi_next', 'star'] as BoardId[])
  for (const id of BOARD_OPTIONS.map((b) => b.id)) {
    boards[id] = list.includes(id)
  }
  includeSt.value = spec?.exclude_st === false
}
function hydrateFromJob(job: StrategyJob): void {
  if (!job.bound) return
  const cfg = job.config ?? {}
  if (cfg.universe) applyUniverse(cfg.universe)
  const schedule = cfg.schedule
  if (schedule?.mode === 'once' || schedule?.mode === 'interval') {
    scheduleEnabled.value = true
    scheduleMode.value = schedule.mode
    runHour.value = Number(schedule.run_hour ?? 15)
    runMinute.value = Number(schedule.run_minute ?? 30)
    intervalMinutes.value = Number(schedule.interval_minutes ?? 10)
    windowStartHour.value = Number(schedule.window_start_hour ?? 9)
    windowStartMinute.value = Number(schedule.window_start_minute ?? 30)
    windowEndHour.value = Number(schedule.window_end_hour ?? 14)
    windowEndMinute.value = Number(schedule.window_end_minute ?? 50)
  } else if (job.enabled && job.cron) {
    scheduleEnabled.value = true
  }
  pushWecom.value = cfg.push_wecom !== false
  nextRuns.value = job.next_runs ?? []
}
function buildUniversePayload(): UniverseSpec {
  const selected = BOARD_OPTIONS.filter((b) => boards[b.id]).map((b) => b.id)
  return {
    preset: 'custom',
    boards: selected.length ? selected : ['main'],
    exclude_st: !includeSt.value,
  }
}
async function save(): Promise<void> {
  if (!props.strategy) return
  saving.value = true
  try {
    const mode: ScheduleMode = scheduleEnabled.value ? scheduleMode.value : 'off'
    const job = await upsertStrategyJob(props.strategy.slug, {
      schedule_mode: mode,
      run_hour: runHour.value,
      run_minute: runMinute.value,
      interval_minutes: intervalMinutes.value,
      window_start_hour: windowStartHour.value,
      window_start_minute: windowStartMinute.value,
      window_end_hour: windowEndHour.value,
      window_end_minute: windowEndMinute.value,
      universe: buildUniversePayload(),
      auto_review: true,
      push_wecom: pushWecom.value,
      enabled: mode !== 'off',
      top_n: 0,
    })
    seedingSchedule = true
    nextRuns.value = job.next_runs?.length ? job.next_runs : previewRuns.value
    seedingSchedule = false
    ElMessage.success(mode === 'off' ? '已关闭定时并移除任务' : '已保存')
    emit('saved', job)
    open.value = false
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '保存失败'))
  } finally {
    saving.value = false
  }
}
function pad(n: number): string {
  return String(n).padStart(2, '0')
}
function formatPercent(value: number | null | undefined): string {
  return typeof value === 'number' ? `${value.toFixed(2)}%` : '—'
}
function formatProfitFactor(value: number | null | undefined): string {
  if (value === Infinity) return '∞'
  return typeof value === 'number' ? value.toFixed(2) : '—'
}
function formatBacktestValue(key: string, value: unknown): string {
  if (key === 'universe' && value && typeof value === 'object' && !Array.isArray(value)) {
    const universe = value as UniverseSpec
    const boards = (universe.boards ?? []).map(
      (board) => BOARD_OPTIONS.find((option) => option.id === board)?.label ?? board,
    )
    const parts = boards.length ? [boards.join('、')] : []
    if (universe.exclude_st === false) parts.push('含 ST')
    else if (universe.exclude_st === true) parts.push('剔除 ST')
    if (!parts.length && universe.preset) parts.push(String(universe.preset))
    return parts.join('，') || '—'
  }
  if (Array.isArray(value)) return value.join('、')
  if (value && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
function formatBacktestConfig(config: Record<string, unknown> | null | undefined): string {
  if (!config) return '—'
  const labels: Record<string, string> = {
    start: '起始', end: '结束', hold_days: '持有', stop_loss_pct: '止损',
    take_profit_pct: '止盈', benchmark: '基准', entry_timing: '入场', mode: '模式', universe: '股票池',
  }
  const values = Object.entries(config).filter(([, value]) => value != null && value !== '')
  return values.length
    ? values.map(([key, value]) => `${labels[key] || key}=${formatBacktestValue(key, value)}`).join('，')
    : '—'
}
function isActiveVersion(version: StrategyVersion): boolean {
  return version.is_active === true || String(version.version) === displayedStrategy.value?.version
}
function buildPreview(
  mode: 'once' | 'interval',
  hour: number,
  minute: number,
  every: number,
  startH: number,
  startM: number,
  endH: number,
  endM: number,
): string[] {
  const now = new Date()
  const day = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
  if (mode === 'once') return [`${day} ${pad(hour)}:${pad(minute)}`]
  const start = startH * 60 + startM
  const end = endH * 60 + endM
  const out: string[] = []
  for (let t = start; t <= end && out.length < 5; t += every) {
    out.push(`${day} ${pad(Math.floor(t / 60))}:${pad(t % 60)}`)
  }
  return out
}
</script>
<template>
  <el-dialog
    v-model="open"
    :title="title"
    :width="dialogWidth()"
    destroy-on-close
    class="strategy-detail-dialog"
  >
    <template v-if="strategy">
      <el-tabs v-model="tab" class="detail-tabs">
        <el-tab-pane label="基础信息" name="basics">
          <el-descriptions :column="2" border size="small" class="detail-desc">
            <el-descriptions-item label="来源">{{ sourceLabel }}</el-descriptions-item>
            <el-descriptions-item label="入场">{{ entryLabel }}</el-descriptions-item>
            <el-descriptions-item label="最少 K 线">{{ displayedStrategy?.min_bars }}</el-descriptions-item>
            <el-descriptions-item label="修订">{{ revisionLabel }}</el-descriptions-item>
            <el-descriptions-item label="当前版本">{{ displayedStrategy?.version || '—' }}</el-descriptions-item>
            <el-descriptions-item label="回测交易数">{{ backtestMetrics?.trades ?? '—' }}</el-descriptions-item>
            <el-descriptions-item label="回测胜率">{{ formatPercent(backtestMetrics?.win_rate) }}</el-descriptions-item>
            <el-descriptions-item label="平均净收益">{{ formatPercent(backtestMetrics?.avg_net_return) }}</el-descriptions-item>
            <el-descriptions-item label="PF">{{ formatProfitFactor(backtestMetrics?.profit_factor) }}</el-descriptions-item>
            <el-descriptions-item label="回测口径" :span="2">{{ backtestConfigLabel }}</el-descriptions-item>
            <el-descriptions-item v-if="displayedStrategy?.entry_instructions" label="买入说明" :span="2">
              {{ displayedStrategy.entry_instructions }}
            </el-descriptions-item>
            <el-descriptions-item label="说明" :span="2">
              {{ displayedStrategy?.description || '—' }}
            </el-descriptions-item>
            <el-descriptions-item label="所需字段" :span="2">
              <div v-if="fieldRows.length" class="field-tags">
                <el-tag
                  v-for="row in fieldRows"
                  :key="row.key"
                  size="small"
                  effect="plain"
                  type="info"
                >
                  {{ row.label }}
                  <span class="field-key">{{ row.key }}</span>
                </el-tag>
              </div>
              <span v-else class="dim">—</span>
            </el-descriptions-item>
          </el-descriptions>
          <div class="version-history" v-loading="loadingVersions">
            <div class="version-history__title">历史版本</div>
            <div v-if="versionRows.length" class="version-list">
              <div v-for="row in versionRows" :key="row.id || row.version" class="version-row">
                <div class="version-row__meta">
                  <strong class="mono">{{ row.version }}</strong>
                  <el-tag v-if="isActiveVersion(row)" size="small" type="success">当前</el-tag>
                  <el-tag v-else-if="row.status" size="small" effect="plain">{{ row.status }}</el-tag>
                  <span class="dim">{{ row.created_at || '—' }}</span>
                </div>
                <div v-if="canManageVersions && !isActiveVersion(row)" class="version-row__actions">
                  <el-button link type="primary" :loading="versionActing === versionKey(row.version)" @click="rollback(row.version)">
                    回滚
                  </el-button>
                  <el-button link type="danger" :disabled="Boolean(versionActing)" @click="removeVersion(row.version)">
                    删除
                  </el-button>
                </div>
              </div>
            </div>
            <span v-else class="dim">暂无历史版本</span>
          </div>
        </el-tab-pane>
        <el-tab-pane label="配置" name="config" v-loading="loadingJob">
          <el-form label-position="left" label-width="5.5rem" class="detail-form" size="small">
            <el-form-item v-if="paramRows.length" label="默认参数">
              <el-descriptions :column="2" size="small" class="param-desc">
                <el-descriptions-item v-for="row in paramRows" :key="row.key" :label="row.label">
                  <span class="mono">{{ row.value }}</span>
                </el-descriptions-item>
              </el-descriptions>
            </el-form-item>
            <el-form-item v-else label="默认参数">
              <span class="dim">无默认参数</span>
            </el-form-item>
            <el-form-item label="行情范围">
              <div class="board-col">
                <div class="board-row">
                  <el-checkbox
                    v-for="b in BOARD_OPTIONS"
                    :key="b.id"
                    v-model="boards[b.id]"
                  >
                    {{ b.label }}
                  </el-checkbox>
                  <el-checkbox v-model="includeSt">含 ST</el-checkbox>
                </div>
                <span class="dim hint">定时与手动选股共用；点保存后生效</span>
              </div>
            </el-form-item>
            <el-form-item label="定时选股">
              <el-switch v-model="scheduleEnabled" />
              <span class="dim hint">开启后按交易日自动跑选股</span>
            </el-form-item>
            <el-form-item label="推送企微">
              <el-switch v-model="pushWecom" :disabled="!scheduleEnabled" />
              <span class="dim hint">
                {{
                  scheduleEnabled
                    ? '定时任务结束后自动推送选股结果（需先在运维配置 Webhook）'
                    : '先开启定时选股后再开推送'
                }}
              </span>
            </el-form-item>
            <template v-if="scheduleEnabled">
              <el-form-item label="方式">
                <el-radio-group v-model="scheduleMode">
                  <el-radio-button value="once">定点</el-radio-button>
                  <el-radio-button value="interval">间隔</el-radio-button>
                </el-radio-group>
              </el-form-item>
              <el-form-item v-if="scheduleMode === 'once'" label="交易日">
                <div class="time-row">
                  <el-select v-model="runHour" class="time-select">
                    <el-option v-for="h in HOUR_OPTS" :key="h" :label="pad(h)" :value="h" />
                  </el-select>
                  <span class="time-sep">:</span>
                  <el-select v-model="runMinute" class="time-select">
                    <el-option v-for="m in MINUTE_OPTS" :key="m" :label="pad(m)" :value="m" />
                  </el-select>
                </div>
              </el-form-item>
              <template v-else>
                <el-form-item label="时段">
                  <div class="time-row">
                    <el-select v-model="windowStartHour" class="time-select">
                      <el-option
                        v-for="h in HOUR_OPTS"
                        :key="`s${h}`"
                        :label="pad(h)"
                        :value="h"
                      />
                    </el-select>
                    <span class="time-sep">:</span>
                    <el-select v-model="windowStartMinute" class="time-select">
                      <el-option
                        v-for="m in MINUTE_OPTS"
                        :key="`sm${m}`"
                        :label="pad(m)"
                        :value="m"
                      />
                    </el-select>
                    <span class="time-sep dim">—</span>
                    <el-select v-model="windowEndHour" class="time-select">
                      <el-option
                        v-for="h in HOUR_OPTS"
                        :key="`e${h}`"
                        :label="pad(h)"
                        :value="h"
                      />
                    </el-select>
                    <span class="time-sep">:</span>
                    <el-select v-model="windowEndMinute" class="time-select">
                      <el-option
                        v-for="m in MINUTE_OPTS"
                        :key="`em${m}`"
                        :label="pad(m)"
                        :value="m"
                      />
                    </el-select>
                  </div>
                </el-form-item>
                <el-form-item label="每隔">
                  <el-select v-model="intervalMinutes" class="interval-select">
                    <el-option
                      v-for="n in INTERVAL_OPTS"
                      :key="n"
                      :label="`${n} 分钟`"
                      :value="n"
                    />
                  </el-select>
                </el-form-item>
              </template>
              <el-form-item :label="scheduleMode === 'once' ? '下次选股' : '近 5 次'">
                <div v-if="displayRuns.length" class="preview-lines">
                  <div v-for="row in displayRuns" :key="row" class="preview-line">{{ row }}</div>
                </div>
                <span v-else class="dim">—</span>
              </el-form-item>
            </template>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </template>
    <template #footer>
      <el-button type="primary" :loading="saving" :disabled="!strategy" @click="save">
        保存
      </el-button>
    </template>
  </el-dialog>
</template>
<style scoped>
.detail-tabs :deep(.el-tabs__header) { margin-bottom: 0.75rem; }
.detail-desc, .param-desc { width: 100%; }
.detail-desc :deep(.el-descriptions__label), .detail-form :deep(.el-form-item__label) { color: var(--mist); }
.detail-desc :deep(.el-descriptions__label) { width: 5.5rem; }
.field-tags, .board-row, .time-row, .version-row__meta, .version-row__actions { display: flex; flex-wrap: wrap; align-items: center; }
.field-tags { gap: 0.35rem; }
.field-key { margin-left: 0.35rem; color: var(--mist); font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace); font-size: 0.72rem; }
.detail-form :deep(.el-form-item) { margin-bottom: 0.85rem; }
.param-desc :deep(.el-descriptions__body) { background: transparent; }
.board-col { display: flex; flex-direction: column; gap: 0.25rem; }
.board-row { gap: 0.15rem 1rem; min-height: 1.75rem; }
.board-col > .hint { margin-left: 0; }
.time-row { gap: 0.25rem; }
.time-select { width: 4.5rem; }
.interval-select { width: 7.5rem; }
.time-sep { padding: 0 0.1rem; }
.preview-lines, .version-list { display: flex; flex-direction: column; gap: 0.15rem; }
.preview-line, .mono { font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace); font-variant-numeric: tabular-nums; }
.preview-line { font-size: 0.82rem; font-weight: 600; }
.version-history { margin-top: 1rem; }
.version-history__title { margin-bottom: 0.35rem; font-size: 0.86rem; font-weight: 600; }
.version-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.35rem 0; border-bottom: 1px solid var(--line, var(--el-border-color-lighter)); }
.version-row__meta { gap: 0.35rem; min-width: 0; }
.version-row__actions { gap: 0.15rem; flex-shrink: 0; }
.dim { color: var(--mist); font-size: 0.82rem; }
.hint { margin-left: 0.55rem; }
</style>
