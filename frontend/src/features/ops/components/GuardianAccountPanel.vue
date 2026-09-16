<script setup lang="ts">
import { defineAsyncComponent, ref } from 'vue'
import type { GuardianAccount } from '@/shared/types/guardian'
const GuardianTradesPanel = defineAsyncComponent(() => import('./GuardianTradesPanel.vue'))
const GuardianPerformancePanel = defineAsyncComponent(() => import('./GuardianPerformancePanel.vue'))
defineProps<{ account: GuardianAccount }>()
const tab = ref('positions')
const money = (cents?: number) => cents == null ? '—' : (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const pnlClass = (value: number) => value > 0 ? 'gain' : value < 0 ? 'loss' : ''
const cost = (value?: number) => value == null ? '—' : value.toFixed(4)
</script>

<template>
  <section class="guardian-account" aria-label="守护现金账户">
    <div class="account-heading"><h3>模拟交易账户</h3><span>初始本金 {{ money(account.initial_capital_cents) }} 元 · T+1 · 遵循自主交易员现有持仓规则</span><span v-if="account.valuation_kind === 'official_close'">{{ account.valuation_date }} 收盘估值</span></div>
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
      <el-tab-pane label="成交明细" name="trades"><GuardianTradesPanel v-if="tab === 'trades'" /></el-tab-pane>
      <el-tab-pane label="个股盈亏" name="performance"><GuardianPerformancePanel v-if="tab === 'performance'" :account="account" /></el-tab-pane>
    </el-tabs>
    <footer class="account-foot"><span>累计费用 {{ money(account.fees_cents) }} 元 · 成本含买入费用，卖出净收入扣除费用后计盈亏</span><span>佣金万 2.5（免 5，无最低收费）；印花税卖出万五；过户费双向十万一</span><span>按新鲜行情参考价模拟成交，未模拟盘口排队及分红送转</span></footer>
  </section>
</template>

<style scoped src="./GuardianAccountPanel.css"></style>
