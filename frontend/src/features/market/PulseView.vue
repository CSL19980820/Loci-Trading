<script setup lang="ts">
import { computed } from 'vue'

import PulseIndexStrip from './components/PulseIndexStrip.vue'
import PulseMarketBoard from './components/PulseMarketBoard.vue'
import PulsePickTable from './components/PulsePickTable.vue'
import PulseTrackTable from './components/PulseTrackTable.vue'
import PulseWatchRail from './components/PulseWatchRail.vue'
import { usePulseHome } from './composables/usePulseHome'
import { usePulseIntelBrief } from './composables/usePulseIntelBrief'
import { usePulseSecondWave } from './composables/usePulseSecondWave'

const {
  loading,
  error,
  indices,
  alertCount,
  sessionText,
  asOfText,
  tapeError,
  alertsError,
  historyError,
  session,
  trackRows,
  todayRows,
  trackNote,
  todayDate,
  boardTab,
  boardRows,
  sectorRows,
  boardNote,
  boardAsOf,
  pickPctMode,
  reload,
  persistSpot,
  spotPersistBusy,
  setBoardTab,
  effectivePct,
} = usePulseHome()

const intelTradeDate = computed(
  () =>
    session.value?.last_trading_day ||
    session.value?.today ||
    '',
)
const { brief, briefError, briefLoading, loadBrief } = usePulseIntelBrief(intelTradeDate)
const { wave, waveError, waveLoading, loadWave } = usePulseSecondWave()

async function refreshAll(): Promise<void> {
  await Promise.all([reload(), loadBrief(), loadWave()])
}

const pickPctNote = computed(() => {
  if (pickPctMode.value === 'live') return '叠实时价'
  if (pickPctMode.value === 'local') return '本地日线价'
  return '价格待取'
})
</script>

<template>
  <div class="page-fill pulse-home" v-loading="loading">
    <div class="pulse-home__toolbar">
      <div class="pulse-home__title">
        <span class="pulse-home__eyebrow">LOCI · TAPE</span>
        <strong>盘面</strong>
        <span class="pulse-home__meta">
          {{ session?.today || '—' }} · {{ asOfText }} · {{ sessionText }}
        </span>
      </div>
      <div class="pulse-home__actions">
        <el-button
          size="small"
          :loading="spotPersistBusy"
          :disabled="loading"
          @click="persistSpot"
        >
          同步现价
        </el-button>
        <el-button size="small" type="primary" plain :loading="loading" @click="refreshAll">
          刷新
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="error"
      class="pulse-home__alert"
      type="error"
      :closable="false"
      :title="error"
      show-icon
    />
    <el-alert
      v-if="tapeError"
      class="pulse-home__alert"
      type="warning"
      :closable="false"
      :title="`指数/持仓行情更新失败：${tapeError}`"
      show-icon
    />
    <el-alert
      v-if="historyError"
      class="pulse-home__alert"
      type="warning"
      :closable="false"
      :title="historyError"
      show-icon
    />
    <el-alert
      v-if="alertsError"
      class="pulse-home__alert"
      type="warning"
      :closable="false"
      :title="`触价提醒不可用，请勿据此判断今日无止损：${alertsError}`"
      show-icon
    />

    <PulseIndexStrip
      :indices="indices"
      :alert-count="alertCount"
      :as-of="asOfText"
      :session-text="sessionText"
    />

    <PulseWatchRail
      class="pulse-home__watch"
      :brief="brief"
      :brief-loading="briefLoading"
      :brief-error="briefError"
      :wave="wave"
      :wave-loading="waveLoading"
      :wave-error="waveError"
    />

    <div class="page-scroll pulse-home__body">
      <div class="pulse-home__grid page-pane">
        <PulseTrackTable
          title="近选跟踪"
          :note="trackNote ? `${pickPctNote} · ${trackNote}` : '暂无近 5 日精选'"
          :rows="trackRows"
          empty="近 5 个交易日还没有精选入库。工作日 15:30 会自动跑盘后选股。"
        />
        <PulseMarketBoard
          :tab="boardTab"
          :rows="boardRows"
          :sector-rows="sectorRows"
          :note="boardNote"
          :as-of="boardAsOf"
          :pct-of="effectivePct"
          @update:tab="setBoardTab"
        />
      </div>

      <PulsePickTable
        class="pulse-home__today"
        title="今日选股"
        :note="
          todayDate
            ? `${todayDate} · 各战法合并 · ${pickPctNote}`
            : '今日尚未落库 · 默认 15:30 盘后自动跑'
        "
        :rows="todayRows"
        empty="今日还没有选股记录。可到选股工作台手动跑，或等 15:30 定时任务。"
        show-strategy
      />
    </div>
  </div>
</template>

<style scoped>
.pulse-home {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0.5rem 0.85rem 0.5rem;
  min-height: 0;
}

.pulse-home__body.page-scroll {
  padding-left: 0;
  padding-right: 0;
  padding-top: 0;
}

.pulse-home__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem 0.75rem;
}

.pulse-home__title {
  display: flex;
  align-items: baseline;
  gap: 0.55rem;
  flex-wrap: wrap;
}

.pulse-home__eyebrow {
  font: 600 var(--fs-kicker) / 1 var(--mono);
  letter-spacing: 0.08em;
  color: var(--seal);
}

/* 与其它页的账页页头同一套字：衬线标题，别再和正文一样粗细字号 */
.pulse-home__title strong {
  font-family: var(--font-display);
  font-size: 1.3rem;
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: 0.01em;
}

.pulse-home__meta {
  font-size: var(--fs-aux);
  color: var(--mist);
  font-variant-numeric: tabular-nums;
}

.pulse-home__actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.pulse-home__alert {
  flex: 0 0 auto;
}

.pulse-home__watch {
  flex-shrink: 0;
}

.pulse-home__body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.pulse-home__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(0, 0.9fr);
  gap: 0.45rem;
  /* 近选/榜样吃主要剩余高度；今日选股压低 */
  min-height: 200px;
  flex: 1 1 auto;
  max-height: none;
}

.pulse-home__today {
  flex: 0 0 auto;
  min-height: 0;
  height: min(22vh, 11.5rem);
  max-height: min(22vh, 11.5rem);
}

@media (max-width: 900px) {
  .pulse-home__grid {
    grid-template-columns: 1fr;
  }

  .pulse-home__today {
    height: auto;
    max-height: min(28vh, 14rem);
  }
}
</style>
