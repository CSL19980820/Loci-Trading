<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowUpRight, Wallet } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import type { AgentPosition } from '@/shared/types/stock_agents'
import { agentMoney, agentTime } from '../agentFormat'

const props = defineProps<{ positions: AgentPosition[]; limit?: number; temporaryLimit?: number; feesCents?: number }>()
const selectedCode = ref<string | null>(null)
const selected = computed(() => props.positions.find(row => row.code === selectedCode.value) ?? null)
const detailOpen = computed({ get: () => selected.value != null, set: (open: boolean) => { if (!open) selectedCode.value = null } })
const tone = (value: number | undefined | null) => (value ?? 0) > 0 ? 'gain' : (value ?? 0) < 0 ? 'loss' : ''
const signed = (value: number | undefined | null) => value == null ? '—' : `${value > 0 ? '+' : ''}${agentMoney(value)}`
const percent = (value: number | undefined | null) => value == null || !Number.isFinite(value) ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
const time = (value?: string | null) => value ? agentTime(value) : '—'
const date = (value?: string | null) => {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '—' : new Intl.DateTimeFormat('sv-SE', { timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit' }).format(parsed)
}
const fullTime = (value?: string | null) => value && date(value) !== '—' ? `${date(value)} ${new Intl.DateTimeFormat('en-GB', { timeZone:'Asia/Shanghai', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false }).format(new Date(value))}` : '—'
const days = (value?: number | null) => value == null ? '—' : `${value} 天`
watch(selected, row => { if (!row) selectedCode.value = null })
</script>

<template>
  <section class="positions-panel" aria-label="持仓明细">
    <header class="portfolio-head">
      <div class="portfolio-title"><h3>当前持仓</h3><UiBadge variant="secondary">{{ positions.length }}<template v-if="limit"> / {{ limit }}</template></UiBadge><UiBadge v-if="temporaryLimit" variant="default">临时上限 {{ temporaryLimit }}</UiBadge></div>
      <span class="portfolio-meta">累计规费 {{ agentMoney(feesCents) }} 元</span>
    </header>
    <div v-if="!positions.length" class="portfolio-empty"><Wallet aria-hidden="true" /><strong>当前空仓</strong><p>资金保留在账户中，等待符合条件的进场机会。</p></div>
    <template v-else>
      <Table class="portfolio-table">
        <colgroup><col style="width:180px"><col style="width:84px"><col style="width:84px"><col style="width:88px"><col style="width:96px"><col style="width:110px"><col style="width:104px"><col style="width:76px"><col></colgroup>
        <TableHeader><TableRow>
          <TableHead>股票</TableHead><TableHead class="number">买入价 / 元</TableHead><TableHead class="number">现价 / 元</TableHead>
          <TableHead class="number">盈亏幅度</TableHead><TableHead class="number">盈亏 / 元</TableHead><TableHead class="number">持仓 / 可卖</TableHead>
          <TableHead>买入日期</TableHead><TableHead>持仓天数</TableHead><TableHead class="reason-column">买入理由</TableHead>
        </TableRow></TableHeader>
        <TableBody><TableRow v-for="row in positions" :key="row.code" class="portfolio-row" @click="selectedCode = row.code">
          <TableCell><Button access="read" variant="ghost" class="stock-identity" :aria-label="`查看 ${row.name || row.code} 持仓详情`" @click.stop="selectedCode = row.code"><strong>{{ row.name || row.code }}</strong><small>{{ row.code }}</small><ArrowUpRight aria-hidden="true" /></Button></TableCell>
          <TableCell class="number">{{ agentMoney(row.entry_price_cents) }}</TableCell><TableCell class="number"><span>{{ agentMoney(row.mark_price_cents) }}</span><small v-if="row.valuation_stale" class="stale-label">陈旧</small></TableCell>
          <TableCell class="number emphasis" :class="tone(row.pnl_pct)">{{ percent(row.pnl_pct) }}</TableCell><TableCell class="number emphasis" :class="tone(row.unrealized_pnl_cents)">{{ signed(row.unrealized_pnl_cents) }}</TableCell>
          <TableCell class="number">{{ row.quantity.toLocaleString('zh-CN') }} / {{ row.available_quantity.toLocaleString('zh-CN') }}</TableCell>
          <TableCell class="date-cell" :title="row.entry_at || undefined">{{ date(row.entry_at) }}</TableCell><TableCell class="date-cell">{{ days(row.holding_days) }}</TableCell>
          <TableCell class="reason-column"><p class="reason-preview" :title="row.entry_reason || undefined">{{ row.entry_reason || '—' }}</p></TableCell>
        </TableRow></TableBody>
      </Table>
      <ul class="portfolio-mobile" aria-label="持仓列表">
        <li v-for="row in positions" :key="row.code"><button type="button" class="portfolio-mobile-row" :aria-label="`查看 ${row.name || row.code} 持仓详情`" @click="selectedCode = row.code">
          <span class="mobile-stock"><span class="stock-identity"><strong>{{ row.name || row.code }}</strong><small>{{ row.code }}</small></span><span class="mobile-pnl" :class="tone(row.unrealized_pnl_cents)"><b>{{ percent(row.pnl_pct) }}</b><small>{{ signed(row.unrealized_pnl_cents) }} 元</small></span></span>
          <span class="mobile-facts"><span><em>买入价</em><b>{{ agentMoney(row.entry_price_cents) }}</b></span><span><em>现价</em><b>{{ agentMoney(row.mark_price_cents) }}</b></span><span><em>买入日期</em><b>{{ date(row.entry_at) }}</b></span><span><em>持仓天数</em><b>{{ days(row.holding_days) }}</b></span><span><em>持仓 / 可卖</em><b>{{ row.quantity }} / {{ row.available_quantity }}</b></span><span><em>持仓市值</em><b>{{ agentMoney(row.market_value_cents) }}</b></span></span>
          <span class="reason-preview mobile-reason">{{ row.entry_reason || '—' }}</span>
        </button></li>
      </ul>
    </template>
    <Dialog v-model:open="detailOpen">
      <DialogContent class="position-detail-dialog sm:max-w-[1080px]" style="display:flex;flex-direction:column;height:min(760px,90dvh);max-height:90dvh;overflow:hidden;gap:16px" data-agent-detail-dialog>
        <DialogHeader v-if="selected" class="text-left" style="flex:none;padding-right:26px"><DialogTitle class="detail-stock"><span>{{ selected.name || selected.code }}</span><small>{{ selected.code }}</small><UiBadge variant="secondary">持仓详情</UiBadge></DialogTitle><DialogDescription class="sr-only">{{ selected.name || selected.code }}持仓详情</DialogDescription></DialogHeader>
        <div v-if="selected" class="position-detail-body" data-agent-detail-scroll>
          <dl class="detail-metrics">
            <div><dt>买入价 / 元</dt><dd>{{ agentMoney(selected.entry_price_cents) }}</dd></div><div><dt>参考现价 / 元</dt><dd>{{ agentMoney(selected.mark_price_cents) }}</dd></div>
            <div><dt>盈亏幅度</dt><dd :class="tone(selected.pnl_pct)">{{ percent(selected.pnl_pct) }}</dd></div><div><dt>浮动盈亏 / 元</dt><dd :class="tone(selected.unrealized_pnl_cents)">{{ signed(selected.unrealized_pnl_cents) }}</dd></div>
            <div><dt>持仓 / 可卖</dt><dd>{{ selected.quantity }} / {{ selected.available_quantity }} 股</dd></div><div><dt>持仓市值 / 元</dt><dd>{{ agentMoney(selected.market_value_cents) }}</dd></div>
            <div><dt>买入日期</dt><dd :title="selected.entry_at || undefined">{{ fullTime(selected.entry_at) }}</dd></div><div><dt>持仓天数</dt><dd>{{ days(selected.holding_days) }}</dd></div>
            <div><dt>含费成本 / 元</dt><dd>{{ Number(selected.average_cost).toFixed(4) }}</dd></div><div><dt>报价时间</dt><dd :title="selected.mark_at">{{ time(selected.mark_at) }}</dd></div>
            <div><dt>报价来源</dt><dd>{{ selected.mark_source || '—' }}</dd></div><div><dt>估值状态</dt><dd>{{ selected.valuation_stale ? '沿用最后有效报价' : '最近有效估值' }}</dd></div>
          </dl>
          <section class="detail-section"><h4>买入理由</h4><p>{{ selected.entry_reason || '—' }}</p></section>
          <div class="detail-plans"><section v-for="item in [{label:'持有计划',text:selected.holding_plan},{label:'止盈条件',text:selected.take_profit_plan},{label:'止损条件',text:selected.stop_loss_plan},{label:'今日退出计划',text:selected.exit_today_plan}]" :key="item.label" class="detail-section"><h4>{{ item.label }}</h4><p>{{ item.text || '—' }}</p></section></div>
          <section v-if="selected.last_review" class="detail-section"><h4>最近评估 <time>{{ time(selected.last_review.at) }}</time></h4><p>{{ selected.last_review.reason || '—' }}</p></section>
        </div>
      </DialogContent>
    </Dialog>
  </section>
</template>

<style scoped>
.positions-panel { display:flex; flex:1 1 0%; flex-direction:column; min-width:0; min-height:0; overflow:hidden; border:1px solid var(--border-subtle); border-radius:var(--radius-lg); background:var(--surface); }
.portfolio-head { display:flex; flex:none; align-items:center; flex-wrap:wrap; justify-content:space-between; gap:8px 16px; padding:13px 16px; border-bottom:1px solid var(--border-subtle); }
.portfolio-title { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }.portfolio-title h3 { margin:0; font-size:14px; font-weight:650; }.portfolio-meta { color:var(--text-tertiary); font:11px/1.5 var(--mono); }
.portfolio-empty { display:flex; flex:1; flex-direction:column; align-items:center; justify-content:center; gap:10px; padding:40px 16px; color:var(--text-tertiary); text-align:center; }.portfolio-empty svg { width:30px; height:30px; opacity:.45; }.portfolio-empty strong { color:var(--text-secondary); font-size:14px; font-weight:550; }.portfolio-empty p { margin:0; font-size:12px; }
.positions-panel :deep([data-slot=table-container]) { flex:1 1 0%; min-height:0; overscroll-behavior:contain; scrollbar-width:thin; }
.positions-panel :deep(.portfolio-table) { table-layout:fixed; min-width:1100px; }.positions-panel :deep(.portfolio-table th) { position:sticky; top:0; z-index:1; height:38px; background:var(--surface-sunken); color:var(--text-tertiary); font-size:11px; font-weight:500; white-space:nowrap; }.positions-panel :deep(.portfolio-table td) { height:63px; padding:9px 12px; font-size:12px; }.positions-panel :deep(.portfolio-table th:first-child),.positions-panel :deep(.portfolio-table td:first-child) { padding-left:16px; }.portfolio-row { cursor:pointer; }.number { text-align:right; font-family:var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap; }.emphasis { font-weight:600; }.date-cell { font:11px/1.5 var(--mono); white-space:nowrap; }
.stock-identity { display:inline-flex; align-items:baseline; gap:7px; height:auto; padding:0; white-space:nowrap; box-shadow:none; background:transparent; }.stock-identity strong { font-size:13px; font-weight:600; }.stock-identity small { color:var(--text-tertiary); font:11px/1.4 var(--mono); }.stock-identity svg { align-self:center; width:12px; height:12px; opacity:.4; }.reason-column { white-space:normal; }.reason-preview { display:-webkit-box; max-width:100%; white-space:normal; margin:0; overflow:hidden; -webkit-line-clamp:2; -webkit-box-orient:vertical; color:var(--text-secondary); font-size:12px; line-height:1.7; overflow-wrap:anywhere; }.stale-label { display:block; color:var(--warn-ink); font:10px/1.4 var(--font); }.gain { color:var(--up); }.loss { color:var(--down); }
.portfolio-mobile { display:none; }.position-detail-dialog[data-slot=dialog-content] { display:flex; flex-direction:column; height:min(760px,90dvh); max-height:90dvh; gap:16px; overflow:hidden; }.position-detail-dialog :deep([data-slot=dialog-header]) { flex:none; padding-right:26px; }.detail-stock { display:flex; align-items:baseline; flex-wrap:wrap; gap:10px; }.detail-stock small { color:var(--text-tertiary); font:13px/1.4 var(--mono); }.position-detail-body { flex:1 1 0%; min-height:0; overflow:auto; overscroll-behavior:contain; }.detail-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:18px 24px; margin:0; padding:18px 20px; border-radius:var(--radius-lg); background:var(--surface-sunken); }.detail-metrics dt { color:var(--text-tertiary); font-size:11px; }.detail-metrics dd { margin:6px 0 0; font:600 15px/1.5 var(--mono); overflow-wrap:anywhere; }.detail-section { padding:18px 0; border-bottom:1px solid var(--border-subtle); }.detail-section h4 { margin:0 0 8px; font-size:13px; font-weight:600; }.detail-section h4 time { margin-left:8px; color:var(--text-tertiary); font:11px/1.5 var(--mono); }.detail-section p { margin:0; color:var(--text-secondary); font-size:13px; line-height:1.85; white-space:pre-wrap; overflow-wrap:anywhere; }.detail-plans { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 28px; }
@media(max-width:767px) { .portfolio-head { padding:11px 12px; }.portfolio-title h3 { font-size:13px; }.positions-panel :deep([data-slot=table-container]) { display:none; }.portfolio-mobile { display:block; flex:1 1 0%; min-height:0; overflow:auto; list-style:none; margin:0; padding:0; scrollbar-width:thin; }.portfolio-mobile li { border-bottom:1px solid var(--border-subtle); }.portfolio-mobile-row { display:block; width:100%; padding:14px 12px; border:0; background:transparent; text-align:left; color:inherit; }.portfolio-mobile-row:focus-visible { outline:2px solid var(--focus-ring); outline-offset:-2px; }.mobile-stock { display:flex; align-items:baseline; justify-content:space-between; gap:10px; }.mobile-pnl { display:flex; flex-direction:column; align-items:flex-end; gap:3px; font-family:var(--mono); }.mobile-pnl b { font-size:14px; }.mobile-pnl small { font-size:11px; }.mobile-facts { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 16px; margin-top:14px; }.mobile-facts>span { display:flex; align-items:baseline; justify-content:space-between; gap:8px; }.mobile-facts em { color:var(--text-tertiary); font-size:11px; font-style:normal; white-space:nowrap; }.mobile-facts b { font:500 11px/1.5 var(--mono); }.mobile-reason { margin-top:12px; padding-top:10px; border-top:1px solid var(--border-subtle); }.detail-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; padding:14px; }.detail-metrics dd { font-size:13px; }.detail-plans { grid-template-columns:minmax(0,1fr); gap:0; }.position-detail-dialog[data-slot=dialog-content] { height:90dvh; max-height:90dvh; } }
</style>
