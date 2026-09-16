<script setup lang="ts">
import { computed } from 'vue'
import type { GuardianReportSection } from '@/shared/types/guardian'
const props = defineProps<{ sections: GuardianReportSection[]; period?: string }>()
const holdingHeading = computed(() => props.period === 'premarket' ? '持仓预案' : props.period === 'weekly' ? '逐股周回顾与下周计划' : '逐股回顾与下一交易日计划')
const opportunityHeading = computed(() => props.period === 'weekly' ? '下周观察机会' : props.period === 'premarket' ? '今日观察机会' : '下一交易日观察机会')
const main = computed(() => props.sections.filter(s => s.kind !== 'notes'))
const notes = computed(() => props.sections.filter(s => s.kind === 'notes'))
</script>

<template>
  <article class="report-document" aria-label="完整交易报告">
    <template v-for="(section, index) in main" :key="section.heading">
      <h3 v-if="section.kind === 'stock' && main[index - 1]?.kind !== 'stock'" class="document-divider">{{ holdingHeading }}</h3>
      <h3 v-if="section.kind === 'opportunity' && main[index - 1]?.kind !== 'opportunity'" class="document-divider">{{ opportunityHeading }}</h3>
      <section class="document-section" :class="`kind-${section.kind}`">
        <header><h4>{{ section.heading }}</h4><span v-if="section.plans.length">{{ section.plan_date }} 计划 · 尚未下单</span></header>
        <dl v-if="section.stats.length" class="document-stats"><div v-for="stat in section.stats" :key="stat.label"><dt>{{ stat.label }}</dt><dd>{{ stat.value }}</dd></div></dl>
        <p v-for="(text, i) in section.paragraphs" :key="i">{{ text }}</p>
        <div v-if="section.plans.length" class="document-plans"><div v-for="(plan, i) in section.plans" :key="i" class="document-plan"><b>{{ plan.label }}</b><div><p>{{ plan.detail }}</p><el-collapse><el-collapse-item title="失效条件与执行时机" :name="i"><p class="plan-meta">{{ plan.meta }}</p></el-collapse-item></el-collapse></div></div></div>
      </section>
    </template>
    <el-collapse class="document-notes"><el-collapse-item v-for="section in notes" :key="section.heading" :title="section.heading" name="notes"><p v-for="(text, i) in section.paragraphs" :key="i">{{ text }}</p></el-collapse-item></el-collapse>
  </article>
</template>

<style scoped>
.report-document { max-width: 980px; margin: 0 auto; padding: var(--gap-4) 0; font-size: var(--fs-body); line-height: 1.85; }
.document-section { padding: var(--gap-4) 0; border-bottom: 1px solid var(--rule-soft); }
.document-section header { display: flex; justify-content: space-between; align-items: baseline; gap: var(--gap-3); flex-wrap: wrap; }
h4 { margin: 0; font-size: var(--fs-title); font-weight: 600; }
header > span, dt { color: var(--muted); font-size: var(--fs-aux); }
p { margin: var(--gap-2) 0; white-space: pre-line; overflow-wrap: anywhere; }
.document-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr)); gap: var(--gap-3); margin: var(--gap-3) 0; }
dd { margin: var(--gap-1) 0 0; font-family: var(--mono); font-weight: 600; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.kind-account dd { font-size: var(--fs-hero); }
.kind-overview { padding-block: var(--gap-4); }
.document-divider { margin: var(--gap-4) 0 0; padding: var(--gap-2); border: 1px solid var(--rule); border-radius: var(--radius); background: var(--surface-sunken); font-size: var(--fs-body); color: var(--ink); font-weight: 600; }
.document-plan { display: grid; grid-template-columns: 105px minmax(0,1fr); gap: var(--gap-3); border-top: 1px dashed var(--rule-soft); padding-block: var(--gap-2); }
.document-plan > b { font-size: var(--fs-aux); padding-top: var(--gap-2); }
.document-plan :deep(.el-collapse) { border: 0; --el-collapse-header-height: 26px; }
.document-plan :deep(.el-collapse-item__header), .document-plan :deep(.el-collapse-item__wrap) { border: 0; background: transparent; color: var(--muted); }
.document-plan :deep(.el-collapse-item__content) { padding-bottom: var(--gap-2); }
.plan-meta { color: var(--muted); font-size: var(--fs-aux); }
.document-notes { margin-top: var(--gap-4); }
@media(max-width:650px) { .document-plan { grid-template-columns: 1fr; gap: 0; } .document-stats { grid-template-columns: repeat(2,1fr); } }
</style>
