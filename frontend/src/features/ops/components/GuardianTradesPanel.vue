<script setup lang="ts">
import { getGuardianTrades } from '@/shared/api/guardian'
import { GUARDIAN_ACTION_LABELS, type GuardianTrade } from '@/shared/types/guardian'
import { useGuardianHistory } from '../composables/useGuardianHistory'
import GuardianHistoryFilter from './GuardianHistoryFilter.vue'
const { range, page, items, total, loading, error, apply, changePage, load } = useGuardianHistory(getGuardianTrades)
const money = (cents?: number) => cents == null ? '—' : (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const pnlClass = (value: number) => value > 0 ? 'gain' : value < 0 ? 'loss' : ''
const tradeLabel = (row: GuardianTrade) => GUARDIAN_ACTION_LABELS[row.action || row.side]
</script>
<template>
  <div aria-label="成交历史">
    <GuardianHistoryFilter :value="range" :loading="loading" @apply="apply" />
    <el-button v-if="error" link @click="load()">重试成交查询</el-button>

        <el-alert v-if="error" :title="error" type="error" :closable="false" />
        <el-table v-loading="loading" :data="items" row-key="id" empty-text="尚无成交；拒单和研判不会生成虚假交易" max-height="350" aria-label="逐笔成交明细">
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
        <el-pagination :current-page="page" :page-size="range.limit" :total="total" layout="total, prev, pager, next" :disabled="loading" @current-change="changePage" />
  </div>
</template>
<style scoped src="./GuardianAccountPanel.css"></style>
