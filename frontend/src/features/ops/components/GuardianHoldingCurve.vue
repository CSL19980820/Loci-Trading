<script setup lang="ts">
import { computed, defineAsyncComponent, onActivated, onDeactivated, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { Bell, Ellipsis, RefreshCw, ShieldCheck } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/shared/components/ui/dropdown-menu'
import { Field, FieldLabel, FieldError } from '@/shared/components/ui/field'
import { Input } from '@/shared/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import Descriptions from '@/shared/components/ui/Descriptions.vue'
import { getHoldingCurve } from '@/shared/api/holdingCurve'
import { formatDateTime } from '@/shared/lib/dateTime'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import type { GuardianAccount } from '@/shared/types/guardian'
import type { HoldingCurve } from '@/shared/types/holdingCurve'
import type { CurveMetric } from './holdingCurvePresentation'

const HoldingCurveChart = defineAsyncComponent(() => import('./HoldingCurveChart.vue'))
const props = defineProps<{ account: GuardianAccount; selectedCode: string }>()
const emit = defineEmits<{ 'update:selectedCode': [value: string]; review: [] }>()
const mobile = useMobileLayout()
const data = shallowRef<HoldingCurve | null>(null)
const days = ref(30), mode = ref<CurveMetric>('drawdown')
const loading = ref(false), error = ref('')
const warningOpen = ref(false), protectionOpen = ref(false)
const threshold = ref(5), thresholdDraft = ref<string | number>(5)
const periods = [{ value:'1',label:'今日' },{ value:'7',label:'7天' },{ value:'30',label:'30天' },{ value:'90',label:'90天' },{ value:'366',label:'一年' }]
try {
  const value = Number(localStorage.getItem('loci.holding-curve.warning'))
  if (value >= .1 && value <= 50) threshold.value = value
} catch { /* Optional browser preference. */ }
const selected = computed({ get: () => props.selectedCode || 'account', set: value => emit('update:selectedCode', value === 'account' ? '' : value) })
const thresholdValid = computed(() => String(thresholdDraft.value).trim() !== '' && Number.isFinite(Number(thresholdDraft.value)) && Number(thresholdDraft.value) >= .1 && Number(thresholdDraft.value) <= 50)
watch(warningOpen, open => { if (open) thresholdDraft.value = threshold.value })
function saveThreshold(): void {
  if (!thresholdValid.value) return
  threshold.value = Math.round(Number(thresholdDraft.value) * 10) / 10
  try { localStorage.setItem('loci.holding-curve.warning', String(threshold.value)) } catch { /* Keep in memory. */ }
  warningOpen.value = false
}
function changeMode(value: unknown): void { if (value === 'drawdown' || value === 'return' || value === 'pnl') mode.value = value }
function changePeriod(value: unknown): void { if (periods.some(item => item.value === value)) days.value = Number(value) }
let controller: AbortController | undefined, timer: ReturnType<typeof setInterval> | undefined
let disposed = false, suspended = false
async function load(clear = false): Promise<void> {
  if (disposed || suspended) return
  controller?.abort()
  const request = new AbortController(); controller = request
  if (clear) data.value = null
  loading.value = true; error.value = ''
  try {
    const result = await getHoldingCurve(props.selectedCode, days.value, request.signal)
    if (!disposed && !request.signal.aborted) data.value = result
  } catch (caught) {
    if (!disposed && !request.signal.aborted) { data.value = null; error.value = caught instanceof Error ? caught.message : '曲线加载失败' }
  } finally { if (controller === request) loading.value = false }
}
function beginPolling(): void { clearInterval(timer); timer = setInterval(() => { if (!document.hidden && !loading.value) void load() }, 30000) }
onMounted(() => { void load(); beginPolling() })
onActivated(() => { if (suspended) { suspended = false; void load(); beginPolling() } })
onDeactivated(() => { suspended = true; controller?.abort(); loading.value = false; clearInterval(timer) })
onUnmounted(() => { disposed = true; controller?.abort(); clearInterval(timer) })
watch(() => [props.selectedCode, days.value], () => { void load(true) })
watch(() => JSON.stringify([props.account.equity_cents, props.account.positions.map(p => [p.code, p.quantity, p.mark_at])]), () => { if (!loading.value) void load() })
watch(() => props.account.positions.map(p => p.code).join(','), () => { if (props.selectedCode && !props.account.positions.some(p => p.code === props.selectedCode)) emit('update:selectedCode', '') })
const risks = computed(() => data.value?.protection.filter(r => !props.selectedCode || r.code === props.selectedCode) ?? [])
</script>

<template>
  <section class="holding-curve" aria-label="持仓收益与回撤">
    <header class="curve-toolbar">
      <ToggleGroup :model-value="mode" type="single" class="curve-modes" aria-label="曲线指标" @update:model-value="changeMode">
        <ToggleGroupItem value="drawdown">回撤</ToggleGroupItem><ToggleGroupItem value="return">收益率</ToggleGroupItem><ToggleGroupItem value="pnl">盈亏金额</ToggleGroupItem>
      </ToggleGroup>
      <div class="curve-filters">
        <Select v-model="selected"><SelectTrigger class="curve-code" aria-label="曲线标的"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="account">账户整体</SelectItem><SelectItem v-for="p in account.positions" :key="p.code" :value="p.code">{{ p.name }} · {{ p.code }}</SelectItem></SelectContent></Select>
        <Select v-if="mobile" :model-value="String(days)" @update:model-value="changePeriod"><SelectTrigger class="curve-period-select" aria-label="曲线区间"><SelectValue /></SelectTrigger><SelectContent><SelectItem v-for="period in periods" :key="period.value" :value="period.value">{{ period.label }}</SelectItem></SelectContent></Select>
        <ToggleGroup v-else :model-value="String(days)" type="single" class="curve-periods" aria-label="曲线区间" @update:model-value="changePeriod"><ToggleGroupItem v-for="period in periods" :key="period.value" :value="period.value">{{ period.label }}</ToggleGroupItem></ToggleGroup>
        <DropdownMenu><DropdownMenuTrigger as-child><Button access="read" variant="ghost" size="icon" aria-label="曲线操作"><Ellipsis /></Button></DropdownMenuTrigger><DropdownMenuContent align="end">
          <DropdownMenuItem access="read" @select="protectionOpen = true"><ShieldCheck />止损保护</DropdownMenuItem>
          <DropdownMenuItem access="read" @select="warningOpen = true"><Bell />预警阈值 {{ threshold }}%</DropdownMenuItem>
          <DropdownMenuItem access="read" :disabled="loading" @select="load()"><RefreshCw />刷新曲线</DropdownMenuItem>
        </DropdownMenuContent></DropdownMenu>
      </div>
    </header>
    <div class="curve-surface" :aria-busy="loading">
      <div v-if="error" class="curve-state" role="alert"><p>{{ error }}</p><Button access="read" variant="outline" @click="load()">重试</Button></div>
      <div v-else-if="!data" class="curve-loading"><Skeleton class="h-20" /><Skeleton class="grow" /></div>
      <HoldingCurveChart v-else-if="data.summary.valid_points" :data="data" :mode="mode" :threshold="threshold" />
      <div v-else class="curve-state">暂无有效估值样本</div>
    </div>
    <Dialog v-model:open="warningOpen"><DialogContent class="sm:max-w-md"><DialogHeader><DialogTitle>回撤预警</DialogTitle><DialogDescription>仅作显示提醒，不执行买卖。</DialogDescription></DialogHeader>
      <form class="curve-warning-form" @submit.prevent="saveThreshold"><Field :data-invalid="!thresholdValid"><FieldLabel for="holding-dd-threshold">预警阈值（%）</FieldLabel><Input id="holding-dd-threshold" v-model="thresholdDraft" type="number" min="0.1" max="50" step="0.1" inputmode="decimal" :aria-invalid="!thresholdValid" /><FieldError v-if="!thresholdValid">请输入0.1至50之间的数值</FieldError></Field><DialogFooter><Button access="read" type="button" variant="outline" @click="warningOpen = false">取消</Button><Button access="read" type="submit" :disabled="!thresholdValid">应用</Button></DialogFooter></form>
    </DialogContent></Dialog>
    <Dialog v-model:open="protectionOpen"><DialogContent class="sm:max-w-3xl"><DialogHeader><DialogTitle>止损保护</DialogTitle><DialogDescription class="sr-only">有效合同与可卖数量</DialogDescription></DialogHeader><div class="curve-protection-list">
      <section v-for="risk in risks" :key="risk.code"><h3>{{ risk.name }} <small>{{ risk.code }}</small></h3><Descriptions :items="[
        {key:'protected',label:'有效止损',value:`${risk.protected_quantity.toLocaleString()} / ${risk.quantity.toLocaleString()} 股`},
        {key:'available',label:'可卖',value:`${risk.available_quantity.toLocaleString()} 股`},
        {key:'locked',label:'T+1锁定',value:`${risk.locked_quantity.toLocaleString()} 股`},
        {key:'state',label:'参考行情',value:risk.stale?'待更新':'有效'},
        {key:'contracts',label:'止损合同',wide:true,value:risk.stops.map(s=>`${s.price.toFixed(2)} 元 × ${s.quantity.toLocaleString()} 股\n有效至 ${formatDateTime(s.valid_until)}${s.reached?' · 已进入止损区':''}`).join('\n\n')},
        {key:'invalid',label:'失效合同',value:risk.invalid_plans,wide:true}
      ]" /></section><p v-if="!risks.length">暂无持仓止损合同</p></div></DialogContent></Dialog>
  </section>
</template>
<style scoped src="./GuardianHoldingCurve.css"></style>
