<script setup lang="ts">
import { computed } from 'vue'
import TradingReportDocument from '@/shared/components/TradingReportDocument.vue'
import type { AgentAssessment, AgentRunDetail } from '@/shared/types/stock_agents'
import { actionName, agentMoney, agentTime, phaseName, statusName } from '../agentFormat'
import { diarySummary, isTradeActionKind, renderAgentMarkdown } from './agentHistoryDisplay'

const props = defineProps<{ run: AgentRunDetail }>()
const result = computed(() => props.run.detail)
const original = computed(() => result.value.summary || props.run.summary || props.run.sections?.find(section => section.kind === 'overview')?.paragraphs.join('\n') || '')
const conclusion = computed(() => diarySummary(original.value, 280))
const modern = computed(() => Boolean(result.value.assessments?.length || result.value.research_plan_structured || result.value.detail))
const legacySections = computed(() => (props.run.sections ?? []).filter(section => section.kind !== 'overview' && !['actions', 'decisions'].includes(section.kind)))
const names = computed(() => {
  const map = new Map<string, string>()
  for (const [code, quote] of Object.entries(result.value.quotes ?? {})) if (quote.name && quote.name !== code) map.set(code, quote.name)
  for (const row of [...(result.value.candidate_scope?.candidates ?? []), ...(result.value.candidate_scope?.sources ?? []),
    ...(result.value.decisions ?? []), ...(result.value.fills ?? [])]) if (row.name && row.name !== row.code) map.set(row.code, row.name)
  return map
})
const stockName = (code: string) => names.value.get(code) || code
const assessments = computed<AgentAssessment[]>(() => {
  const rows = [...(result.value.assessments ?? [])]
  for (const code of result.value.assessment_coverage?.unreviewed_codes ?? []) if (!rows.some(row => row.code === code)) rows.push({
    code, stance: 'unreviewed', summary: '本轮没有保存该股票的独立研判。', focus: false, evidence_refs: [],
  })
  return rows
})
const stanceLabel = (stance: AgentAssessment['stance']) => ({ participate: '可参与', wait: '等待', avoid: '回避', exit: '退出判断', unreviewed: '未研判' }[stance])
const decisionLabel = (action: string) => isTradeActionKind(action) ? `拟${actionName(action)}` : actionName(action)
const fillLabel = (fill: NonNullable<AgentRunDetail['detail']['fills']>[number]) =>
  fill.origin === 'legacy_conversion' || fill.quote_source === 'legacy_conversion' ? '历史折算（非新成交）' : `已模拟${actionName(fill.action || fill.side)}`
const evidenceHref = (reference: string) => /^https?:\/\//i.test(reference) ? reference : undefined
const learningGroups = computed(() => [
  { title: '本轮沉淀经验', items: result.value.learning?.lessons ?? [] },
  { title: '选股与判分建议', items: result.value.learning?.optimization_proposals ?? [] },
].filter(group => group.items.length))
const originals = computed(() => {
  const texts = [['保存摘要', original.value], ['原有完整分析', result.value.analysis || ''], ['原有正文', result.value.body || ''], ['原有研究计划', result.value.research_plan || '']]
  const seen = new Set<string>()
  const rows = []
  for (const [title, text] of texts) if (text && !seen.has(text)) {
    seen.add(text); rows.push({ title: title!, text, html: renderAgentMarkdown(text) })
  }
  return rows
})
</script>

<template>
  <article class="agent-report-document" aria-label="智能体工作报告">
    <header class="agent-report-title"><p>保存于 {{ agentTime(run.started_at) }} · {{ statusName(run.status) }}<span v-if="result.analysis_only"> · 研究</span></p><h2>{{ phaseName(run.phase) }}</h2></header>
    <section class="agent-report-conclusion"><h3>本轮结论</h3><p>{{ conclusion || '本轮没有保存文字结论。' }}</p></section>
    <p v-if="result.error" class="agent-report-error">{{ result.error }}</p>
    <section v-if="result.detail" class="agent-report-context"><h3>市场与本轮变化</h3><dl><div><dt>市场判断</dt><dd>{{ result.detail.market_summary || '未记录' }}</dd></div><div><dt>本轮变化</dt><dd>{{ result.detail.changes || '未记录' }}</dd></div><div><dt>后续重点</dt><dd>{{ result.detail.next_steps || '未记录' }}</dd></div></dl></section>

    <section v-if="assessments.length" class="agent-report-assessments" aria-label="分股票研判">
      <div class="agent-report-section-head"><h3>分股票研判</h3><span v-if="result.assessment_coverage">已研判 {{ result.assessment_coverage.reviewed }} / {{ result.assessment_coverage.total }} · 未研判 {{ result.assessment_coverage.unreviewed_codes.length }}</span><span v-else>本轮保存 {{ assessments.length }} 份判断 · 覆盖范围未记录</span></div>
      <div class="agent-report-stock-grid"><section v-for="stock in assessments" :key="stock.code" class="agent-report-stock" :data-stance="stock.stance"><header><h4>{{ stockName(stock.code) }} <small v-if="stockName(stock.code) !== stock.code">{{ stock.code }}</small></h4><span class="agent-report-stance">{{ stanceLabel(stock.stance) }}</span><span v-if="stock.focus" class="agent-report-focus">重点跟进</span></header><p>{{ stock.summary }}</p><p v-if="stock.expected_entry_price != null" class="agent-report-note">预期进入价 {{ stock.expected_entry_price.toFixed(2) }} 元</p><p v-if="stock.data_status === 'missing'" class="agent-report-error">本轮数据缺失</p><details class="agent-report-evidence"><summary>证据引用 · {{ stock.evidence_refs.length }}</summary><ul v-if="stock.evidence_refs.length"><li v-for="reference in stock.evidence_refs" :key="reference"><a v-if="evidenceHref(reference)" :href="evidenceHref(reference)" target="_blank" rel="noopener noreferrer">{{ reference }}</a><code v-else>{{ reference }}</code></li></ul><p v-else>本轮未保存证据引用。</p></details></section></div>
    </section>

    <section class="agent-report-execution" aria-label="实际模拟成交回执"><h3>实际成交</h3><div v-if="result.fills?.length" class="agent-report-stock-grid"><section v-for="(fill, index) in result.fills" :key="index" class="agent-report-stock"><header><h4>{{ stockName(fill.code) }} <small>{{ fill.code }}</small></h4><span class="agent-report-stance is-filled">{{ fillLabel(fill) }}</span></header><dl class="agent-report-fill"><div><dt>股数</dt><dd>{{ fill.quantity?.toLocaleString() ?? '未保存' }}</dd></div><div><dt>成交价 / 元</dt><dd>{{ agentMoney(fill.price_cents) }}</dd></div><div><dt>费用 / 元</dt><dd>{{ agentMoney(fill.fees_cents) }}</dd></div><div><dt>成交时间</dt><dd>{{ (fill.occurred_at || fill.at) ? agentTime(fill.occurred_at || fill.at) : '未保存' }}</dd></div></dl><p v-if="fill.reason">{{ fill.reason }}</p></section></div><p v-else class="agent-report-note">{{ Array.isArray(result.fills) ? '本轮无模拟成交。' : '旧记录未附成交回执，具体成交请以成交记录为准。' }}</p></section>
    <section v-if="result.rejects?.length" class="agent-report-rejects" aria-label="拒单与未执行"><h3>未执行</h3><section v-for="(reject, index) in result.rejects" :key="index" class="agent-report-stock"><header><h4>{{ reject.code ? stockName(reject.code) : '执行请求' }}</h4><span class="agent-report-stance is-rejected">{{ reject.action ? actionName(reject.action) : '请求' }} · 未执行</span></header><p>{{ reject.reason || '本轮未保存拒单原因。' }}</p></section></section>
    <section v-if="result.decisions?.length" class="agent-report-decisions" aria-label="决策与观察管理"><h3>决策与观察管理</h3><div class="agent-report-stock-grid"><section v-for="(decision, index) in result.decisions" :key="index" class="agent-report-stock"><header><h4>{{ stockName(decision.code) }}</h4><span class="agent-report-stance">{{ decisionLabel(decision.action) }}</span><small>{{ isTradeActionKind(decision.action) ? '交易意图' : ['watch','unwatch'].includes(decision.action) ? '观察管理' : '持仓判断' }}</small></header><p>{{ decision.reason }}</p><p v-if="decision.quantity" class="agent-report-note">请求数量 {{ decision.quantity.toLocaleString() }} 股</p></section></div></section>

    <section v-if="result.research_plan_structured" class="agent-report-plan" aria-label="接续研究计划"><div class="agent-report-section-head"><h3>接续研究计划</h3><span v-if="result.research_plan_structured.next_trade_date">{{ result.research_plan_structured.next_trade_date }}</span></div><p>{{ result.research_plan_structured.market_view }}</p><div class="agent-report-stock-grid"><section v-for="stock in result.research_plan_structured.stocks" :key="stock.code" class="agent-report-stock"><h4>{{ stockName(stock.code) }}</h4><dl><div><dt>参与条件</dt><dd>{{ stock.entry_condition || '未给出' }}</dd></div><div><dt>退出条件</dt><dd>{{ stock.exit_condition || '未给出' }}</dd></div><div><dt>失效条件</dt><dd>{{ stock.invalidation || '未给出' }}</dd></div><div><dt>下次复核</dt><dd>{{ stock.next_check || '未给出' }}</dd></div></dl></section></div></section>
    <section v-for="group in learningGroups" :key="group.title" class="agent-report-learning"><h3>{{ group.title }}</h3><div class="agent-report-stock-grid"><section v-for="lesson in group.items" :key="lesson.id" class="agent-report-stock"><h4>{{ lesson.title }}</h4><p>{{ lesson.finding }}</p><p class="agent-report-note">{{ {pending:'待验证',supported:'有证据支持',rejected:'已被否定'}[lesson.status] }} · {{ lesson.sample_size }} 个{{ {executed:'模拟成交',observed:'观察',hypothetical:'假设'}[lesson.sample_basis] }}样本</p><details class="agent-report-evidence"><summary>证据与验证计划</summary><dl><div><dt>适用条件</dt><dd>{{ lesson.conditions }}</dd></div><div><dt>样本口径</dt><dd>{{ lesson.sample_definition }}</dd></div><div><dt>验证计划</dt><dd>{{ lesson.validation_plan }}</dd></div></dl><ul><li v-for="reference in lesson.evidence_refs" :key="reference"><code>{{ reference }}</code></li></ul><p v-for="(example,index) in lesson.positive_examples" :key="`positive-${index}`">支持：{{ example.interpretation }} · {{ example.evidence_ref }}</p><p v-for="(example,index) in lesson.counter_examples" :key="`counter-${index}`">反例：{{ example.interpretation }} · {{ example.evidence_ref }}</p></details></section></div></section>
    <TradingReportDocument v-if="!modern && legacySections.length" :sections="legacySections" />
    <details v-if="originals.length" class="agent-report-original">
      <summary>查看保存的原文</summary>
      <section v-for="item in originals" :key="item.title"><h4>{{ item.title }}</h4><div class="agent-report-markdown" v-html="item.html" /><details class="agent-report-source"><summary>原始文本</summary><pre>{{ item.text }}</pre></details></section>
    </details>
    <footer v-if="result.usage" class="agent-report-usage"><span v-if="result.usage.model">{{ result.usage.model }}</span><span v-if="result.usage.elapsed_ms != null">耗时 {{ (result.usage.elapsed_ms / 1000).toFixed(1) }} 秒</span><span v-if="result.usage.tool_calls != null">工具 {{ result.usage.tool_calls }} 次</span></footer>
  </article>
</template>

<style scoped>
.agent-report-document { min-width:0; max-width:1040px; margin:0 auto; font-size:14px; line-height:1.8; }
.agent-report-document :deep(.trading-report) { max-width:none; border:0; padding:0; background:transparent; }
.agent-report-conclusion h2 { margin:0 0 12px; font-size:18px; font-weight:650; }
.agent-report-title { margin:0 0 24px; padding-bottom:18px; border-bottom:1px solid var(--border-subtle); }
.agent-report-title h2 { margin:6px 0; font-size:24px; font-weight:650; }.agent-report-title p,.agent-report-title>span { margin:0; color:var(--text-tertiary); font-size:12px; }
.agent-report-document h3 { margin:0 0 12px; font-size:16px; font-weight:650; }.agent-report-document h4 { margin:0; font-size:14px; font-weight:600; }
.agent-report-document > section { margin-top:24px; }.agent-report-document p { white-space:pre-wrap; overflow-wrap:anywhere; }
.agent-report-conclusion { padding:18px 20px; border-radius:10px; background:var(--surface-sunken); }.agent-report-conclusion p { margin:0; font-size:16px; line-height:1.8; }
.agent-report-section-head { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:8px; }.agent-report-section-head>span { font-size:12px; color:var(--text-tertiary); }
.agent-report-stock-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }.agent-report-stock { min-width:0; padding:16px 18px; border:1px solid var(--border-subtle); border-radius:10px; background:var(--surface); }
.agent-report-stock + .agent-report-stock { margin-top:0; }.agent-report-rejects>.agent-report-stock + .agent-report-stock { margin-top:10px; }
.agent-report-stock header { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }.agent-report-stock header h4 { flex:1; min-width:0; }.agent-report-stock small { color:var(--text-tertiary); font:11px var(--mono); }
.agent-report-stance,.agent-report-focus { display:inline-flex; padding:2px 7px; border-radius:5px; background:var(--surface-sunken); color:var(--text-secondary); font-size:11px; white-space:nowrap; }.agent-report-focus { color:var(--seal-ink); background:var(--seal-soft); }
.is-filled { color:var(--seal-ink); background:var(--seal-soft); }.is-rejected,.agent-report-error { color:var(--warn-ink); }
.agent-report-note { color:var(--text-tertiary); font-size:12px; }.agent-report-stock p { margin:10px 0 0; }
.agent-report-document dl { display:grid; gap:10px; margin:12px 0 0; }.agent-report-document dl>div { display:grid; grid-template-columns:90px minmax(0,1fr); gap:12px; }.agent-report-document dt { font-size:12px; color:var(--text-tertiary); }.agent-report-document dd { margin:0; white-space:pre-wrap; overflow-wrap:anywhere; }
.agent-report-document .agent-report-fill { grid-template-columns:repeat(2,minmax(0,1fr)); }.agent-report-document .agent-report-fill>div { display:block; }.agent-report-fill dd { font-variant-numeric:tabular-nums; }
.agent-report-evidence { margin-top:14px; padding-top:12px; border-top:1px solid var(--border-subtle); font-size:12px; }.agent-report-evidence summary { cursor:pointer; width:fit-content; color:var(--text-secondary); }.agent-report-evidence ul { margin:10px 0 0; padding:0; list-style:none; }.agent-report-evidence li+li { margin-top:8px; }.agent-report-evidence code,.agent-report-evidence a { overflow-wrap:anywhere; }.agent-report-evidence a { color:var(--seal-ink); }
.agent-report-usage { display:flex; flex-wrap:wrap; gap:8px 16px; padding-top:20px; font-size:11px; color:var(--text-tertiary); }
.agent-report-original { margin-top:24px; padding:16px 18px; border:1px solid var(--border-subtle); border-radius:10px; background:var(--surface-sunken); }
.agent-report-original > summary,.agent-report-source > summary { cursor:pointer; width:fit-content; font-size:13px; font-weight:600; }
.agent-report-original > .agent-report-markdown { padding-top:16px; }
.agent-report-source { margin-top:16px; color:var(--text-secondary); }
.agent-report-source pre { white-space:pre-wrap; overflow-wrap:anywhere; font:12px/1.8 var(--mono); }
.agent-report-markdown { min-width:0; overflow-wrap:anywhere; }
.agent-report-markdown :deep(p) { white-space:pre-wrap; margin:0 0 12px; }
.agent-report-markdown :deep(h1),.agent-report-markdown :deep(h2) { margin:20px 0 10px; font-size:18px; line-height:1.5; }
.agent-report-markdown :deep(h3),.agent-report-markdown :deep(h4) { margin:16px 0 8px; font-size:15px; line-height:1.6; }
.agent-report-markdown :deep(table) { width:100%; border-collapse:collapse; table-layout:fixed; font-size:13px; }
.agent-report-markdown :deep(th),.agent-report-markdown :deep(td) { padding:9px 12px; border:1px solid var(--border-subtle); text-align:left; overflow-wrap:anywhere; }
.agent-report-markdown :deep(pre) { white-space:pre-wrap; overflow-wrap:anywhere; padding:14px; background:var(--surface-sunken); border-radius:8px; }
.agent-report-markdown :deep(a) { color:var(--seal-ink); text-decoration:underline; text-underline-offset:3px; }
.agent-report-markdown :deep(blockquote) { padding-left:14px; border-left:3px solid var(--border-subtle); margin:12px 0; color:var(--text-secondary); }
@media(max-width:767px) { .agent-report-document { font-size:13px; }.agent-report-stock-grid { grid-template-columns:minmax(0,1fr); }.agent-report-title h2 { font-size:21px; }.agent-report-conclusion { padding:14px; }.agent-report-conclusion p { font-size:14px; }.agent-report-stock { padding:14px; } .agent-report-original { padding:12px; } }
</style>
