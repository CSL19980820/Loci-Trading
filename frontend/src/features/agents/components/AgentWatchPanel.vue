<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowUpRight, Telescope } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import type { AgentWatch } from '@/shared/types/stock_agents'
import { agentMoney, agentTime } from '../agentFormat'

const props = defineProps<{ stocks: AgentWatch[]; selectedToday?: number; selectionLimit?: number; watchLimit?: number; falcon?: boolean }>()
const selectedCode = ref<string | null>(null)
const selected = computed(() => props.stocks.find(row => row.code === selectedCode.value) ?? null)
const detailOpen = computed({ get: () => selected.value != null, set: (open: boolean) => { if (!open) selectedCode.value = null } })
const time = (value?: string | null) => value ? agentTime(value) : '—'
const date = (value?: string | null) => {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : new Intl.DateTimeFormat('sv-SE', { timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit' }).format(parsed)
}
const fullTime = (value?: string | null) => value && date(value) !== '—' ? `${date(value)} ${new Intl.DateTimeFormat('en-GB', { timeZone:'Asia/Shanghai', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false }).format(new Date(value))}` : '—'
watch(selected, row => { if (!row) selectedCode.value = null })
</script>

<template>
  <section class="watch-panel" aria-label="观察标的明细">
    <header class="watch-head"><div class="watch-title"><h3>观察名单</h3><UiBadge variant="secondary">{{ stocks.length }}</UiBadge><UiBadge v-if="falcon" variant="secondary">近5个交易日</UiBadge></div><span v-if="!falcon" class="watch-head-meta">今日入选 {{ selectedToday || 0 }}<template v-if="selectionLimit"> / {{ selectionLimit }}</template><template v-if="watchLimit"> · 人工观察上限 {{ watchLimit }}</template></span></header>
    <div v-if="!stocks.length" class="watch-empty"><Telescope aria-hidden="true" /><strong>尚无观察标的</strong><p>系统候选进入观察后，在这里跟踪进场条件与最新评估。</p></div>
    <template v-else>
      <Table class="watch-table">
        <colgroup><col style="width:180px"><col style="width:104px"><col style="width:92px"><col style="width:92px"><col style="width:126px"><col style="width:140px"><col></colgroup>
        <TableHeader><TableRow><TableHead>股票</TableHead><TableHead>观察日期</TableHead><TableHead class="number">观察价 / 元</TableHead><TableHead class="number">现价 / 元</TableHead><TableHead class="number">预期进入价 / 元</TableHead><TableHead>最新评估时间</TableHead><TableHead class="review-column">最新评估</TableHead></TableRow></TableHeader>
        <TableBody><TableRow v-for="row in stocks" :key="row.code" class="watch-row" @click="selectedCode = row.code">
          <TableCell><Button access="read" variant="ghost" class="stock-identity" :aria-label="`查看 ${row.name || row.code} 观察详情`" @click.stop="selectedCode = row.code"><strong>{{ row.name || row.code }}</strong><small>{{ row.code }}</small><ArrowUpRight aria-hidden="true" /></Button></TableCell>
          <TableCell class="date-cell" :title="row.observed_at || undefined">{{ date(row.observed_at) }}</TableCell><TableCell class="number">{{ agentMoney(row.observed_price_cents) }}</TableCell><TableCell class="number" :title="row.current_price_at ? `报价时间 ${time(row.current_price_at)}` : undefined">{{ agentMoney(row.current_price_cents) }}</TableCell><TableCell class="number">{{ agentMoney(row.expected_entry_price_cents) }}</TableCell><TableCell class="date-cell" :title="row.reviewed_at || undefined">{{ time(row.reviewed_at) }}</TableCell><TableCell class="review-column"><p class="review-preview" :title="row.review_reason || undefined">{{ row.review_reason || '—' }}</p></TableCell>
        </TableRow></TableBody>
      </Table>
      <ul class="watch-mobile" aria-label="观察列表"><li v-for="row in stocks" :key="row.code"><button type="button" class="watch-mobile-row" :aria-label="`查看 ${row.name || row.code} 观察详情`" @click="selectedCode = row.code">
        <span class="mobile-stock"><span class="stock-identity"><strong>{{ row.name || row.code }}</strong><small>{{ row.code }}</small></span><ArrowUpRight aria-hidden="true" /></span>
        <span class="mobile-facts"><span><em>观察日期</em><b>{{ date(row.observed_at) }}</b></span><span><em>观察价</em><b>{{ agentMoney(row.observed_price_cents) }}</b></span><span><em>现价</em><b>{{ agentMoney(row.current_price_cents) }}</b></span><span><em>预期进入价</em><b>{{ agentMoney(row.expected_entry_price_cents) }}</b></span></span>
        <span class="mobile-review"><small>最新评估 {{ time(row.reviewed_at) }}</small><span class="review-preview">{{ row.review_reason || '—' }}</span></span>
      </button></li></ul>
    </template>
    <Dialog v-model:open="detailOpen">
      <DialogContent class="watch-detail-dialog sm:max-w-[1080px]" style="display:flex;flex-direction:column;height:min(760px,90dvh);max-height:90dvh;overflow:hidden;gap:16px" data-agent-detail-dialog>
        <DialogHeader v-if="selected" class="text-left" style="flex:none;padding-right:26px"><DialogTitle class="detail-stock"><span>{{ selected.name || selected.code }}</span><small>{{ selected.code }}</small><UiBadge variant="secondary">观察详情</UiBadge></DialogTitle><DialogDescription class="sr-only">{{ selected.name || selected.code }}观察详情</DialogDescription></DialogHeader>
        <div v-if="selected" class="watch-detail-body" data-agent-detail-scroll>
          <dl class="detail-metrics">
            <div><dt>观察日期</dt><dd :title="selected.observed_at || undefined">{{ fullTime(selected.observed_at) }}</dd></div><div><dt>观察价 / 元</dt><dd>{{ agentMoney(selected.observed_price_cents) }}</dd></div><div><dt>现价 / 元</dt><dd>{{ agentMoney(selected.current_price_cents) }}</dd></div><div><dt>预期进入价 / 元</dt><dd>{{ agentMoney(selected.expected_entry_price_cents) }}</dd></div>
            <div><dt>最近报价</dt><dd :title="selected.current_price_at || undefined">{{ fullTime(selected.current_price_at) }}</dd></div><div><dt>最新评估时间</dt><dd :title="selected.reviewed_at || undefined">{{ fullTime(selected.reviewed_at) }}</dd></div><div><dt>来源信号日期</dt><dd>{{ selected.source_signal_date || '—' }}</dd></div><div><dt>来源有效至</dt><dd>{{ selected.source_expires_on || '—' }}</dd></div>
          </dl>
          <section class="detail-section"><h4>最新评估</h4><p>{{ selected.review_reason || '—' }}</p></section>
          <section class="detail-section"><h4>观察依据</h4><p>{{ selected.reason || '—' }}</p></section>
          <section class="detail-section"><h4>参与条件</h4><p>{{ selected.entry_condition || '—' }}</p></section>
          <section class="detail-section"><h4>撤出观察条件</h4><p>{{ selected.exit_condition || '—' }}</p></section>
          <section v-if="selected.source_reason" class="detail-section"><h4>系统来源</h4><p>{{ selected.source_reason }}</p></section>
          <section v-if="selected.source_refs?.length" class="detail-section"><h4>来源记录</h4><ul class="source-list"><li v-for="(source,index) in selected.source_refs" :key="index"><div><strong>{{ source.strategy_slug || source.source || '来源待核对' }}</strong><span>{{ source.signal_date || '—' }}<template v-if="source.expires_on"> · 有效至 {{ source.expires_on }}</template><template v-if="source.score != null"> · 评分 {{ source.score }}</template></span></div><p>{{ source.reason || '—' }}</p></li></ul></section>
        </div>
      </DialogContent>
    </Dialog>
  </section>
</template>

<style scoped>
.watch-panel { display:flex; flex:1 1 0%; flex-direction:column; min-width:0; min-height:0; overflow:hidden; border:1px solid var(--border-subtle); border-radius:var(--radius-lg); background:var(--surface); }.watch-head { display:flex; flex:none; align-items:center; flex-wrap:wrap; justify-content:space-between; gap:8px 16px; padding:13px 16px; border-bottom:1px solid var(--border-subtle); }.watch-title { display:flex; align-items:center; gap:8px; }.watch-title h3 { margin:0; font-size:14px; font-weight:650; }.watch-head-meta { color:var(--text-tertiary); font:11px/1.5 var(--mono); }.watch-empty { display:flex; flex:1; flex-direction:column; align-items:center; justify-content:center; gap:10px; padding:40px 16px; color:var(--text-tertiary); text-align:center; }.watch-empty svg { width:30px; height:30px; opacity:.45; }.watch-empty strong { color:var(--text-secondary); font-size:14px; font-weight:550; }.watch-empty p { margin:0; font-size:12px; }
.watch-panel :deep([data-slot=table-container]) { flex:1 1 0%; min-height:0; overscroll-behavior:contain; scrollbar-width:thin; }.watch-panel :deep(.watch-table) { table-layout:fixed; min-width:1000px; }.watch-panel :deep(.watch-table th) { position:sticky; top:0; z-index:1; height:38px; background:var(--surface-sunken); color:var(--text-tertiary); font-size:11px; font-weight:500; white-space:nowrap; }.watch-panel :deep(.watch-table td) { height:67px; padding:10px 12px; font-size:12px; }.watch-panel :deep(.watch-table th:first-child),.watch-panel :deep(.watch-table td:first-child) { padding-left:16px; }.watch-row { cursor:pointer; }.number { text-align:right; font-family:var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap; }.date-cell { font:11px/1.5 var(--mono); white-space:nowrap; }.stock-identity { display:inline-flex; align-items:baseline; gap:7px; height:auto; padding:0; white-space:nowrap; box-shadow:none; background:transparent; }.stock-identity strong { font-size:13px; font-weight:600; }.stock-identity small { color:var(--text-tertiary); font:11px/1.4 var(--mono); }.stock-identity svg { align-self:center; width:12px; height:12px; opacity:.4; }.review-column { white-space:normal; }.review-preview { display:-webkit-box; max-width:100%; white-space:normal; margin:0; overflow:hidden; -webkit-line-clamp:2; -webkit-box-orient:vertical; color:var(--text-secondary); font-size:12px; line-height:1.7; overflow-wrap:anywhere; }.watch-mobile { display:none; }
.watch-detail-dialog[data-slot=dialog-content] { display:flex; flex-direction:column; height:min(760px,90dvh); max-height:90dvh; gap:16px; overflow:hidden; }.watch-detail-dialog :deep([data-slot=dialog-header]) { flex:none; padding-right:26px; }.detail-stock { display:flex; align-items:baseline; flex-wrap:wrap; gap:10px; }.detail-stock small { color:var(--text-tertiary); font:13px/1.4 var(--mono); }.watch-detail-body { flex:1 1 0%; min-height:0; overflow:auto; overscroll-behavior:contain; }.detail-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:18px 24px; margin:0; padding:18px 20px; border-radius:var(--radius-lg); background:var(--surface-sunken); }.detail-metrics dt { color:var(--text-tertiary); font-size:11px; }.detail-metrics dd { margin:6px 0 0; font:600 15px/1.5 var(--mono); overflow-wrap:anywhere; }.detail-section { padding:18px 0; border-bottom:1px solid var(--border-subtle); }.detail-section h4 { margin:0 0 8px; font-size:13px; font-weight:600; }.detail-section p { margin:0; color:var(--text-secondary); font-size:13px; line-height:1.85; white-space:pre-wrap; overflow-wrap:anywhere; }.source-list { list-style:none; margin:0; padding:0; }.source-list li { padding:12px 0; border-bottom:1px solid var(--border-subtle); }.source-list li:last-child { border:0; }.source-list li>div { display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 14px; margin-bottom:6px; }.source-list strong { font-size:12px; font-weight:550; }.source-list span { color:var(--text-tertiary); font:11px/1.5 var(--mono); }
@media(max-width:767px) { .watch-head { padding:11px 12px; }.watch-title h3 { font-size:13px; }.watch-panel :deep([data-slot=table-container]) { display:none; }.watch-mobile { display:block; flex:1 1 0%; min-height:0; overflow:auto; list-style:none; margin:0; padding:0; scrollbar-width:thin; }.watch-mobile li { border-bottom:1px solid var(--border-subtle); }.watch-mobile-row { display:block; width:100%; padding:14px 12px; border:0; background:transparent; text-align:left; color:inherit; }.watch-mobile-row:focus-visible { outline:2px solid var(--focus-ring); outline-offset:-2px; }.mobile-stock { display:flex; align-items:baseline; justify-content:space-between; gap:10px; }.mobile-stock>svg { width:14px; height:14px; color:var(--text-tertiary); }.mobile-facts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 16px; margin-top:14px; }.mobile-facts>span { display:flex; align-items:baseline; justify-content:space-between; gap:8px; }.mobile-facts em { color:var(--text-tertiary); font-size:11px; font-style:normal; white-space:nowrap; }.mobile-facts b { font:500 11px/1.5 var(--mono); }.mobile-review { display:block; margin-top:12px; padding-top:10px; border-top:1px solid var(--border-subtle); }.mobile-review>small { display:block; margin-bottom:6px; color:var(--text-tertiary); font:10px/1.5 var(--mono); }.detail-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; padding:14px; }.detail-metrics dd { font-size:13px; }.watch-detail-dialog[data-slot=dialog-content] { height:90dvh; max-height:90dvh; } }
</style>
