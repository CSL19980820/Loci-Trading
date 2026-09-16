<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AgentEquity } from '@/shared/types/stock_agents'
import { agentMoney, agentTime } from '../agentFormat'
const props = defineProps<{ points:AgentEquity[]; loading?:boolean; error?:string }>()
const mode = ref('pnl')
const selected = ref<number | null>(null)
const values = computed(() => props.points.map(p => (mode.value === 'pnl' ? p.pnl_cents : p.equity_cents) / 100))
const bounds = computed(() => {
  const low = Math.min(...values.value, mode.value === 'pnl' ? 0 : Infinity)
  const high = Math.max(...values.value, mode.value === 'pnl' ? 0 : -Infinity)
  if (!Number.isFinite(low) || !Number.isFinite(high)) return { low:0, high:1 }
  const pad = Math.max((high-low) * .18, Math.max(Math.abs(high) * .001,1))
  return { low:low-pad, high:high+pad }
})
const y = (value:number) => 235 - (value - bounds.value.low) / (bounds.value.high - bounds.value.low) * 210
const x = (index:number) => props.points.length <= 1 ? 445 : 82 + index / (props.points.length - 1) * 760
const coordinates = computed(() => values.value.map((v,i) => `${x(i)},${y(v)}`).join(' '))
const current = computed(() => selected.value == null ? props.points.at(-1) : props.points[selected.value])
const last = computed(() => props.points.at(-1))
const ticks = computed(() => Array.from({ length:4 },(_,i) => bounds.value.low + (bounds.value.high-bounds.value.low) * i / 3))
function inspect(event:MouseEvent) {
  const rect = (event.currentTarget as SVGElement).getBoundingClientRect()
  if (!props.points.length || !rect.width) return
  selected.value = Math.max(0,Math.min(props.points.length-1,Math.round(((event.clientX-rect.left) / rect.width * 900-82) / 760 * (props.points.length-1))))
}
</script>
<template>
  <section class="equity-panel">
    <header><div><h3>{{ mode === 'pnl' ? '累计盈利曲线' : '模拟资产曲线' }}</h3><p>{{ mode === 'pnl' ? '已扣除累计投入，追加资金不会抬高盈利。' : '包含追加资金；资产增长不等于投资盈利。' }}</p></div><el-radio-group v-model="mode" size="small" @change="selected = null"><el-radio-button value="pnl">盈利</el-radio-button><el-radio-button value="equity">资产</el-radio-button></el-radio-group></header>
    <el-skeleton v-if="loading && !points.length" :rows="5" animated class="chart-loading" />
    <el-alert v-else-if="error" :title="error" type="error" :closable="false" />
    <template v-else-if="points.length">
      <div class="chart-value"><strong>{{ agentMoney(mode === 'pnl' ? current?.pnl_cents : current?.equity_cents) }}<small>元</small></strong><span>{{ current?.day }}<em v-if="current?.stale">含陈旧报价</em></span></div>
      <svg viewBox="0 0 900 275" role="img" :aria-label="`${mode === 'pnl' ? '累计盈利' : '资产'}曲线，共${points.length}个日度快照，最新${agentMoney(mode === 'pnl' ? last?.pnl_cents : last?.equity_cents)}元`" @mousemove="inspect" @mouseleave="selected = null">
        <g v-for="tick in ticks" :key="tick" class="chart-grid"><line x1="82" x2="842" :y1="y(tick)" :y2="y(tick)" /><text x="70" :y="y(tick)+4" text-anchor="end">{{ tick.toLocaleString('zh-CN',{ maximumFractionDigits:Math.abs(tick)<10 ? 2 : 0 }) }}</text></g>
        <line v-if="mode === 'pnl'" class="zero-line" x1="82" x2="842" :y1="y(0)" :y2="y(0)" />
        <polyline v-if="points.length>1" class="equity-line" :points="coordinates" />
        <circle v-if="last" class="equity-dot" :cx="x(points.length-1)" :cy="y(values.at(-1) ?? 0)" r="4" />
        <g v-if="selected !== null && current"><line class="cursor-line" :x1="x(selected)" :x2="x(selected)" y1="20" y2="238" /><circle class="equity-dot" :cx="x(selected)" :cy="y(values[selected] ?? 0)" r="4" /></g>
        <text class="axis-date" x="82" y="265">{{ points[0]?.day }}</text><text class="axis-date" x="842" y="265" text-anchor="end">{{ last?.day }}</text>
      </svg>
      <footer><span>日度最后快照 · 最新估值 {{ agentTime(current?.at) }}</span><span v-if="points.length===1">已建立账户，后续工作将累积曲线。</span><span v-else>移动指针查看历史 · {{ points.length }} 个快照</span></footer>
    </template>
    <el-empty v-else description="暂无账户快照" :image-size="60" />
  </section>
</template>
<style scoped>
.equity-panel { --el-border-color-darker: var(--el-border-color-dark); }
.equity-panel { padding:26px; border:1px solid var(--line); border-radius:12px; background:var(--el-bg-color); min-width:0; }header { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; }h3 { font-size:15px; font-weight:600; margin:0 0 9px; }header p { margin:0; font-size:11px; color:var(--muted); line-height:1.7; }.chart-value { display:flex; gap:18px; align-items:baseline; margin:24px 0 0; }.chart-value strong { font-weight:550; font-size:26px; font-variant-numeric:tabular-nums; letter-spacing:-.03em; }.chart-value small { font-weight:400; font-size:11px; color:var(--muted); margin-left:8px; }.chart-value span { font-size:11px; color:var(--muted); }.chart-value em { font-style:normal; color:var(--el-color-warning); margin-left:9px; }svg { width:100%; height:auto; display:block; min-height:190px; overflow:visible; }.chart-grid line { stroke:var(--line); stroke-width:1; stroke-dasharray:3 5; }.chart-grid text,.axis-date { fill:var(--muted); font-size:11px; }.equity-line { stroke:var(--seal-ink,var(--el-color-primary)); stroke-width:2.4; fill:none; stroke-linecap:round; stroke-linejoin:round; vector-effect:non-scaling-stroke; }.equity-dot { fill:var(--seal-ink,var(--el-color-primary)); stroke:var(--el-bg-color); stroke-width:2; }.zero-line { stroke:var(--el-border-color-darker); stroke-width:1; }.cursor-line { stroke:var(--muted); stroke-dasharray:3 4; }footer { display:flex; justify-content:space-between; gap:12px; font-size:10px; color:var(--muted); margin-top:12px; line-height:1.7; }.chart-loading { margin-top:30px; }
@media(max-width:600px) { .equity-panel { padding:19px 14px; }header { gap:12px; flex-wrap:wrap; }.chart-value strong { font-size:23px; }footer { flex-direction:column; } }
</style>
