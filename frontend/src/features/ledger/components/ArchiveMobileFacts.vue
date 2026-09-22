<script setup lang="ts">
import { computed } from 'vue'
import type { Bar } from '@/shared/types/quant-market'
import { compactNumber } from '@/shared/lib/format'
const props = defineProps<{ bar: Bar | null; previous: Bar | null }>()
function price(value: number | null | undefined): string { return value == null || !Number.isFinite(value) ? '—' : value.toFixed(2) }
function tone(value: number | null | undefined): string { const previous = props.previous?.close; return value == null || previous == null ? '' : value > previous ? 'up' : value < previous ? 'down' : '' }
const values = computed(() => {
 const b = props.bar, previous = props.previous?.close
 const amplitude = b?.high != null && b?.low != null && previous ? `${((b.high - b.low) / previous * 100).toFixed(2)}%` : '—'
 return [
  { label:'昨收', value:price(previous) }, { label:'今开', value:price(b?.open), tone:tone(b?.open) },
  { label:'最高', value:price(b?.high), tone:tone(b?.high) }, { label:'最低', value:price(b?.low), tone:tone(b?.low) },
  { label:'成交额', value:compactNumber(b?.amount) }, { label:'成交量', value:compactNumber(b?.volume) },
  { label:'换手率', value:b?.turnover == null ? '—' : `${(b.turnover * 100).toFixed(2)}%` }, { label:'振幅', value:amplitude },
 ]
})
</script>
<template><dl class="mobile-stock-facts" aria-label="最新行情读数"><div v-for="item in values" :key="item.label"><dt>{{ item.label }}</dt><dd :class="item.tone">{{ item.value }}</dd></div></dl></template>
<style scoped>
.mobile-stock-facts { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px 10px; margin:0; padding:9px 12px 10px; border-bottom:1px solid var(--border-subtle); }
.mobile-stock-facts div { min-width:0; }
.mobile-stock-facts dt { color:var(--text-tertiary); font-size:10px; line-height:16px; }
.mobile-stock-facts dd { margin:1px 0 0; font:600 12px/18px var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap; }
.up { color:var(--up); }.down { color:var(--down); }
</style>
