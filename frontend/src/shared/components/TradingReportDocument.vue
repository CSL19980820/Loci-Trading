<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { Button } from '@/shared/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/shared/components/ui/collapsible'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import type { GuardianReportSection } from '@/shared/types/guardian'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
const mobile = useMobileLayout()

const props = defineProps<{ sections: GuardianReportSection[]; title?: string; metadata?: string }>()
const opened = ref(false)
const feedback = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
const isAppendix = (s: GuardianReportSection) => Boolean(s.detail && !s.plans.length &&
  (['account', 'notes'].includes(s.kind) || (s.kind === 'stock' && !s.paragraphs.length)))
const available = computed(() => props.sections.filter(s => s.paragraphs.length || s.stats.length || s.plans.length))
const body = computed(() => available.value.filter(s => !isAppendix(s)).sort((a,b) => rank(a)-rank(b)))
function rank(s: GuardianReportSection) { return s.kind === 'overview' ? 0 : s.kind === 'account' ? 1 : 2 }
const groups = computed(() => [
  { key:'body', detail:false, sections:body.value },
  { key:'appendix', detail:true, sections:available.value.filter(isAppendix) },
].filter(group => group.sections.length))
function tone(stat: {label:string;value:string}) {
  if (!/盈亏|回撤|收益/.test(stat.label)) return ''
  const number = Number(stat.value.replace(/[,元%]/g,'').replace('−','-'))
  return Number.isFinite(number) ? number > 0 ? 'gain' : number < 0 ? 'loss' : '' : ''
}
async function copyBody() {
  const lines = [props.title, props.metadata]
  for (const section of body.value) {
    if (section.kind !== 'overview' && section.kind !== 'account') lines.push(section.heading)
    if (section.stats.length) lines.push(section.stats.map(s => `${s.label}：${s.value}`).join(' · '))
    lines.push(...section.paragraphs)
    if (section.plans.length) lines.push(`${section.plan_date || '后续交易日'}条件计划 · 尚未下单`)
    for (const plan of section.plans) lines.push(`${plan.label}：${plan.detail}\n${plan.meta}`)
  }
  try { await navigator.clipboard.writeText(lines.filter(Boolean).join('\n\n')); feedback.value = '已复制' }
  catch { feedback.value = '复制失败，请直接选中文字复制' }
  clearTimeout(timer); timer = setTimeout(() => feedback.value = '', 2400)
}
watch(() => props.sections, () => { opened.value = false; feedback.value = '' })
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <article class="trading-report" aria-label="交易报告">
    <header v-if="title || metadata" class="report-header"><h3 v-if="title">{{ title }}</h3><p v-if="metadata" class="report-metadata">{{ metadata }}</p></header>
    <Collapsible v-for="group in groups" :key="group.key" :open="!group.detail || opened" class="report-group" :class="{ appendix:group.detail }" @update:open="opened = $event">
      <CollapsibleTrigger v-if="group.detail" class="appendix-trigger"><span aria-hidden="true">{{ opened ? '⌄' : '›' }}</span>账务与成交依据</CollapsibleTrigger>
      <CollapsibleContent>
        <section v-for="(section,index) in group.sections" :key="section.kind + ':' + section.heading + ':' + index" class="report-section" :class="['kind-' + section.kind, {'account-brief':section.kind === 'account' && !section.detail}]">
          <header v-if="section.kind !== 'overview' && !(section.kind === 'account' && !section.detail)" class="section-header"><h4>{{ section.heading }}</h4><span v-if="section.plans.length">{{ section.plan_date || '后续交易日' }} · 条件计划，尚未下单</span></header>
          <dl v-if="section.stats.length" class="report-stats"><div v-for="stat in section.stats" :key="stat.label"><dt>{{ stat.label }}</dt><dd :class="tone(stat)">{{ stat.value }}</dd></div></dl>
          <p v-for="(paragraph,i) in section.paragraphs" :key="i" class="report-paragraph">{{ paragraph }}</p>
          <div v-if="mobile && section.plans.length" class="report-mobile-plans"><section v-for="(plan,i) in section.plans" :key="i"><h5>{{ plan.label }}</h5><p>{{ plan.detail }}</p><p v-if="plan.meta" class="report-mobile-condition">{{ plan.meta }}</p></section></div>
          <div v-else-if="section.plans.length" class="report-plans"><Table><TableHeader><TableRow><TableHead>判断 / 计划</TableHead><TableHead>触发、失效与执行时机</TableHead></TableRow></TableHeader><TableBody><TableRow v-for="(plan,i) in section.plans" :key="i" class="document-plan"><TableCell class="plan-label">{{ plan.label }}</TableCell><TableCell><p>{{ plan.detail }}</p><p class="plan-conditions">{{ plan.meta }}</p></TableCell></TableRow></TableBody></Table></div>
        </section>
      </CollapsibleContent>
    </Collapsible>
    <footer v-if="body.length" class="report-footer"><span role="status">{{ feedback }}</span><Button access="read" variant="ghost" size="sm" @click="copyBody">复制正文</Button></footer>
  </article>
</template>

<style scoped>
.trading-report{font-family:"Microsoft YaHei","PingFang SC",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:940px;margin:0 auto;padding:24px 28px 10px;border:1px solid var(--rule-soft,var(--line));border-radius:9px;background:var(--surface);color:var(--ink);font-size:15px;line-height:1.75;min-width:0}
.report-header{padding-bottom:8px}.report-header h3{font-family:inherit;margin:0;font-size:22px;font-weight:600;line-height:1.45}.report-metadata{margin:7px 0 0;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.report-section{padding:18px 0;border-bottom:1px solid var(--rule-soft,var(--line));min-width:0}.report-section:last-child{border-bottom:0}.section-header{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:8px 16px;margin-bottom:9px}.section-header h4{font-family:inherit;margin:0;font-size:14px;font-weight:600;line-height:1.7;overflow-wrap:anywhere}.section-header>span{font-size:12px;color:var(--muted)}
.report-paragraph{margin:0 0 9px;white-space:pre-line;overflow-wrap:anywhere}.report-paragraph:last-child{margin-bottom:0}.kind-overview{padding:12px 0 16px;border:0}.kind-overview .report-paragraph{font-size:16px;font-weight:550;line-height:1.75}.account-brief{padding:0 0 5px;border:0}
.report-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:12px 18px;margin:0}.report-stats dt{font-size:12px;color:var(--muted)}.report-stats dd{margin:3px 0 0;font-size:15px;font-weight:550;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.account-brief .report-stats{grid-template-columns:repeat(3,minmax(0,1fr));background:var(--surface-sunken);padding:11px 16px;border-radius:6px;gap:16px}.account-brief dd{font-size:17px}.gain{color:var(--up)}.loss{color:var(--down)}
.report-plans{margin-top:10px}.report-plans :deep(table){width:100%;font-size:15px;line-height:1.75;table-layout:fixed}.report-plans :deep(th){font-size:12px;color:var(--muted);height:auto;padding:6px 10px;background:var(--surface-sunken);font-weight:400}.report-plans :deep(th:first-child){width:190px}.report-plans :deep(td){padding:11px 10px;vertical-align:top;white-space:normal;overflow-wrap:anywhere}.report-plans :deep(tr:last-child){border-bottom:0}.report-plans :deep(.plan-label){font-size:13px;font-weight:550}.report-plans p{white-space:pre-line;margin:0}.report-plans .plan-conditions{margin-top:7px;color:var(--muted);font-size:13px}.kind-warning{color:var(--warn-ink)}
.appendix{margin-top:12px;border-top:1px solid var(--rule-soft,var(--line))}.appendix-trigger{display:flex;align-items:center;gap:7px;padding:12px 0;background:transparent;border:0;cursor:pointer;color:var(--muted);font-size:12px}.appendix-trigger:focus-visible{outline:2px solid var(--ink);outline-offset:3px}.appendix-trigger>span{font-size:17px;line-height:1}.appendix .report-section{padding:14px 0}.appendix .report-paragraph{font-size:13px}.appendix .report-stats dt{font-size:11px}.appendix .report-stats dd{font-size:13px}.report-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-top:7px;color:var(--muted);font-size:12px}.report-footer button{font-size:12px;font-weight:400}
@media(max-width:650px){.trading-report{padding:18px 18px 9px}.report-header h3{font-size:21px}.report-metadata{font-size:11px}.kind-overview .report-paragraph{font-size:15px}.report-section{padding:16px 0}.account-brief .report-stats{padding:10px;gap:8px}.account-brief .report-stats>div+div{padding-left:8px}.account-brief dt{font-size:11px}.account-brief dd{font-size:14px}.report-plans :deep(thead){display:none}.report-plans :deep(tbody){display:block}.report-plans :deep(tr){display:block;padding:11px 0}.report-plans :deep(td){display:block;border:0;padding:0}.report-plans :deep(.plan-label){margin-bottom:6px}.report-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
<style scoped>
.report-mobile-plans { display:flex; flex-direction:column; margin-top:10px; gap:10px; }
.report-mobile-plans>section { padding:10px 12px; background:var(--surface-sunken); border-radius:7px; }
.report-mobile-plans h5 { font:600 13px/1.6 var(--font); margin:0 0 6px; color:var(--text-primary); }
.report-mobile-plans p { font-size:14px; line-height:1.85; white-space:pre-line; overflow-wrap:anywhere; margin:0; }
.report-mobile-plans p.report-mobile-condition { margin-top:8px; color:var(--text-secondary); font-size:12px; }
@media(max-width:767px) {
 .trading-report { width:100%; max-width:none; padding:14px 14px 8px; border:0; font-size:14px; line-height:1.85; }
 .report-header { display:flex; flex-wrap:wrap; align-items:baseline; gap:3px 9px; padding-bottom:8px; }
 .report-header h3 { font-size:16px; }.report-metadata { margin:0; font-size:11px; }
 .section-header h4 { font-size:15px; }.section-header>span { font-size:11px; }
 .kind-overview .report-paragraph { font-size:15px; line-height:1.85; font-weight:500; }
 .account-brief .report-stats { grid-template-columns:repeat(2,minmax(0,1fr)); background:transparent; padding:0; gap:10px; }
 .account-brief .report-stats>div+div { border:0; padding:0; }
 .report-section { padding:14px 0; }
}
</style>
