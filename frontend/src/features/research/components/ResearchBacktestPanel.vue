<script setup lang="ts">
/**
 * 可审计研究回测面板。
 *
 * 这里只剩「怎么摆」：指标 / 验证 / 风险三组事实、战法下拉的中文文案、冻结输入与
 * 来源证据、artifact manifest、回放比对回执。提交与轮询那套状态机（含两个防串序号
 * 与 KeepAlive 停表）在 useResearchBacktestJob，状态词表在 researchBacktestStatus。
 */
import { computed, ref } from 'vue'
import { DataLine, Download, RefreshRight, VideoPlay } from '@element-plus/icons-vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { researchArtifactUrl } from '@/shared/api/quant_research'
import { strategyLabel } from '@/shared/lib/format'

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
import { stageType, statusLabel, statusType } from './researchBacktestStatus'
import { summarizeReplayComparison } from './researchReplayComparison'
import { useResearchBacktestJob } from './useResearchBacktestJob'

/** 长口径说明不进页面：挂在「严格 PIT」开关的 tooltip 上。 */
const STRICT_PIT_HINT = '开启：训练 / OOS 区间与历史股票池标识必填，后端逐日复核可见日、成员、来源与 OHLC，缺证据即失败。关闭：结果仅供探索，不能作为证据、假设通过或生产默认。'

const {
  runs,
  strategies,
  selectedRun,
  workflow,
  loading,
  submitting,
  replaying,
  error,
  activeJob,
  pollingFailed,
  replayResult,
  range,
  trainRange,
  oosRange,
  form,
  load,
  selectRun,
  submit,
  replay,
  retryPolling,
  applyPublication,
  setHistoricalUniverse,
} = useResearchBacktestJob()

/** 人工签署 / 否决两个弹窗只是这屏的开合，不进状态机。 */
const publishOpen = ref(false)
const rejectionOpen = ref(false)

const detailGroups = computed(() => {
  const run = selectedRun.value
  if (!run) return []
  const groups = [
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
  const conclusion = run.conclusion as Record<string, unknown> | undefined
  const account = conclusion?.portfolio_summary as Record<string, unknown> | undefined
  if (account) {
    const number = (key: string, suffix = '') => {
      const value = account[key]
      return typeof value === 'number' && Number.isFinite(value)
        ? `${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}${suffix}`
        : '—'
    }
    groups.unshift({ title: '资金账户（每日收盘估值）', items: [
      { key: '初始资金', value: number('initial_capital', ' 元') },
      { key: '期末权益', value: number('final_equity', ' 元') },
      { key: '账户收益', value: number('return_pct', '%') },
      { key: '最大回撤', value: number('max_drawdown_pct', '%') },
      { key: '已平仓交易', value: number('closed_trades', ' 笔') },
      { key: '未平仓', value: number('open_positions', ' 笔') },
      { key: '已计费用', value: number('fees_paid', ' 元') },
    ] })
  }
  return groups
})

/**
 * 战法下拉：**界面上不摆英文 slug**。option 文案一律中文（后端 name 本身是
 * slug 形状时退回共享词表），value 仍是 slug——后端契约要的就是 slug。
 * allow-create 保留手填口子：目录里没有的新战法照样能提交。
 */
const strategyOptions = computed(() =>
  strategies.value.map((s) => {
    const name = String(s.name || '').trim()
    const slugShaped = /^[a-z0-9][a-z0-9._-]*$/.test(name)
    return { slug: s.slug, label: name && !slugShaped ? name : strategyLabel(s.slug) }
  }),
)

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

const runRows = computed(() => runs.value as unknown as Record<string, unknown>[])

const runColumns: BasicTableColumn[] = [
  { prop: 'run_id', label: 'run id', minWidth: 180, showOverflowTooltip: true },
  { prop: 'strategy_slug', label: '战法', minWidth: 120, showOverflowTooltip: true, formatter: (row) => strategyLabel(String(row.strategy_slug ?? '')) },
  { prop: 'status', label: '状态', width: 90, slotName: 'status' },
  { prop: 'actual_as_of', label: '截止日', width: 116 },
  { prop: 'run_id', label: '操作', width: 82, fixed: 'right', slotName: 'actions' },
]

const sourceEvidenceTableRows = computed(() => sourceEvidenceRows.value as unknown as Record<string, unknown>[])
const artifactRows = computed(() => (selectedRun.value?.artifact_manifest ?? []) as unknown as Record<string, unknown>[])

const sourceEvidenceColumns: BasicTableColumn[] = [
  { prop: 'kind', label: '证据类型', width: 96 },
  { prop: 'sourceId', label: '来源', width: 140, showOverflowTooltip: true },
  { prop: 'state', label: '状态', width: 100, showOverflowTooltip: true },
  { prop: 'sourceUrl', label: '链接', minWidth: 160, showOverflowTooltip: true, slotName: 'url' },
  { prop: 'detail', label: '来源回执', minWidth: 240, showOverflowTooltip: true },
]

const artifactColumns: BasicTableColumn[] = [
  { prop: 'path', label: '路径', minWidth: 180, showOverflowTooltip: true },
  { prop: 'artifact_type', label: '类型', width: 140, showOverflowTooltip: true },
  { prop: 'sha256', label: 'SHA-256', minWidth: 150, slotName: 'hash' },
  { prop: 'path', label: '下载', width: 76, fixed: 'right', slotName: 'download' },
]

defineExpose({ load, setHistoricalUniverse })
</script>

<template>
  <section class="backtest-panel research-surface" aria-label="可审计研究回测">
    <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行（用户原话：一行能显示的话两行） -->
    <header class="section-head">
      <h3><el-icon aria-hidden="true"><DataLine /></el-icon>研究回测</h3>
      <el-button size="small" :icon="RefreshRight" :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-form class="backtest-form" label-position="right" label-width="6.5em" size="small">
      <el-form-item label="战法" required>
        <el-select
          v-model="form.strategy"
          class="full"
          filterable
          allow-create
          default-first-option
          placeholder="选择战法"
        >
          <el-option
            v-for="s in strategyOptions"
            :key="s.slug"
            :label="s.label"
            :value="s.slug"
          />
        </el-select>
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
      <el-form-item label="回测区间" required class="form-wide">
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日"
          end-placeholder="结束日"
          unlink-panels
        />
      </el-form-item>
      <el-form-item label="训练区间" required class="form-wide">
        <el-date-picker v-model="trainRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="训练开始" end-placeholder="训练结束" unlink-panels />
      </el-form-item>
      <el-form-item label="OOS 区间" required class="form-wide">
        <el-date-picker v-model="oosRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="OOS 开始" end-placeholder="OOS 结束" unlink-panels />
      </el-form-item>
      <el-form-item label="历史股票池" class="form-wide">
        <el-input v-model="form.historicalUniverseId" placeholder="historical_universe_id" />
      </el-form-item>
      <el-form-item label="严格 PIT">
        <el-tooltip :content="STRICT_PIT_HINT" placement="top">
          <el-switch v-model="form.strictPit" aria-label="严格 PIT 模式" />
        </el-tooltip>
      </el-form-item>
      <el-form-item class="form-action" label-width="0">
        <el-button type="primary" native-type="button" :icon="VideoPlay" :loading="submitting" @click="submit">提交回测</el-button>
      </el-form-item>
    </el-form>
    <el-alert
      v-if="!form.strictPit"
      title="非严格 PIT：结果仅供探索"
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

    <BasicTable
      :columns="runColumns"
      :data-source="runRows"
      :pagination="false"
      :loading="loading"
      row-key="run_id"
      stripe
      empty-text="还没有跑过研究回测"
      empty-reason="填好区间后点「提交回测」"
    >
      <template #status="{ row }">
        <el-tag size="small" effect="plain" :type="statusType(String(row.status))">{{ statusLabel(String(row.status)) }}</el-tag>
      </template>
      <template #actions="{ row }">
        <el-button text size="small" @click="selectRun(String(row.run_id))">查看该轮</el-button>
      </template>
    </BasicTable>

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
      <el-tooltip v-if="isExploratoryRun" :content="runEvidenceDescription" placement="top">
        <el-alert
          :title="runEvidenceTitle"
          type="warning"
          show-icon
          :closable="false"
          class="panel-alert"
        />
      </el-tooltip>
      <div class="workflow-strip" aria-label="研究工作流">
        <el-tag v-if="workflow" size="small" effect="plain" :type="statusType(workflow.status)">工作流 · {{ statusLabel(workflow.status) }}</el-tag>
        <el-tag v-for="(stage, name) in workflow?.stages || {}" :key="name" size="small" effect="plain" :type="stageType(stage.status)" :title="stage.error || stage.failure_code">
          {{ name }} · {{ stage.status }} · {{ stage.attempts }} 次
        </el-tag>
        <span v-if="!workflow" class="missing">工作流未提供</span>
      </div>
      <el-alert
        v-if="selectedRun.status === 'awaiting_human_review' || workflow?.status === 'awaiting_human_review'"
        title="待人工签署，不能作为证据"
        type="warning"
        show-icon
        :closable="false"
        class="panel-alert"
      />
      <el-alert
        v-if="workflowProblems.length"
        :title="`工作流阻断：${workflowProblems.join('；')}`"
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
        <div class="artifact-head"><h4>冻结输入与来源证据</h4></div>
        <el-descriptions v-if="provenanceEntries.length" :column="1" border size="small">
          <el-descriptions-item v-for="entry in provenanceEntries" :key="entry.key" :label="entry.key"><code>{{ entry.value }}</code></el-descriptions-item>
        </el-descriptions>
        <el-alert
          v-if="!Object.keys(temporalMembership).length"
          title="缺 temporal_membership 冻结快照"
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
        <BasicTable
          :columns="sourceEvidenceColumns"
          :data-source="sourceEvidenceTableRows"
          :pagination="false"
          stripe
          empty-text="暂无来源证据"
        >
          <template #url="{ row }">
            <el-link v-if="row.sourceUrl" :href="String(row.sourceUrl)" target="_blank" rel="noopener noreferrer">{{ row.sourceUrl }}</el-link>
            <span v-else class="missing">后端未提供链接</span>
          </template>
        </BasicTable>
      </section>
      <section class="artifact-section">
        <div class="artifact-head"><h4>证据文件清单</h4><code :title="selectedRun.artifact_manifest_sha256">{{ selectedRun.artifact_manifest_sha256 || '后端未提供摘要' }}</code></div>
        <BasicTable
          :columns="artifactColumns"
          :data-source="artifactRows"
          :pagination="false"
          stripe
          empty-text="暂无证据文件"
        >
          <template #hash="{ row }">
            <code :title="String(row.sha256 || '')">{{ String(row.sha256 || '').slice(0, 16) }}...</code>
          </template>
          <template #download="{ row }">
            <el-link :href="researchArtifactUrl(selectedRun!.run_id, String(row.path))" :icon="Download" aria-label="下载 artifact" />
          </template>
        </BasicTable>
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
.section-head, .run-detail-head, .job-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--gap-3); padding: var(--pad-sheet); border-bottom: 1px solid var(--rule); }
.section-head h3, h4 { margin: 0; font-size: var(--fs-title); font-weight: 700; letter-spacing: .03em; }
/* 表单栅格挂在 el-form 自身：不插裸 div，label 宽仍由 EP 的 label-width 算 */
.backtest-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--gap-1) var(--gap-3); align-items: start; padding: var(--pad-sheet); border-bottom: 1px solid var(--rule); }
.backtest-form :deep(.el-form-item) { margin-bottom: 0; min-width: 0; }
.backtest-form :deep(.el-date-editor) { width: 100%; }
.form-action { justify-content: flex-end; }
/* 日期区间控件压到 200px 会折行：整行占满，控件本身再收到可读宽度 */
.form-wide { grid-column: 1 / -1; }
.form-wide :deep(.el-form-item__content) { max-width: 28rem; }
.panel-alert { margin: var(--gap-2) var(--pad-sheet-x); }
.job-state { border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.job-head { align-items: center; justify-content: flex-start; }
.job-head code { margin-right: auto; }
.job-meta { display: flex; flex-wrap: wrap; gap: var(--gap-1) var(--gap-2); padding: var(--gap-2) var(--pad-sheet-x); color: var(--mist); font: var(--fs-aux)/1.4 var(--mono); }
.job-retry { padding: 0 var(--pad-sheet-x) var(--gap-2); }
.run-detail-head { align-items: center; margin-top: var(--gap-2); border-top: 1px solid var(--rule); }
.run-detail-head div, .run-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-1); color: var(--mist); font-size: var(--fs-aux); }
code { color: var(--ink); font-family: var(--mono); font-size: var(--fs-aux); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.workflow-strip { display: flex; flex-wrap: wrap; gap: var(--gap-1); padding: var(--pad-sheet); border-bottom: 1px solid var(--rule); }
.detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--gap-2); padding: var(--pad-sheet); }
.fact-group { min-width: 0; }
.fact-group h4, .artifact-section h4, .provenance-section h4 { margin: 0 0 var(--gap-1); font-size: var(--fs-body); }
.fact-group :deep(.el-descriptions__label) { width: 40%; font-size: var(--fs-aux); overflow-wrap: anywhere; }
.fact-group :deep(.el-descriptions__content) { font: var(--fs-aux)/1.35 var(--mono); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.artifact-section, .provenance-section { padding: var(--pad-sheet); border-top: 1px solid var(--rule); }
.evidence-alert { margin: var(--gap-2) 0; }
.artifact-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: var(--gap-1) var(--gap-3); margin-bottom: var(--gap-1); }
.artifact-head h4 { margin-bottom: 0; }
.replay-section { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-1) var(--gap-2); padding: var(--pad-sheet); border-top: 1px solid var(--rule); color: var(--mist); font-size: var(--fs-aux); }
.replay-section h4 { flex-basis: 100%; margin: 0; color: var(--ink); }
.replay-section code { max-width: 100%; }
.missing { color: var(--mist); font-size: var(--fs-aux); }
@media (max-width: 700px) {
  .section-head, .run-detail-head { flex-direction: column; }
  .form-wide :deep(.el-form-item__content) { max-width: none; }
}
</style>
<style scoped src="./ResearchSurfaces.css"></style>
