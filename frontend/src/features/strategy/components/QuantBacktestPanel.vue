<script setup lang="ts">
import { computed, toRef } from 'vue'
import { InfoFilled, Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { copyText } from '@/shared/lib/clipboard'
import { strategyLabel } from '@/shared/lib/format'
import type { StrategyInfo } from '@/shared/types/quant'

import { buildHorizonSummaryText } from '../composables/quantBacktestSummary'
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
  entryLabel, entryDetail, subtitle, rangeShortcuts, tripCostPct,
  resultMeta, rangeLabel, activeHasResult,
  applyPreset, onRangeChange, disabledDate, run, stop, skippedText,
} = useQuantBacktestPanel({ strategies: strategiesRef, lockedSlug: lockedSlugRef })

async function copyHorizonSummary(): Promise<void> {
  if (!horizonResult.value) return
  const text = buildHorizonSummaryText({
    strategy: strategySlug.value,
    range: rangeLabel.value,
    entry: entryLabel.value,
    t1: horizonResult.value.horizons.t1 ?? null,
    t3: horizonResult.value.horizons.t3 ?? null,
  })
  if (await copyText(text)) ElMessage.success('已复制回测摘要')
  else ElMessage.error('复制失败，请手动选中摘要文本复制')
}
</script>

<template>
  <section class="bt" :aria-busy="busy" aria-label="战法回测">
    <header class="bt-rail">
      <el-form class="bt-rail__form" label-position="top" @submit.prevent="run">
        <el-form-item label="回测口径" class="bt-field bt-field--mode">
          <el-tooltip placement="bottom-start" :content="subtitle">
            <el-radio-group v-model="mode" :disabled="busy" aria-label="回测口径">
              <el-radio-button value="horizon">信号 T+N</el-radio-button>
              <el-radio-button value="trade">成交回测</el-radio-button>
            </el-radio-group>
          </el-tooltip>
        </el-form-item>
        <el-form-item label="战法" class="bt-field bt-field--strategy">
          <el-input v-if="lockedSlug" :model-value="lockedLabel" readonly />
          <el-select
            v-else v-model="strategySlug" filterable placeholder="选择战法"
            :disabled="loading || !strategies.length || busy"
          >
            <el-option v-for="s in strategyOptions" :key="s.slug" :label="s.label" :value="s.slug" />
          </el-select>
        </el-form-item>
        <el-form-item label="回测区间" class="bt-field bt-field--range">
          <el-date-picker
            v-model="range" type="daterange" value-format="YYYY-MM-DD"
            start-placeholder="开始日期" end-placeholder="结束日期"
            :disabled-date="disabledDate" :shortcuts="rangeShortcuts" :disabled="busy"
            @change="onRangeChange"
          />
        </el-form-item>
        <div class="bt-presets" role="group" aria-label="快捷区间">
          <el-button-group>
            <el-button :type="activePreset === 30 ? 'primary' : 'default'" :disabled="busy" @click="applyPreset(30)">近一月</el-button>
            <el-button :type="activePreset === 90 ? 'primary' : 'default'" :disabled="busy" @click="applyPreset(90)">近三月</el-button>
            <el-button :type="activePreset === 180 ? 'primary' : 'default'" :disabled="busy" @click="applyPreset(180)">近六月</el-button>
          </el-button-group>
        </div>
        <div class="bt-actions">
          <el-button type="primary" native-type="submit" :loading="busy" :disabled="!strategies.length">跑回测</el-button>
          <el-tooltip v-if="busy" content="中止本页等待；已提交的服务端计算可能继续执行">
            <el-button plain @click="stop">停止等待</el-button>
          </el-tooltip>
        </div>
      </el-form>

      <div v-if="mode === 'trade'" class="bt-trade-cfg">
        <el-form inline label-position="left" label-width="5em" class="bt-config-form">
          <el-form-item label="持有日">
            <el-input-number v-model="holdDays" :min="1" :max="60" :disabled="busy" controls-position="right" />
          </el-form-item>
          <el-form-item label="止损">
            <el-switch v-model="stopLossEnabled" :disabled="busy" inline-prompt active-text="开" inactive-text="关" />
          </el-form-item>
          <el-form-item v-if="stopLossEnabled" label="止损%">
            <el-input-number v-model="stopLossPct" :min="-50" :max="0" :step="0.5" :disabled="busy" controls-position="right" />
          </el-form-item>
          <el-form-item class="bt-cost-toggle">
            <el-button link type="primary" :aria-expanded="showCost" @click="showCost = !showCost">{{ showCost ? '收起成本' : '成本参数' }}</el-button>
            <span class="bt-trip">往返约 {{ tripCostPct.toFixed(2) }}%</span>
          </el-form-item>
        </el-form>
        <el-form v-if="showCost" inline label-position="left" label-width="6.5em" class="bt-config-form bt-cost">
          <el-form-item label="佣金 bps">
            <el-input-number v-model="commissionBps" :min="0" :max="50" :step="0.5" :disabled="busy" controls-position="right" />
          </el-form-item>
          <el-form-item label="印花税 bps">
            <el-input-number v-model="stampDutyBps" :min="0" :max="50" :step="0.5" :disabled="busy" controls-position="right" />
          </el-form-item>
          <el-form-item label="滑点 bps">
            <el-input-number v-model="slippageBps" :min="0" :max="50" :step="0.5" :disabled="busy" controls-position="right" />
          </el-form-item>
        </el-form>
      </div>

      <div class="bt-context">
        <el-tooltip :content="entryDetail" placement="bottom-start">
          <span class="bt-entry" tabindex="0">入场 <strong>{{ entryLabel }}</strong><el-icon><InfoFilled /></el-icon></span>
        </el-tooltip>
        <el-tooltip :content="expectedHint" placement="bottom">
          <span class="bt-eta" tabindex="0">全市场逐日回放</span>
        </el-tooltip>
        <span class="bt-context__hint">切换口径保留结果</span>
      </div>
    </header>

    <!-- 进度不能遮住操作区；stop 只取消客户端等待，不宣称已终止服务端任务。 -->
    <div v-if="busy" class="bt-progress" role="status" aria-live="polite">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>正在回测<span class="bt-progress__time">已等待 {{ elapsedSec }}s</span></span>
      <span class="bt-progress__hint">{{ expectedHint }}</span>
    </div>
    <el-alert v-if="errorText" :title="errorText" type="error" show-icon closable class="bt-alert" @close="errorText = ''" />

    <EmptyState v-if="!activeHasResult && !busy" description="还没有回测结果" reason="选好战法后点「跑回测」" />

    <div v-if="mode === 'horizon' && horizonResult" :key="`${resultMeta}-hz`" class="bt-result">
      <div class="bt-result__bar">
        <p class="bt-result__meta">{{ resultMeta }} · 信号回测</p>
        <el-button @click="copyHorizonSummary">复制摘要</el-button>
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
