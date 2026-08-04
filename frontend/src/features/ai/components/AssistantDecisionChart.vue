<script setup lang="ts">
import { computed } from 'vue'

import { candidateDecisions, decimal, percent } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

const props = defineProps<{ artifact: AiChartArtifact }>()

interface Candle { open: number; close: number; high: number; low: number }

const chartData = computed<Record<string, unknown>>(() => {
  const data = props.artifact?.data
  return data && typeof data === 'object' && !Array.isArray(data) ? data : {}
})

const candles = computed<Candle[]>(() => {
  try {
    const rows = listValue(chartData.value.bars ?? chartData.value.kline ?? chartData.value.candles)
    return rows.map((row) => ({
      open: numberAt(row, 'open', 1), close: numberAt(row, 'close', 2), high: numberAt(row, 'high', 3), low: numberAt(row, 'low', 4),
    })).filter((row) => [row.open, row.close, row.high, row.low].every(Number.isFinite))
  } catch {
    return []
  }
})
const candidates = computed(() => {
  try {
    return candidateDecisions(chartData.value)
  } catch {
    return []
  }
})
const bounds = computed(() => {
  const values = candles.value.flatMap((row) => [row.low, row.high])
  if (!values.length) return { min: 0, max: 1 }
  return { min: Math.min(...values), max: Math.max(...values) }
})

function y(value: number): number { const range = bounds.value.max - bounds.value.min || 1; return 84 - ((value - bounds.value.min) / range) * 72 }
function x(index: number): number { return 12 + index * (176 / Math.max(candles.value.length - 1, 1)) }
function color(candle: Candle): string { return candle.close >= candle.open ? 'var(--up)' : 'var(--down)' }
function tagType(decision: string): 'success' | 'warning' | 'info' { return /精选|通过|入选/.test(decision) ? 'success' : /落选|拒绝/.test(decision) ? 'info' : 'warning' }
function metricTone(value: number | undefined): string { return value == null ? '' : value >= 0 ? 'is-up' : 'is-down' }
function listValue(value: unknown): unknown[] { return Array.isArray(value) ? value : [] }
function objectAt(row: unknown, key: string): unknown { return row && typeof row === 'object' && !Array.isArray(row) ? (row as Record<string, unknown>)[key] : undefined }
function numberAt(row: unknown, key: string, index: number): number { return Array.isArray(row) ? numeric(row[index]) ?? Number.NaN : numeric(objectAt(row, key)) ?? Number.NaN }
function numeric(value: unknown): number | undefined { return typeof value === 'number' && Number.isFinite(value) ? value : undefined }
</script>

<template>
  <section class="assistant-chart" :aria-label="artifact.title || (artifact.kind === 'qianlong_kline' ? '潜龙 K 线' : '候选精选图')">
    <div class="assistant-chart__heading">
      <h3>{{ artifact.title || (artifact.kind === 'qianlong_kline' ? '潜龙 K 线' : '候选精选图') }}</h3>
      <el-tag v-if="artifact.kind === 'candidate_verdict'" size="small" type="info">{{ candidates.length }} 只</el-tag>
    </div>
    <svg v-if="artifact.kind === 'qianlong_kline' && candles.length" viewBox="0 0 200 96" role="img" aria-label="K 线裁决图">
      <g v-for="(candle, index) in candles" :key="index" :stroke="color(candle)" :fill="color(candle)">
        <line :x1="x(index)" :x2="x(index)" :y1="y(candle.high)" :y2="y(candle.low)" stroke-width="1" />
        <rect :x="x(index) - 2.5" :y="Math.min(y(candle.open), y(candle.close))" width="5" :height="Math.max(2, Math.abs(y(candle.open) - y(candle.close)))" />
      </g>
    </svg>
    <div v-else-if="artifact.kind === 'candidate_verdict' && candidates.length" class="assistant-chart__candidates">
      <article v-for="candidate in candidates" :key="candidate.id" class="assistant-candidate">
        <div class="assistant-candidate__head">
          <strong>{{ candidate.name }}</strong>
          <span v-if="candidate.code" class="assistant-candidate__code">{{ candidate.code }}</span>
          <el-tag size="small" :type="tagType(candidate.decision)">{{ candidate.decision }}{{ candidate.score != null ? ` ${decimal(candidate.score)}` : '' }}</el-tag>
        </div>
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="涨跌"><span :class="metricTone(candidate.pctChange)">{{ percent(candidate.pctChange) }}</span></el-descriptions-item>
          <el-descriptions-item label="量比">{{ decimal(candidate.volumeRatio) }}</el-descriptions-item>
          <el-descriptions-item label="MA5 偏离"><span :class="metricTone(candidate.ma5Deviation)">{{ percent(candidate.ma5Deviation) }}</span></el-descriptions-item>
          <el-descriptions-item label="MA20 偏离"><span :class="metricTone(candidate.ma20Deviation)">{{ percent(candidate.ma20Deviation) }}</span></el-descriptions-item>
          <el-descriptions-item label="时点">{{ candidate.timing || candidate.occurredOn || '—' }}</el-descriptions-item>
          <el-descriptions-item label="失效条件">{{ candidate.invalidation || '—' }}</el-descriptions-item>
        </el-descriptions>
        <p class="assistant-candidate__reason"><span>理由</span>{{ candidate.reason || '—' }}</p>
      </article>
    </div>
    <el-empty v-else :image-size="48" description="工具未返回可展示的数据" />
  </section>
</template>

<style scoped>
.assistant-chart { margin-top: .5rem; padding: .55rem; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--panel-2); }
.assistant-chart__heading { display: flex; align-items: center; justify-content: space-between; gap: .4rem; margin-bottom: .4rem; }
.assistant-chart h3 { margin: 0; font-size: .78rem; }
.assistant-chart svg { display: block; width: 100%; max-height: 8rem; }
.assistant-chart__candidates { display: grid; gap: .45rem; }
.assistant-candidate { padding: .45rem; border: 1px solid var(--rule); border-radius: 4px; background: var(--paper); }
.assistant-candidate__head { display: flex; align-items: baseline; gap: .35rem; min-width: 0; margin-bottom: .35rem; font-size: .76rem; }
.assistant-candidate__head strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assistant-candidate__code { color: var(--mist); font-family: var(--mono); font-size: .72rem; }
.assistant-candidate__head :deep(.el-tag) { margin-left: auto; }
.assistant-candidate :deep(.el-descriptions__label) { width: 4.4rem; color: var(--mist); font-size: .68rem; }
.assistant-candidate :deep(.el-descriptions__content) { font-size: .7rem; }
.assistant-candidate__reason { margin: .4rem 0 0; color: var(--muted); font-size: .72rem; line-height: 1.4; white-space: pre-wrap; overflow-wrap: anywhere; }
.assistant-candidate__reason span { margin-right: .35rem; color: var(--mist); }
.is-up { color: var(--up); }
.is-down { color: var(--down); }
</style>
