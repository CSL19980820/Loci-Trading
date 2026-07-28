<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import {
  CapabilityUnavailableError,
  getMarketCoverage,
  getStrategies,
  runBacktest,
  runScreen,
  syncMarket,
} from '@/shared/api/quant'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import StatCard from '@/shared/components/ui/StatCard.vue'
import type { BacktestResult, MarketCoverage, ScreenResult, StrategyInfo } from '@/shared/types/quant'

import QuantAnalysisPanel from './components/QuantAnalysisPanel.vue'
import QuantResultsPanel from './components/QuantResultsPanel.vue'
import QuantStrategiesPanel from './components/QuantStrategiesPanel.vue'
import QuantStrategyConfigDialog from './components/QuantStrategyConfigDialog.vue'
import QuantUniverseBar from './components/QuantUniverseBar.vue'
import { useQuantAnalysis } from './composables/useQuantAnalysis'
import { useQuantConfig } from './composables/useQuantConfig'
import { useQuantUniverse } from './composables/useQuantUniverse'

const activeTab = ref('strategies')
const strategies = ref<StrategyInfo[]>([])
const coverage = ref<MarketCoverage | null>(null)
const screenResult = ref<ScreenResult | null>(null)
const backtestResult = ref<BacktestResult | null>(null)
const busy = ref(false)
const syncBusy = ref(false)
const unavailable = ref('')

const setUnavailable = (msg: string) => {
  unavailable.value = msg
}
const setBusy = (v: boolean) => {
  busy.value = v
}

const {
  universePresets,
  universeStats,
  universePreset,
  universeBoards,
  excludeSt,
  previewCount,
  previewFunnelText,
  currentUniverse,
  applyPreset,
  onBoardsChange,
  onExcludeStChange,
  previewPool: runPreviewPool,
  loadUniverseMeta,
} = useQuantUniverse()

const {
  compareResult,
  optimizeResult,
  optimizeExpanded,
  optimizeRowsShown,
  analysisBusy,
  analysisLabel,
  optimizeTarget,
  analysisStart,
  runCompare,
  runOptimize,
  restoreAnalysisResults,
  clearAnalysisResults,
} = useQuantAnalysis(setUnavailable)

const {
  configTarget,
  configOpen,
  strategyJobs,
  llmProviders,
  configForm,
  selectedProviderModels,
  configTitle,
  openConfig,
  saveConfig,
  removeConfig,
} = useQuantConfig(strategies, setBusy, setUnavailable)

const needsBootstrap = computed(() =>
  /行情仓是空的|没有可同步的标的|数据体检未通过|empty_store|请先刷新证券列表/i.test(unavailable.value),
)

async function guard<T>(task: () => Promise<T>): Promise<T | null> {
  busy.value = true
  unavailable.value = ''
  try {
    return await task()
  } catch (caught: unknown) {
    unavailable.value =
      caught instanceof CapabilityUnavailableError
        ? caught.message
        : caught instanceof Error
          ? caught.message
          : '请求失败'
    return null
  } finally {
    busy.value = false
  }
}

async function reload(): Promise<void> {
  await guard(async () => {
    const [list, cov] = await Promise.all([getStrategies(), getMarketCoverage()])
    strategies.value = list
    coverage.value = cov
    await loadUniverseMeta()
  })
}

async function previewPool(): Promise<void> {
  await guard(() => runPreviewPool())
}

async function screen(slug: string): Promise<void> {
  backtestResult.value = null
  const result = await guard(() => runScreen({ strategy: slug, universe: currentUniverse() }))
  if (result) {
    screenResult.value = result
    activeTab.value = 'results'
    ElMessage.success(`选股完成：${result.picks.length} 只 · ${result.trade_date}`)
  }
}

async function backtest(slug: string): Promise<void> {
  screenResult.value = null
  const result = await guard(() =>
    runBacktest({
      strategy: slug,
      hold_days: 3,
      stop_loss_pct: -6,
      benchmark: '000300',
      universe: currentUniverse(),
    }),
  )
  if (result) {
    backtestResult.value = result
    activeTab.value = 'results'
  }
}

async function bootstrapMarket(): Promise<void> {
  syncBusy.value = true
  unavailable.value = ''
  ElMessage.info('同步可能需要一两分钟，请稍候')
  try {
    const report = await syncMarket({
      refresh_instruments: true,
      limit: 200,
      workers: 6,
      interval: 0.1,
    })
    ElMessage.success(
      `同步完成：成功 ${String(report.succeeded ?? 0)} / 跳过 ${String(report.skipped ?? 0)}`
        + (report.spot_rows ? ` · 当日实时 ${String(report.spot_rows)} 行` : ''),
    )
    coverage.value = await getMarketCoverage()
  } catch (caught: unknown) {
    unavailable.value = caught instanceof Error ? caught.message : '同步失败'
  } finally {
    syncBusy.value = false
  }
}

onMounted(() => {
  restoreAnalysisResults()
  void reload()
})
</script>

<template>
  <div class="page-fill">
    <PageHeader
      title="工坊"
      :subtitle="
        coverage
          ? `${coverage.codes} 只 · ${coverage.first_date || '—'} ~ ${coverage.last_date || '—'}`
          : undefined
      "
    >
      <el-button :disabled="busy" @click="reload">刷新</el-button>
      <el-button type="primary" :loading="syncBusy" @click="bootstrapMarket">同步行情</el-button>
    </PageHeader>

    <div class="page-scroll quant-scroll quant-scroll--busy">
      <PageBusy overlay :busy="busy && !coverage" />
      <el-alert
        v-if="unavailable"
        :title="unavailable"
        type="error"
        show-icon
        closable
        class="mb"
        @close="unavailable = ''"
      >
        <template v-if="needsBootstrap" #default>
          <p class="hint">行情仓为空或过期时选股会被拒绝。先同步行情。</p>
          <el-button size="small" type="primary" :loading="syncBusy" @click="bootstrapMarket">同步行情</el-button>
        </template>
      </el-alert>

      <el-alert
        v-if="coverage && coverage.codes === 0"
        type="warning"
        show-icon
        :closable="false"
        class="mb"
        title="行情仓为空：选股 / 回测都会失败"
      >
        <el-button size="small" type="primary" :loading="syncBusy" @click="bootstrapMarket">同步行情</el-button>
      </el-alert>

      <section v-if="coverage" class="stat-strip cols-5" aria-label="行情仓">
        <StatCard label="证券" :value="coverage.codes.toLocaleString('zh-CN')" />
        <StatCard label="日线行数" :value="coverage.rows.toLocaleString('zh-CN')" />
        <StatCard label="最新交易日" :value="coverage.last_date || '—'" />
        <StatCard label="同步失败" :value="coverage.failed_codes" :tone="coverage.failed_codes ? 'down' : ''" />
        <StatCard label="库体积" :value="`${(coverage.db_bytes / 1e6).toFixed(0)} MB`" />
      </section>

      <QuantUniverseBar
        v-model:universe-preset="universePreset"
        v-model:universe-boards="universeBoards"
        v-model:exclude-st="excludeSt"
        :universe-presets="universePresets"
        :universe-stats="universeStats"
        :preview-count="previewCount"
        :preview-funnel-text="previewFunnelText"
        :busy="busy"
        @apply-preset="applyPreset"
        @boards-change="onBoardsChange"
        @exclude-st-change="onExcludeStChange"
        @preview-pool="previewPool"
      />

      <el-tabs v-model="activeTab" class="quant-tabs">
        <el-tab-pane label="战法" name="strategies">
          <QuantStrategiesPanel
            :strategies="strategies"
            @screen="screen"
            @backtest="backtest"
            @config="openConfig"
          />
        </el-tab-pane>

        <el-tab-pane label="分析" name="analysis">
          <QuantAnalysisPanel
            :strategies="strategies"
            :analysis-busy="analysisBusy"
            :analysis-label="analysisLabel"
            v-model:optimize-target="optimizeTarget"
            v-model:analysis-start="analysisStart"
            v-model:optimize-expanded="optimizeExpanded"
            :compare-result="compareResult"
            :optimize-result="optimizeResult"
            :optimize-rows-shown="optimizeRowsShown"
            @run-compare="runCompare"
            @run-optimize="runOptimize"
            @clear-analysis-results="clearAnalysisResults"
          />
        </el-tab-pane>

        <el-tab-pane label="本次结果" name="results">
          <QuantResultsPanel :screen-result="screenResult" :backtest-result="backtestResult" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>

  <QuantStrategyConfigDialog
    v-model="configOpen"
    :title="configTitle"
    :config-target="configTarget"
    :busy="busy"
    :form="configForm"
    :selected-provider-models="selectedProviderModels"
    :llm-providers="llmProviders"
    :strategy-jobs="strategyJobs"
    @save="saveConfig"
    @remove="removeConfig"
    @closed="configTarget = ''"
  />
</template>

<style scoped>
.mb {
  margin-bottom: 0.65rem;
}
.hint {
  margin: 0.35rem 0 0.65rem;
  color: var(--muted);
  font-size: 0.88rem;
}
.quant-scroll {
  padding-bottom: 0.5rem;
}
.quant-scroll--busy {
  position: relative;
  min-height: 12rem;
}
.quant-tabs :deep(.el-tabs__header) {
  margin-bottom: 0.55rem;
}
</style>
