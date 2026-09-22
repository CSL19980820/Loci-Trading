<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
import { ChevronDown } from '@lucide/vue'
import { computed, ref } from 'vue'
import type { GuardianStatus } from '@/shared/types/guardian'
import { agentMoney } from '@/features/agents/agentFormat'
const props = defineProps<{ data: Pick<GuardianStatus, 'state' | 'observation_count'> & { config: Pick<GuardianStatus['config'], 'model'> } }>()
const expanded = ref(false)
const allocation = computed(() => props.data.state.equity_cents ? `${(props.data.state.market_value_cents / props.data.state.equity_cents * 100).toFixed(1)}%` : '—')
const tone = (v: number) => v > 0 ? 'gain' : v < 0 ? 'loss' : ''
const signed = (v: number) => (v > 0 ? '+' : '') + agentMoney(v)
</script>
<template>
 <section class="guardian-mobile-summary" aria-label="模拟账户资产，单位元">
  <div class="mobile-equity-row">
   <div><span class="mobile-equity-label">模拟净资产 / 元</span><strong class="mobile-equity">{{ agentMoney(data.state.equity_cents) }}</strong></div>
   <div class="mobile-pnl"><span class="mobile-equity-label">累计盈亏 / 元</span><strong :class="tone(data.state.total_pnl_cents)">{{ signed(data.state.total_pnl_cents) }}</strong></div>
  </div>
  <div class="mobile-account-facts"><span>现金 <b>{{ agentMoney(data.state.cash_cents) }}</b></span><span>市值 <b>{{ agentMoney(data.state.market_value_cents) }}</b></span><Button access="read" variant="ghost" type="button" :aria-expanded="expanded" aria-label="账户与模型详情" @click="expanded = !expanded">详情<ChevronDown :size="13" :class="{ expanded }" /></Button></div>
  <dl v-if="expanded" class="mobile-account-detail">
    <div><dt>投入本金</dt><dd>{{ agentMoney(data.state.initial_capital_cents) }}</dd></div>
    <div><dt>累计规费</dt><dd>{{ agentMoney(data.state.fees_cents) }}</dd></div>
   <div><dt>已实现</dt><dd :class="tone(data.state.realized_pnl_cents)">{{ agentMoney(data.state.realized_pnl_cents) }}</dd></div>
   <div><dt>浮动</dt><dd :class="tone(data.state.unrealized_pnl_cents)">{{ agentMoney(data.state.unrealized_pnl_cents) }}</dd></div>
   <div><dt>仓位</dt><dd>{{ allocation }}</dd></div><div><dt>自主观察</dt><dd>{{ data.observation_count ?? 0 }}</dd></div>
   <div class="mobile-account-model"><dt>模型</dt><dd>{{ data.config.model || '未配置' }}</dd></div>
   <div v-if="data.state.valuation_date" class="mobile-account-model"><dt>估值</dt><dd>{{ data.state.valuation_date }} · {{ data.state.valuation_kind === 'official_close' ? '收盘估值' : '参考估值' }}</dd></div>
  </dl>
 </section>
</template>
<style scoped>
.guardian-mobile-summary { padding:9px 11px 4px; border:1px solid var(--border-subtle); border-radius:10px; background:var(--surface); min-width:0; }
.mobile-equity-row { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px; }
.mobile-equity-label { display:block; font-size:11px; color:var(--text-tertiary); line-height:20px; }
.mobile-equity-row strong { display:block; font:600 clamp(17px,4.8vw,22px)/1.45 var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap; }
.mobile-pnl { text-align:right; }
.mobile-account-facts { display:flex; align-items:center; flex-wrap:wrap; gap:3px 10px; color:var(--text-tertiary); font-size:11px; }
.mobile-account-facts b { color:var(--text-secondary); font-weight:550; font-variant-numeric:tabular-nums; }
.mobile-account-facts button { display:flex; align-items:center; gap:3px; margin-left:auto; min-height:32px; padding:0 2px 0 8px; border:0; color:var(--text-secondary); background:transparent; font:inherit; cursor:pointer; }
.mobile-account-facts svg.expanded { transform:rotate(180deg); }
.mobile-account-detail { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 14px; margin:4px 0 7px; padding-top:9px; border-top:1px solid var(--border-subtle); }
.mobile-account-detail div { display:flex; justify-content:space-between; gap:8px; min-width:0; font-size:12px; }
.mobile-account-detail dt { color:var(--text-tertiary); white-space:nowrap; }
.mobile-account-detail dd { margin:0; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; text-align:right; }
.mobile-account-model { grid-column:1/-1; }
.gain { color:var(--up); }.loss { color:var(--down); }
</style>
