<script setup lang="ts">
import { Card, CardHeader, CardContent, CardTitle } from '@/shared/components/ui/card'
import { computed } from 'vue'

import { candidateDecisions, decimal, percent } from '../assistantArtifacts'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Badge } from '@/shared/components/ui/badge'
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

function decisionClass(decision: string): string {
  if (/精选|通过|入选/.test(decision)) return 'border-transparent bg-ok-soft text-ok'
  if (/落选|拒绝/.test(decision)) return 'border-transparent bg-info-soft text-info-ink'
  return 'border-transparent bg-warn-soft text-warn-ink'
}
function metricTone(value: number | undefined): string {
  return value == null ? '' : value >= 0 ? 'is-up' : 'is-down'
}
</script>

<template>
  <Card class="assistant-chart assistant-card" aria-label="候选精选图">
    <CardHeader class="assistant-card__heading">
      <CardTitle>{{ artifact.title || '候选精选图' }}</CardTitle>
      <Badge variant="outline">{{ candidates.length }} 只</Badge>
    </CardHeader>
    <CardContent class="assistant-card__content">
    <div v-if="candidates.length" class="assistant-chart__candidates">
      <article v-for="candidate in candidates" :key="candidate.id" class="assistant-candidate">
        <div class="assistant-candidate__head">
          <strong>{{ candidate.name }}</strong>
          <span v-if="candidate.code" class="assistant-candidate__code">{{ candidate.code }}</span>
          <Badge variant="outline" class="assistant-candidate__verdict" :class="decisionClass(candidate.decision)">
            {{ candidate.decision }}{{ candidate.score != null ? ` ${decimal(candidate.score)}` : '' }}
          </Badge>
        </div>
        <dl class="assistant-candidate__facts">
          <div class="assistant-candidate__fact">
            <dt>涨跌</dt>
            <dd><span :class="metricTone(candidate.pctChange)">{{ percent(candidate.pctChange) }}</span></dd>
          </div>
          <div class="assistant-candidate__fact">
            <dt>量比</dt>
            <dd>{{ decimal(candidate.volumeRatio) }}</dd>
          </div>
          <div class="assistant-candidate__fact">
            <dt>MA5 偏离</dt>
            <dd><span :class="metricTone(candidate.ma5Deviation)">{{ percent(candidate.ma5Deviation) }}</span></dd>
          </div>
          <div class="assistant-candidate__fact">
            <dt>MA20 偏离</dt>
            <dd><span :class="metricTone(candidate.ma20Deviation)">{{ percent(candidate.ma20Deviation) }}</span></dd>
          </div>
          <div class="assistant-candidate__fact">
            <dt>时点</dt>
            <dd>{{ candidate.timing || candidate.occurredOn || '—' }}</dd>
          </div>
          <div class="assistant-candidate__fact">
            <dt>失效条件</dt>
            <dd>{{ candidate.invalidation || '—' }}</dd>
          </div>
        </dl>
        <p class="assistant-candidate__reason"><span>理由</span>{{ candidate.reason || '—' }}</p>
      </article>
    </div>
    <EmptyState v-else description="暂无可展示的数据" reason="先跑一次选股" />
    </CardContent>
  </Card>
</template>

<style scoped>
.assistant-chart__candidates { display: grid; gap: .45rem; }
.assistant-candidate { padding: .45rem; border: 1px solid var(--rule); border-radius: var(--ai-r-chip); background: var(--paper); }
.assistant-candidate__head { display: flex; align-items: baseline; gap: .35rem; min-width: 0; margin-bottom: .35rem; font-size: var(--ai-fs-body); }
.assistant-candidate__head strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.assistant-candidate__code { color: var(--mist); font-family: var(--mono); font-size: var(--ai-fs-meta); }
.assistant-candidate__verdict { margin-left: auto; }
.assistant-candidate__facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--gap-1) var(--gap-2); margin: 0; }
.assistant-candidate__fact { display: grid; grid-template-columns: 4.4rem minmax(0, 1fr); gap: var(--gap-2); align-items: baseline; padding: var(--gap-1) var(--gap-2); min-width: 0; }
.assistant-candidate__fact dt { color: var(--mist); font-size: var(--ai-fs-meta); }
.assistant-candidate__fact dd { margin: 0; min-width: 0; font-size: var(--ai-fs-aux); overflow-wrap: anywhere; }
.assistant-candidate__reason { margin: .4rem 0 0; color: var(--muted); font-size: var(--ai-fs-aux); line-height: 1.4; white-space: pre-wrap; overflow-wrap: anywhere; }
.assistant-candidate__reason span { margin-right: .35rem; color: var(--mist); }
.is-up { color: var(--up); }
.is-down { color: var(--down); }
</style>
