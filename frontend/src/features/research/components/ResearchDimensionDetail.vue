<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck } from '@element-plus/icons-vue'

import type { ResearchQuality } from '@/shared/types/quant'

import type { ResearchDimensionRow } from '../researchTypes'

const props = defineProps<{
  row: ResearchDimensionRow | null
}>()

const result = computed(() => props.row?.result || null)
const values = computed(() => result.value?.values || {})
const recentRows = computed<Record<string, unknown>[]>(() => {
  const raw = values.value.recent
  return Array.isArray(raw)
    ? raw.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    : []
})
const valueEntries = computed(() =>
  Object.entries(values.value)
    .filter(([key]) => !['recent', 'method_notes'].includes(key))
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .slice(0, 16),
)
const technicalMetrics = computed(() => [
  { key: 'close', label: '收盘', value: values.value.close, suffix: '' },
  { key: 'rsi14', label: 'RSI14', value: values.value.rsi14, suffix: '' },
  { key: 'macd_hist', label: 'MACD 柱', value: values.value.macd_hist, suffix: '' },
  { key: 'volume_ratio20', label: '量比20', value: values.value.volume_ratio20, suffix: 'x' },
  { key: 'stage', label: 'Stage', value: values.value.stage, suffix: '' },
  { key: 'vcp_possible', label: 'VCP 代理', value: values.value.vcp_possible, suffix: '' },
])

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

function formatValue(value: unknown): string {
  if (value === true) return '是'
  if (value === false) return '否'
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? String(value)
      : value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
  }
  return String(value ?? '—')
}

function sourceText(row: ResearchDimensionRow): string {
  return row.result?.source || '未接入'
}
</script>

<template>
  <section v-if="props.row" class="dimension-detail" aria-live="polite">
    <header class="detail-head">
      <div>
        <span class="research-kicker">{{ props.row.group }} · {{ props.row.key }}</span>
        <h3>{{ props.row.name }}</h3>
        <p>{{ props.row.summary }}</p>
      </div>
      <el-tag :type="qualityType(result?.quality)" effect="plain">
        {{ qualityText(result?.quality) }}
      </el-tag>
    </header>

    <div class="detail-meta">
      <span>来源 <strong>{{ sourceText(props.row) }}</strong></span>
      <span>观察日 <strong>{{ result?.as_of || '—' }}</strong></span>
      <span>历史安全 <strong>{{ props.row.historical_safe ? '可回放' : '需时点证据' }}</strong></span>
    </div>

    <template v-if="props.row.key === '2_kline' && result">
      <div class="technical-grid">
        <div v-for="metric in technicalMetrics" :key="metric.key" class="technical-cell">
          <span>{{ metric.label }}</span>
          <strong :class="{ 'is-null': metric.value === null || metric.value === undefined }">
            {{ formatValue(metric.value) }}{{ metric.value !== null && metric.value !== undefined ? metric.suffix : '' }}
          </strong>
        </div>
      </div>
      <div class="detail-block">
        <div class="block-heading">
          <span>最近 60 根</span>
          <span>{{ formatValue(values.bars) }} 根样本</span>
        </div>
        <el-table :data="recentRows" size="small" height="250" stripe>
          <el-table-column prop="trade_date" label="日期" width="112" />
          <el-table-column prop="close" label="收盘" align="right" />
          <el-table-column prop="ma20" label="MA20" align="right" />
          <el-table-column prop="rsi14" label="RSI14" align="right" />
          <el-table-column prop="macd_hist" label="MACD 柱" align="right" />
        </el-table>
      </div>
    </template>

    <template v-else-if="result && valueEntries.length">
      <div class="value-grid">
        <div v-for="[key, value] in valueEntries" :key="key" class="value-cell">
          <span>{{ key }}</span>
          <strong>{{ formatValue(value) }}</strong>
        </div>
      </div>
    </template>

    <div v-else class="gap-empty">
      <el-empty description="当前没有可核验事实" :image-size="58" />
    </div>

    <div v-if="result?.data_gaps.length" class="gap-strip">
      <span class="gap-title">缺口</span>
      <span v-for="gap in result.data_gaps" :key="gap">{{ gap }}</span>
    </div>
    <div v-if="result?.evidence.length" class="evidence-strip">
      <el-icon aria-hidden="true"><CircleCheck /></el-icon>
      <span>证据已绑定</span>
      <code :title="result.evidence[0].payload_sha256">
        {{ result.evidence[0].payload_sha256.slice(0, 16) }}…
      </code>
    </div>
  </section>
</template>

<style scoped>
.dimension-detail {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.research-kicker {
  display: block;
  color: var(--mist);
  font: 0.68rem/1.2 var(--mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.82rem 0.9rem;
  border-bottom: 1px solid var(--rule);
}

.detail-head > div {
  min-width: 0;
}

.detail-head h3 {
  margin: 0.22rem 0 0;
  color: var(--ink);
  font-size: 0.98rem;
  font-weight: 700;
  letter-spacing: 0;
}

.detail-head p {
  max-width: 70ch;
  margin: 0.28rem 0 0;
  color: var(--mist);
  font-size: 0.8rem;
  line-height: 1.4;
}

.detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1rem;
  padding: 0.6rem 0.9rem;
  border-bottom: 1px solid var(--rule);
  color: var(--mist);
  font-size: 0.76rem;
}

.detail-meta strong {
  color: var(--ink);
  font-weight: 600;
}

.technical-grid,
.value-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin: 0.8rem 0.9rem;
  border: 1px solid var(--rule);
  background: var(--rule);
}

.technical-cell,
.value-cell {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
  padding: 0.62rem 0.7rem;
  background: var(--sheet);
}

.technical-cell span,
.value-cell span {
  color: var(--mist);
  font-size: 0.72rem;
}

.technical-cell strong,
.value-cell strong {
  overflow-wrap: anywhere;
  color: var(--ink);
  font: 700 0.92rem/1.25 var(--mono);
  font-variant-numeric: tabular-nums;
}

.technical-cell strong.is-null {
  color: var(--mist);
}

.detail-block {
  margin: 0 0.9rem 0.8rem;
}

.block-heading {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 0.4rem;
  color: var(--mist);
  font-size: 0.76rem;
}

.gap-empty {
  padding: 0.5rem 0;
}

.gap-strip,
.evidence-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem 0.6rem;
  margin: 0 0.9rem 0.75rem;
  padding: 0.6rem 0.7rem;
  border-inline-start: 3px solid var(--seal);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-size: 0.76rem;
  line-height: 1.45;
}

.gap-title {
  font-weight: 700;
}

.evidence-strip {
  border-inline-start-color: var(--lake);
  background: var(--lake-soft);
  color: var(--lake);
}

.evidence-strip code {
  color: var(--ink);
  font-family: var(--mono);
  font-size: 0.74rem;
  overflow-wrap: anywhere;
}

@media (max-width: 560px) {
  .technical-grid,
  .value-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
