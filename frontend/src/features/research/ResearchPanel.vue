<script setup lang="ts">
import { CircleCheck, CircleX as CircleClose, FileCheck as DocumentChecked, RefreshCw as RefreshRight, Search, TriangleAlert as WarningFilled } from '@lucide/vue'
import { default as TextField } from '@/shared/components/ui/app/TextField.vue'
import { default as RadioChoices } from '@/shared/components/ui/app/RadioChoices.vue'
import { default as RadioButton } from '@/shared/components/ui/app/RadioButton.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { Notice, StatusBadge, IconBox } from '@/shared/components/ui/app/presentation'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'

import { computed, onMounted, ref, watch } from 'vue'


import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import HeaderStat from '@/shared/components/ui/HeaderStat.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import type {
  ResearchBudget,
  ResearchQuality,
  ResearchSourceAttempt,
} from '@/shared/types/quant'

import ResearchDimensionDetail from './components/ResearchDimensionDetail.vue'
import ResearchDimensionRail from './components/ResearchDimensionRail.vue'
import ResearchEvidencePanel from './components/ResearchEvidencePanel.vue'
import ResearchBacktestPanel from './components/ResearchBacktestPanel.vue'
import ResearchFactorPanel from './components/ResearchFactorPanel.vue'
import ResearchHypothesisPanel from './components/ResearchHypothesisPanel.vue'
import ResearchRunPanel from './components/ResearchRunPanel.vue'
import ResearchTemporalDataPanel from './components/ResearchTemporalDataPanel.vue'
import { useResearchProfile } from './composables/useResearchProfile'
import type { ResearchDimensionRow } from './researchTypes'

const props = defineProps<{
  initialCode?: string
}>()

const code = ref(String(props.initialCode || '').trim())
const budget = ref<ResearchBudget>('standard')
const selectedKey = ref('2_kline')
const section = ref('profile')
const sectionTabs = [
  { name: 'profile', label: '标的剖面' },
  { name: 'factor', label: '因子实验' },
  { name: 'temporal', label: '时点数据' },
  { name: 'backtest', label: '研究回测' },
  { name: 'hypothesis', label: '假说审核' },
]
const backtestPanel = ref<{
  load: () => Promise<void>
  setHistoricalUniverse: (universeId: string) => void
} | null>(null)
const hypothesisPanel = ref<{ load: () => Promise<void> } | null>(null)

const {
  catalog,
  profile,
  loading,
  archiveLoading,
  runLoading,
  catalogLoading,
  error,
  archivedRun,
  activeRun,
  runs,
  dimensionsCount,
  loadCatalog,
  loadProfile,
  archiveProfile,
  loadRun,
  resumeRun,
} = useResearchProfile()

const budgets: { id: ResearchBudget; label: string }[] = [
  { id: 'lite', label: '轻量' },
  { id: 'standard', label: '标准' },
  { id: 'deep', label: '深度' },
]

const dimensionRows = computed<ResearchDimensionRow[]>(() => {
  const results = new Map((profile.value?.dimensions || []).map((row) => [row.key, row]))
  return (catalog.value?.dimensions || []).map((spec) => ({
    ...spec,
    result: results.get(spec.key),
  }))
})
const selectedRow = computed(() =>
  dimensionRows.value.find((row) => row.key === selectedKey.value) || dimensionRows.value[0] || null,
)
const subjectName = computed(() => String(profile.value?.subject.name || '未命名标的'))
const subjectIndustry = computed(() => String(profile.value?.subject.industry || '行业未登记'))
const quality = computed(() => profile.value?.quality || null)
const qualityLabel = computed(() => qualityText(quality.value?.overall))
const revisionShort = computed(() => {
  const revision = String(profile.value?.quality.market_revision || '')
  return revision ? `${revision.slice(0, 12)}…` : '—'
})
const warningCount = computed(
  () => quality.value?.findings.filter((item) => item.severity !== 'info').length || 0,
)
const sourceEvidence = computed<Record<string, unknown>>(() => {
  const value = profile.value?.market_snapshot.source_evidence
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
})
const sourceTelemetryWarnings = computed(() => {
  const evidence = sourceEvidence.value
  const warnings: string[] = []
  const unresolved = stringList(evidence.unresolved_codes)
  const unparsed = stringList(evidence.unparsed_codes)
  const missingAttempts = stringList(evidence.attempts_not_observed_codes)
  const failedSources = recordList(evidence.sources)
    .filter((item) => item.state === 'failed')
    .map((item) => String(item.source_id || '未知来源'))
  const fallbackSources = recordList(evidence.receipts)
    .filter((item) => item.fallback_used)
    .map((item) => String(item.code || item.receipt_id || '未知回执'))
  if (evidence.attempts_not_observed) warnings.push(`缺少真实来源 attempt：${missingAttempts.join('、') || '当前输入'}`)
  if (failedSources.length) warnings.push(`来源失败：${failedSources.join('、')}`)
  if (unresolved.length) warnings.push(`未解析代码：${unresolved.join('、')}`)
  if (unparsed.length) warnings.push(`无法标准化代码：${unparsed.join('、')}`)
  if (fallbackSources.length) warnings.push(`已发生来源回退：${fallbackSources.join('、')}`)
  return warnings
})

watch(
  () => props.initialCode,
  (value) => {
    const next = String(value || '').trim()
    if (next && next !== code.value) {
      code.value = next
      void submit()
    }
  },
)

function qualityText(value: ResearchQuality | undefined): string {
  if (value === 'full') return '完整'
  if (value === 'partial') return '部分完整'
  if (value === 'error') return '计算错误'
  return '缺失'
}

function qualityType(value: ResearchQuality | undefined): 'success' | 'warning' | 'info' | 'danger' {
  if (value === 'full') return 'success'
  if (value === 'partial') return 'warning'
  if (value === 'error') return 'danger'
  return 'info'
}

function statusIcon(value: ResearchQuality | undefined) {
  if (value === 'full') return CircleCheck
  if (value === 'error') return CircleClose
  return WarningFilled
}

function recordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => item !== null && typeof item === 'object' && !Array.isArray(item))
    : []
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : []
}

function attemptObserved(attempt: ResearchSourceAttempt): boolean {
  if (attempt.observed === false || attempt.attempts_not_observed) return false
  return !sourceEvidence.value.attempts_not_observed
}

function sourceStateText(attempt: ResearchSourceAttempt): string {
  if (!attemptObserved(attempt)) return '未观测回执'
  if (attempt.unresolved) return '未解析'
  if (attempt.fallback_used) return '回退命中'
  if (attempt.state === 'selected') return '已命中'
  if (attempt.state === 'probed') return '探针成功'
  if (attempt.state === 'failed') return '失败'
  if (attempt.state === 'registered') return '仅登记'
  return '待探测'
}

function sourceStateType(attempt: ResearchSourceAttempt): 'success' | 'warning' | 'info' | 'danger' {
  if (!attemptObserved(attempt) || attempt.unresolved) return 'warning'
  if (attempt.state === 'selected') return 'success'
  if (attempt.state === 'failed') return 'danger'
  if (attempt.state === 'registered') return 'warning'
  return 'info'
}

function validCode(value: string): boolean {
  return /^(?:sh|sz|bj)?\d{6}$/i.test(value.trim())
}

async function submit(): Promise<void> {
  const value = code.value.trim()
  if (!validCode(value)) {
    error.value = '请输入 6 位证券代码，可带 sh / sz / bj 前缀'
    return
  }
  await loadProfile(value, budget.value)
}

async function refresh(): Promise<void> {
  if (code.value.trim()) await submit()
  else await loadCatalog()
}

async function archive(): Promise<void> {
  const value = code.value.trim()
  if (!validCode(value)) {
    error.value = '请输入有效证券代码后再归档研究快照'
    return
  }
  await archiveProfile(value, budget.value)
}

function selectHistoricalUniverse(universeId: string): void {
  backtestPanel.value?.setHistoricalUniverse(universeId)
}

onMounted(() => {
  void loadCatalog()
  void backtestPanel.value?.load()
  void hypothesisPanel.value?.load()
  if (code.value) void submit()
})
</script>

<template>
  <div class="research-panel page-fill" aria-label="研究工作台">
    <PageBusy v-if="catalogLoading && !catalog" label="加载研究目录…" />

    <!--
      页头不印「研究剖面」：上层 PageTabs 的「研究」高亮着就已经交代了身份，
      英文 kicker 与那句介绍段各再占一行 —— 三行只干一行的事。标题删掉，
      口径进 note 的 ⓘ，维度数变行内读数，代码框 / 预算档 / 读取 / 归档 / 刷新
      全部压在同一条功能行上。
    -->
    <PageToolbar
      dense
      note="事实、来源、缺口分开呈现；研究标签不直接生成生产信号"
    >
      <form class="research-query" @submit.prevent="submit">
        <TextField
          v-model="code"
          class="research-code"
          clearable
          maxlength="8"
          aria-label="证券代码"
          placeholder="输入证券代码"
        >
          <template #prepend>标的</template>
        </TextField>
        <RadioChoices v-model="budget" size="small" aria-label="研究预算">
          <RadioButton v-for="item in budgets" :key="item.id" :value="item.id">
            {{ item.label }}
          </RadioButton>
        </RadioChoices>
        <ActionButton access="read" tone="primary" :icon="Search" :busy="loading" @click="submit">读取</ActionButton>
        <ActionButton :icon="DocumentChecked" :busy="archiveLoading" :disabled="!profile || loading" @click="archive">归档</ActionButton>
        <ActionButton access="read" variant="ghost" :icon="RefreshRight" :disabled="loading" aria-label="刷新研究剖面" @click="refresh" />
      </form>
      <template #stats>
        <HeaderStat label="维度" :value="catalog ? dimensionsCount : '—'" />
      </template>
    </PageToolbar>

    <Notice
      v-if="error"
      :title="error"
      tone="error"
      show-icon
      closable
      class="research-alert"
      @close="error = ''"
    />

    <PageTabs v-model="section" :items="sectionTabs" :sticky="false" dense aria-label="研究分区" />
    <div class="research-content">
    <div v-show="section === 'profile'" class="research-section">
    <ResearchRunPanel
      :runs="runs"
      :active-run="activeRun"
      :loading="runLoading"
      @load="loadRun"
      @resume="resumeRun"
    />

    <template v-if="profile">
      <section class="research-summary" aria-label="研究摘要">
        <div class="subject-lockup">
          <!-- 「SUBJECT」这行英文 kicker 删掉：下面就是标的名 + 代码 + 行业，遮住它也认得出来 -->
          <strong>{{ subjectName }}</strong>
          <code>{{ profile.code }}</code>
          <span>{{ subjectIndustry }}</span>
        </div>
        <div class="summary-metric">
          <span>总体质量</span>
          <StatusBadge :tone="qualityType(quality?.overall)" effect="plain">
            <IconBox aria-hidden="true"><component :is="statusIcon(quality?.overall)" /></IconBox>
            {{ qualityLabel }}
          </StatusBadge>
        </div>
        <div class="summary-metric">
          <span>完整度</span>
          <strong>{{ quality?.completeness_ratio == null ? '—' : `${(quality.completeness_ratio * 100).toFixed(0)}%` }}</strong>
        </div>
        <div class="summary-metric">
          <span>版本锚点</span>
          <code :title="quality?.market_revision || ''">{{ revisionShort }}</code>
        </div>
        <div class="summary-metric">
          <span>门禁提示</span>
          <strong :class="{ 'is-warning': quality?.blocked || warningCount }">
            {{ quality?.blocked ? '阻断' : `${warningCount} 项` }}
          </strong>
        </div>
      </section>

      <section v-if="profile.source_attempts.length || profile.artifact_id" class="source-receipts" aria-label="来源回执">
        <!-- 英文 kicker 换成中文行内标签：这排 tag 没有别的东西说明它是什么，所以留，但不占整行 -->
        <span class="research-kicker">来源回执</span>
        <StatusBadge
          v-if="profile.artifact_id"
          :tone="profile.artifact_status === 'stale' ? 'warning' : 'success'"
          size="small"
          effect="plain"
        >
          {{ profile.artifact_status === 'stale' ? '快照已过期' : '快照已归档' }} · {{ profile.artifact_id }}
        </StatusBadge>
        <StatusBadge
          v-for="attempt in profile.source_attempts"
          :key="attempt.source_id"
          :tone="sourceStateType(attempt)"
          size="small"
          effect="plain"
          :title="attempt.error || attempt.row_sources.join(', ')"
        >
          {{ attempt.source_id }} · {{ sourceStateText(attempt) }}
        </StatusBadge>
      </section>

      <!--
        不用 description（AGENTS.md §3.9 文案规范）：title 只报「出了什么事」，
        具体是哪几条降级用 el-tag 列出来 —— 那是结构化证据，不是说明文字。
      -->
      <Notice
        v-if="sourceTelemetryWarnings.length"
        class="research-alert"
        tone="warning"
        show-icon
        :closable="false"
        title="行情来源 telemetry 不完整或已降级"
      >
        <StatusBadge
          v-for="warning in sourceTelemetryWarnings"
          :key="warning"
          size="small"
          tone="warning"
          effect="plain"
          class="telemetry-tag"
        >{{ warning }}</StatusBadge>
      </Notice>

      <!-- 那句「可查看中间事实但别当结论」是口径解释，进 tooltip；alert 只报异常本身 -->
      <HintTooltip
        v-if="quality?.blocked"
        placement="bottom-start"
        content="可查看中间事实；不要标记为完整研究，也不要直接用于生产信号"
      >
        <Notice
          class="research-alert"
          tone="warning"
          show-icon
          :closable="false"
          title="研究结果未通过核验门禁"
        />
      </HintTooltip>

      <ResearchEvidencePanel :profile="profile" :run="activeRun || archivedRun" />

      <div class="research-layout">
        <ResearchDimensionRail
          :rows="dimensionRows"
          :selected-key="selectedKey"
          @select="selectedKey = $event"
        />
        <ResearchDimensionDetail :row="selectedRow" />
      </div>
    </template>

    <section v-else-if="catalog" class="catalog-blank" aria-label="研究目录预览">
      <EmptyState
        description="输入证券代码读取研究剖面"
        reason="填写代码后点击读取"
      />
      <div class="source-band">
        <span class="research-kicker">来源登记</span>
        <StatusBadge v-for="source in catalog.sources" :key="source.id" size="small" effect="plain">
          {{ source.name_cn }} · {{ source.health }}
        </StatusBadge>
      </div>
    </section>

    </div>
    <div v-show="section === 'factor'" class="research-section"><ResearchFactorPanel /></div>
    <div v-show="section === 'temporal'" class="research-section"><ResearchTemporalDataPanel @select-universe="selectHistoricalUniverse" /></div>
    <div v-show="section === 'backtest'" class="research-section"><ResearchBacktestPanel ref="backtestPanel" /></div>
    <div v-show="section === 'hypothesis'" class="research-section"><ResearchHypothesisPanel ref="hypothesisPanel" /></div>
    </div>
  </div>
</template>

<style scoped src="./ResearchPanel.css"></style>
<style scoped src="./ResearchPanel.responsive.css"></style>
