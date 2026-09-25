<script setup lang="ts">
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import { toast } from 'vue-sonner'

import { computed, reactive, ref, useId, watch } from 'vue'

import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'
import { Spinner } from '@/shared/components/ui/spinner'

import {
  deleteStrategyVersion,
  getStrategyJob,
  getStrategyVersions,
  rollbackStrategyVersion,
  upsertStrategyJob,
} from '@/shared/api/quant_strategy'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import type { StrategyInfo, StrategyJob, StrategyVersion, UniverseSpec } from '@/shared/types/quant'
import StrategyDetailBasicsPane from './StrategyDetailBasicsPane.vue'
import StrategyDetailConfigPane, { type StrategyDetailConfigForm } from './StrategyDetailConfigPane.vue'
import StrategyRecentPicks from './StrategyRecentPicks.vue'
import StrategyVersionList from './StrategyVersionList.vue'
import {
  BOARD_OPTIONS,
  buildPreview,
  formatPercent,
  formatProfitFactor,
  pad,
  strategyEntryLabel,
  strategyRevisionLabel,
  strategySourceLabel,
  type BoardId,
  type ScheduleMode,
} from './strategyDetailFormat'

type DetailTab = 'basics' | 'config' | 'picks' | 'versions'

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

const configForm = reactive<StrategyDetailConfigForm>({
  boards: { main: true, chi_next: true, star: true, bse: false },
  includeSt: false,
  scheduleEnabled: false,
  scheduleMode: 'once',
  pushWecom: true,
  runHour: 15,
  runMinute: 30,
  intervalMinutes: 10,
  windowStartHour: 9,
  windowStartMinute: 30,
  windowEndHour: 14,
  windowEndMinute: 50,
})

const nextRuns = ref<string[]>([])
let seedingSchedule = false

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const displayedStrategy = computed(() => strategySnapshot.value ?? props.strategy)
const title = computed(() => displayedStrategy.value?.name || '战法详情')
const panelId = useId()
const picksCount = ref(0)

const tabModel = computed({
  get: () => tab.value,
  set: (value: string) => {
    tab.value = value === 'config' || value === 'picks' || value === 'versions' ? value : 'basics'
  },
})

const tabItems = computed<PageTabItem[]>(() => [
  { name: 'basics', label: '概览' },
  { name: 'config', label: '调度与范围' },
  { name: 'picks', label: '近期选出', badge: picksCount.value || undefined },
  { name: 'versions', label: '版本', badge: versionHistory.value.length || undefined },
])

const metrics = computed(() => {
  const m = displayedStrategy.value?.backtest_metrics ?? null
  const net = m?.avg_net_return
  return [
    { key: 'trades', label: '回测交易', value: m?.trades == null ? '—' : String(m.trades), tone: '' },
    { key: 'win', label: '胜率', value: formatPercent(m?.win_rate), tone: '' },
    {
      key: 'net',
      label: '平均净收益',
      value: formatPercent(net),
      tone: typeof net === 'number' ? (net > 0 ? 'is-up' : net < 0 ? 'is-down' : '') : '',
    },
    { key: 'pf', label: '盈亏比 PF', value: formatProfitFactor(m?.profit_factor), tone: '' },
  ]
})

const versionText = computed(() => {
  const raw = String(displayedStrategy.value?.version || '').trim()
  if (!raw) return ''
  return raw.toLowerCase().startsWith('v') ? raw : `v${raw}`
})

/** 修订指纹：内置战法显示「内置」不重复，公式战法给前 8 位 */
const revisionText = computed(() => {
  const text = strategyRevisionLabel(displayedStrategy.value)
  return text === '—' || text === strategySourceLabel(displayedStrategy.value) ? '' : text
})

const scheduleSummary = computed(() => {
  if (!configForm.scheduleEnabled) return '未定时'
  if (configForm.scheduleMode === 'interval') return `盘中每 ${configForm.intervalMinutes} 分钟`
  return `交易日 ${pad(configForm.runHour)}:${pad(configForm.runMinute)}`
})

const canManageVersions = computed(() => {
  const strategy = displayedStrategy.value
  return Boolean(
    strategy
    && (strategy.editable === true || strategy.source_kind === 'formula' || strategy.source_kind === 'python'),
  )
})

const previewRuns = computed(() => {
  if (!configForm.scheduleEnabled) return [] as string[]
  return buildPreview(
    configForm.scheduleMode,
    configForm.runHour,
    configForm.runMinute,
    configForm.intervalMinutes,
    configForm.windowStartHour,
    configForm.windowStartMinute,
    configForm.windowEndHour,
    configForm.windowEndMinute,
  )
})

/** 保存/拉取后用服务端；改表单时回落到本地预览 */
const displayRuns = computed(() =>
  nextRuns.value.length ? nextRuns.value : previewRuns.value,
)

watch(
  () => [
    configForm.scheduleEnabled,
    configForm.scheduleMode,
    configForm.runHour,
    configForm.runMinute,
    configForm.intervalMinutes,
    configForm.windowStartHour,
    configForm.windowStartMinute,
    configForm.windowEndHour,
    configForm.windowEndMinute,
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

function patchConfig(partial: Partial<StrategyDetailConfigForm>): void {
  if (partial.boards) Object.assign(configForm.boards, partial.boards)
  const { boards: _boards, ...rest } = partial
  Object.assign(configForm, rest)
}

async function refreshVersions(slug: string): Promise<void> {
  const requestSeq = ++versionRequestSeq
  loadingVersions.value = true
  try {
    const versions = await getStrategyVersions(slug)
    if (requestSeq !== versionRequestSeq || displayedStrategy.value?.slug !== slug) return
    versionHistory.value = versions
  } catch (caught: unknown) {
    if (requestSeq === versionRequestSeq) {
      toast.error(toErrorMessage(caught, '读取版本历史失败'))
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
    toast.success(`已回滚到 ${version}`)
    await refreshVersions(strategy.slug)
  } catch (caught: unknown) {
    if (isVersionActionCurrent(actionSeq, strategy.slug)) {
      toast.error(toErrorMessage(caught, '回滚版本失败'))
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
    toast.success(`已删除版本 ${version}`)
    await refreshVersions(strategy.slug)
  } catch (caught: unknown) {
    if (isVersionActionCurrent(actionSeq, strategy.slug)) {
      toast.error(toErrorMessage(caught, '删除版本失败'))
    }
  } finally {
    if (actionSeq === versionActionSeq) versionActing.value = ''
  }
}

function resetSchedule(): void {
  configForm.scheduleEnabled = false
  configForm.scheduleMode = 'once'
  configForm.pushWecom = true
  configForm.runHour = 15
  configForm.runMinute = 47
  configForm.intervalMinutes = 10
  configForm.windowStartHour = 9
  configForm.windowStartMinute = 30
  configForm.windowEndHour = 14
  configForm.windowEndMinute = 50
  nextRuns.value = []
}

function applyUniverse(spec: UniverseSpec | null | undefined): void {
  const list = spec?.boards?.length
    ? spec.boards
    : (['main', 'chi_next', 'star'] as BoardId[])
  for (const id of BOARD_OPTIONS.map((b) => b.id)) {
    configForm.boards[id] = list.includes(id)
  }
  configForm.includeSt = spec?.exclude_st === false
}

function hydrateFromJob(job: StrategyJob): void {
  if (!job.bound) return
  const cfg = job.config ?? {}
  if (cfg.universe) applyUniverse(cfg.universe)
  const schedule = cfg.schedule
  if (schedule?.mode === 'once' || schedule?.mode === 'interval') {
    configForm.scheduleEnabled = true
    configForm.scheduleMode = schedule.mode
    configForm.runHour = Number(schedule.run_hour ?? 15)
    configForm.runMinute = Number(schedule.run_minute ?? 30)
    configForm.intervalMinutes = Number(schedule.interval_minutes ?? 10)
    configForm.windowStartHour = Number(schedule.window_start_hour ?? 9)
    configForm.windowStartMinute = Number(schedule.window_start_minute ?? 30)
    configForm.windowEndHour = Number(schedule.window_end_hour ?? 14)
    configForm.windowEndMinute = Number(schedule.window_end_minute ?? 50)
  } else if (job.enabled && job.cron) {
    configForm.scheduleEnabled = true
  }
  configForm.pushWecom = cfg.push_wecom !== false
  nextRuns.value = job.next_runs ?? []
}

function buildUniversePayload(): UniverseSpec {
  const selected = BOARD_OPTIONS.filter((b) => configForm.boards[b.id]).map((b) => b.id)
  return {
    preset: 'custom',
    boards: selected.length ? selected : ['main'],
    exclude_st: !configForm.includeSt,
  }
}

async function save(): Promise<void> {
  if (!props.strategy) return
  saving.value = true
  try {
    const mode: ScheduleMode = configForm.scheduleEnabled ? configForm.scheduleMode : 'off'
    const job = await upsertStrategyJob(props.strategy.slug, {
      schedule_mode: mode,
      run_hour: configForm.runHour,
      run_minute: configForm.runMinute,
      interval_minutes: configForm.intervalMinutes,
      window_start_hour: configForm.windowStartHour,
      window_start_minute: configForm.windowStartMinute,
      window_end_hour: configForm.windowEndHour,
      window_end_minute: configForm.windowEndMinute,
      universe: buildUniversePayload(),
      auto_review: true,
      push_wecom: configForm.pushWecom,
      enabled: mode !== 'off',
      top_n: 0,
    })
    seedingSchedule = true
    nextRuns.value = job.next_runs?.length ? job.next_runs : previewRuns.value
    seedingSchedule = false
    toast.success(mode === 'off' ? '已关闭定时并移除任务' : '已保存')
    emit('saved', job)
    open.value = false
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '保存失败'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="sd flex flex-col gap-0 overflow-hidden p-0 sm:max-w-[880px]">
      <DialogHeader class="sd__hero text-left">
        <div class="sd__crumbs">
          <span class="sd__source">{{ strategySourceLabel(displayedStrategy) }}</span>
          <span v-if="versionText" class="sd__ver">{{ versionText }}</span>
          <span>{{ strategyEntryLabel(displayedStrategy) }}</span>
          <span v-if="displayedStrategy?.min_bars">{{ displayedStrategy.min_bars }} 根</span>
          <span v-if="revisionText" class="sd__ver" :title="displayedStrategy?.strategy_revision">{{ revisionText }}</span>
        </div>
        <div class="sd__title-row">
          <DialogTitle class="sd__title">{{ title }}</DialogTitle>
          <span class="sd__sched" :class="{ 'is-on': configForm.scheduleEnabled }">
            <i aria-hidden="true" />{{ scheduleSummary }}
          </span>
        </div>
        <DialogDescription class="sr-only">战法详情</DialogDescription>
      </DialogHeader>

      <template v-if="strategy">
        <dl class="sd__metrics" aria-label="回测读数">
          <div v-for="item in metrics" :key="item.key" class="sd__metric">
            <dt>{{ item.label }}</dt>
            <dd :class="item.tone">{{ item.value }}</dd>
          </div>
        </dl>

        <PageTabs v-model="tabModel" :items="tabItems" :panel-id="panelId" :sticky="false" aria-label="战法详情分区" class="sd__tabs" />

        <div :id="panelId" class="sd__body" role="tabpanel" tabindex="0" :aria-labelledby="`${panelId}-tab-${tab}`">
          <StrategyDetailBasicsPane v-show="tab === 'basics'" :strategy="displayedStrategy" />
          <fieldset v-show="tab === 'config'" :disabled="visitor" class="sd__fieldset">
            <StrategyDetailConfigPane
              :config="configForm"
              :loading-job="loadingJob"
              :display-runs="displayRuns"
              @patch-config="patchConfig"
            />
          </fieldset>
          <StrategyRecentPicks v-show="tab === 'picks'" :slug="strategy.slug" @count="(value) => (picksCount = value)" />
          <StrategyVersionList
            v-show="tab === 'versions'"
            :rows="versionHistory"
            :current-version="displayedStrategy?.version"
            :loading="loadingVersions"
            :can-manage="canManageVersions && !visitor"
            :acting="versionActing"
            @rollback="rollback"
            @remove="removeVersion"
          />
        </div>
      </template>

      <DialogFooter class="sd__foot">
        <Button access="read" variant="ghost" size="sm" @click="open = false">关闭</Button>
        <Button v-if="tab === 'config'" size="sm" :disabled="saving || !strategy" @click="save">
          <Spinner v-if="saving" class="animate-spin" aria-hidden="true" />
          保存调度
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.sd__hero {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 22px 56px 16px 24px;
  background:
    radial-gradient(110% 160% at 0% 0%, color-mix(in oklab, var(--seal) 10%, transparent), transparent 64%),
    var(--surface);
}

.sd__crumbs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.sd__crumbs > span + span::before {
  content: '·';
  margin-right: 10px;
  color: var(--text-disabled);
}

.sd__source {
  color: var(--seal-ink);
  font-weight: 600;
}

.sd__ver {
  font-family: var(--mono);
}

.sd__title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  min-width: 0;
}

.sd__title {
  margin: 0;
  color: var(--text-primary);
  font-size: 24px;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.sd__sched {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  color: var(--text-tertiary);
  font: 500 var(--fs-kicker) / 1 var(--mono);
}

.sd__sched i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--border-strong);
}

.sd__sched.is-on {
  border-color: var(--ok-border);
  background: var(--ok-soft);
  color: var(--text-primary);
}

.sd__sched.is-on i {
  background: var(--ok);
}

.sd__metrics {
  display: grid;
  flex-shrink: 0;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 0 24px;
}

.sd__metric {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  background: var(--surface-canvas);
  box-shadow: inset 0 0 0 1px var(--border-subtle);
}

.sd__metric dt {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.sd__metric dd {
  margin: 0;
  color: var(--text-primary);
  font: 650 20px / 1.1 var(--mono);
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.sd__metric dd.is-up { color: var(--up); }
.sd__metric dd.is-down { color: var(--down); }

.sd__tabs {
  flex-shrink: 0;
  margin: 12px 0 0;
  padding: 0 14px;
}

.sd__body {
  flex: 1 1 auto;
  min-height: 0;
  padding: 18px 24px 22px;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.sd__body:focus-visible {
  outline: none;
}

.sd__fieldset {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.sd__foot {
  display: flex;
  flex-direction: row;
  flex-shrink: 0;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 24px;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-canvas);
}

@media (max-width: 640px) {
  .sd__hero {
    padding: 16px 48px 12px 16px;
  }

  .sd__title {
    font-size: 20px;
  }

  .sd__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin: 0 16px;
  }


  .sd__tabs {
    padding: 0 6px;
  }

  .sd__body {
    padding: 14px 16px 18px;
  }

  .sd__foot {
    padding: 10px 16px calc(10px + env(safe-area-inset-bottom, 0));
  }
}
</style>
