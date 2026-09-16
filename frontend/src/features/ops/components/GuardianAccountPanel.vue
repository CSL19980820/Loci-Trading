<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { getGuardianTrades } from '@/shared/api/guardian'
import { GUARDIAN_ACTION_LABELS } from '@/shared/types/guardian'
import type { GuardianAccount, GuardianTrade, GuardianPerformance } from '@/shared/types/guardian'

const props = defineProps<{ account: GuardianAccount; trades: { items: GuardianTrade[]; total: number }; performance: GuardianPerformance[] }>()
const tab = ref('positions')
const page = ref(1)
const history = ref(props.trades)
const loading = ref(false)
const error = ref('')
let controller: AbortController | undefined
watch(() => props.trades, value => { if (page.value === 1) history.value = value })
onUnmounted(() => controller?.abort())
async function changePage(value: number) {
  controller?.abort()
  const request = new AbortController()
  controller = request
  loading.value = true; error.value = ''
  try {
    const result = await getGuardianTrades((value - 1) * 50, 50, request.signal)
    if (!request.signal.aborted) { history.value = result; page.value = value }
  } catch (e) { if (!request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (controller === request) loading.value = false }
}
const money = (cents?: number) => cents == null ? '—' : (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const cost = (value?: number) => value == null ? '—' : value.toFixed(4)
const pnlClass = (value: number) => value > 0 ? 'gain' : value < 0 ? 'loss' : ''
const tradeLabel = (row: GuardianTrade) => GUARDIAN_ACTION_LABELS[row.action || row.side]
const performanceRows = computed(() => props.performance.map(item => {
  const position = props.account.positions.find(p => p.code === item.code)
  return { ...item, quantity: position?.quantity ?? 0, floating: position?.unrealized_pnl_cents ?? 0,
    total: item.realized_pnl_cents + (position?.unrealized_pnl_cents ?? 0) }
}))
</script>

<template>
  <section class="guardian-account" aria-label="守护现金账户">
    <div class="account-heading"><h3>模拟交易账户</h3><span>初始本金 {{ money(account.initial_capital_cents) }} 元 · T+1 · 默认3只，换仓过渡最多4只</span><span v-if="account.valuation_kind === 'official_close'">{{ account.valuation_date }} 收盘估值</span></div>
    <div class="account-totals">
      <div class="account-total-primary"><span>总资产 / 元</span><strong>{{ money(account.equity_cents) }}</strong></div>
      <div><span>可用现金</span><strong>{{ money(account.cash_cents) }}</strong></div>
      <div><span>持仓市值</span><strong>{{ money(account.market_value_cents) }}</strong></div>
      <div><span>累计盈亏</span><strong :class="pnlClass(account.total_pnl_cents)">{{ money(account.total_pnl_cents) }}</strong></div>
      <div><span>已实现盈亏</span><strong :class="pnlClass(account.realized_pnl_cents)">{{ money(account.realized_pnl_cents) }}</strong></div>
      <div><span>浮动盈亏</span><strong :class="pnlClass(account.unrealized_pnl_cents)">{{ money(account.unrealized_pnl_cents) }}</strong></div>
    </div>
    <el-alert v-if="account.stale_codes?.length" type="warning" :closable="false" show-icon :title="`部分持仓沿用最后有效报价：${account.stale_codes.join('、')}，请核对行情时间`" />
    <el-tabs v-model="tab" class="account-tabs">
      <el-tab-pane :label="`精确持仓 · ${account.positions.length}`" name="positions">
        <div v-if="account.positions.length" class="position-cards" aria-label="精确持仓明细">
          <article v-for="row in account.positions" :key="row.code" class="position-card">
            <header><h4>{{ row.name }}（{{ row.code }}）</h4><b :class="pnlClass(row.unrealized_pnl_cents)">{{ money(row.unrealized_pnl_cents) }} 元</b></header>
            <dl><div><dt>持仓 / 可卖</dt><dd>{{ row.quantity.toLocaleString() }} / {{ row.available_quantity.toLocaleString() }} 股</dd></div><div><dt>含费每股成本</dt><dd>{{ cost(row.average_cost) }} 元</dd></div><div><dt>成本总额</dt><dd>{{ money(row.cost_cents) }} 元</dd></div><div><dt>参考现价</dt><dd>{{ money(row.mark_price_cents) }} 元</dd></div></dl>
            <div class="position-plans"><p><b>持股</b>{{ row.holding_plan || '等待下一轮研判' }}</p><p><b>止盈</b>{{ row.take_profit_plan || '等待下一轮研判' }}</p><p><b>止损</b>{{ row.stop_loss_plan || '等待下一轮研判' }}</p><p v-if="row.exit_today_plan"><b>换仓</b>{{ row.exit_today_plan }}</p></div>
          </article>
        </div>
        <el-empty v-else description="当前空仓，等待有依据的交易机会" :image-size="64" />
      </el-tab-pane>
      <el-tab-pane :label="`成交明细 · ${trades.total}`" name="trades">
        <el-alert v-if="error" :title="error" type="error" :closable="false" />
        <el-table v-loading="loading" :data="history.items" row-key="id" empty-text="尚无成交；拒单和研判不会生成虚假交易" max-height="350" aria-label="逐笔成交明细">
          <el-table-column type="expand"><template #default="{ row }"><div class="trade-detail"><p>成交编号：{{ row.id }} · 行情 {{ row.quote_source }} / {{ row.quote_at }}</p><p>佣金 {{ money(row.commission_cents) }} 元 · 印花税 {{ money(row.stamp_tax_cents) }} 元 · 过户费 {{ money(row.transfer_cents) }} 元</p><p>持仓 {{ row.before_quantity }} → {{ row.after_quantity }} 股 · 成交后现金 {{ money(row.cash_after_cents) }} 元 · 卖出分摊成本 {{ money(row.allocated_cost_cents) }} 元</p><p>买卖依据：{{ row.reason }}</p><p v-if="row.holding_plan">持有计划：{{ row.holding_plan }}</p></div></template></el-table-column>
          <el-table-column label="成交时间" width="178"><template #default="{ row }">{{ row.occurred_at.slice(0, 19).replace('T', ' ') }}</template></el-table-column>
          <el-table-column label="股票" min-width="125"><template #default="{ row }">{{ row.name }}<small class="cell-note">（{{ row.code }}）</small></template></el-table-column>
          <el-table-column label="方向" width="85"><template #default="{ row }">{{ tradeLabel(row) }}<small v-if="row.origin === 'legacy_conversion'" class="cell-note">旧仓折算</small></template></el-table-column>
          <el-table-column prop="quantity" label="股数" align="right" width="90" />
          <el-table-column label="成交价 / 元" align="right" width="105"><template #default="{ row }">{{ money(row.price_cents) }}</template></el-table-column>
          <el-table-column label="成交额 / 元" align="right" width="120"><template #default="{ row }">{{ money(row.gross_cents) }}</template></el-table-column>
          <el-table-column label="费用 / 元" align="right" width="100"><template #default="{ row }">{{ money(row.fees_cents) }}</template></el-table-column>
          <el-table-column label="本笔盈亏 / 元" align="right" width="125"><template #default="{ row }"><span :class="pnlClass(row.realized_pnl_cents)">{{ row.side === 'sell' ? money(row.realized_pnl_cents) : '—' }}</span></template></el-table-column>
          <el-table-column label="成交后 / 股" prop="after_quantity" align="right" width="115" />
        </el-table>
        <el-pagination v-if="history.total > 50" :current-page="page" :page-size="50" :total="history.total" layout="total, prev, pager, next" :disabled="loading" @current-change="changePage" />
      </el-tab-pane>
      <el-tab-pane label="个股盈亏" name="performance">
        <el-table :data="performanceRows" row-key="code" empty-text="成交后按股票累计盈亏，清仓记录持续保留" max-height="350">
          <el-table-column label="股票" min-width="130"><template #default="{ row }">{{ row.name }}<small class="cell-note">（{{ row.code }}）</small></template></el-table-column>
          <el-table-column label="累计买入 / 股" prop="bought_quantity" align="right" min-width="115" />
          <el-table-column label="累计卖出 / 股" prop="sold_quantity" align="right" min-width="115" />
          <el-table-column label="当前持仓 / 股" prop="quantity" align="right" min-width="115" />
          <el-table-column label="已实现 / 元" align="right" min-width="110"><template #default="{ row }">{{ money(row.realized_pnl_cents) }}</template></el-table-column>
          <el-table-column label="浮动 / 元" align="right" min-width="110"><template #default="{ row }">{{ money(row.floating) }}</template></el-table-column>
          <el-table-column label="累计盈亏 / 元" align="right" min-width="125"><template #default="{ row }"><span :class="pnlClass(row.total)">{{ money(row.total) }}</span></template></el-table-column>
          <el-table-column label="累计费用 / 元" align="right" min-width="120"><template #default="{ row }">{{ money(row.fees_cents) }}</template></el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
    <footer class="account-foot"><span>累计费用 {{ money(account.fees_cents) }} 元 · 成本含买入费用，卖出净收入扣除费用后计盈亏</span><span>佣金万 2.5（免 5，无最低收费）；印花税卖出万五；过户费双向十万一</span><span>按新鲜行情参考价模拟成交，未模拟盘口排队及分红送转</span></footer>
  </section>
</template>

<style scoped>
.guardian-account { flex: 1 1 auto; min-width: 0; min-height: 0; overflow: auto; overscroll-behavior: contain; padding: var(--gap-3); border: 1px solid var(--rule); border-radius: var(--radius); background: var(--surface); }
.account-heading { display: flex; gap: var(--gap-3); align-items: baseline; flex-wrap: wrap; }
.account-heading h3 { margin: 0; font-size: var(--fs-body); }
.account-heading > span, .account-foot, .cell-note { color: var(--muted); font-size: var(--fs-aux); }
.account-totals { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 10rem), 1fr)); gap: 1px; padding: 1px; margin-block: var(--gap-3); background: var(--rule); border: 1px solid var(--rule); border-radius: var(--radius); overflow: hidden; }
.account-totals > div { display: grid; align-content: start; gap: var(--gap-2); min-width: 0; padding: var(--gap-3); background: var(--surface-sunken); }
.account-totals span { color: var(--muted); font-size: var(--fs-aux); }
.account-totals strong { font: 600 var(--fs-hero) var(--mono); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.account-total-primary strong { font-size: var(--fs-tape); }
.cell-note { display: block; margin-top: 3px; }
.gain { color: var(--up); }
.loss { color: var(--down); }
.trade-detail { padding: var(--gap-3) var(--gap-4); }
.trade-detail p { margin-block: var(--gap-2); }
.account-foot { display: flex; flex-wrap: wrap; gap: var(--gap-2) var(--gap-4); padding-top: var(--gap-3); line-height: 1.8; }
.account-tabs :deep(.el-table) { font-variant-numeric: tabular-nums; }
@media (max-width: 650px) { .account-totals { grid-template-columns: repeat(2, minmax(0, 1fr)); } .account-totals strong { font-size: var(--fs-title); } .account-total-primary { grid-column: 1 / -1; } .account-total-primary strong { font-size: var(--fs-tape); } }
.position-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,20rem),1fr)); gap:var(--gap-2); padding-block:var(--gap-2); }
.position-card { border:1px solid var(--rule); border-radius:var(--radius); padding:var(--gap-3); background:var(--surface); min-width:0; overflow-wrap:anywhere; }
.position-card header { display:flex; flex-direction:column; gap:var(--gap-2); }
.position-card h4 { margin:0; font-size:var(--fs-body); }
.position-card header > b { font:600 var(--fs-hero) var(--mono); font-variant-numeric:tabular-nums; }
.position-card dl { display:grid; grid-template-columns:repeat(2,1fr); gap:var(--gap-3) var(--gap-2); }
.position-card dt { font-size:var(--fs-aux); color:var(--muted); }
.position-card dd { margin:var(--gap-1) 0 0; font:600 var(--fs-aux) var(--mono); font-variant-numeric:tabular-nums; }
.position-plans { border-top:1px solid var(--rule-soft); padding-top:var(--gap-1); }
.position-plans p { font-size:var(--fs-aux); line-height:1.8; margin:var(--gap-2) 0; }
.position-plans b { margin-right:var(--gap-2); }
@media(max-width:1100px) { .position-cards { grid-template-columns:1fr; } .position-card dl { grid-template-columns:repeat(4,1fr); } }
@media(max-width:650px) { .position-card dl { grid-template-columns:repeat(2,1fr); } }
</style>
