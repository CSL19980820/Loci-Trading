<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Plus, RefreshRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  createResearchHypothesis,
  listResearchHypotheses,
  reviewResearchHypothesis,
  transitionResearchHypothesis,
} from '@/shared/api/quant'
import type {
  ResearchEvidenceLink,
  ResearchHypothesis,
  ResearchHypothesisStatus,
} from '@/shared/types/quant'

import EmptyState from '@/shared/components/ui/EmptyState.vue'

const hypotheses = ref<ResearchHypothesis[]>([])
const selectedId = ref('')
const loading = ref(false)
const creating = ref(false)
const transitioning = ref(false)
const error = ref('')
const reviewOpen = ref(false)
const reviewDecision = ref<'validated' | 'rejected'>('validated')
const createForm = ref({
  hypothesisId: '',
  title: '',
  thesis: '',
  strategyRevision: '',
  metricName: '',
  metricOperator: '>=' as '>=' | '>' | '<=' | '<' | '==',
  metricThreshold: 0,
  failureConditions: '',
  actor: '',
})
const reviewForm = ref({ actor: '', reason: '', runId: '', artifactSha: '', summary: '', metricsJson: '', asOf: '' })

const selected = computed(() => hypotheses.value.find((item) => item.hypothesis_id === selectedId.value) || null)
const canStartTesting = computed(() => selected.value?.status === 'exploring')
const canMonitor = computed(() => selected.value?.status === 'validated')

function statusType(status: ResearchHypothesisStatus): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'validated') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'testing' || status === 'monitoring') return 'warning'
  return 'info'
}

function update(item: ResearchHypothesis): void {
  const index = hypotheses.value.findIndex((entry) => entry.hypothesis_id === item.hypothesis_id)
  if (index < 0) hypotheses.value = [item, ...hypotheses.value]
  else hypotheses.value.splice(index, 1, item)
  selectedId.value = item.hypothesis_id
}

function evidenceFromForm(required: boolean): ResearchEvidenceLink[] | null {
  const hasAny = Object.values(reviewForm.value).some((value) => value.trim())
  if (!hasAny && !required) return []
  if (!reviewForm.value.runId.trim() || !reviewForm.value.artifactSha.trim() || !reviewForm.value.summary.trim()) {
    error.value = '关联证据要填批次编号、证据文件指纹和摘要'
    return null
  }
  let observedMetrics: Record<string, number> = {}
  if (reviewForm.value.metricsJson.trim()) {
    try {
      const parsed = JSON.parse(reviewForm.value.metricsJson) as unknown
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
      observedMetrics = Object.fromEntries(Object.entries(parsed).map(([key, value]) => [key, Number(value)]))
      if (Object.values(observedMetrics).some((value) => !Number.isFinite(value))) throw new Error()
    } catch {
      error.value = '观测指标必须是数值 JSON 对象，例如 {"profit_factor": 1.2}'
      return null
    }
  }
  return [{
    run_id: reviewForm.value.runId.trim(),
    artifact_sha256: reviewForm.value.artifactSha.trim(),
    summary: reviewForm.value.summary.trim(),
    observed_metrics: observedMetrics,
    as_of: reviewForm.value.asOf.trim(),
  }]
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const response = await listResearchHypotheses()
    hypotheses.value = response.items
    if (!selectedId.value && response.items[0]) selectedId.value = response.items[0].hypothesis_id
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '读取假设失败'
  } finally {
    loading.value = false
  }
}

async function create(): Promise<void> {
  const form = createForm.value
  if (![form.hypothesisId, form.title, form.thesis, form.strategyRevision, form.metricName, form.failureConditions, form.actor].every((value) => value.trim())) {
    error.value = '请补全假设、策略版本、指标、失败条件和操作者'
    return
  }
  creating.value = true
  error.value = ''
  try {
    const result = await createResearchHypothesis({
      hypothesis_id: form.hypothesisId.trim(),
      title: form.title.trim(),
      thesis: form.thesis.trim(),
      strategy_revision: form.strategyRevision.trim(),
      metrics: [{ name: form.metricName.trim(), operator: form.metricOperator, threshold: form.metricThreshold }],
      failure_conditions: form.failureConditions.split('\n').map((item) => item.trim()).filter(Boolean),
      actor: form.actor.trim(),
    })
    update(result.hypothesis)
    ElMessage.success('假设已创建')
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '创建假设失败'
  } finally {
    creating.value = false
  }
}

async function transition(target: 'testing' | 'monitoring'): Promise<void> {
  if (!selected.value) return
  const actor = createForm.value.actor.trim()
  if (!actor) {
    error.value = '请在创建表单填写操作者后再执行状态迁移'
    return
  }
  transitioning.value = true
  error.value = ''
  try {
    const result = await transitionResearchHypothesis(selected.value.hypothesis_id, {
      target,
      actor,
      reason: target === 'testing' ? '开始测试' : '进入持续监控',
      evidence: [],
      expected_revision: selected.value.revision,
    })
    update(result.hypothesis)
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '状态迁移失败，请刷新后重试'
  } finally {
    transitioning.value = false
  }
}

async function review(): Promise<void> {
  if (!selected.value || !reviewForm.value.actor.trim() || !reviewForm.value.reason.trim()) {
    error.value = '人工审核需填写操作者和审核理由'
    return
  }
  const evidence = evidenceFromForm(reviewDecision.value === 'validated')
  if (!evidence) return
  transitioning.value = true
  error.value = ''
  try {
    const result = await reviewResearchHypothesis(selected.value.hypothesis_id, {
      decision: reviewDecision.value,
      actor: reviewForm.value.actor.trim(),
      reason: reviewForm.value.reason.trim(),
      evidence,
      expected_revision: selected.value.revision,
    })
    update(result.hypothesis)
    reviewOpen.value = false
    ElMessage.success('人工审核已记录')
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '人工审核失败，请刷新假设后重试'
  } finally {
    transitioning.value = false
  }
}

defineExpose({ load })
</script>

<template>
  <section class="hypothesis-panel" aria-label="研究假设与人工审核">
    <header class="section-head">
      <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行（用户原话：一行能显示的话两行） -->
      <h3>假设与人工审核</h3>
      <el-button size="small" :icon="RefreshRight" :loading="loading" @click="load">刷新</el-button>
    </header>
    <el-form
      class="hypothesis-form"
      label-position="right"
      label-width="6.5em"
      size="small"
      @submit.prevent="create"
    >
      <el-form-item label="假设 ID" required>
        <el-input v-model="createForm.hypothesisId" placeholder="仅英文、数字、- 或 _" />
      </el-form-item>
      <el-form-item label="标题" required>
        <el-input v-model="createForm.title" />
      </el-form-item>
      <el-form-item label="策略版本" required>
        <el-input v-model="createForm.strategyRevision" />
      </el-form-item>
      <el-form-item label="指标名" required>
        <el-input v-model="createForm.metricName" placeholder="后端实际指标名" />
      </el-form-item>
      <el-form-item label="阈值" required class="metric-threshold">
        <el-select v-model="createForm.metricOperator" class="metric-threshold__op" aria-label="比较符">
          <el-option v-for="operator in ['>=', '>', '<=', '<', '==']" :key="operator" :value="operator" />
        </el-select>
        <el-input-number v-model="createForm.metricThreshold" controls-position="right" class="metric-threshold__value" />
      </el-form-item>
      <el-form-item label="操作者" required>
        <el-input v-model="createForm.actor" />
      </el-form-item>
      <el-form-item label="论断" required class="form-wide">
        <el-input v-model="createForm.thesis" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="失败条件" required class="form-wide">
        <el-input v-model="createForm.failureConditions" type="textarea" :rows="2" placeholder="每行一项" />
      </el-form-item>
      <el-form-item class="form-action" label-width="0">
        <el-button type="primary" native-type="submit" :icon="Plus" :loading="creating">创建假设</el-button>
      </el-form-item>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" class="panel-alert" />
    <el-table v-if="hypotheses.length" :data="hypotheses" size="small" row-key="hypothesis_id" highlight-current-row @row-click="selectedId = $event.hypothesis_id">
      <el-table-column prop="hypothesis_id" label="ID" min-width="120" show-overflow-tooltip />
      <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
      <el-table-column label="状态" width="94"><template #default="{ row }"><el-tag size="small" effect="plain" :type="statusType(row.status)">{{ row.status }}</el-tag></template></el-table-column>
      <el-table-column prop="revision" label="修订" width="68" />
      <el-table-column label="审核" width="76" fixed="right"><template #default="{ row }"><el-button text size="small" @click.stop="selectedId = row.hypothesis_id; reviewOpen = true">审核</el-button></template></el-table-column>
    </el-table>
    <EmptyState v-else-if="!loading" description="还没有假设" reason="先写清验证目标与通过门槛" />
    <section v-if="selected" class="hypothesis-detail">
      <div class="detail-head">
        <div><strong>{{ selected.title }}</strong><code>{{ selected.hypothesis_id }} · r{{ selected.revision }}</code></div>
        <div>
          <el-button v-if="canStartTesting" text size="small" :loading="transitioning" @click="transition('testing')">开始测试</el-button>
          <el-button v-if="canMonitor" text size="small" :loading="transitioning" @click="transition('monitoring')">进入监控</el-button>
          <el-button text size="small" :icon="Check" @click="reviewOpen = true">人工审核</el-button>
        </div>
      </div>
      <p class="thesis">{{ selected.thesis }}</p>
      <div class="detail-grid">
        <div>
          <span>预注册指标</span>
          <el-tag v-for="metric in selected.metrics" :key="metric.name" size="small" effect="plain">{{ metric.name }} {{ metric.operator }} {{ metric.threshold }}</el-tag>
          <span v-if="!selected.metrics.length" class="missing">未提供</span>
        </div>
        <div>
          <span>失败条件</span>
          <el-tag v-for="item in selected.failure_conditions" :key="item" size="small" effect="plain" type="warning">{{ item }}</el-tag>
          <span v-if="!selected.failure_conditions.length" class="missing">未提供</span>
        </div>
      </div>
      <div class="evidence-list">
        <span>关联证据</span>
        <el-table v-if="selected.evidence_links.length" :data="selected.evidence_links" size="small">
          <el-table-column prop="run_id" label="批次" min-width="120" />
          <el-table-column prop="summary" label="摘要" min-width="160" show-overflow-tooltip />
          <el-table-column label="证据指纹" min-width="150"><template #default="{ row }"><code :title="row.artifact_sha256">{{ row.artifact_sha256.slice(0, 16) }}...</code></template></el-table-column>
        </el-table>
        <EmptyState v-else description="还没有挂上证据" reason="点「人工审核」补一条" />
      </div>
    </section>
    <el-dialog v-model="reviewOpen" title="人工审核" width="min(92vw, 640px)" :close-on-click-modal="false">
      <el-alert
        v-if="reviewDecision === 'validated'"
        type="info"
        :closable="false"
        title="通过需附证据指纹与真实观测值"
        show-icon
        class="panel-alert panel-alert--flush"
      />
      <el-form class="review-form" label-position="right" label-width="6.5em" size="small">
        <el-form-item label="决定">
          <el-radio-group v-model="reviewDecision">
            <el-radio-button value="validated">通过</el-radio-button>
            <el-radio-button value="rejected">否决</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="操作者" required><el-input v-model="reviewForm.actor" /></el-form-item>
        <el-form-item label="审核理由" required><el-input v-model="reviewForm.reason" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="证据批次"><el-input v-model="reviewForm.runId" /></el-form-item>
        <el-form-item label="证据指纹"><el-input v-model="reviewForm.artifactSha" /></el-form-item>
        <el-form-item label="证据摘要"><el-input v-model="reviewForm.summary" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="观测指标">
          <el-tooltip content="数值 JSON 对象；缺项留空，不要估算" placement="top">
            <el-input v-model="reviewForm.metricsJson" type="textarea" :rows="2" placeholder='{"profit_factor": 1.2}' />
          </el-tooltip>
        </el-form-item>
        <el-form-item label="截止日"><el-date-picker v-model="reviewForm.asOf" value-format="YYYY-MM-DD" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviewOpen = false">取消</el-button>
        <el-button type="primary" :loading="transitioning" @click="review">记录审核</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.hypothesis-panel { overflow: hidden; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); }
.section-head, .detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--gap-3); padding: var(--pad-sheet); border-bottom: 1px solid var(--rule); }
.section-head h3 { margin: 0; font-size: var(--fs-title); font-weight: 700; letter-spacing: .03em; }

/* 表单栅格挂在 el-form 自身：不插裸 div，label 宽仍由 EP 的 label-width 算 */
.hypothesis-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--gap-1) var(--gap-3);
  align-items: start;
  padding: var(--pad-sheet);
  border-bottom: 1px solid var(--rule);
}
.hypothesis-form :deep(.el-form-item) { margin-bottom: 0; min-width: 0; }
.form-wide { grid-column: 1 / -1; }
.form-action { justify-content: flex-end; }
.metric-threshold :deep(.el-form-item__content) { flex-wrap: nowrap; gap: var(--gap-1); }
.metric-threshold__op { width: 4.6rem; flex: 0 0 auto; }
.metric-threshold__value { min-width: 0; flex: 1 1 auto; }
.panel-alert { margin: var(--gap-2) var(--pad-sheet-x); }
.panel-alert--flush { margin: 0 0 var(--gap-2); }

.hypothesis-detail { border-top: 1px solid var(--rule); }
.detail-head { align-items: center; }
.detail-head > div { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-1); }
.detail-head strong { font-size: var(--fs-title); }
.detail-head code, code { font: var(--fs-aux) var(--mono); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.thesis { margin: 0; padding: var(--pad-sheet); color: var(--ink); font-size: var(--fs-body); line-height: 1.45; }
.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--gap-2);
  padding: var(--pad-sheet);
  border-top: 1px solid var(--rule);
}
.detail-grid > div, .evidence-list { display: flex; flex-wrap: wrap; gap: var(--gap-1); align-content: flex-start; }
.detail-grid > div > span:first-child, .evidence-list > span:first-child { flex-basis: 100%; color: var(--mist); font-size: var(--fs-aux); }
.evidence-list { padding: var(--pad-sheet); border-top: 1px solid var(--rule); }
.evidence-list :deep(.el-table), .evidence-list :deep(.empty-state) { width: 100%; }
.missing { color: var(--mist); font-size: var(--fs-aux); }
.review-form { margin-top: var(--gap-2); }
.review-form :deep(.el-date-editor) { width: 100%; }
@media (max-width: 600px) {
  .section-head, .detail-head { flex-direction: column; }
}
</style>
