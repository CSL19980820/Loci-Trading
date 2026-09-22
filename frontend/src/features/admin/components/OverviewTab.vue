<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref } from 'vue'
import { RefreshCw, Search } from '@lucide/vue'
import { getAdminModelUsage, type ModelUsageItem } from '@/shared/api/admin'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import DateField from '@/shared/components/ui/app/DateField.vue'
import ChoiceField from '@/shared/components/ui/app/ChoiceField.vue'
import ChoiceOption from '@/shared/components/ui/app/ChoiceOption.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { guardianToday, guardianDaysAgo } from '@/features/ops/composables/useGuardianHistory'
import { toErrorMessage } from '@/shared/lib/errors'
import { formatTokens } from '../lib/adminFormat'
const ModelUsageChart = defineAsyncComponent(() => import('./ModelUsageChart.vue'))
const today = guardianToday()
const dates = ref<[string, string] | null>([`${today.slice(0,7)}-01`, today])
const applied = ref<[string, string]>([`${today.slice(0,7)}-01`, today])
const view = ref('area')
const metric = ref('tokens')
const grouping = ref('model')
const model = ref('all')
const loading = ref(false)
const loaded = ref(false)
const error = ref('')
const incomplete = ref(false)
const rows = ref<ModelUsageItem[]>([])
const revision = ref(0)
const modelKey = (item: ModelUsageItem) => JSON.stringify([item.provider, item.model])
const models = computed(() => [...new Map(rows.value.map(row => [modelKey(row), { key: modelKey(row), label: `${row.model} · ${row.provider}` }])).values()])
const filtered = computed(() => model.value === 'all' ? rows.value : rows.value.filter(row => modelKey(row) === model.value))
const totals = computed(() => filtered.value.reduce((sum, row) => ({ input: sum.input + row.input_tokens, output: sum.output + row.output_tokens, calls: sum.calls + row.calls }), { input: 0, output: 0, calls: 0 }))
const summary = computed(() => [
  { label: '合计 Tokens', value: formatTokens(totals.value.input + totals.value.output), exact: totals.value.input + totals.value.output },
  { label: '输入 Tokens', value: formatTokens(totals.value.input), exact: totals.value.input },
  { label: '输出 Tokens', value: formatTokens(totals.value.output), exact: totals.value.output },
  { label: '调用次数', value: totals.value.calls.toLocaleString('zh-CN'), exact: totals.value.calls },
])
const tableRows = computed(() => {
  const grouped = new Map<string, ModelUsageItem>()
  for (const item of filtered.value) {
    const key = JSON.stringify([grouping.value === 'daily' ? item.day : '', item.provider, item.model])
    const row = grouped.get(key) ?? { ...item, input_tokens: 0, output_tokens: 0, calls: 0 }
    row.input_tokens += item.input_tokens; row.output_tokens += item.output_tokens; row.calls += item.calls
    grouped.set(key, row)
  }
  return [...grouped.values()].map(item => ({ ...item, total: item.input_tokens + item.output_tokens })).sort((a,b) => (grouping.value === 'daily' ? b.day.localeCompare(a.day) : 0) || b.total - a.total)
})
const numeric = (prop: string) => (row: Record<string, unknown>) => Number(row[prop] || 0).toLocaleString('zh-CN')
const columns = computed<BasicTableColumn[]>(() => [
  ...(grouping.value === 'daily' ? [{ prop: 'day', label: '日期', width: 112 }] : []),
  { prop: 'model', label: '模型', minWidth: 150, showOverflowTooltip: true },
  { prop: 'provider', label: '提供方', minWidth: 110, showOverflowTooltip: true },
  { prop: 'calls', label: '调用次数', minWidth: 86, align: 'right', formatter: numeric('calls') },
  { prop: 'input_tokens', label: '输入 Tokens', minWidth: 110, align: 'right', formatter: numeric('input_tokens') },
  { prop: 'output_tokens', label: '输出 Tokens', minWidth: 110, align: 'right', formatter: numeric('output_tokens') },
  { prop: 'total', label: '合计 Tokens', minWidth: 118, align: 'right', formatter: numeric('total') },
])
async function loadPage(params: { currentPage: number; pageSize: number }) {
  const offset = (params.currentPage - 1) * params.pageSize
  return { list: tableRows.value.slice(offset, offset + params.pageSize), total: tableRows.value.length }
}
let generation = 0
async function load(): Promise<void> {
  if (!dates.value?.[0] || !dates.value?.[1] || dates.value[1] < dates.value[0]) { error.value = '请选择有效日期范围'; return }
  if ((Date.parse(dates.value[1]) - Date.parse(dates.value[0])) / 86400000 > 366) { error.value = '单次查询最多 366 天'; return }
  const range: [string, string] = [...dates.value]
  const request = ++generation
  loading.value = true; error.value = ''
  try {
    const data = await getAdminModelUsage(...range)
    if (request !== generation) return
    rows.value = data.items; incomplete.value = data.unavailable_tenants.length > 0
    applied.value = range; loaded.value = true; revision.value++
    if (model.value !== 'all' && !models.value.some(item => item.key === model.value)) model.value = 'all'
  } catch (caught) { if (request === generation) error.value = toErrorMessage(caught, '读取模型用量失败') }
  finally { if (request === generation) loading.value = false }
}
function preset(mode: 'today' | 'week' | 'month'): void {
  const day = guardianToday()
  dates.value = [mode === 'today' ? day : mode === 'week' ? guardianDaysAgo(6, day) : `${day.slice(0,7)}-01`, day]
  void load()
}
onMounted(() => { void load() })
onUnmounted(() => { generation++ })
</script>
<template>
  <section class="usage-workspace" aria-label="大模型用量">
    <header class="usage-header">
      <h1>大模型用量</h1><span v-if="loaded" class="usage-period">{{ applied[0] }} — {{ applied[1] }}</span>
      <Button access="read" variant="outline" size="sm" :disabled="loading" @click="load"><RefreshCw :class="{ 'animate-spin': loading }" />刷新</Button>
    </header>
    <form class="usage-filters" @submit.prevent="load">
      <div class="usage-presets"><Button access="read" type="button" variant="outline" size="sm" @click="preset('today')">今天</Button><Button access="read" type="button" variant="outline" size="sm" @click="preset('week')">近7天</Button><Button access="read" type="button" variant="outline" size="sm" @click="preset('month')">本月</Button></div>
      <DateField v-model="dates" type="daterange" value-format="YYYY-MM-DD" aria-label="用量日期范围" class="usage-dates" />
      <Button access="read" type="submit" size="sm" :disabled="loading"><Search />查询</Button>
      <ChoiceField v-model="model" aria-label="筛选模型" class="usage-model"><ChoiceOption value="all" label="全部模型" /><ChoiceOption v-for="item in models" :key="item.key" :value="item.key" :label="item.label" /></ChoiceField>
    </form>
    <Alert v-if="error" variant="destructive"><AlertTitle>{{ error }}{{ loaded ? '；下方保留上次成功查询的结果' : '' }}</AlertTitle></Alert>
    <Alert v-if="incomplete"><AlertTitle>部分账号用量读取失败，以下统计不完整；缺失日期不按零用量处理。</AlertTitle></Alert>
    <div class="usage-stats"><div v-for="item in summary" :key="item.label"><span>{{ item.label }}</span><strong :title="loaded ? item.exact.toLocaleString('zh-CN') : '尚未取得数据'">{{ loaded ? item.value : '—' }}</strong></div></div>
    <div class="usage-viewbar">
      <PageTabs v-model="view" variant="pill" :sticky="false" aria-label="用量展示方式" :items="[{name:'table',label:'列表'},{name:'line',label:'曲线'},{name:'area',label:'面积'}]" />
      <PageTabs v-if="view === 'table'" v-model="grouping" variant="pill" :sticky="false" aria-label="用量分组" :items="[{name:'model',label:'按模型'},{name:'daily',label:'按日明细'}]" />
      <PageTabs v-else v-model="metric" variant="pill" :sticky="false" aria-label="图表指标" :items="[{name:'tokens',label:'Tokens'},{name:'calls',label:'调用次数'}]" />
    </div>
    <div class="usage-body" :aria-busy="loading">
      <PageBusy :busy="loading" overlay label="读取用量…" />
      <BasicTable v-if="view === 'table'" :key="`${grouping}:${model}:${revision}`" :columns="columns" :request="loadPage" :pagination="{pageSize:20,pageSizes:[20,50,100]}" height="100%" empty-text="所选范围暂无用量记录" />
      <ModelUsageChart v-else-if="loaded && filtered.length" :rows="filtered" :start="applied[0]" :end="applied[1]" :mode="view === 'area' ? 'area' : 'line'" :metric="metric === 'calls' ? 'calls' : 'tokens'" :incomplete="incomplete" />
      <EmptyState v-else-if="!loading" :description="error && !loaded ? '用量读取失败，请重试' : '所选范围暂无用量记录'" />
    </div>
  </section>
</template>
<style scoped>
.usage-workspace { display:flex; flex-direction:column; flex:1 1 0%; min-height:0; min-width:0; gap:8px; overflow:hidden; }
.usage-header { display:flex; align-items:center; gap:12px; flex:none; min-width:0; }
.usage-header h1 { margin:0; font-size:17px; font-weight:650; }
.usage-header>button { margin-left:auto; }
.usage-period { color:var(--text-tertiary); font-size:12px; white-space:nowrap; }
.usage-filters { display:flex; align-items:center; flex-wrap:wrap; gap:6px; flex:none; min-width:0; }
.usage-presets { display:flex; gap:4px; }
.usage-dates { width:265px; max-width:100%; }
.usage-model { width:230px; min-width:0; margin-left:auto; }
.usage-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; padding:10px 0; flex:none; }
.usage-stats>div { display:flex; align-items:baseline; justify-content:space-between; gap:8px; min-width:0; border-inline-start:1px solid var(--border-subtle); padding-left:12px; }
.usage-stats>div:first-child { border:0; padding-left:0; }
.usage-stats span { font-size:12px; color:var(--text-tertiary); }
.usage-stats strong { font:650 21px/1.3 var(--mono); color:var(--text-primary); font-variant-numeric:tabular-nums; }
.usage-viewbar { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:6px; flex:none; }
.usage-viewbar :deep(.page-tabs) { margin-bottom:0; }
.usage-body { position:relative; display:flex; flex-direction:column; flex:1 1 0%; min-height:0; min-width:0; border:1px solid var(--border-subtle); border-radius:10px; overflow:hidden; background:var(--surface); }
.usage-body > :deep(.empty-state) { margin:auto; }
@media(max-width:1100px) { .usage-stats>div { flex-direction:column; gap:3px; } }
@media(max-width:640px) {
  .usage-workspace { gap:6px; }
  .usage-header { flex-wrap:wrap; gap:4px 8px; }
  .usage-header h1 { font-size:16px; }
  .usage-period { order:3; width:100%; font-size:11px; }
  .usage-filters { display:grid; grid-template-columns:minmax(0,1fr) auto; }
  .usage-presets { grid-column:1; grid-row:1; }
  .usage-dates { width:100%; grid-column:1; grid-row:2; }
  .usage-filters>button { grid-column:2; grid-row:2; }
  .usage-model { grid-column:1/-1; grid-row:3; width:100%; }
  .usage-stats { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 16px; padding:6px 0; }
  .usage-stats>div { flex-direction:row; border:0; padding:0; }
  .usage-stats strong { font-size:18px; }
  .usage-stats span { font-size:11px; }
  .usage-body { min-height:200px; }
}
</style>
