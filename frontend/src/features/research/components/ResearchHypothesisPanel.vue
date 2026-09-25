<script setup lang="ts">
import { Check, Library as Collection, Plus, RefreshCw as RefreshRight } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { IconBox, Notice, StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as FormLayout } from '@/shared/components/ui/app/FormLayout.vue'
import { default as FormField } from '@/shared/components/ui/app/FormField.vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { default as NumberInput } from '@/shared/components/ui/app/NumberInput.vue'
import { default as DialogPanel } from '@/shared/components/ui/app/DialogPanel.vue'
import { default as RadioChoices } from '@/shared/components/ui/app/RadioChoices.vue'
import { default as RadioButton } from '@/shared/components/ui/app/RadioButton.vue'
import { default as DateField } from '@/shared/components/ui/app/DateField.vue'

import { useId, computed, ref } from 'vue'



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

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import UiField from '@/shared/components/ui/UiField.vue'

const hypotheses = ref<ResearchHypothesis[]>([])
const selectedId = ref('')
const metricOperatorId = useId()
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

const hypothesisRows = computed(() => hypotheses.value as unknown as Record<string, unknown>[])
const evidenceRows = computed(() => (selected.value?.evidence_links ?? []) as unknown as Record<string, unknown>[])

const hypothesisColumns: BasicTableColumn[] = [
  { prop: 'hypothesis_id', label: 'ID', minWidth: 120, showOverflowTooltip: true },
  { prop: 'title', label: '标题', minWidth: 160, showOverflowTooltip: true },
  { prop: 'status', label: '状态', width: 94, slotName: 'status' },
  { prop: 'revision', label: '修订', width: 68 },
  { prop: 'hypothesis_id', label: '审核', width: 76, fixed: 'right', slotName: 'review' },
]

const evidenceColumns: BasicTableColumn[] = [
  { prop: 'run_id', label: '批次', minWidth: 120 },
  { prop: 'summary', label: '摘要', minWidth: 160, showOverflowTooltip: true },
  { prop: 'artifact_sha256', label: '证据指纹', minWidth: 150, slotName: 'hash' },
]

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
    toast.success('假设已创建')
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
    toast.success('人工审核已记录')
  } catch (caught: unknown) {
    error.value = caught instanceof Error ? caught.message : '人工审核失败，请刷新假设后重试'
  } finally {
    transitioning.value = false
  }
}

defineExpose({ load })
</script>

<template>
  <section class="hypothesis-panel research-surface" aria-label="研究假设与人工审核">
    <header class="section-head">
      <!-- 英文 kicker 删除：它和下一行中文标题说的是同一件事，白占一行（用户原话：一行能显示的话两行） -->
      <h3><IconBox aria-hidden="true"><Collection /></IconBox>假设与人工审核</h3>
      <ActionButton access="read" size="small" :icon="RefreshRight" :busy="loading" @click="load">刷新</ActionButton>
    </header>
    <FormLayout
      class="hypothesis-form"
      label-position="right"
      label-width="6.5em"
      size="small"
      @submit.prevent="create"
    >
      <FormField label="假设 ID" required>
        <TextField v-model="createForm.hypothesisId" placeholder="仅英文、数字、- 或 _" />
      </FormField>
      <FormField label="标题" required>
        <TextField v-model="createForm.title" />
      </FormField>
      <FormField label="策略版本" required>
        <TextField v-model="createForm.strategyRevision" />
      </FormField>
      <FormField label="指标名" required>
        <TextField v-model="createForm.metricName" placeholder="后端实际指标名" />
      </FormField>
      <FormField label="阈值" required class="metric-threshold">
        <ChoiceField :id="metricOperatorId" v-model="createForm.metricOperator" class="metric-threshold__op" aria-label="比较符">
          <ChoiceOption v-for="operator in ['>=', '>', '<=', '<', '==']" :key="operator" :value="operator" />
        </ChoiceField>
        <NumberInput v-model="createForm.metricThreshold" controls-position="right" class="metric-threshold__value" />
      </FormField>
      <FormField label="操作者" required>
        <TextField v-model="createForm.actor" />
      </FormField>
      <FormField label="论断" required class="form-wide">
        <TextField v-model="createForm.thesis" type="textarea" :rows="2" />
      </FormField>
      <FormField label="失败条件" required class="form-wide">
        <TextField v-model="createForm.failureConditions" type="textarea" :rows="2" placeholder="每行一项" />
      </FormField>
      <FormField class="form-action" label-width="0">
        <ActionButton tone="primary" type="submit" :icon="Plus" :busy="creating">创建假设</ActionButton>
      </FormField>
    </FormLayout>
    <Notice v-if="error" :title="error" tone="error" show-icon :closable="false" class="panel-alert" />
    <BasicTable
      :columns="hypothesisColumns"
      :data-source="hypothesisRows"
      :pagination="false"
      :loading="loading"
      row-key="hypothesis_id"
      stripe
      empty-text="还没有假设"
      empty-reason="先写清验证目标与通过门槛"
      @row-click="(row) => { selectedId = String(row.hypothesis_id) }"
    >
      <template #status="{ row }">
        <StatusBadge size="small" effect="plain" :tone="statusType(row.status as ResearchHypothesisStatus)">{{ row.status }}</StatusBadge>
      </template>
      <template #review="{ row }">
        <ActionButton variant="ghost" size="small" @click.stop="selectedId = String(row.hypothesis_id); reviewOpen = true">审核</ActionButton>
      </template>
    </BasicTable>
    <section v-if="selected" class="hypothesis-detail">
      <div class="detail-head">
        <div><strong>{{ selected.title }}</strong><code>{{ selected.hypothesis_id }} · r{{ selected.revision }}</code></div>
        <div>
          <ActionButton v-if="canStartTesting" variant="ghost" size="small" :busy="transitioning" @click="transition('testing')">开始测试</ActionButton>
          <ActionButton v-if="canMonitor" variant="ghost" size="small" :busy="transitioning" @click="transition('monitoring')">进入监控</ActionButton>
          <ActionButton variant="ghost" size="small" :icon="Check" @click="reviewOpen = true">人工审核</ActionButton>
        </div>
      </div>
      <p class="thesis">{{ selected.thesis }}</p>
      <div class="detail-grid">
        <div>
          <span>预注册指标</span>
          <StatusBadge v-for="metric in selected.metrics" :key="metric.name" size="small" effect="plain">{{ metric.name }} {{ metric.operator }} {{ metric.threshold }}</StatusBadge>
          <span v-if="!selected.metrics.length" class="missing">未提供</span>
        </div>
        <div>
          <span>失败条件</span>
          <StatusBadge v-for="item in selected.failure_conditions" :key="item" size="small" effect="plain" tone="warning">{{ item }}</StatusBadge>
          <span v-if="!selected.failure_conditions.length" class="missing">未提供</span>
        </div>
      </div>
      <div class="evidence-list">
        <span>关联证据</span>
        <BasicTable
          :columns="evidenceColumns"
          :data-source="evidenceRows"
          :pagination="false"
          stripe
          empty-text="还没有挂上证据"
          empty-reason="点「人工审核」补一条"
        >
          <template #hash="{ row }">
            <code :title="String(row.artifact_sha256)">{{ String(row.artifact_sha256).slice(0, 16) }}...</code>
          </template>
        </BasicTable>
      </div>
    </section>
    <DialogPanel v-model="reviewOpen" class="research-modal" append-to-body title="人工审核" width="min(92vw, 640px)" :close-on-click-modal="false">
      <Notice
        v-if="reviewDecision === 'validated'"
        tone="info"
        :closable="false"
        title="通过需附证据指纹与真实观测值"
        show-icon
        class="panel-alert panel-alert--flush"
      />
      <div class="review-fields">
        <UiField label="决定">
          <RadioChoices v-model="reviewDecision" aria-label="审核决定">
            <RadioButton value="validated">通过</RadioButton>
            <RadioButton value="rejected">否决</RadioButton>
          </RadioChoices>
        </UiField>
        <UiField label="操作者" required>
          <TextField v-model="reviewForm.actor" />
        </UiField>
        <UiField label="审核理由" required>
          <TextField v-model="reviewForm.reason" type="textarea" :rows="2" />
        </UiField>
        <UiField label="证据批次">
          <TextField v-model="reviewForm.runId" />
        </UiField>
        <UiField label="证据指纹">
          <TextField v-model="reviewForm.artifactSha" />
        </UiField>
        <UiField label="证据摘要">
          <TextField v-model="reviewForm.summary" type="textarea" :rows="2" />
        </UiField>
        <UiField label="观测指标" description="数值 JSON 对象；缺项留空，不要估算">
          <TextField v-model="reviewForm.metricsJson" type="textarea" :rows="2" placeholder='{"profit_factor": 1.2}' />
        </UiField>
        <UiField label="截止日">
          <DateField v-model="reviewForm.asOf" value-format="YYYY-MM-DD" />
        </UiField>
      </div>
      <template #footer>
        <ActionButton access="read" @click="reviewOpen = false">取消</ActionButton>
        <ActionButton tone="primary" :busy="transitioning" @click="review">记录审核</ActionButton>
      </template>
    </DialogPanel>
  </section>
</template>

<style scoped>
.hypothesis-panel { overflow: hidden; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--sheet); }
.section-head, .detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--gap-3); padding: var(--pad-sheet); border-bottom: 1px solid var(--rule); }
.section-head h3 { margin: 0; font-size: var(--fs-title); font-weight: 700; letter-spacing: .03em; }
.hypothesis-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--gap-1) var(--gap-3);
  align-items: start;
  padding: var(--pad-sheet);
  border-bottom: 1px solid var(--rule);
}
.hypothesis-form :deep(.form-field) { margin-bottom: 0; min-width: 0; }
.form-wide { grid-column: 1 / -1; }
.form-action { justify-content: flex-end; }
.metric-threshold :deep(.form-field__content) { flex-wrap: nowrap; gap: var(--gap-1); }
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
.evidence-list :deep(.data-grid),
.evidence-list :deep(.empty-state) { width: 100%; }
.missing { color: var(--mist); font-size: var(--fs-aux); }
.review-form { margin-top: var(--gap-2); }
.review-form :deep(.date-field) { width: 100%; }
@media (max-width: 600px) {
  .section-head, .detail-head { flex-direction: column; }
}
</style>
<style scoped src="./ResearchSurfaces.css"></style>
