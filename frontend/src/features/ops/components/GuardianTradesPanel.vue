<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { Button } from '@/shared/components/ui/button'
import Descriptions, { type DescriptionItem } from '@/shared/components/ui/Descriptions.vue'
import RecordDetailsDialog from '@/shared/components/ui/RecordDetailsDialog.vue'
import { formatDateTime } from '@/shared/lib/dateTime'
import { vBusy } from '@/shared/directives/busy'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { Notice } from '@/shared/components/ui/app/presentation'
import { default as DataGrid } from '@/shared/components/ui/app/DataGrid.vue'
import { default as DataColumn } from '@/shared/components/ui/app/DataColumn.vue'
import { default as Pager } from '@/shared/components/ui/app/Pager.vue'

import { getGuardianTrades } from '@/shared/api/guardian'
import { GUARDIAN_ACTION_LABELS, type GuardianTrade } from '@/shared/types/guardian'
import { useGuardianHistory } from '../composables/useGuardianHistory'
import GuardianHistoryFilter from './GuardianHistoryFilter.vue'
const { range, page, items, total, loading, error, apply, changePage, load } = useGuardianHistory(getGuardianTrades)
const money = (cents?: number) => cents == null ? '—' : (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const pnlClass = (value: number) => value > 0 ? 'gain' : value < 0 ? 'loss' : ''
const tradeLabel = (raw: unknown) => { const row = raw as GuardianTrade; return GUARDIAN_ACTION_LABELS[row.action || row.side] }
const selected = shallowRef<GuardianTrade>()
const detailOpen = computed({ get: () => Boolean(selected.value), set: value => { if (!value) selected.value = undefined } })
function openTrade(raw: unknown): void { selected.value = raw as GuardianTrade }
const detailItems = computed<DescriptionItem[]>(() => {
  const row = selected.value
  if (!row) return []
  return [
    {key:'stock',label:'股票',value:`${row.name}（${row.code}）`},
    {key:'side',label:'成交方向',value:tradeLabel(row)},
    {key:'time',label:'成交时间',value:formatDateTime(row.occurred_at)},
    {key:'quantity',label:'成交股数',value:`${row.quantity.toLocaleString()} 股`,mono:true},
    {key:'price',label:'成交价',value:`${money(row.price_cents)} 元`,mono:true},
    {key:'gross',label:'成交金额',value:`${money(row.gross_cents)} 元`,mono:true},
    {key:'fees',label:'费用合计',value:`${money(row.fees_cents)} 元`,mono:true},
    {key:'pnl',label:'本笔盈亏',value:row.side === 'sell' ? `${money(row.realized_pnl_cents)} 元` : '—',mono:true,tone:row.side === 'sell' ? (row.realized_pnl_cents > 0 ? 'positive' : row.realized_pnl_cents < 0 ? 'negative' : undefined) : undefined},
    {key:'commission',label:'佣金',value:`${money(row.commission_cents)} 元`,mono:true},
    {key:'stamp',label:'印花税',value:`${money(row.stamp_tax_cents)} 元`,mono:true},
    {key:'transfer',label:'过户费',value:`${money(row.transfer_cents)} 元`,mono:true},
    {key:'cost',label:'分摊成本',value:row.side === 'sell' ? `${money(row.allocated_cost_cents)} 元` : '—',mono:true},
    {key:'holding',label:'持仓变化',value:`${row.before_quantity.toLocaleString()} → ${row.after_quantity.toLocaleString()} 股`,mono:true},
    {key:'cash',label:'成交后现金',value:`${money(row.cash_after_cents)} 元`,mono:true},
    {key:'reason',label:'成交依据',value:row.reason,wide:true},
    {key:'plan',label:'持仓计划',value:row.holding_plan,wide:true},
    {key:'quote',label:'行情来源',value:row.quote_source},
    {key:'quoteAt',label:'行情时间',value:formatDateTime(row.quote_at)},
    {key:'id',label:'成交编号',value:row.id,wide:true,mono:true},
  ]
})
</script>
<template>
  <div class="workspace-list guardian-trades" aria-label="成交历史">
    <GuardianHistoryFilter searchable :value="range" :loading="loading" @apply="apply" />
    <ActionButton access="read" v-if="error" variant="link" @click="load()">重试成交查询</ActionButton>

        <Notice v-if="error" :title="error" tone="error" :closable="false" />
    <DataGrid v-busy="loading" :data="items" row-key="id" empty-text="尚无成交；拒单和研判不会生成虚假交易" aria-label="逐笔成交明细" @row-click="openTrade">
          <DataColumn label="成交时间" width="178"><template #default="{ row }">{{ row.occurred_at.slice(0, 19).replace('T', ' ') }}</template></DataColumn>
          <DataColumn label="股票" min-width="125"><template #default="{ row }">{{ row.name }}<small class="cell-note">（{{ row.code }}）</small></template></DataColumn>
          <DataColumn label="方向" width="85"><template #default="{ row }">{{ tradeLabel(row) }}<small v-if="row.origin === 'legacy_conversion'" class="cell-note">旧仓折算</small></template></DataColumn>
          <DataColumn prop="quantity" label="股数" align="right" width="90" />
          <DataColumn label="成交价 / 元" align="right" width="105"><template #default="{ row }">{{ money(row.price_cents) }}</template></DataColumn>
          <DataColumn label="成交额 / 元" align="right" width="120"><template #default="{ row }">{{ money(row.gross_cents) }}</template></DataColumn>
          <DataColumn label="费用 / 元" align="right" width="100"><template #default="{ row }">{{ money(row.fees_cents) }}</template></DataColumn>
          <DataColumn label="本笔盈亏 / 元" align="right" width="125"><template #default="{ row }"><span :class="pnlClass(row.realized_pnl_cents)">{{ row.side === 'sell' ? money(row.realized_pnl_cents) : '—' }}</span></template></DataColumn>
          <DataColumn label="成交后 / 股" prop="after_quantity" align="right" width="115" />
          <DataColumn label="" width="70"><template #default="{ row }"><Button access="read" variant="ghost" size="sm" :aria-label="`查看${row.name}成交详情`" @click.stop="openTrade(row)">详情</Button></template></DataColumn>
        </DataGrid>
    <div class="guardian-mobile-ledger" aria-label="移动端成交明细">
      <article v-for="row in items" :key="row.id" class="ledger-card">
        <header><strong>{{ row.name }} <small>{{ row.code }}</small></strong><span>{{ tradeLabel(row) }}</span></header>
        <time>{{ row.occurred_at.slice(0,19).replace('T',' ') }}</time>
        <dl>
          <div><dt>股数</dt><dd>{{ row.quantity }}</dd></div><div><dt>成交价</dt><dd>{{ money(row.price_cents) }}</dd></div>
          <div><dt>成交额</dt><dd>{{ money(row.gross_cents) }}</dd></div><div><dt>费用</dt><dd>{{ money(row.fees_cents) }}</dd></div>
          <div><dt>本笔盈亏</dt><dd :class="pnlClass(row.realized_pnl_cents)">{{ row.side === 'sell' ? money(row.realized_pnl_cents) : '—' }}</dd></div><div><dt>成交后持仓</dt><dd>{{ row.after_quantity }} 股</dd></div>
        </dl>
        <Button access="read" variant="ghost" size="sm" class="ledger-detail-button" :aria-label="`查看${row.name}成交详情`" @click="openTrade(row)">查看详情</Button>
      </article>
      <p v-if="!items.length && !loading" class="ledger-empty">所选日期暂无成交</p>
    </div>
    <RecordDetailsDialog v-model:open="detailOpen" title="成交详情" :description="selected ? `${selected.name} · ${selected.code}` : undefined"><Descriptions :items="detailItems" /></RecordDetailsDialog>
    <Pager :current-page="page" :page-size="range.limit" :total="total" layout="total, prev, pager, next" :disabled="loading" @current-change="changePage" />
  </div>
</template>
<style scoped src="./GuardianAccountPanel.css"></style>
<style scoped>
.guardian-trades :deep(tbody tr) { cursor:pointer; }
.ledger-detail-button { margin-top:10px; width:100%; border-top:1px solid var(--border-subtle); border-radius:0; }
</style>
