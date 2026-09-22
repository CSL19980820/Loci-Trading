<script setup lang="ts">
import { computed } from 'vue'
import { Bell, ChevronRight, CircleHelp, Ellipsis, RefreshCw, ShieldCheck } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/shared/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import { formatDateTime } from '@/shared/lib/dateTime'
import type { GuardianAccount } from '@/shared/types/guardian'
import type { HoldingCurve } from '@/shared/types/holdingCurve'

const props = defineProps<{
  account: GuardianAccount; selectedCode: string; data: HoldingCurve; days: number
  mode: 'drawdown' | 'return' | 'pnl'; threshold: number; loading: boolean
}>()
const emit = defineEmits<{
  code: [value: string]; period: [value: string]; mode: [value: string]; refresh: []
  warning: []; method: []; protection: []; episode: []; quality: []
}>()
const summary = computed(() => props.data.summary)
const current = computed(() => summary.value.current_drawdown_pct)
const exceeded = computed(() => current.value != null && -current.value >= props.threshold)
const historical = computed(() => summary.value.max_drawdown_pct != null && -summary.value.max_drawdown_pct >= props.threshold)
const state = computed(() => current.value == null ? '估值待更新' : exceeded.value ? '已触及预警' : historical.value ? '区间内曾触及' : '未触及预警')
const distance = computed(() => current.value == null ? null : props.threshold + current.value)
const incomplete = computed(() => props.data.excluded_points || props.data.coverage.missing_snapshots || props.data.coverage.truncated)
const periods = [{ value:'1',label:'今日' },{ value:'7',label:'近7天' },{ value:'30',label:'近30天' },{ value:'90',label:'近90天' },{ value:'366',label:'近一年' }]
const pct = (value: number | null) => value == null ? '—' : `${value.toFixed(2)}%`
const money = (value: number | null) => value == null ? '—' : `${value > 0 ? '+' : ''}${(value / 100).toLocaleString('zh-CN', {minimumFractionDigits:2,maximumFractionDigits:2})}`
</script>

<template>
  <div class="mobile-curve">
    <div class="mobile-curve__scope">
      <Select :model-value="selectedCode || 'account'" @update:model-value="value => emit('code', String(value) === 'account' ? '' : String(value))">
        <SelectTrigger aria-label="曲线标的" class="mobile-curve__stock"><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem value="account">账户整体</SelectItem><SelectItem v-for="position in account.positions" :key="position.code" :value="position.code">{{ position.name }} · {{ position.code }}</SelectItem></SelectContent>
      </Select>
      <Select :model-value="String(days)" @update:model-value="value => emit('period', String(value))">
        <SelectTrigger aria-label="曲线区间" class="mobile-curve__period"><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem v-for="period in periods" :key="period.value" :value="period.value">{{ period.label }}</SelectItem></SelectContent>
      </Select>
      <DropdownMenu><DropdownMenuTrigger as-child><Button access="read" variant="ghost" size="icon" aria-label="曲线操作"><Ellipsis /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem access="read" :disabled="loading" @select="emit('refresh')"><RefreshCw />刷新曲线</DropdownMenuItem>
          <DropdownMenuItem access="read" @select="emit('warning')"><Bell />预警阈值 {{ threshold }}%</DropdownMenuItem>
          <DropdownMenuItem access="read" @select="emit('protection')"><ShieldCheck />止损保护</DropdownMenuItem>
          <DropdownMenuItem access="read" @select="emit('method')"><CircleHelp />计算口径</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
    <section class="mobile-curve__surface" :aria-busy="loading">
      <header class="mobile-curve__hero">
        <div class="mobile-curve__label"><span>当前回撤</span><span class="mobile-curve__state" :class="{'is-breached':exceeded,'is-pending':current == null}"><i />{{ state }}</span></div>
        <div class="mobile-curve__current" :class="{'is-breached':exceeded}">{{ pct(current) }}</div>
        <div class="mobile-curve__pnl"><span>{{ selectedCode ? '本轮持仓盈亏' : '账户累计盈亏' }}</span><b :class="(summary.last_valid_pnl_cents ?? 0) > 0 ? 'is-profit' : (summary.last_valid_pnl_cents ?? 0) < 0 ? 'is-loss' : ''">{{ money(summary.last_valid_pnl_cents) }} <small>元</small></b></div>
        <p v-if="current == null" class="mobile-curve__stale">最近有效回撤 {{ pct(summary.last_valid_drawdown_pct) }} · {{ formatDateTime(summary.last_valid_at) }}</p>
        <div class="mobile-curve__comparison">
          <Button access="read" variant="ghost" type="button" @click="emit('episode')"><span>最大回撤 <ChevronRight /></span><strong>{{ pct(summary.max_drawdown_pct) }}</strong></Button>
          <Button access="read" variant="ghost" type="button" @click="emit('warning')"><span>{{ exceeded ? '超出预警线' : `距${threshold}%预警线` }} <ChevronRight /></span><strong>{{ distance == null ? '—' : Math.abs(distance).toFixed(2) }} <small v-if="distance != null">个百分点</small></strong></Button>
        </div>
      </header>
      <div class="mobile-curve__switch">
        <ToggleGroup :model-value="mode" type="single" aria-label="曲线指标" @update:model-value="value => { if (value) emit('mode', String(value)) }">
          <ToggleGroupItem value="drawdown">回撤</ToggleGroupItem><ToggleGroupItem value="return">收益率</ToggleGroupItem><ToggleGroupItem value="pnl">盈亏金额</ToggleGroupItem>
        </ToggleGroup>
      </div>
      <slot />
      <Button access="read" variant="ghost" type="button" class="mobile-curve__quality" @click="emit('quality')"><time>{{ formatDateTime(summary.last_valid_at).slice(11,16) || '—' }} 更新</time><span :class="{ 'is-incomplete': incomplete }">{{ incomplete ? '采样不完整' : `${summary.valid_points} 个有效样本` }}<ChevronRight /></span></Button>
    </section>
  </div>
</template>

<style scoped>
.mobile-curve { width:100%; min-width:0; display:flex; flex-direction:column; gap:9px; padding:0 0 10px; }
.mobile-curve__scope { display:grid; grid-template-columns:minmax(0,1fr) 108px 40px; gap:6px; align-items:center; }
.mobile-curve__stock,.mobile-curve__period { width:100%; height:40px; font-size:13px; box-shadow:none; min-width:0; }
.mobile-curve__stock :deep([data-slot='select-value']) { overflow:hidden; text-overflow:ellipsis; }
.mobile-curve__surface { background:var(--surface); border:1px solid var(--border-subtle); border-radius:12px; overflow:hidden; }
.mobile-curve__hero { padding:16px 16px 8px; }
.mobile-curve__label { display:flex; align-items:center; justify-content:space-between; gap:8px; color:var(--text-secondary); font-size:13px; }
.mobile-curve__state { display:flex; align-items:center; gap:5px; font-size:11px; color:var(--text-secondary); }
.mobile-curve__state i { width:5px; height:5px; background:currentColor; border-radius:50%; }
.mobile-curve__current { margin:5px 0 9px; color:var(--text-primary); font:600 36px/1.15 var(--font); letter-spacing:-.045em; font-variant-numeric:tabular-nums; }
.mobile-curve__pnl { display:flex; align-items:baseline; justify-content:space-between; gap:8px; font-size:12px; color:var(--text-tertiary); }
.mobile-curve__pnl b { font:600 14px var(--font); font-variant-numeric:tabular-nums; color:var(--text-primary); }
.mobile-curve__pnl small { font-size:11px; font-weight:400; color:var(--text-tertiary); }
.mobile-curve__pnl b.is-profit { color:var(--up); }.mobile-curve__pnl b.is-loss { color:var(--down); }
.mobile-curve__comparison { display:grid; grid-template-columns:1fr 1fr; gap:12px; border-top:1px solid var(--border-subtle); margin-top:12px; padding-top:9px; }
.mobile-curve__comparison button { display:flex; flex-direction:column; align-items:flex-start; gap:4px; padding:2px 0 6px; border:0; background:transparent; text-align:left; min-height:52px; }
.mobile-curve__comparison button>span { display:flex; align-items:center; gap:3px; color:var(--text-tertiary); font-size:11px; }
.mobile-curve__comparison svg { width:11px; height:11px; }
.mobile-curve__comparison strong { color:var(--text-primary); font-size:18px; line-height:1.2; font-weight:600; font-variant-numeric:tabular-nums; }
.mobile-curve__comparison strong small { font-size:10px; font-weight:400; color:var(--text-tertiary); }
.mobile-curve__switch { padding:8px 12px 4px; border-top:1px solid var(--border-subtle); }
.mobile-curve__switch :deep([data-slot='toggle-group']) { width:100%; background:var(--surface-sunken); padding:3px; border-radius:8px; }
.mobile-curve__switch :deep(button) { flex:1; height:33px; min-width:0; border-radius:5px; font-size:13px; color:var(--text-secondary); }
.mobile-curve__switch :deep(button[data-state='on']) { background:var(--surface); color:var(--text-primary); font-weight:600; box-shadow:var(--shadow-xs); }
.mobile-curve__quality { display:flex; align-items:center; justify-content:space-between; gap:8px; width:100%; min-height:40px; padding:8px 14px; border:0; border-top:1px solid var(--border-subtle); background:transparent; color:var(--text-tertiary); font-size:11px; }
.mobile-curve__quality>span { display:flex; align-items:center; gap:4px; }.mobile-curve__quality svg { width:13px; height:13px; }
.mobile-curve__stale { color:var(--warn); font-size:11px; line-height:1.6; margin:6px 0 0; }
.is-breached { color:var(--up); }.is-pending,.is-incomplete { color:var(--warn); }
@media(max-height:720px) { .mobile-curve__hero { padding-top:12px; }.mobile-curve__current { font-size:32px; }.mobile-curve__comparison { margin-top:9px; } }
</style>
