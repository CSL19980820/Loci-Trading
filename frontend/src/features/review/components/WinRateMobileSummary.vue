<script setup lang="ts">
import { signedPct } from '@/shared/lib/format'
import { sampleBadgeLabel, winRateText } from '@/shared/lib/winrate'

defineProps<{
  label: string
  horizon: number
  rate: number | null
  settled: number
  observing: number
  average: number | null
  best?: number
  loading: boolean
}>()
</script>

<template>
  <section class="mobile-winrate" aria-label="当前统计摘要" :aria-busy="loading">
    <div class="mobile-winrate__primary">
      <div><span>{{ label }}</span><strong>{{ winRateText(rate) }}</strong></div>
      <div><span>已结算样本</span><strong>{{ settled.toLocaleString() }}<small>条</small></strong></div>
    </div>
    <div class="mobile-winrate__secondary">
      <span>T+{{ horizon }} 均收益 <b :class="average == null ? '' : average >= 0 ? 'up' : 'down'">{{ signedPct(average) }}</b></span>
      <span>最佳持有期 <b>{{ best ? `T+${best}` : '样本不足' }}</b></span>
    </div>
    <p>{{ loading ? '正在更新统计…' : sampleBadgeLabel(settled) || '按已结算样本统计' }}<span v-if="observing"> · {{ observing }} 条观察中，不计入</span></p>
  </section>
</template>

<style scoped>
.mobile-winrate { border:1px solid var(--border-subtle); border-radius:12px; background:var(--surface); padding:14px; }
.mobile-winrate__primary { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.mobile-winrate__primary>div { display:flex; flex-direction:column; gap:5px; min-width:0; }
.mobile-winrate__primary span { color:var(--text-tertiary); font-size:12px; }
.mobile-winrate strong { font-size:26px; font-weight:600; line-height:1.3; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
.mobile-winrate strong small { font-size:11px; font-weight:400; color:var(--text-tertiary); margin-left:5px; }
.mobile-winrate__secondary { display:flex; flex-wrap:wrap; gap:6px 15px; margin-top:12px; font-size:11px; color:var(--text-tertiary); }
.mobile-winrate b { color:var(--text-primary); font-weight:500; }
.mobile-winrate b.up { color:var(--up); }
.mobile-winrate b.down { color:var(--down); }
.mobile-winrate p { font-size:11px; line-height:1.6; margin:8px 0 0; color:var(--text-tertiary); }
</style>
