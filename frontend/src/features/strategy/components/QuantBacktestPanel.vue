<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, toRef, type Ref } from 'vue'
import { ChartLine, CircleAlert, Copy, Info, Play, Square, X } from '@lucide/vue'
import { toast } from 'vue-sonner'

import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Card, CardAction, CardHeader, CardTitle } from '@/shared/components/ui/card'
import DateField from '@/shared/components/ui/app/DateField.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import {
  NumberField,
  NumberFieldContent,
  NumberFieldDecrement,
  NumberFieldIncrement,
  NumberFieldInput,
} from '@/shared/components/ui/number-field'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Switch } from '@/shared/components/ui/switch'
import StatCard from '@/shared/components/ui/StatCard.vue'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { copyText } from '@/shared/lib/clipboard'
import { strategyLabel } from '@/shared/lib/format'
import type { StrategyInfo } from '@/shared/types/quant'

import { buildHorizonSummaryText } from '../composables/quantBacktestSummary'
import { signed } from '../composables/quantFormat'
import { useQuantBacktestPanel } from '../composables/useQuantBacktestPanel'
import QuantBacktestCompareStrip from './QuantBacktestCompareStrip.vue'
import QuantBacktestHorizonCard from './QuantBacktestHorizonCard.vue'
import QuantBacktestTradeResult from './QuantBacktestTradeResult.vue'

const props = defineProps<{
  strategies: StrategyInfo[]
  loading?: boolean
  /** 策稿页注入：锁定当前技能，不展示战法下拉 */
  lockedSlug?: string
  lockedName?: string
}>()

const strategiesRef = computed(() => props.strategies)

/** 后端名称缺失或仍是 slug 时只转换展示文案，不改变请求中的标识。 */
function cnName(name: string | null | undefined, slug: string): string {
  const text = String(name || '').trim()
  if (text && !/^[a-z0-9][a-z0-9._-]*$/.test(text)) return text
  return strategyLabel(slug || text)
}

const strategyOptions = computed(() =>
  props.strategies.map((s) => ({ slug: s.slug, label: cnName(s.name, s.slug) })),
)
const lockedLabel = computed(() => cnName(props.lockedName, String(props.lockedSlug || '')))
const lockedSlugRef = toRef(props, 'lockedSlug')

const {
  strategySlug, range, mode, busy, elapsedSec, expectedHint,
  horizonResult, tradeResult, errorText, activePreset, showCost,
  holdDays, stopLossEnabled, stopLossPct, commissionBps, stampDutyBps, slippageBps,
  entryLabel, entryDetail, tripCostPct,
  resultMeta, rangeLabel, activeHasResult,
  applyPreset, onRangeChange, disabledDate, run, stop, skippedText,
} = useQuantBacktestPanel({ strategies: strategiesRef, lockedSlug: lockedSlugRef })

/**
 * NumberField 清空输入框时会给出 `undefined`；落回该字段的下限而不是 NaN。
 *
 * 处理函数在脚本里先把 ref 绑好再交给模板：模板里 `holdDays` 这类绑定已被解包成
 * `number`，把它当参数传进模板表达式拿不到 ref 本身。
 */
function numberSetter(target: Ref<number>, fallback: number): (value: number | undefined) => void {
  return (value) => {
    target.value = typeof value === 'number' && Number.isFinite(value) ? value : fallback
  }
}

const setHoldDays = numberSetter(holdDays, 1)
const setStopLossPct = numberSetter(stopLossPct, 0)
const setCommissionBps = numberSetter(commissionBps, 0)
const setStampDutyBps = numberSetter(stampDutyBps, 0)
const setSlippageBps = numberSetter(slippageBps, 0)

async function copyHorizonSummary(): Promise<void> {
  if (!horizonResult.value) return
  const text = buildHorizonSummaryText({
    strategy: strategySlug.value,
    range: rangeLabel.value,
    entry: entryLabel.value,
    t1: horizonResult.value.horizons.t1 ?? null,
    t3: horizonResult.value.horizons.t3 ?? null,
  })
  if (await copyText(text)) toast.success('已复制回测摘要')
  else toast.error('复制失败，请手动选中摘要文本复制')
}

/** KPI 卡上的读数：胜率一位小数，均值带符号；缺样本给 — */
function fmtRate(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1)}%`
}

function fmtSigned(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return signed(value)
}

function toneOf(value: number | null | undefined): 'up' | 'down' | '' {
  if (value == null || !Number.isFinite(value) || value === 0) return ''
  return value > 0 ? 'up' : 'down'
}
</script>

<template>
  <section class="bt" :aria-busy="busy" aria-label="战法回测">
    <Card class="bt-rail">
      <CardHeader class="border-b">
        <CardTitle>参数</CardTitle>
        <CardAction>
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            :model-value="mode"
            :disabled="busy"
            aria-label="回测口径"
            @update:model-value="(value) => (mode = value as 'horizon' | 'trade')"
          >
            <ToggleGroupItem value="horizon">信号 T+N</ToggleGroupItem>
            <ToggleGroupItem value="trade">成交回测</ToggleGroupItem>
          </ToggleGroup>
        </CardAction>
      </CardHeader>

      <form class="bt-rail__form" @submit.prevent="run">
        <div class="bt-field bt-field--strategy">
          <span class="bt-field__label">战法</span>
          <Input v-if="lockedSlug" :model-value="lockedLabel" readonly />
          <Select
            v-else
            :model-value="strategySlug"
            :disabled="loading || !strategies.length || busy"
            @update:model-value="(value) => (strategySlug = String(value))"
          >
            <SelectTrigger class="w-full" aria-label="选择战法">
              <SelectValue placeholder="选择战法" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="s in strategyOptions" :key="s.slug" :value="s.slug">
                {{ s.label }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="bt-field bt-field--range">
          <span class="bt-field__label">回测区间</span>
          <DateField v-model="range" type="daterange" value-format="YYYY-MM-DD"
            aria-label="回测区间" :disabled="busy" :disabled-date="disabledDate"
            class="w-full" @change="onRangeChange" />
        </div>
        <div class="bt-field bt-field--presets">
          <span class="bt-field__label">快捷区间</span>
          <div class="bt-presets" role="group" aria-label="快捷区间">
            <Button access="read" type="button" size="sm" :variant="activePreset === 30 ? 'secondary' : 'outline'" :disabled="busy" @click="applyPreset(30)">近一月</Button>
            <Button access="read" type="button" size="sm" :variant="activePreset === 90 ? 'secondary' : 'outline'" :disabled="busy" @click="applyPreset(90)">近三月</Button>
            <Button access="read" type="button" size="sm" :variant="activePreset === 180 ? 'secondary' : 'outline'" :disabled="busy" @click="applyPreset(180)">近六月</Button>
          </div>
        </div>
        <div class="bt-actions">
          <Button type="submit" :disabled="busy || !strategies.length">
            <Spinner v-if="busy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
            <Play v-else aria-hidden="true" />
            跑回测
          </Button>
          <Tooltip v-if="busy">
            <TooltipTrigger as-child>
              <Button type="button" variant="outline" @click="stop"><Square aria-hidden="true" />停止等待</Button>
            </TooltipTrigger>
            <TooltipContent>中止本页等待；已提交的服务端计算可能继续执行</TooltipContent>
          </Tooltip>
        </div>
      </form>

      <div v-if="mode === 'trade'" class="bt-trade-cfg">
        <div class="bt-config-form">
          <div class="bt-inline-field">
            <span class="bt-inline-field__label">持有日</span>
            <NumberField :model-value="holdDays" :min="1" :max="60" :disabled="busy" class="bt-num" @update:model-value="setHoldDays">
              <NumberFieldContent>
                <NumberFieldInput aria-label="持有日" />
                <NumberFieldIncrement />
                <NumberFieldDecrement />
              </NumberFieldContent>
            </NumberField>
          </div>
          <div class="bt-inline-field">
            <span class="bt-inline-field__label">止损</span>
            <Switch v-model="stopLossEnabled" :disabled="busy" aria-label="启用止损" />
          </div>
          <div v-if="stopLossEnabled" class="bt-inline-field">
            <span class="bt-inline-field__label">止损%</span>
            <NumberField :model-value="stopLossPct" :min="-50" :max="0" :step="0.5" :disabled="busy" class="bt-num" @update:model-value="setStopLossPct">
              <NumberFieldContent>
                <NumberFieldInput aria-label="止损百分比" />
                <NumberFieldIncrement />
                <NumberFieldDecrement />
              </NumberFieldContent>
            </NumberField>
          </div>
          <div class="bt-inline-field bt-cost-toggle">
            <Button access="read" variant="link" size="sm" class="h-auto p-0" :aria-expanded="showCost" @click="showCost = !showCost">
              {{ showCost ? '收起成本' : '成本参数' }}
            </Button>
            <span class="bt-trip">往返约 {{ tripCostPct.toFixed(2) }}%</span>
          </div>
        </div>
        <div v-if="showCost" class="bt-config-form bt-cost">
          <div class="bt-inline-field">
            <span class="bt-inline-field__label">佣金 bps</span>
            <NumberField :model-value="commissionBps" :min="0" :max="50" :step="0.5" :disabled="busy" class="bt-num" @update:model-value="setCommissionBps">
              <NumberFieldContent>
                <NumberFieldInput aria-label="佣金 bps" />
                <NumberFieldIncrement />
                <NumberFieldDecrement />
              </NumberFieldContent>
            </NumberField>
          </div>
          <div class="bt-inline-field">
            <span class="bt-inline-field__label">印花税 bps</span>
            <NumberField :model-value="stampDutyBps" :min="0" :max="50" :step="0.5" :disabled="busy" class="bt-num" @update:model-value="setStampDutyBps">
              <NumberFieldContent>
                <NumberFieldInput aria-label="印花税 bps" />
                <NumberFieldIncrement />
                <NumberFieldDecrement />
              </NumberFieldContent>
            </NumberField>
          </div>
          <div class="bt-inline-field">
            <span class="bt-inline-field__label">滑点 bps</span>
            <NumberField :model-value="slippageBps" :min="0" :max="50" :step="0.5" :disabled="busy" class="bt-num" @update:model-value="setSlippageBps">
              <NumberFieldContent>
                <NumberFieldInput aria-label="滑点 bps" />
                <NumberFieldIncrement />
                <NumberFieldDecrement />
              </NumberFieldContent>
            </NumberField>
          </div>
        </div>
      </div>

      <div class="bt-context">
        <Tooltip>
          <TooltipTrigger as-child>
            <span class="bt-entry" tabindex="0">
              入场 <strong>{{ entryLabel }}</strong>
              <Info class="bt-entry__icon" aria-hidden="true" />
            </span>
          </TooltipTrigger>
          <TooltipContent side="bottom" align="start">{{ entryDetail }}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger as-child>
            <span class="bt-eta" tabindex="0">全市场逐日回放</span>
          </TooltipTrigger>
          <TooltipContent side="bottom">{{ expectedHint }}</TooltipContent>
        </Tooltip>
      </div>
    </Card>

    <!-- 进度不能遮住操作区；stop 只取消客户端等待，不宣称已终止服务端任务。 -->
    <div v-if="busy" class="bt-progress" role="status" aria-live="polite">
      <Spinner class="bt-progress__spin animate-spin motion-reduce:animate-none" aria-hidden="true" />
      <span>正在回测<span class="bt-progress__time">已等待 {{ elapsedSec }}s</span></span>
      <span class="bt-progress__hint">{{ expectedHint }}</span>
    </div>
    <Alert v-if="errorText" variant="destructive" class="bt-alert">
      <CircleAlert />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ errorText }}</AlertTitle>
        <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="errorText = ''">
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>

    <Card v-if="!activeHasResult && !busy" class="bt-empty">
      <EmptyState :icon="ChartLine" description="还没有回测结果" reason="选好战法与区间后点「跑回测」；信号 T+N 看胜率分布，成交回测看资金曲线" />
    </Card>

    <div v-if="mode === 'horizon' && horizonResult" :key="`${resultMeta}-hz`" class="bt-result">
      <div class="bt-result__bar">
        <p class="bt-result__meta">{{ resultMeta }} · 信号回测</p>
        <Button access="read" variant="outline" size="sm" @click="copyHorizonSummary">
          <Copy aria-hidden="true" />
          复制摘要
        </Button>
      </div>
      <div class="stat-strip cols-4 bt-kpis" aria-label="回测读数">
        <StatCard label="T+1 胜率" :value="fmtRate(horizonResult.horizons.t1?.win_rate)" :hint="`有效样本 ${horizonResult.horizons.t1?.n ?? 0}`" />
        <StatCard label="T+1 均值（高点）" :value="fmtSigned(horizonResult.horizons.t1?.avg)" :tone="toneOf(horizonResult.horizons.t1?.avg)" :hint="horizonResult.horizons.t1?.close_avg != null ? `收盘口径 ${fmtSigned(horizonResult.horizons.t1?.close_avg)}` : undefined" />
        <StatCard label="T+3 胜率" :value="fmtRate(horizonResult.horizons.t3?.win_rate)" :hint="`有效样本 ${horizonResult.horizons.t3?.n ?? 0}`" />
        <StatCard label="T+3 均值（高点）" :value="fmtSigned(horizonResult.horizons.t3?.avg)" :tone="toneOf(horizonResult.horizons.t3?.avg)" :hint="horizonResult.horizons.t3?.close_avg != null ? `收盘口径 ${fmtSigned(horizonResult.horizons.t3?.close_avg)}` : undefined" />
      </div>
      <QuantBacktestCompareStrip :t1="horizonResult.horizons.t1" :t3="horizonResult.horizons.t3" />
      <div class="bt-horizons">
        <QuantBacktestHorizonCard title="T+1" :stats="horizonResult.horizons.t1 ?? null" />
        <QuantBacktestHorizonCard title="T+3" :stats="horizonResult.horizons.t3 ?? null" />
      </div>
      <p class="bt-footnote">高点口径是乐观上沿；收盘口径更接近可兑现。止损、成本与资金曲线见「成交回测」。</p>
      <p v-if="skippedText(horizonResult.skipped)" class="bt-skip">跳过：{{ skippedText(horizonResult.skipped) }}</p>
    </div>
    <div v-if="mode === 'trade' && tradeResult" :key="`${resultMeta}-tr`" class="bt-result">
      <p class="bt-result__meta">{{ resultMeta }} · 成交回测</p>
      <QuantBacktestTradeResult :result="tradeResult" :strategy-label="strategySlug" :range-label="rangeLabel" />
      <p v-if="skippedText(tradeResult.skipped)" class="bt-skip">跳过：{{ skippedText(tradeResult.skipped) }}</p>
    </div>
  </section>
</template>

<style scoped src="./QuantBacktestPanel.css"></style>
