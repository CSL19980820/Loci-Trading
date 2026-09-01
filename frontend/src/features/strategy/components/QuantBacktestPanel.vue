<script setup lang="ts">
import { computed, toRef } from 'vue'
import { ElMessage } from 'element-plus'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { copyText } from '@/shared/lib/clipboard'
import { strategyLabel } from '@/shared/lib/format'
import type { StrategyInfo } from '@/shared/types/quant'

import {
  buildHorizonSummaryText,
} from '../composables/quantBacktestSummary'
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

/**
 * 下拉与锁定框的文案一律中文：后端 name 缺失、或它本身就是 slug 形状
 * （`sanyuan-tail-v1`）时退回共享词表。value 仍是 slug，接口契约不变。
 */
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
  strategySlug,
  range,
  mode,
  busy,
  elapsedSec,
  expectedHint,
  horizonResult,
  tradeResult,
  errorText,
  activePreset,
  showCost,
  holdDays,
  stopLossEnabled,
  stopLossPct,
  commissionBps,
  stampDutyBps,
  slippageBps,
  entryLabel,
  entryDetail,
  subtitle,
  rangeShortcuts,
  tripCostPct,
  resultMeta,
  rangeLabel,
  activeHasResult,
  applyPreset,
  onRangeChange,
  disabledDate,
  run,
  stop,
  skippedText,
} = useQuantBacktestPanel({
  strategies: strategiesRef,
  lockedSlug: lockedSlugRef,
})

async function copyHorizonSummary(): Promise<void> {
  if (!horizonResult.value) return
  const text = buildHorizonSummaryText({
    strategy: strategySlug.value,
    range: rangeLabel.value,
    entry: entryLabel.value,
    t1: horizonResult.value.horizons.t1 ?? null,
    t3: horizonResult.value.horizons.t3 ?? null,
  })
  if (await copyText(text)) ElMessage.success('已复制 Horizon 摘要')
  else ElMessage.error('复制失败，请手动选中摘要文本复制')
}
</script>

<template>
  <div
    class="bt"
    v-loading="busy"
    :element-loading-text="`正在回测全市场信号 · 已跑 ${elapsedSec}s · ${expectedHint}`"
  >
    <!--
      不留「战法回测」标题：这块只出现在工坊的「回测」Tab 与策稿台底坞的「回测」页里，
      两处高亮的分区名已经说完了。原来标题下面那行口径副标题（subtitle）也不留在版面上，
      挂到「口径」切换器的 tooltip 上 —— 它本来就是解释这个切换器的。
    -->
    <header class="bt-rail">
      <el-form class="bt-rail__form" inline label-position="left" label-width="6.5em" @submit.prevent="run">
        <el-form-item label="口径">
          <el-tooltip placement="bottom-start" :content="subtitle">
            <el-radio-group v-model="mode" :disabled="busy" size="default">
              <el-radio-button value="horizon">Horizon T+N</el-radio-button>
              <el-radio-button value="trade">成交回测</el-radio-button>
            </el-radio-group>
          </el-tooltip>
        </el-form-item>
        <el-form-item label="战法">
          <el-input
            v-if="lockedSlug"
            :model-value="lockedLabel"
            readonly
            style="width: 180px"
          />
          <el-select
            v-else
            v-model="strategySlug"
            filterable
            placeholder="选择战法"
            style="width: 180px"
            :disabled="loading || !strategies.length || busy"
          >
            <el-option
              v-for="s in strategyOptions"
              :key="s.slug"
              :label="s.label"
              :value="s.slug"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="区间">
          <el-date-picker
            v-model="range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始"
            end-placeholder="结束"
            :disabled-date="disabledDate"
            :shortcuts="rangeShortcuts"
            :disabled="busy"
            style="width: 250px"
            @change="onRangeChange"
          />
        </el-form-item>
        <el-form-item>
          <el-button-group class="bt-presets">
            <el-button
              :type="activePreset === 30 ? 'primary' : 'default'"
              :disabled="busy"
              @click="applyPreset(30)"
            >
              近一月
            </el-button>
            <el-button
              :type="activePreset === 90 ? 'primary' : 'default'"
              :disabled="busy"
              @click="applyPreset(90)"
            >
              近三月
            </el-button>
            <el-button
              :type="activePreset === 180 ? 'primary' : 'default'"
              :disabled="busy"
              @click="applyPreset(180)"
            >
              近六月
            </el-button>
          </el-button-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="busy" :disabled="!strategies.length" @click="run">
            跑回测
          </el-button>
          <el-button v-if="busy" type="warning" plain @click="stop">停止回测</el-button>
        </el-form-item>
        <el-form-item>
          <span class="bt-eta">
            {{ busy ? `已跑 ${elapsedSec}s · ${expectedHint}` : `预计：${expectedHint}` }}
          </span>
        </el-form-item>
      </el-form>

      <div v-if="mode === 'trade'" class="bt-trade-cfg">
        <el-form inline label-position="left" label-width="6.5em">
          <el-form-item label="持有日">
            <el-input-number v-model="holdDays" :min="1" :max="60" :disabled="busy" controls-position="right" />
          </el-form-item>
          <el-form-item label="止损">
            <el-switch v-model="stopLossEnabled" :disabled="busy" inline-prompt active-text="开" inactive-text="关" />
          </el-form-item>
          <el-form-item v-if="stopLossEnabled" label="止损%">
            <el-input-number
              v-model="stopLossPct"
              :min="-50"
              :max="0"
              :step="0.5"
              :disabled="busy"
              controls-position="right"
            />
          </el-form-item>
          <el-form-item>
            <el-button link type="primary" @click="showCost = !showCost">
              {{ showCost ? '收起成本' : '成本参数' }}
            </el-button>
            <span class="bt-trip">一趟约 {{ tripCostPct.toFixed(2) }}%</span>
          </el-form-item>
        </el-form>
        <el-form v-if="showCost" inline label-position="left" label-width="6.5em" class="bt-cost">
          <el-form-item label="佣金bps">
            <el-input-number v-model="commissionBps" :min="0" :max="50" :step="0.5" :disabled="busy" controls-position="right" />
          </el-form-item>
          <el-form-item label="印花税bps">
            <el-input-number v-model="stampDutyBps" :min="0" :max="50" :step="0.5" :disabled="busy" controls-position="right" />
          </el-form-item>
          <el-form-item label="滑点bps">
            <el-input-number v-model="slippageBps" :min="0" :max="50" :step="0.5" :disabled="busy" controls-position="right" />
          </el-form-item>
        </el-form>
      </div>

      <p class="bt-rail__meta">
        入场 <strong>{{ entryLabel }}</strong>
        <span class="dot">·</span>
        {{ entryDetail }}
        <span class="dot">·</span>
        切换口径会保留上次结果 · 设置记在本会话
      </p>
    </header>

    <el-alert
      v-if="errorText"
      :title="errorText"
      type="error"
      show-icon
      closable
      class="bt-alert"
      @close="errorText = ''"
    />

    <EmptyState
      v-if="!activeHasResult && !busy"
      description="还没有回测结果"
      reason="选好口径与战法后点「跑回测」"
    />

    <div v-if="mode === 'horizon' && horizonResult" class="bt-result" :key="`${resultMeta}-hz`">
      <div class="bt-result__bar">
        <p class="bt-result__meta">{{ resultMeta }} · horizon</p>
        <el-button size="small" @click="copyHorizonSummary">复制摘要</el-button>
      </div>
      <QuantBacktestCompareStrip
        :t1="horizonResult.horizons.t1"
        :t3="horizonResult.horizons.t3"
      />
      <div class="bt-horizons">
        <QuantBacktestHorizonCard title="T+1" :stats="horizonResult.horizons.t1 ?? null" />
        <QuantBacktestHorizonCard title="T+3" :stats="horizonResult.horizons.t3 ?? null" />
      </div>
      <p class="bt-footnote">
        高点口径是乐观上沿；收盘口径更接近可兑现。要看止损/成本/资金曲线请切「成交回测」（结果会保留）。
      </p>
      <p v-if="skippedText(horizonResult.skipped)" class="bt-skip">
        跳过：{{ skippedText(horizonResult.skipped) }}
      </p>
    </div>

    <div v-if="mode === 'trade' && tradeResult" class="bt-result" :key="`${resultMeta}-tr`">
      <p class="bt-result__meta">{{ resultMeta }} · trade</p>
      <QuantBacktestTradeResult
        :result="tradeResult"
        :strategy-label="strategySlug"
        :range-label="rangeLabel"
      />
      <p v-if="skippedText(tradeResult.skipped)" class="bt-skip">
        跳过：{{ skippedText(tradeResult.skipped) }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.bt {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  min-height: 0;
  padding: 0 var(--gap-1) var(--gap-2);
  position: relative;
}
.bt-rail {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--sheet) 92%, var(--paper)) 0%, var(--sheet) 100%);
}

.bt-rail__form {
  margin: 0;
}
.bt-rail__form :deep(.el-form-item),
.bt-trade-cfg :deep(.el-form-item),
.bt-cost :deep(.el-form-item) {
  margin-bottom: var(--gap-1);
}
.bt-trade-cfg {
  padding-top: var(--gap-1);
  border-top: 1px dashed var(--rule);
}
.bt-eta {
  font-size: var(--fs-aux);
  color: var(--mist);
}

.bt-trip {
  margin-left: var(--gap-2);
  font: var(--fs-aux)/1.4 var(--mono);
  color: var(--mist);
}
.bt-rail__meta {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
  line-height: 1.45;
}
.bt-rail__meta strong {
  color: var(--ink);
  font-weight: 600;
}
.bt-rail__meta .dot {
  margin: 0 var(--gap-1);
  opacity: 0.5;
}
.bt-alert {
  margin: 0;
}
.bt-result {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  min-height: 0;
  animation: bt-in 0.28s ease both;
}
.bt-result__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-1);
}
.bt-result__meta {
  margin: 0;
  font: var(--fs-aux)/1.4 var(--mono);
  color: var(--mist);
}
.bt-horizons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--gap-2);
  min-height: 0;
}
.bt-footnote,
.bt-skip {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
  line-height: 1.45;
}
@keyframes bt-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .bt-result {
    animation: none;
  }
}
@media (max-width: 960px) {
  .bt-horizons {
    grid-template-columns: 1fr;
  }
}
</style>
