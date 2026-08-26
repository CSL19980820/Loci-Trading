<script setup lang="ts">
import { computed, onActivated, onDeactivated, onUnmounted, ref } from 'vue'
import { Download, RefreshRight, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import type {
  ResearchBacktestJob,
  ResearchBacktestRun,
  ResearchBacktestPublicationResult,
  ResearchReplayResult,
  ResearchWorkflow,
} from '@/shared/types/quant-research'

import {
  getResearchBacktestRun,
  getResearchBacktestJob,
  getResearchWorkflow,
  listResearchBacktestRuns,
  replayResearchBacktestRun,
  researchArtifactUrl,
  submitResearchBacktestJob,
} from '@/shared/api/quant_research'

import ResearchPublicationDialog from './ResearchPublicationDialog.vue'
import ResearchRejectionDialog from './ResearchRejectionDialog.vue'
import {
  isExploratoryRun as isExploratoryRunFor,
  printable,
  provenanceEntries as provenanceEntriesFor,
  runEvidenceDescription as runEvidenceDescriptionFor,
  runEvidenceTitle as runEvidenceTitleFor,
  sourceEvidenceIssues as sourceEvidenceIssuesFor,
  sourceEvidenceRows as sourceEvidenceRowsFor,
  temporalMembership as temporalMembershipFor,
} from './researchBacktestEvidence'
import { validateResearchBacktestForm } from './researchBacktestForm'
import { summarizeReplayComparison } from './researchReplayComparison'

const runs = ref<ResearchBacktestRun[]>([])
const selectedRun = ref<ResearchBacktestRun | null>(null)
const workflow = ref<ResearchWorkflow | null>(null)
const loading = ref(false)
const submitting = ref(false)
const replaying = ref(false)
const error = ref('')
const activeJob = ref<ResearchBacktestJob | null>(null)
const pollingFailed = ref(false)
const replayResult = ref<ResearchReplayResult | null>(null)
const publishOpen = ref(false)
const rejectionOpen = ref(false)
const readSequence = ref(0)
let pollTimer: ReturnType<typeof setTimeout> | undefined
let pollSequence = 0
const range = ref<string[]>([])
const trainRange = ref<string[]>([])
const oosRange = ref<string[]>([])
const form = ref({
  strategy: '',
  holdDays: 3,
  initialCapital: 200000,
  maxPositions: 2,
  historicalUniverseId: '',
  strictPit: false,
})

const detailGroups = computed(() => {
  const run = selectedRun.value
  if (!run) return []
  return [
    ['回测指标', run.metrics],
    ['验证结果', run.validation],
    ['风险透视', run.risk_xray],
  ].map(([title, values]) => ({
    title: String(title),
    items: Object.entries((values || {}) as Record<string, unknown>).map(([key, value]) => ({
      key,
      value: printable(value),
    })),
  }))
})

const provenanceEntries = computed(() => provenanceEntriesFor(selectedRun.value))
const temporalMembership = computed(() => temporalMembershipFor(selectedRun.value))
const isExploratoryRun = computed(() => isExploratoryRunFor(selectedRun.value))
const runEvidenceTitle = computed(() => runEvidenceTitleFor(selectedRun.value))
const runEvidenceDescription = computed(() => runEvidenceDescriptionFor(selectedRun.value))
const sourceEvidenceRows = computed(() => sourceEvidenceRowsFor(selectedRun.value))
const sourceEvidenceIssues = computed(() => sourceEvidenceIssuesFor(selectedRun.value))

const workflowProblems = computed(() => Object.entries(workflow.value?.stages ?? {})
  .flatMap(([name, stage]) => {
    const reason = stage.error || stage.failure_code || stage.blocked_by.join('、')
    return reason ? [`${name}：${reason}`] : []
  }))

const replaySummary = computed(() => (
  replayResult.value ? summarizeReplayComparison(replayResult.value.comparison) : null
))

function statusType(status: string): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'completed') return 'success'
  if (status === 'stale' || status === 'awaiting_human_review') return 'warning'
  if (status === 'failed' || status === 'rejected') return 'danger'
  return 'info'
}

function statusLabel(status: string): string {
  return ({
    queued: '排队中', waiting: '等待中', running: '运行中', awaiting_human_review: '待人工签署', completed: '已完成', stale: '已过期', failed: '失败', rejected: '已拒绝',
  })[status] || status
}

function stageType(status: string): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'blocked') return 'danger'
  if (status === 'running' || status === 'waiting') return 'warning'
  return 'info'
}

function updateRun(next: ResearchBacktestRun): void {
  const index = runs.value.findIndex((item) => item.run_id === next.run_id)
  if (index < 0) runs.value = [next, ...runs.value]
  else runs.value.splice(index, 1, next)
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

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const response = await listResearchBacktestRuns()
    runs.value = response.items
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '读取研究回测失败'
  } finally {
    loading.value = false
  }
}

async function selectRun(runId: string): Promise<void> {
  const sequence = ++readSequence.value
  loading.value = true
  error.value = ''
  replayResult.value = null
  try {
    const [run, nextWorkflow] = await Promise.all([
      getResearchBacktestRun(runId),
      getResearchWorkflow(runId),
    ])
    if (sequence !== readSequence.value) return
    selectedRun.value = run
    workflow.value = nextWorkflow
    updateRun(run)
  } catch (caught: unknown) {
    if (sequence === readSequence.value) {
      error.value = caught instanceof Error ? caught.message : '读取研究回测详情失败'
    }
  } finally {
    if (sequence === readSequence.value) loading.value = false
  }
}

async function submit(): Promise<void> {
  const validationError = validateResearchBacktestForm({
    strategy: form.value.strategy,
    range: range.value,
    trainRange: trainRange.value,
    oosRange: oosRange.value,
    historicalUniverseId: form.value.historicalUniverseId,
    strictPit: form.value.strictPit,
  })
  if (validationError) {
    error.value = validationError
    return
  }
  const hasTrain = trainRange.value.length === 2
  const hasOos = oosRange.value.length === 2
  stopPolling()
  const sequence = pollSequence
  submitting.value = true
  error.value = ''
  activeJob.value = null
  pollingFailed.value = false
  try {
    const result = await submitResearchBacktestJob({
      strategy: form.value.strategy.trim(),
      start: range.value[0],
      end: range.value[1],
      backtest_config: { hold_days: form.value.holdDays },
      initial_capital: form.value.initialCapital,
      max_positions: form.value.maxPositions,
      split: hasTrain && hasOos ? {
        train_start: trainRange.value[0], train_end: trainRange.value[1],
        oos_start: oosRange.value[0], oos_end: oosRange.value[1],
      } : undefined,
      historical_universe_id: form.value.historicalUniverseId.trim() || undefined,
      strict_pit: form.value.strictPit,
    })
    if (sequence !== pollSequence) return
    activeJob.value = result.job
    ElMessage.success('研究回测任务已提交')
    void pollJob(result.job.id, sequence)
  } catch (caught: unknown) {
    if (sequence === pollSequence) {
      error.value = caught instanceof Error ? caught.message : '提交研究回测失败'
    }
  } finally {
    if (sequence === pollSequence) submitting.value = false
  }
}

async function pollJob(jobId: string, sequence: number): Promise<void> {
  try {
    const response = await getResearchBacktestJob(jobId)
    if (sequence !== pollSequence || activeJob.value?.id !== jobId) return
    pollingFailed.value = false
    activeJob.value = response.job
    if (response.job.status === 'completed' && response.job.run_id) {
      await load()
      if (sequence !== pollSequence || activeJob.value?.id !== jobId) return
      await selectRun(response.job.run_id)
      return
    }
    if (response.job.status === 'completed') {
      error.value = '任务已完成，但后端未返回 run id'
      return
    }
    if (response.job.status === 'failed') {
      error.value = response.job.error || '研究回测任务失败'
      return
    }
    schedulePoll(jobId, sequence)
  } catch (caught: unknown) {
    if (sequence === pollSequence && activeJob.value?.id === jobId) {
      error.value = caught instanceof Error ? caught.message : '读取研究回测任务状态失败'
      pollingFailed.value = true
    }
  }
}

async function replay(): Promise<void> {
  if (!selectedRun.value) return
  replaying.value = true
  error.value = ''
  try {
    const result = await replayResearchBacktestRun(selectedRun.value.run_id)
    selectedRun.value = result.run_card
    workflow.value = result.workflow
    updateRun(result.run_card)
    await selectRun(result.run_card.run_id)
    replayResult.value = result
    const summary = summarizeReplayComparison(result.comparison)
    if (summary.matches) ElMessage.success(summary.message)
    else ElMessage.warning(summary.message)
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '回放失败'
  } finally {
    replaying.value = false
  }
}

function applyPublication(result: ResearchBacktestPublicationResult): void {
  selectedRun.value = result.run_card
  workflow.value = result.workflow
  replayResult.value = null
  updateRun(result.run_card)
}

function setHistoricalUniverse(universeId: string): void {
  form.value.historicalUniverseId = universeId
}

defineExpose({ load, setHistoricalUniverse })

onDeactivated(stopPolling)
onActivated(() => {
  const status = activeJob.value?.status
  if (status && status !== 'completed' && status !== 'failed') retryPolling()
})
onUnmounted(stopPolling)
</script>

<template>
  <section class="backtest-panel" aria-label="可审计研究回测">
    <header class="section-head">
      <div>
        <span class="research-kicker">AUDITABLE BACKTEST</span>
        <h3>研究回测</h3>
        <p>异步提交后读取任务、run、工作流和 artifact；页面不自行推导指标。</p>
      </div>
      <el-button size="small" :icon="RefreshRight" :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-form class="backtest-form" label-position="top">
      <el-form-item label="策略 slug" required>
        <el-input v-model="form.strategy" placeholder="例如 sanyuan-tail-v1" />
      </el-form-item>
      <el-form-item label="回测区间" required>
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日"
          end-placeholder="结束日"
          unlink-panels
        />
      </el-form-item>
      <el-form-item label="训练区间" required class="range-pair">
        <el-date-picker v-model="trainRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="训练开始" end-placeholder="训练结束" unlink-panels />
      </el-form-item>
      <el-form-item label="OOS 区间（与训练成对）" required class="range-pair">
        <el-date-picker v-model="oosRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="OOS 开始" end-placeholder="OOS 结束" unlink-panels />
      </el-form-item>
      <el-form-item label="历史股票池标识（可选）" class="universe-id">
        <el-input v-model="form.historicalUniverseId" placeholder="historical_universe_id" />
      </el-form-item>
      <el-form-item label="持有日">
        <el-input-number v-model="form.holdDays" :min="1" :max="60" controls-position="right" />
      </el-form-item>
      <el-form-item label="初始资金">
        <el-input-number v-model="form.initialCapital" :min="1" :max="100000000" :step="10000" controls-position="right" />
      </el-form-item>
      <el-form-item label="最大持仓">
        <el-input-number v-model="form.maxPositions" :min="1" :max="100" controls-position="right" />
      </el-form-item>
      <el-form-item label="PIT 严格模式">
        <el-switch v-model="form.strictPit" />
      </el-form-item>
      <el-form-item class="form-action">
        <el-button type="primary" native-type="button" :icon="VideoPlay" :loading="submitting" @click="submit">提交回测</el-button>
      </el-form-item>
    </el-form>
    <el-alert
      v-if="form.strictPit"
      title="严格 PIT 模式：必须完整填写训练/OOS 区间和历史股票池标识；缺一项将拒绝提交。"
      description="提交后仍由后端逐日复核可见日、真实成员、行情来源回执和 OHLC 覆盖；任一证据缺失都会保留失败原因。"
      type="warning"
      show-icon
      :closable="false"
      class="panel-alert"
    />
    <el-alert
      v-else
      title="探索性 / 降级研究"
      description="未开启严格 PIT 时，后端会保留警告和证据缺口；结果不能作为严格证据、假设通过或生产默认的依据。"
      type="warning"
      show-icon
      :closable="false"
      class="panel-alert"
    />
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="panel-alert" />
    <section v-if="activeJob" class="job-state" aria-label="研究回测任务状态">
      <div class="job-head">
        <span>任务</span>
        <code>{{ activeJob.id }}</code>
        <el-tag size="small" effect="plain" :type="statusType(activeJob.status)">{{ statusLabel(activeJob.status) }}</el-tag>
      </div>
      <div class="job-meta"><span>run id</span><code>{{ activeJob.run_id || '等待后端生成' }}</code></div>
      <div v-if="pollingFailed" class="job-retry">
        <el-button type="warning" plain size="small" :icon="RefreshRight" @click="retryPolling">重试读取任务状态</el-button>
      </div>
    </section>

    <el-table v-if="runs.length" :data="runs" size="small" row-key="run_id" highlight-current-row>
      <el-table-column prop="run_id" label="run id" min-width="180" show-overflow-tooltip />
      <el-table-column prop="strategy_slug" label="策略" min-width="120" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><el-tag size="small" effect="plain" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="actual_as_of" label="截止日" width="116" />
      <el-table-column label="操作" width="82" fixed="right">
        <template #default="{ row }"><el-button text size="small" @click="selectRun(row.run_id)">查看</el-button></template>
      </el-table-column>
    </el-table>
    <el-empty
      v-else-if="!loading"
      description="还没有跑过研究回测。填好回测区间与训练 / OOS 区间后点「提交回测」"
      :image-size="48"
    />

    <template v-if="selectedRun">
      <div class="run-detail-head">
        <div><span>当前 run</span><code>{{ selectedRun.run_id }}</code></div>
        <div class="run-actions">
          <el-button
            v-if="selectedRun.status === 'awaiting_human_review'"
            type="primary"
            plain
            size="small"
            @click="publishOpen = true"
          >人工签署发布</el-button>
          <el-button
            v-if="selectedRun.status === 'awaiting_human_review'"
            type="danger"
            plain
            size="small"
            @click="rejectionOpen = true"
          >人工否决</el-button>
          <el-button text size="small" :icon="RefreshRight" :loading="replaying" @click="replay">重放并刷新</el-button>
        </div>
      </div>
      <el-alert
        v-if="selectedRun.error"
        :title="selectedRun.error"
        type="error"
        show-icon
        :closable="false"
        class="panel-alert"
      />
      <el-alert
        :title="runEvidenceTitle"
        :description="runEvidenceDescription"
        :type="isExploratoryRun ? 'warning' : 'info'"
        show-icon
        :closable="false"
        class="panel-alert"
      />
      <div class="workflow-strip" aria-label="研究工作流">
        <el-tag v-if="workflow" size="small" effect="plain" :type="statusType(workflow.status)">工作流 · {{ statusLabel(workflow.status) }}</el-tag>
        <el-tag v-for="(stage, name) in workflow?.stages || {}" :key="name" size="small" effect="plain" :type="stageType(stage.status)" :title="stage.error || stage.failure_code">
          {{ name }} · {{ stage.status }} · {{ stage.attempts }} 次
        </el-tag>
        <span v-if="!workflow" class="missing">工作流未提供</span>
      </div>
      <el-alert
        v-if="selectedRun.status === 'awaiting_human_review' || workflow?.status === 'awaiting_human_review'"
        title="待人工签署"
        description="当前研究尚未完成发布，不能作为已通过证据或生产默认。"
        type="warning"
        show-icon
        :closable="false"
        class="panel-alert"
      />
      <el-alert
        v-if="workflowProblems.length"
        title="研究工作流存在阻断或失败阶段"
        :description="workflowProblems.join('；')"
        type="error"
        show-icon
        :closable="false"
        class="panel-alert"
      />
      <section v-if="replayResult" class="replay-section" aria-label="回放比对回执">
        <h4>回放比对</h4>
        <el-tag size="small" effect="plain" :type="replaySummary?.matches ? 'success' : 'danger'">
          {{ replaySummary?.label || '回放结果未确认' }}
        </el-tag>
        <span v-if="replaySummary && !replaySummary.matches">不一致项：{{ replaySummary.mismatches.join('、') || '后端未提供细项' }}</span>
        <span>源冻结输入 <code :title="replayResult.comparison.source_manifest_sha256">{{ replayResult.comparison.source_manifest_sha256 || '未提供' }}</code></span>
        <span>回执 <code :title="replayResult.receipt.sha256">{{ replayResult.receipt.path || '未提供' }} · {{ replayResult.receipt.sha256 || '未提供' }}</code></span>
      </section>
      <div class="detail-grid">
        <section v-for="group in detailGroups" :key="group.title" class="fact-group">
          <h4>{{ group.title }}</h4>
          <el-descriptions v-if="group.items.length" :column="1" border size="small">
            <el-descriptions-item v-for="item in group.items" :key="item.key" :label="item.key">{{ item.value }}</el-descriptions-item>
          </el-descriptions>
          <span v-else class="missing">后端未提供</span>
        </section>
      </div>
      <section class="provenance-section">
        <div class="artifact-head"><h4>冻结输入与来源证据</h4><span>后端 run card 原始回执</span></div>
        <el-descriptions v-if="provenanceEntries.length" :column="1" border size="small">
          <el-descriptions-item v-for="entry in provenanceEntries" :key="entry.key" :label="entry.key"><code>{{ entry.value }}</code></el-descriptions-item>
        </el-descriptions>
        <el-alert
          v-if="!Object.keys(temporalMembership).length"
          title="后端未提供 temporal_membership 冻结快照"
          description="页面不能据此声明历史股票池或 PIT 证据已通过。"
          type="warning"
          show-icon
          :closable="false"
          class="evidence-alert"
        />
        <el-alert
          v-for="issue in sourceEvidenceIssues"
          :key="issue"
          :title="issue"
          type="error"
          show-icon
          :closable="false"
          class="evidence-alert"
        />
        <el-table v-if="sourceEvidenceRows.length" :data="sourceEvidenceRows" size="small">
          <el-table-column prop="kind" label="证据类型" width="96" />
          <el-table-column prop="sourceId" label="来源" width="140" show-overflow-tooltip />
          <el-table-column prop="state" label="状态" width="100" show-overflow-tooltip />
          <el-table-column label="链接" min-width="160" show-overflow-tooltip><template #default="{ row }"><el-link v-if="row.sourceUrl" :href="row.sourceUrl" target="_blank" rel="noopener noreferrer">{{ row.sourceUrl }}</el-link><span v-else class="missing">后端未提供链接</span></template></el-table-column>
          <el-table-column prop="detail" label="来源回执" min-width="240" show-overflow-tooltip />
        </el-table>
        <span v-else class="missing">后端未提供 source_evidence；该 run 不能作为已核验的来源证据。</span>
      </section>
      <section class="artifact-section">
        <div class="artifact-head"><h4>Artifact manifest</h4><code :title="selectedRun.artifact_manifest_sha256">{{ selectedRun.artifact_manifest_sha256 || '后端未提供摘要' }}</code></div>
        <el-table v-if="selectedRun.artifact_manifest.length" :data="selectedRun.artifact_manifest" size="small">
          <el-table-column prop="path" label="路径" min-width="180" show-overflow-tooltip />
          <el-table-column prop="artifact_type" label="类型" width="140" show-overflow-tooltip />
          <el-table-column label="SHA-256" min-width="150"><template #default="{ row }"><code :title="row.sha256">{{ row.sha256.slice(0, 16) }}...</code></template></el-table-column>
          <el-table-column label="下载" width="76" fixed="right"><template #default="{ row }"><el-link :href="researchArtifactUrl(selectedRun!.run_id, row.path)" :icon="Download" aria-label="下载 artifact" /></template></el-table-column>
        </el-table>
        <span v-else class="missing">后端未提供 artifact</span>
      </section>
    </template>
    <ResearchPublicationDialog
      v-model:visible="publishOpen"
      :run="selectedRun"
      @published="applyPublication"
    />
    <ResearchRejectionDialog
      v-model:visible="rejectionOpen"
      :run="selectedRun"
      @rejected="applyPublication"
    />
  </section>
</template>

<style scoped>
.backtest-panel { overflow: hidden; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); }
.section-head, .run-detail-head, .job-head { display: flex; align-items: flex-start; justify-content: space-between; gap: .75rem; padding: .82rem .9rem; border-bottom: 1px solid var(--rule); }
.research-kicker { display: block; color: var(--mist); font: .68rem/1.2 var(--mono); letter-spacing: .08em; }
.section-head h3, h4 { margin: .22rem 0 0; font-size: .98rem; letter-spacing: 0; }
.section-head p { margin: .28rem 0 0; color: var(--mist); font-size: .76rem; }
.backtest-form { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .4rem .65rem; align-items: end; padding: .72rem .9rem; border-bottom: 1px solid var(--rule); }
.backtest-form :deep(.el-form-item) { margin-bottom: 0; }
.backtest-form :deep(.el-date-editor) { width: 100%; }
.form-action { justify-content: flex-end; }
.range-pair { grid-column: span 2; }
.universe-id { grid-column: span 2; }
.panel-alert { margin: .65rem .9rem; }
.job-state { border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.job-head { align-items: center; justify-content: flex-start; }
.job-head code { margin-right: auto; }
.job-meta { display: flex; flex-wrap: wrap; gap: .4rem .7rem; padding: .58rem .9rem; color: var(--mist); font: .73rem/1.4 var(--mono); }
.job-retry { padding: 0 .9rem .58rem; }
.run-detail-head { align-items: center; margin-top: .65rem; border-top: 1px solid var(--rule); }
.run-detail-head div, .run-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem; color: var(--mist); font-size: .76rem; }
code { color: var(--ink); font-family: var(--mono); font-size: .72rem; overflow-wrap: anywhere; }
.workflow-strip { display: flex; flex-wrap: wrap; gap: .4rem; padding: .7rem .9rem; border-bottom: 1px solid var(--rule); }
.detail-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .65rem; padding: .75rem .9rem; }
.fact-group { min-width: 0; }
.fact-group h4, .artifact-section h4, .provenance-section h4 { margin: 0 0 .4rem; font-size: .82rem; }
.fact-group :deep(.el-descriptions__label) { width: 40%; font-size: .72rem; overflow-wrap: anywhere; }
.fact-group :deep(.el-descriptions__content) { font: .72rem/1.35 var(--mono); overflow-wrap: anywhere; }
.artifact-section, .provenance-section { padding: .7rem .9rem; border-top: 1px solid var(--rule); }
.evidence-alert { margin: .55rem 0; }
.artifact-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: .4rem .75rem; margin-bottom: .4rem; }
.artifact-head h4 { margin-bottom: 0; }
.replay-section { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem .7rem; padding: .7rem .9rem; border-top: 1px solid var(--rule); color: var(--mist); font-size: .75rem; }
.replay-section h4 { flex-basis: 100%; margin: 0; color: var(--ink); }
.replay-section code { max-width: 100%; }
.missing { color: var(--mist); font-size: .75rem; }
@media (max-width: 1180px) { .backtest-form { grid-template-columns: repeat(2, minmax(0, 1fr)); } .detail-grid { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .section-head, .run-detail-head { flex-direction: column; } .backtest-form { grid-template-columns: 1fr; } .range-pair, .universe-id { grid-column: auto; } }
</style>
