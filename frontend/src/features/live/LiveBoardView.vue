<script setup lang="ts">
/*
 * 盯盘大屏。
 *
 * 版型（自上而下全定高，只有主区吃弹性高度）：
 *   顶栏 40 → 指数带 64 → 主区 flex:1（左 1.6 : 右 1）→ 跑马灯 22 → 状态栏 24
 * 左列自上而下：涨跌分布条 110 → 四榜单 2×2 吃满；右列：信号流整列吃满。
 *
 * 块与块之间靠 1px hairline（grid gap + 容器底色）分层，不用阴影、不用大圆角（D3）。
 */
import { computed } from 'vue'
import type { QuoteRow } from '@/shared/api/marketStream'
import { useLiveBoard } from './composables/useLiveBoard'
import { useBoardInk } from './composables/useBoardInk'
import LiveTopBar from './components/LiveTopBar.vue'
import IndexBar from './components/IndexBar.vue'
import HeatStrip from './components/HeatStrip.vue'
import RankColumn from './components/RankColumn.vue'
import SignalStream from './components/SignalStream.vue'
import TickerTape from './components/TickerTape.vue'
import LiveStatusBar from './components/LiveStatusBar.vue'

const {
  status,
  dataStale,
  sourceError,
  staleMs,
  lastAsOf,
  source,
  sessionPhase,
  isLive,
  distribution,
  quotesList,
  indexRows,
  indexTrails,
  gainersRows,
  losersRows,
  turnoverRows,
  amountRows,
  signals,
  newSignalIds,
  connect,
} = useLiveBoard()

// 大屏默认跟随用户自选外观；「暗色」是顶栏上的显式开关，不替用户改色
const { inkOn, toggleInk } = useBoardInk()

/*
 * 整屏消费的全量报价直接用 useLiveBoard 增量维护的 quotesList。
 * 这里原来是 `computed(() => Array.from(quotesMap.value.values()))`——每帧走一遍
 * Map 迭代器物化整个数组，再把新引用级联给 HeatStrip / TickerTape / 状态栏。
 */

/** 四张榜单的身份：色条 + 数值口径。涨跌用红绿（价格语义），换手/额用蓝/黄。 */
const RANKS = [
  { key: 'gainers', title: '涨幅榜', valueType: 'pct', accent: 'up', hint: '待开盘' },
  { key: 'losers', title: '跌幅榜', valueType: 'pct', accent: 'down', hint: '待开盘' },
  { key: 'turnover', title: '换手率榜', valueType: 'turnover', accent: 'info', hint: '待开盘' },
  { key: 'amount', title: '成交额榜', valueType: 'amount', accent: 'warn', hint: '待开盘' },
] as const

const rankRows = computed<Record<string, QuoteRow[]>>(() => ({
  gainers: gainersRows.value,
  losers: losersRows.value,
  turnover: turnoverRows.value,
  amount: amountRows.value,
}))
</script>

<template>
  <div class="page-fill page-fill--flush live-board live-board-theme">
    <!-- page-fill--flush：壳给右侧容器加了左右内边距，这个逃生舱让大屏保持满幅 -->
    <LiveTopBar
      :status="status"
      :as-of="lastAsOf"
      :session-phase="sessionPhase"
      :is-live="isLive"
      :data-stale="dataStale"
      :stale-ms="staleMs"
      :source-error="sourceError"
      :ink-on="inkOn"
      @refresh="connect"
      @toggle-ink="toggleInk"
    />

    <IndexBar :rows="indexRows" :trails="indexTrails" />

    <main class="live-board__main">
      <div class="live-board__left">
        <HeatStrip :rows="quotesList" :distribution="distribution" />

        <div class="live-board__ranks">
          <RankColumn
            v-for="col in RANKS"
            :key="col.key"
            :title="col.title"
            :rows="rankRows[col.key] ?? []"
            :value-type="col.valueType"
            :accent="col.accent"
      :status="status"
            :empty-hint="col.hint"
          />
        </div>
      </div>

      <SignalStream :signals="signals" :new-signal-ids="newSignalIds" :status="status" />
    </main>

    <TickerTape :rows="quotesList" />

    <LiveStatusBar
      :source="source"
      :status="status"
      :as-of="lastAsOf"
      :stale-ms="staleMs"
      :source-error="sourceError"
      :quote-count="quotesList.length"
      :signal-count="signals.length"
    />
  </div>
</template>

<!--
  live-theme.css 必须是**全局**样式：里面的 .live-block / .live-num / --live-* 由
各子组件消费，套上 scoped 的 data-v 属性后子组件内部元素匹配不到。
-->
<style>
@import './live-theme.css';
</style>

<style scoped>
/* .page-fill 已经给了 flex:1 / height:100% / overflow:hidden（style.layout.css） */
.live-board {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background-color: var(--live-bg);
  user-select: none;
}

/*
 * 主区：左 1.6 : 右 1。gap 1px + 容器底色 = 块间 hairline，
 * 既省掉每块的 border，也不会出现双线。
 */
.live-board__main {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
  gap: 1px;
  background-color: var(--live-rule);
  overflow: hidden;
}

.live-board__left {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.live-board__ranks {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: repeat(2, minmax(0, 1fr));
  gap: 1px;
  background-color: var(--live-rule);
  overflow: hidden;
}

/* 超宽屏：榜单摊成一排四列，信号流不变 */
@media (min-width: 1800px) {
  .live-board__ranks {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    grid-template-rows: minmax(0, 1fr);
  }
}

/* 窄屏：信号流退到左列之下，主区改内滚，不产生文档级滚动条 */
@media (max-width: 1100px) {
  .live-board__main {
    grid-template-columns: minmax(0, 1fr);
    grid-auto-rows: minmax(14rem, auto);
    overflow-y: auto;
  }
}
</style>
