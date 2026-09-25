<script setup lang="ts">
import { useElementSize } from '@vueuse/core'
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { Badge } from '@/shared/components/ui/badge'
import { useChartTheme } from '@/shared/lib/useChartTheme'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import KlineChart from '@/shared/components/charts/KlineChart.vue'
import { quantRequest, query } from '@/shared/api/quant_client'
import { artifactIdentity } from '../assistantArtifactState'
import { parseKlineBars, ASSISTANT_KLINE_MA } from '../assistantArtifacts'
import type { AiChartArtifact } from '@/shared/types/ai_assistant'
import type { KlineHoverPayload, IndicatorKind } from '@/shared/lib/klineConfig'

const props = defineProps<{ artifact: AiChartArtifact }>()
const identity = computed(() => artifactIdentity(props.artifact))
const resolvedName = ref('')
const bars = computed(() => parseKlineBars(props.artifact.data ?? {}))
const hover = shallowRef<KlineHoverPayload | null>(null)
const indicator = ref<IndicatorKind>('macd')
const maPeriods = [...ASSISTANT_KLINE_MA]
const plotElement = ref<HTMLElement | null>(null)
const { width: plotWidth } = useElementSize(plotElement)
const visibleBars = computed(() => plotWidth.value > 600 ? 60 : 30)
const { tokens } = useChartTheme()
const adjustments: Record<string,string> = {qfq:'前复权',hfq:'后复权',none:'不复权'}
const current = computed(() => hover.value?.bar ?? bars.value.at(-1))
const prevClose = computed(() => hover.value ? hover.value.prevClose : bars.value.at(-2)?.close)
const change = computed(() => current.value?.close != null && prevClose.value != null && prevClose.value > 0 ? (current.value.close / prevClose.value - 1) * 100 : null)
const name = computed(() => identity.value.name || resolvedName.value || '名称暂缺')
const adjustment = computed(() => (adjustments[String(props.artifact.data.adjust)] ?? ''))
const price = (value: unknown) => value == null || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(2)
const amount = (value: unknown) => {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  return Math.abs(n) >= 1e8 ? `${(n / 1e8).toFixed(2)} 亿元` : Math.abs(n) >= 1e4 ? `${(n / 1e4).toFixed(2)} 万元` : `${n.toFixed(2)} 元`
}
function changeIndicator(value: unknown): void { if (value === 'macd' || value === 'kdj') indicator.value = value }
let controller: AbortController | undefined
watch(() => [identity.value.code, identity.value.name], async () => {
  controller?.abort(); resolvedName.value = ''
  if (!identity.value.code || identity.value.name) return
  const request = new AbortController(); controller = request
  try {
    const rows = await quantRequest<Array<{code:string;name:string}>>(`/market/search${query({q:identity.value.code,limit:20})}`, {signal:request.signal})
    if (!request.signal.aborted) resolvedName.value = rows.find(row => row.code === identity.value.code)?.name || ''
  } catch { /* Metadata failure must not hide valid historical prices. */ }
}, {immediate:true})
watch(bars, () => { hover.value = null })
onBeforeUnmount(() => controller?.abort())
</script>
<template>
  <Card class="assistant-kline-card" :aria-label="`${name} ${identity.code} 日K`">
    <CardHeader class="kline-heading">
      <div class="kline-identity"><CardTitle>{{ name }} <small>{{ identity.code }}</small></CardTitle><div class="kline-context"><Badge variant="outline">日 K</Badge><span v-if="adjustment">{{ adjustment }}</span><time>{{ current?.trade_date }}</time></div></div>
      <ToggleGroup :model-value="indicator" type="single" aria-label="副图指标" @update:model-value="changeIndicator"><ToggleGroupItem value="macd">MACD</ToggleGroupItem><ToggleGroupItem value="kdj">KDJ</ToggleGroupItem></ToggleGroup>
    </CardHeader>
    <CardContent class="kline-content">
      <template v-if="bars.length">
        <dl class="kline-readings" aria-label="K线价格读数">
          <div><dt>收盘 / 元</dt><dd :class="change != null ? change > 0 ? 'positive' : change < 0 ? 'negative' : '' : ''">{{ price(current?.close) }}</dd></div>
          <div><dt>涨跌幅</dt><dd :class="change != null ? change > 0 ? 'positive' : change < 0 ? 'negative' : '' : ''">{{ change == null ? '—' : `${change > 0 ? '+' : ''}${change.toFixed(2)}%` }}</dd></div>
          <div><dt>开盘 / 元</dt><dd>{{ price(current?.open) }}</dd></div><div><dt>最高 / 元</dt><dd>{{ price(current?.high) }}</dd></div><div><dt>最低 / 元</dt><dd>{{ price(current?.low) }}</dd></div><div><dt>成交额</dt><dd>{{ amount(current?.amount) }}</dd></div>
        </dl>
        <div class="kline-ma" aria-label="均线读数"><span v-for="(ma,index) in hover?.ma" :key="ma.period" :style="{ color: tokens.maPalette[index] }">MA{{ ma.period }} <b>{{ price(ma.value) }}</b></span></div>
        <div ref="plotElement" class="kline-plot"><KlineChart scroll-through :bars="bars" period="day" :indicator="indicator" :ma-periods="maPeriods" :visible-bars="visibleBars" :stock-code="identity.code" :stock-name="name" @hover="hover = $event" /></div>
      </template>
      <EmptyState v-else compact description="该区间暂无有效K线数据" />
    </CardContent>
  </Card>
</template>
<style scoped>
.assistant-kline-card { width:100%; min-width:0; padding:0; gap:0; overflow:hidden; box-shadow:none; container-type:inline-size; }
.kline-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:16px 20px 12px; }
.kline-identity { display:flex; align-items:baseline; flex-wrap:wrap; gap:8px 14px; min-width:0; }
.kline-identity :deep([data-slot='card-title']) { font-size:16px; font-weight:600; }.kline-identity small { margin-left:8px; font:12px var(--mono); color:var(--text-tertiary); }
.kline-context { display:flex; align-items:center; gap:8px; color:var(--text-tertiary); font-size:11px; }
.kline-heading :deep([data-slot='toggle-group-item']) { height:28px; font-size:11px; padding:0 8px; }
.kline-content { padding:0 16px 12px; }
.kline-readings { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:8px; margin:0; padding:14px 4px 10px; border-top:1px solid var(--border-subtle); }
.kline-readings dt { margin-bottom:4px; color:var(--text-tertiary); font-size:11px; }.kline-readings dd { margin:0; font-size:16px; font-weight:550; font-variant-numeric:tabular-nums; }
.kline-readings .positive { color:var(--up); }.kline-readings .negative { color:var(--down); }
.kline-ma { display:flex; align-items:center; flex-wrap:wrap; gap:12px; min-height:24px; font-size:11px; font-variant-numeric:tabular-nums; }.kline-ma b { font-weight:500; }.ma-0 { color:var(--text-secondary); }.ma-1 { color:var(--info); }.ma-2 { color:var(--warn); }
.kline-plot { width:100%; height:clamp(340px,46dvh,500px); min-height:340px; }
.kline-plot :deep(.kline-chart__canvas) { min-height:0; }
@media(max-width:640px) { .kline-heading { padding:12px; align-items:flex-start; }.kline-content { padding:0 10px 8px; }.kline-readings { grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }.kline-readings dd { font-size:15px; }.kline-plot { height:330px; min-height:330px; } }
@container (max-width: 600px) {
  .kline-readings { grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px 8px; }
  .kline-heading { padding:12px; align-items:flex-start; }
  .kline-content { padding:0 10px 10px; }
  .kline-plot { height:340px; min-height:340px; }
}
</style>
