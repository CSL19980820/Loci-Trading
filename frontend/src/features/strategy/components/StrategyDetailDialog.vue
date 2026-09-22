<script setup lang="ts">
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import { toast } from 'vue-sonner'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as TabSet } from '@/shared/components/ui/app/TabSet.vue'
import { default as TabPage } from '@/shared/components/ui/app/TabPage.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import { computed, reactive, ref, watch } from 'vue'

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
import StrategyDetailBasicsPane from './StrategyDetailBasicsPane.vue'
import StrategyDetailConfigPane, { type StrategyDetailConfigForm } from './StrategyDetailConfigPane.vue'
import {
  BOARD_OPTIONS,
  buildPreview,
  type BoardId,
  type ScheduleMode,
  strategyParamRows,
} from './strategyDetailFormat'

type DetailTab = 'basics' | 'config'

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
const paramRows = computed(() => strategyParamRows(displayedStrategy.value))

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
  <DialogPanel
    v-model="open"
    :title="title"
    :width="dialogWidth()"
    destroy-on-close
    class="strategy-detail-dialog"
  >
    <template v-if="strategy">
      <TabSet v-model="tab" class="detail-tabs">
        <TabPage label="基础信息" name="basics">
          <StrategyDetailBasicsPane
            :strategy="displayedStrategy"
            :loading-versions="loadingVersions"
            :version-rows="versionHistory"
            :can-manage-versions="canManageVersions && !visitor"
            :version-acting="versionActing"
            @rollback="rollback"
            @remove-version="removeVersion"
          />
        </TabPage>
        <TabPage label="配置" name="config">
          <fieldset :disabled="visitor" class="detail-read-config">
          <StrategyDetailConfigPane
            :config="configForm"
            :param-rows="paramRows"
            :loading-job="loadingJob"
            :display-runs="displayRuns"
            @patch-config="patchConfig"
          />
          </fieldset>
        </TabPage>
      </TabSet>
    </template>
    <template #footer>
      <ActionButton tone="primary" :busy="saving" :disabled="!strategy" @click="save">
        保存
      </ActionButton>
    </template>
  </DialogPanel>
</template>

<style scoped>
.detail-tabs :deep(.tab-set__list) { margin-bottom: 0.75rem; }
.detail-read-config { min-width: 0; padding: 0; margin: 0; border: 0; }
.detail-tabs :deep(.tab-page) { padding-top: 0.25rem; }
</style>
