<script setup lang="ts">
import { ChartNoAxesCombined as DataAnalysis, Download, RefreshCw as RefreshRight, Play as VideoPlay } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { IconBox, StatusBadge, Notice, DetailList, DetailItem, ActionLink } from '@/shared/components/ui/app/presentation'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { default as DateField } from '@/shared/components/ui/app/DateField.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

import { computed, onActivated, onDeactivated, onUnmounted, ref } from 'vue'



import {
  getResearchBacktestRun,
  getResearchFactorJob,
  researchArtifactUrl,
  submitPth252FactorJob,
} from '@/shared/api/quant_research'
import type {
  CreatePth252FactorJobPayload,
  Pth252FactorSplit,
  ResearchBacktestJob,
  ResearchBacktestRun,
} from '@/shared/types/quant-research'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import UiField from '@/shared/components/ui/UiField.vue'

type FactorForm = {
  range: [string, string]
  split: Pth252FactorSplit
  historicalUniverseId: string
}

type DetailGroup = {
  title: string
  items: Array<{ key: string; value: string }>
}

const form = ref<FactorForm>({
  range: ['2018-01-02', '2026-07-07'],
  split: {
    train_start: '2018-01-02',
    train_end: '2018-12-28',
    oos_start: '2019-01-02',
    oos_end: '2026-07-07',
  },
  historicalUniverseId: '',
})
const submitting = ref(false)
const loadingRun = ref(false)
const error = ref('')
const activeJob = ref<ResearchBacktestJob | null>(null)
const pollingFailed = ref(false)
const completedRun = ref<ResearchBacktestRun | null>(null)
let pollTimer: ReturnType<typeof setTimeout> | undefined
let pollSequence = 0

const runDetails = computed<DetailGroup[]>(() => {
  const run = completedRun.value
  if (!run) return []
  return [
    ['核心指标', run.metrics],
    ['验证结果', run.validation],
  ].map(([title, values]) => ({
    title: String(title),
    items: Object.entries((values || {}) as Record<string, unknown>).map(([key, value]) => ({
      key,
      value: printable(value),
    })),
  }))
})

function printable(value: unknown): string {
  if (value === null || value === undefined || value === '') return '后端未提供'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function statusLabel(status: ResearchBacktestJob['status']): string {
  return ({ queued: '排队中', running: '运行中', completed: '已完成', failed: '失败' })[status] || status
}

function statusType(status: ResearchBacktestJob['status']): 'success' | 'info' | 'warning' | 'danger' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function validateForm(): string {
  const [start, end] = form.value.range
  const split = form.value.split
  if (!start || !end || !split.train_start || !split.train_end || !split.oos_start || !split.oos_end) {
    return '请完整填写样本区间和 train / OOS 四个日期'
  }
  if (!form.value.historicalUniverseId.trim()) return '严格 PIT 必须填写已导入的历史股票池标识'
  if (start > end) return '样本结束日不能早于开始日'
  if (split.train_start < start || split.oos_end > end) {
    return 'train / OOS 必须位于样本总区间内'
  }
  if (split.train_start > split.train_end) return 'train 结束日不能早于 train 开始日'
  if (split.oos_start > split.oos_end) return 'OOS 结束日不能早于 OOS 开始日'
  if (split.train_end >= split.oos_start) return 'OOS 必须严格晚于 train，不能重叠或倒序'
  return ''
}

function requestPayload(): CreatePth252FactorJobPayload {
  const [start, end] = form.value.range
  return {
    factor_id: 'pth252',
    start,
    end,
    split: { ...form.value.split },
    top_quantile: 0.9,
    rebalance_every: 20,
    backtest_config: {
      hold_days: 20,
      stop_loss_pct: null,
      take_profit_pct: null,
      commission_bps: 3,
      stamp_duty_bps: 10,
      slippage_bps: 5,
      allow_limit_up_entry: false,
      benchmark: '000300',
    },
    initial_capital: 200000,
    max_positions: 20,
    strict_pit: true,
    historical_universe_id: form.value.historicalUniverseId.trim(),
  }
}

function stopPolling(): void {
  pollSequence += 1
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = undefined
}

function schedulePoll(jobId: string, sequence: number): void {
  pollTimer = setTimeout(() => {
    void pollJob(jobId, sequence)
  }, 1500)
}

function retryPolling(): void {
  const jobId = activeJob.value?.id
  if (!jobId) return
  stopPolling()
  const sequence = pollSequence
  error.value = ''
  pollingFailed.value = false
  void pollJob(jobId, sequence)
}

async function loadCompletedRun(job: ResearchBacktestJob, sequence: number): Promise<void> {
  const runId = String(job.run_id || '').trim()
  if (!runId) {
    error.value = '任务已完成，但后端未返回 run id'
    return
  }
  loadingRun.value = true
  try {
    const run = await getResearchBacktestRun(runId)
    if (sequence !== pollSequence || activeJob.value?.id !== job.id) return
    completedRun.value = run
  } catch (caught: unknown) {
    if (sequence === pollSequence && activeJob.value?.id === job.id) {
      error.value = caught instanceof Error ? caught.message : '读取 PTH252 运行结果失败'
    }
  } finally {
    if (sequence === pollSequence && activeJob.value?.id === job.id) loadingRun.value = false
  }
}

async function pollJob(jobId: string, sequence: number): Promise<void> {
  try {
    const response = await getResearchFactorJob(jobId)
    if (sequence !== pollSequence || activeJob.value?.id !== jobId) return
    pollingFailed.value = false
    activeJob.value = response.job
    if (response.job.status === 'completed') {
      await loadCompletedRun(response.job, sequence)
      return
    }
    if (response.job.status === 'failed') {
      error.value = response.job.error || 'PTH252 因子实验失败'
      if (response.job.run_id) await loadCompletedRun(response.job, sequence)
      return
    }
    schedulePoll(jobId, sequence)
  } catch (caught: unknown) {
    if (sequence === pollSequence && activeJob.value?.id === jobId) {
      error.value = caught instanceof Error ? caught.message : '读取 PTH252 任务状态失败'
      pollingFailed.value = true
    }
  }
}

async function submit(): Promise<void> {
  const validationError = validateForm()
  if (validationError) {
    error.value = validationError
    return
  }

  stopPolling()
  const sequence = pollSequence
  submitting.value = true
  error.value = ''
  activeJob.value = null
  pollingFailed.value = false
  completedRun.value = null
  try {
    const result = await submitPth252FactorJob(requestPayload())
    if (sequence !== pollSequence) return
    activeJob.value = result.job
    toast.success('PTH252 因子实验已提交')
    void pollJob(result.job.id, sequence)
  } catch (caught: unknown) {
    if (sequence === pollSequence) {
      error.value = caught instanceof Error ? caught.message : 'PTH252 因子实验提交被拒绝'
    }
  } finally {
    if (sequence === pollSequence) submitting.value = false
  }
}

onDeactivated(stopPolling)
onActivated(() => {
  const status = activeJob.value?.status
  if (status && status !== 'completed' && status !== 'failed') retryPolling()
})
onUnmounted(stopPolling)
const artifactRows = computed(() => (completedRun.value?.artifact_manifest ?? []) as unknown as Record<string, unknown>[])

const artifactColumns: BasicTableColumn[] = [
  { prop: 'path', label: '路径', minWidth: 180, showOverflowTooltip: true },
  { prop: 'artifact_type', label: '类型', width: 130, showOverflowTooltip: true },
  { prop: 'path', label: '下载', width: 76, fixed: 'right', slotName: 'download' },
]

</script>

<template>
  <section class="factor-panel research-surface" aria-labelledby="pth252-title">
    <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行（用户原话：一行能显示的话两行） -->
    <header class="section-head">
      <h3 id="pth252-title"><IconBox aria-hidden="true"><DataAnalysis /></IconBox>PTH252</h3>
      <HintTooltip content="研究候选，不改变生产策略。Top 10% 只保留可成交标的；数据缺失或不可成交的位置留空，不以弱票替补。" placement="top">
        <StatusBadge tone="info" effect="plain">仅研究</StatusBadge>
      </HintTooltip>
    </header>

    <div class="factor-form">
      <UiField class="form-wide" label="样本区间">
        <DateField
          v-model="form.range"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日"
          end-placeholder="结束日"
        />
      </UiField>
      <UiField label="train 开始">
        <DateField v-model="form.split.train_start" type="date" value-format="YYYY-MM-DD" />
      </UiField>
      <UiField label="train 结束">
        <DateField v-model="form.split.train_end" type="date" value-format="YYYY-MM-DD" />
      </UiField>
      <UiField label="OOS 开始">
        <DateField v-model="form.split.oos_start" type="date" value-format="YYYY-MM-DD" />
      </UiField>
      <UiField label="OOS 结束">
        <DateField v-model="form.split.oos_end" type="date" value-format="YYYY-MM-DD" />
      </UiField>
      <UiField label="历史股票池">
        <TextField v-model="form.historicalUniverseId" placeholder="例如 a-share-pit-v1" clearable />
      </UiField>
      <div class="flex items-end">
        <ActionButton tone="primary" :icon="VideoPlay" :busy="submitting" @click="submit">提交实验</ActionButton>
      </div>
    </div>

    <div class="fixed-config" aria-label="固定实验配置">
      <span>Top quantile 0.9</span>
      <span>每 20 日调仓</span>
      <span>持有 20 日</span>
      <span>20 席位 / 20 万</span>
      <span>严格 PIT</span>
      <span>沪深 300</span>
    </div>

    <Notice
      v-if="error"
      :title="error"
      tone="error"
      show-icon
      :closable="false"
      class="panel-alert"
    />

    <section v-if="activeJob" class="job-state" aria-label="PTH252 任务状态">
      <div class="job-head">
        <span>任务</span>
        <code>{{ activeJob.id }}</code>
        <StatusBadge :tone="statusType(activeJob.status)" effect="plain">{{ statusLabel(activeJob.status) }}</StatusBadge>
      </div>
      <div class="job-meta">
        <span>run id</span>
        <code>{{ activeJob.run_id || '等待后端生成' }}</code>
        <span v-if="loadingRun">正在读取运行结果…</span>
      </div>
      <Notice
        v-if="activeJob.error"
        :title="activeJob.error"
        tone="error"
        show-icon
        :closable="false"
        class="job-error"
      />
      <div v-if="pollingFailed" class="job-retry">
        <ActionButton access="read" tone="warning" plain size="small" :icon="RefreshRight" @click="retryPolling">重试读取任务状态</ActionButton>
      </div>
    </section>

    <template v-if="completedRun">
      <div class="run-head">
        <span>实验 run</span>
        <code>{{ completedRun.run_id }}</code>
        <StatusBadge :tone="statusType(completedRun.status === 'failed' ? 'failed' : 'completed')" effect="plain">
          {{ completedRun.status }}
        </StatusBadge>
      </div>
      <div class="detail-grid">
        <section v-for="group in runDetails" :key="group.title" class="detail-group">
          <h4>{{ group.title }}</h4>
          <DetailList v-if="group.items.length" :column="1" border size="small">
            <DetailItem v-for="item in group.items" :key="item.key" :label="item.key">
              {{ item.value }}
            </DetailItem>
          </DetailList>
          <span v-else class="missing">后端未提供</span>
        </section>
      </div>
      <section class="artifact-section">
        <h4>实验文件</h4>
        <BasicTable
          :columns="artifactColumns"
          :data-source="artifactRows"
          :pagination="false"
          stripe
          empty-text="后端未提供 artifact"
        >
          <template #download="{ row }">
            <ActionLink
              :href="researchArtifactUrl(completedRun!.run_id, String(row.path))"
              :icon="Download"
              :aria-label="`下载 artifact ${row.path}`"
            />
          </template>
        </BasicTable>
      </section>
    </template>
  </section>
</template>

<style scoped>
.factor-panel { overflow: hidden; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); }
.section-head, .job-head, .run-head { display: flex; align-items: center; justify-content: space-between; gap: var(--gap-3); padding: var(--pad-sheet); border-bottom: 1px solid var(--rule); }
.section-head h3, h4 { margin: 0; font-size: var(--fs-title); font-weight: 700; letter-spacing: .03em; }
.factor-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--gap-1) var(--gap-3); align-items: start; padding: var(--pad-sheet); }
.factor-form :deep(.form-field) { margin-bottom: 0; min-width: 0; }
.factor-form :deep(.date-field) { width: 100%; }
.form-action { justify-content: flex-end; }
/* 区间控件压到 200px 会折行：整行占满，控件本身再收到可读宽度 */
.form-wide { grid-column: 1 / -1; }
.form-wide :deep(.form-field__content) { max-width: 28rem; }
.fixed-config, .job-meta { display: flex; flex-wrap: wrap; gap: var(--gap-1) var(--gap-2); padding: var(--gap-2) var(--pad-sheet-x); color: var(--mist); font: var(--fs-aux)/1.4 var(--mono); }
.fixed-config span + span::before { content: '·'; margin-right: var(--gap-2); color: var(--rule); }
.panel-alert { margin: var(--gap-2) var(--pad-sheet-x); }
.job-state { border-top: 1px solid var(--rule); }
.job-head { justify-content: flex-start; }
.job-head code { margin-right: auto; }
.job-meta { padding-top: 0; }
.job-meta span:last-child { color: var(--ink); }
.job-error { margin: 0 var(--pad-sheet-x) var(--gap-2); }
.job-retry { padding: 0 var(--pad-sheet-x) var(--gap-2); }
.run-head { justify-content: flex-start; border-top: 1px solid var(--rule); }
.run-head code { margin-right: auto; }
code { color: var(--ink); font-family: var(--mono); font-size: var(--fs-aux); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--gap-2); padding: var(--pad-sheet); }
.detail-group { min-width: 0; }
.detail-group h4, .artifact-section h4 { margin: 0 0 var(--gap-1); font-size: var(--fs-body); }
.detail-group :deep(.detail-item__label) { width: 40%; font-size: var(--fs-aux); overflow-wrap: anywhere; }
.detail-group :deep(.detail-item__content) { font: var(--fs-aux)/1.35 var(--mono); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.artifact-section { padding: var(--pad-sheet); border-top: 1px solid var(--rule); }
.missing { color: var(--mist); font-size: var(--fs-aux); }
@media (max-width: 700px) {
  .section-head { align-items: flex-start; flex-direction: column; }
  .form-wide :deep(.form-field__content) { max-width: none; }
}
</style>
<style scoped src="./ResearchSurfaces.css"></style>
