<script setup lang="ts">
import { computed } from 'vue'
import { BookOpen, FlaskConical } from '@lucide/vue'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import type { FalconLearningMemory, FalconLesson, FalconOptimizationProposal } from '@/shared/types/stock_agents'
import { phaseName } from '../agentFormat'

const props = defineProps<{ memory?: FalconLearningMemory | null }>()
const groups = computed(() => [
  { key: 'lessons', title: '择时经验', icon: BookOpen, entries: props.memory?.lessons ?? [], limit: props.memory?.limits?.lessons ?? 12, empty: '尚无已沉淀经验' },
  { key: 'proposals', title: '选股与判分建议', icon: FlaskConical, entries: props.memory?.optimization_proposals ?? [], limit: props.memory?.limits?.optimization_proposals ?? 8, empty: '尚无优化建议' },
])
function statusText(status:FalconLesson['status']) {
  return { pending: '待验证', supported: '有证据支持', rejected: '已否定' }[status]
}
function sampleText(basis:FalconLesson['sample_basis']) {
  return { executed: '实际模拟成交', observed: '观察样本', hypothetical: '假设样本' }[basis]
}
function proposal(entry:FalconLesson):FalconOptimizationProposal | null {
  return 'proposed_change' in entry ? entry as FalconOptimizationProposal : null
}
</script>

<template>
  <section class="falcon-learning" aria-label="猎隼经验沉淀">
    <div class="falcon-learning__head">
      <h2>经验沉淀</h2>
      <p v-if="memory?.last_review_date">最近沉淀 {{ memory.last_review_date }} · {{ phaseName(memory.last_review_phase) }}</p>
    </div>
    <div class="falcon-learning__grid" data-agent-workspace-scroll role="region" aria-label="经验与优化建议" tabindex="0">
      <Card v-for="group in groups" :key="group.key" class="falcon-learning__card">
        <CardHeader class="falcon-learning__card-head border-b">
          <CardTitle class="flex items-center gap-2"><component :is="group.icon" class="size-4 text-muted-foreground" aria-hidden="true" />{{ group.title }}<UiBadge variant="secondary">{{ group.entries.length }} / {{ group.limit }}</UiBadge></CardTitle>
        </CardHeader>
        <CardContent class="falcon-learning__body p-0" data-agent-workspace-scroll role="region" :aria-label="`${group.title}列表`" tabindex="0">
          <ul v-if="group.entries.length" class="falcon-learning__list">
            <li v-for="entry in group.entries" :key="entry.id" class="falcon-learning__entry">
              <div class="falcon-learning__title">
                <h3>{{ entry.title }}</h3>
                <UiBadge :variant="entry.status === 'supported' ? 'ok' : 'secondary'">{{ statusText(entry.status) }}</UiBadge>
              </div>
              <p class="falcon-learning__finding">{{ entry.finding }}</p>
              <p v-if="proposal(entry)" class="falcon-learning__change"><b>{{ proposal(entry)?.target === 'selection' ? '选股改进' : '判分改进' }}</b> · {{ proposal(entry)?.proposed_change }}</p>
              <p class="falcon-learning__sample">{{ sampleText(entry.sample_basis) }} · {{ entry.sample_size }} 个样本<template v-if="entry.last_review_date"> · {{ entry.last_review_date }}</template></p>
              <details class="falcon-learning__details">
                <summary>证据与验证计划</summary>
                <dl>
                  <div><dt>适用条件</dt><dd>{{ entry.conditions }}</dd></div>
                  <div><dt>样本口径</dt><dd>{{ entry.sample_definition }}</dd></div>
                  <div><dt>验证计划</dt><dd>{{ entry.validation_plan }}</dd></div>
                  <div><dt>证据引用</dt><dd><ul v-if="entry.evidence_refs.length"><li v-for="reference in entry.evidence_refs" :key="reference"><code>{{ reference }}</code></li></ul><span v-else>尚无证据引用</span></dd></div>
                  <div v-if="entry.positive_examples.length"><dt>支持样本</dt><dd><ul><li v-for="(example,index) in entry.positive_examples" :key="index"><p>{{ example.interpretation }}</p><code>{{ example.evidence_ref }}</code></li></ul></dd></div>
                  <div v-if="entry.counter_examples.length"><dt>反例</dt><dd><ul><li v-for="(example,index) in entry.counter_examples" :key="index"><p>{{ example.interpretation }}</p><code>{{ example.evidence_ref }}</code></li></ul></dd></div>
                </dl>
              </details>
            </li>
          </ul>
          <EmptyState v-else :description="group.empty" reason="完成日复盘或周复盘后在此累积" compact />
        </CardContent>
      </Card>
    </div>
  </section>
</template>

<style scoped>
.falcon-learning { display:flex; flex-direction:column; height:100%; min-width:0; min-height:0; }
.falcon-learning__head { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:6px 16px; margin-bottom:12px; }
.falcon-learning__head h2 { margin:0; font-size:15px; font-weight:650; }
.falcon-learning__head p, .falcon-learning__sample { margin:0; color:var(--text-tertiary); font-size:12px; line-height:1.6; }
.falcon-learning__head { flex-shrink:0; }
.falcon-learning__grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); grid-template-rows:minmax(0,1fr); flex:1 1 0%; min-height:0; min-width:0; overflow:hidden; gap:var(--gap-4); }
.falcon-learning__card { min-height:0; min-width:0; overflow:hidden; }
.falcon-learning__card-head { flex-shrink:0; }
.falcon-learning__body { flex:1 1 0%; min-height:0; min-width:0; overflow:auto; scrollbar-width:thin; scrollbar-color:var(--border-default) transparent; }
.falcon-learning__body:focus-visible, .falcon-learning__grid:focus-visible { outline:2px solid var(--focus-ring,var(--seal)); outline-offset:-2px; }
.falcon-learning__list { margin:0; padding:0; list-style:none; }
.falcon-learning__entry { padding:16px; overflow-wrap:anywhere; }
.falcon-learning__entry + .falcon-learning__entry { border-top:1px solid var(--border-subtle); }
.falcon-learning__title { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
.falcon-learning__title h3 { flex:1; min-width:0; margin:0; font-size:13px; font-weight:600; line-height:1.6; }
.falcon-learning__finding, .falcon-learning__change { margin:8px 0; font-size:13px; line-height:1.75; white-space:pre-wrap; }
.falcon-learning__change b { font-weight:600; }
.falcon-learning__details { margin-top:10px; color:var(--text-secondary); font-size:12px; line-height:1.7; }
.falcon-learning__details summary { width:fit-content; cursor:pointer; color:var(--text-primary); }
.falcon-learning__details dl { display:grid; gap:10px; margin:12px 0 0; }
.falcon-learning__details dt { color:var(--text-tertiary); }
.falcon-learning__details dd { margin:2px 0 0; white-space:pre-wrap; }
.falcon-learning__details ul { padding:0; margin:0; list-style:none; }
.falcon-learning__details li + li { margin-top:8px; }
.falcon-learning__details p { margin:0; }
.falcon-learning__details code { font-size:11px; color:var(--text-tertiary); }
@media(max-width:767px) { .falcon-learning__grid { grid-template-columns:1fr; grid-template-rows:repeat(2,minmax(18rem,1fr)); overflow:auto; } }
</style>
