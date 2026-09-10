<script setup lang="ts">
import { computed } from 'vue'

import { candidateDecisions, decimal, percent } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'

import './assistant-card.css'

const props = defineProps<{ artifact: AiChartArtifact }>()

const chartData = computed<Record<string, unknown>>(() => {
  const data = props.artifact?.data
  return data && typeof data === 'object' && !Array.isArray(data) ? data : {}
})

const candidates = computed(() => {
  try {
    return candidateDecisions(chartData.value)
  } catch {
    return []
  }
})

function tagType(decision: string): 'success' | 'warning' | 'info' {
  return /精选|通过|入选/.test(decision) ? 'success' : /落选|拒绝/.test(decision) ? 'info' : 'warning'
}
function metricTone(value: number | undefined): string {
  return value == null ? '' : value >= 0 ? 'is-up' : 'is-down'
}
</script>

<template>
  <section class="assistant-chart assistant-card" aria-label="候选精选图">
    <div class="assistant-card__heading">
      <h3>{{ artifact.title || '候选精选图' }}</h3>
      <el-tag size="small" type="info">{{ candidates.length }} 只</el-tag>
    </div>
    <div v-if="candidates.length" class="assistant-chart__candidates">
      <article v-for="candidate in candidates" :key="candidate.id" class="assistant-candidate">
        <div class="assistant-candidate__head">
          <strong>{{ candidate.name }}</strong>
          <span v-if="candidate.code" class="assistant-candidate__code">{{ candidate.code }}</span>
          <el-tag size="small" :type="tagType(candidate.decision)">
            {{ candidate.decision }}{{ candidate.score != null ? ` ${decimal(candidate.score)}` : '' }}
          </el-tag>
        </div>
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="涨跌">
            <span :class="metricTone(candidate.pctChange)">{{ percent(candidate.pctChange) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="量比">{{ decimal(candidate.volumeRatio) }}</el-descriptions-item>
          <el-descriptions-item label="MA5 偏离">
            <span :class="metricTone(candidate.ma5Deviation)">{{ percent(candidate.ma5Deviation) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="MA20 偏离">
            <span :class="metricTone(candidate.ma20Deviation)">{{ percent(candidate.ma20Deviation) }}</span>
          </el-descriptions-item>
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
.assistant-chart__candidates { display: grid; gap: .45rem; }
.assistant-candidate { padding: .45rem; border: 1px solid var(--rule); border-radius: var(--ai-r-chip); background: var(--paper); }
.assistant-candidate__head { display: flex; align-items: baseline; gap: .35rem; min-width: 0; margin-bottom: .35rem; font-size: var(--ai-fs-body); }
.assistant-candidate__head strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assistant-candidate__code { color: var(--mist); font-family: var(--mono); font-size: var(--ai-fs-meta); }
.assistant-candidate__head :deep(.el-tag) { margin-left: auto; }
.assistant-candidate :deep(.el-descriptions__label) { width: 4.4rem; color: var(--mist); font-size: var(--ai-fs-meta); }
.assistant-candidate :deep(.el-descriptions__content) { font-size: var(--ai-fs-aux); }
.assistant-candidate__reason { margin: .4rem 0 0; color: var(--muted); font-size: var(--ai-fs-aux); line-height: 1.4; white-space: pre-wrap; overflow-wrap: anywhere; }
.assistant-candidate__reason span { margin-right: .35rem; color: var(--mist); }
.is-up { color: var(--up); }
.is-down { color: var(--down); }
</style>
