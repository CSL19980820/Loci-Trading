<script setup lang="ts">
import { ChartNoAxesCombined, ChevronRight } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import type { GuardianAccount } from '@/shared/types/guardian'

defineProps<{ account: GuardianAccount }>()
const emit = defineEmits<{ curve: [code: string]; detail: [code: string] }>()
const money = (value?: number) => value == null ? '—' : (value / 100).toLocaleString('zh-CN', {minimumFractionDigits:2, maximumFractionDigits:2})
const tone = (value?: number) => (value ?? 0) > 0 ? 'is-profit' : (value ?? 0) < 0 ? 'is-loss' : ''
</script>
<template>
  <div class="mobile-positions">
    <article v-for="position in account.positions" :key="position.code" class="mobile-position">
      <header>
        <div class="mobile-position__identity"><strong>{{ position.name }}</strong><span>{{ position.code }}</span></div>
        <div class="mobile-position__pnl"><b :class="tone(position.unrealized_pnl_cents)">{{ position.unrealized_pnl_cents > 0 ? '+' : '' }}{{ money(position.unrealized_pnl_cents) }}</b><span>浮动盈亏 · 元</span></div>
      </header>
      <dl>
        <div><dt>持仓 / 可卖</dt><dd>{{ position.quantity.toLocaleString() }} / {{ position.available_quantity.toLocaleString() }}<small>股</small></dd></div>
        <div><dt>现价 / 含费成本</dt><dd>{{ money(position.mark_price_cents) }} / {{ position.average_cost?.toFixed(4) ?? '—' }}<small>元</small></dd></div>
      </dl>
      <footer><Button access="read" variant="ghost" size="sm" :aria-label="`查看${position.name}持仓曲线`" @click="emit('curve',position.code)"><ChartNoAxesCombined />走势</Button><Button access="read" variant="ghost" size="sm" @click="emit('detail',position.code)">持仓详情<ChevronRight /></Button></footer>
    </article>
    <div v-if="!account.positions.length" class="mobile-positions__empty">当前空仓</div>

  </div>
</template>
<style scoped>
.mobile-positions { display:flex; flex-direction:column; gap:10px; width:100%; padding-bottom:10px; }
.mobile-position { border:1px solid var(--border-subtle); border-radius:12px; background:var(--surface); padding:12px 14px 4px; min-width:0; }
.mobile-position header { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
.mobile-position__identity { display:flex; flex-direction:column; gap:3px; min-width:0; }.mobile-position__identity strong { font-size:15px; font-weight:600; line-height:1.5; overflow-wrap:anywhere; }.mobile-position__identity>span { color:var(--text-tertiary); font:11px var(--mono); }
.mobile-position__pnl { display:flex; align-items:flex-end; flex-direction:column; gap:4px; flex:none; }.mobile-position__pnl b { font-size:18px; font-weight:600; font-variant-numeric:tabular-nums; }.mobile-position__pnl>span { font-size:10px; color:var(--text-tertiary); }
.mobile-position dl { display:grid; grid-template-columns:1fr 1.1fr; gap:8px; margin:13px 0 10px; }.mobile-position dl>div { min-width:0; }.mobile-position dt { color:var(--text-tertiary); font-size:11px; margin-bottom:5px; }.mobile-position dd { font-size:12px; font-variant-numeric:tabular-nums; margin:0; white-space:nowrap; }.mobile-position dd small { color:var(--text-tertiary); font-size:10px; margin-left:4px; }
.mobile-position footer { display:flex; justify-content:space-between; border-top:1px solid var(--border-subtle); padding-top:3px; }.mobile-position footer button { font-size:12px; padding-inline:0; min-height:36px; }.mobile-position footer svg { width:14px; height:14px; }
.is-profit { color:var(--up); }.is-loss { color:var(--down); }
.mobile-positions__empty { padding:60px 20px; text-align:center; color:var(--text-tertiary); font-size:14px; }
</style>
