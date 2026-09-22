<script setup lang="ts">
import { computed } from 'vue'
import type { GuardianPosition } from '@/shared/types/guardian'
import Descriptions, { type DescriptionItem } from '@/shared/components/ui/Descriptions.vue'
import RecordDetailsDialog from '@/shared/components/ui/RecordDetailsDialog.vue'

const props = defineProps<{ position?: GuardianPosition }>()
const open = defineModel<boolean>('open', { default:false })
const money = (cents?: number) => cents == null ? '—' : `${(cents / 100).toLocaleString('zh-CN', {minimumFractionDigits:2,maximumFractionDigits:2})} 元`
const items = computed<DescriptionItem[]>(() => {
 const row = props.position
 if (!row) return []
 return [
  {key:'name',label:'股票名称',value:row.name}, {key:'code',label:'股票代码',value:row.code,mono:true},
  {key:'quantity',label:'持仓股数',value:`${row.quantity.toLocaleString()} 股`,mono:true}, {key:'available',label:'可卖股数',value:`${row.available_quantity.toLocaleString()} 股`,mono:true},
  {key:'cost',label:'含费成本',value:row.average_cost == null ? '—' : `${row.average_cost.toFixed(4)} 元`,mono:true}, {key:'price',label:'参考现价',value:money(row.mark_price_cents),mono:true},
  {key:'total',label:'成本总额',value:money(row.cost_cents),mono:true}, {key:'market',label:'持仓市值',value:money(row.market_value_cents),mono:true},
  {key:'pnl',label:'浮动盈亏',value:money(row.unrealized_pnl_cents),mono:true,tone:row.unrealized_pnl_cents > 0 ? 'positive' : row.unrealized_pnl_cents < 0 ? 'negative' : undefined}, {key:'source',label:'行情来源',value:row.mark_source},
  {key:'holding',label:'持仓计划',value:row.holding_plan,wide:true},
  {key:'profit',label:'止盈计划',value:row.take_profit_plan,wide:true},
  {key:'stop',label:'止损计划',value:row.stop_loss_plan,wide:true},
  {key:'exit',label:'换仓计划',value:row.exit_today_plan,wide:true},
  {key:'entry',label:'建仓依据',value:row.entry_context?.reason,wide:true},
  {key:'review',label:'最近研判',value:row.last_review?.reason,wide:true},
 ]
})
</script>
<template>
 <RecordDetailsDialog v-model:open="open" title="持仓详情" :description="position ? `${position.name} · ${position.code}` : undefined"><Descriptions :items="items" /></RecordDetailsDialog>
</template>
