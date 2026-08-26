<script setup lang="ts">
import { computed, toRef } from 'vue'
import { ElMessage } from 'element-plus'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
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
const lockedSlugRef = toRef(props, 'lockedSlug')

const {
  strategySlug,
  range,
  mode,
  busy,
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
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制 Horizon 摘要')
  } catch {
    ElMessage.error('复制失败')
  }
}
</script>

<template>
  <div class="bt" v-loading="busy" element-loading-text="正在回测全市场信号，请稍候…">
    <header class="bt-rail">
      <div class="bt-rail__title">
        <h2>战法回测</h2>
        <p>{{ subtitle }}</p>
      </div>
      <el-form class="bt-rail__form" inline @submit.prevent="run">
        <el-form-item label="口径">
          <el-radio-group v-model="mode" :disabled="busy" size="default">
            <el-radio-button value="horizon">Horizon T+N</el-radio-button>
            <el-radio-button value="trade">成交回测</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="战法">
          <el-input
            v-if="lockedSlug"
            :model-value="lockedName || lockedSlug"
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
              v-for="s in strategies"
              :key="s.slug"
              :label="s.name"
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
        </el-form-item>
      </el-form>

      <div v-if="mode === 'trade'" class="bt-trade-cfg">
        <el-form inline>
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
        <el-form v-if="showCost" inline class="bt-cost">
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
      description="选口径与战法，用近一月 / 三月 / 六月再跑。全市场可能要几十秒。"
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
  gap: 0.85rem;
  min-height: 14rem;
  padding: 0.15rem 0.35rem 0.5rem;
  position: relative;
}
.bt-rail {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0.85rem 1rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius, 8px);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--sheet) 92%, var(--paper)) 0%, var(--sheet) 100%);
}
.bt-rail__title h2 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 650;
  color: var(--ink);
}
.bt-rail__title p {
  margin: 0.2rem 0 0;
  font-size: 0.8rem;
  color: var(--mist);
}
.bt-rail__form {
  margin: 0;
}
.bt-rail__form :deep(.el-form-item),
.bt-trade-cfg :deep(.el-form-item),
.bt-cost :deep(.el-form-item) {
  margin-bottom: 0.35rem;
}
.bt-trade-cfg {
  padding-top: 0.15rem;
  border-top: 1px dashed var(--rule);
}
.bt-trip {
  margin-left: 0.5rem;
  font: 0.78rem/1.4 var(--mono);
  color: var(--mist);
}
.bt-rail__meta {
  margin: 0;
  font-size: 0.8rem;
  color: var(--mist);
  line-height: 1.45;
}
.bt-rail__meta strong {
  color: var(--ink);
  font-weight: 600;
}
.bt-rail__meta .dot {
  margin: 0 0.35rem;
  opacity: 0.5;
}
.bt-alert {
  margin: 0;
}
.bt-result {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-height: 0;
  animation: bt-in 0.28s ease both;
}
.bt-result__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem;
}
.bt-result__meta {
  margin: 0;
  font: 0.78rem/1.4 var(--mono);
  color: var(--mist);
}
.bt-horizons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.85rem;
  min-height: 0;
}
.bt-footnote,
.bt-skip {
  margin: 0;
  font-size: 0.8rem;
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
