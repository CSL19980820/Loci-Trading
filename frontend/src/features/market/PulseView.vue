<script setup lang="ts">
import { computed } from 'vue'

import PulseIndexStrip from './components/PulseIndexStrip.vue'
import PulseMarketBoard from './components/PulseMarketBoard.vue'
import PulsePickTable from './components/PulsePickTable.vue'
import PulseTrackTable from './components/PulseTrackTable.vue'
import { usePulseHome } from './composables/usePulseHome'

const {
  loading,
  error,
  indices,
  bagPct,
  positionCount,
  alertCount,
  sessionText,
  asOfText,
  tapeError,
  historyError,
  session,
  trackRows,
  todayRows,
  trackNote,
  todayDate,
  boardTab,
  boardRows,
  boardNote,
  pickPctMode,
  reload,
  setBoardTab,
  effectivePct,
} = usePulseHome()

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
        <strong>盘面</strong>
        <span class="pulse-home__meta">
          {{ session?.today || '—' }} · {{ asOfText }} · {{ sessionText }}
        </span>
      </div>
      <div class="pulse-home__actions">
        <el-button size="small" :loading="loading" @click="reload">刷新</el-button>
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

    <PulseIndexStrip
      :indices="indices"
      :bag-pct="bagPct"
      :position-count="positionCount"
      :alert-count="alertCount"
      :as-of="asOfText"
      :session-text="sessionText"
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
          :note="boardNote"
          :pct-of="effectivePct"
          @update:tab="setBoardTab"
        />
      </div>

      <PulsePickTable
        class="pulse-home__today"
          title="今日选股"
          :note="
            todayDate
            ? `${todayDate} · 各策略合并 · ${pickPctNote}`
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
  /* 与 .page-scroll 水平内边距一致，顶栏/指数条与下方卡片对齐 */
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
}

.pulse-home__title strong {
  font-size: 0.95rem;
}

.pulse-home__meta {
  font-size: 0.75rem;
  color: var(--mist);
  font-variant-numeric: tabular-nums;
}

.pulse-home__actions {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.pulse-home__alert {
  flex: 0 0 auto;
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
  grid-template-columns: minmax(0, 1.65fr) minmax(0, 0.85fr);
  gap: 0.55rem;
  min-height: 240px;
  flex: 1 1 auto;
}

.pulse-home__today {
  flex: 0 1 auto;
  min-height: 160px;
}

@media (max-width: 900px) {
  .pulse-home__grid {
    grid-template-columns: 1fr;
  }

  .pulse-home__today {
    max-height: none;
  }
}
</style>
