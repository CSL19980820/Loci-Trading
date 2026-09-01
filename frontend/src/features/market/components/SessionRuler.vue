<script setup lang="ts">
/**
 * A 股交易日刻度尺：按真实时段比例分段的横轨。
 * 午休画成断口（不画轨），刻针是当前时刻。时段推导在 `sessionRuler.ts`（纯函数 + 单测）。
 */
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'

import {
  computeSessionRuler,
  pctOfMinute,
  RULER_SEGMENTS,
  RULER_TICKS,
  segmentFill,
} from './sessionRuler'

const props = defineProps<{
  /** 后端 session.is_trading_day；缺省时按工作日兜底 */
  isTradingDay?: boolean | null
}>()

/** 30s 一跳足够：最小刻度是「分」。 */
const TICK_MS = 30_000

const now = ref(new Date())
let timer: ReturnType<typeof setInterval> | null = null

/** 注册/移除无条件对称；KeepAlive 离页也停表，回页立刻补一次当前时刻。 */
function startClock(): void {
  stopClock()
  now.value = new Date()
  timer = setInterval(() => {
    now.value = new Date()
  }, TICK_MS)
}

function stopClock(): void {
  if (timer) clearInterval(timer)
  timer = null
}

onMounted(startClock)
onActivated(startClock)
onDeactivated(stopClock)
onUnmounted(stopClock)

const state = computed(() =>
  computeSessionRuler({ now: now.value, isTradingDay: props.isTradingDay ?? null }),
)

/** 断口段不画轨；已收盘/休市整轨不填充。 */
const bars = computed(() => {
  const fillMinute = state.value.dimmed ? null : state.value.minutes
  return RULER_SEGMENTS.filter((seg) => seg.kind !== 'break').map((seg) => {
    const left = pctOfMinute(seg.startMin)
    return {
      id: seg.id,
      kind: seg.kind,
    label: seg.label,
      left,
      width: pctOfMinute(seg.endMin) - left,
      fill: segmentFill(seg, fillMinute) * 100,
    }
  })
})

const ticks = computed(() =>
  RULER_TICKS.map((tick) => ({ label: tick.label, pct: pctOfMinute(tick.min) })),
)

const legend = '09:15 竞价 · 09:30–11:30 早盘 · 11:30–13:00 午休 · 13:00–14:57 午盘 · 14:57 收盘竞价'
</script>

<template>
  <div class="ruler" :class="{ 'is-dim': state.dimmed }">
    <span class="ruler__edge">09:15</span>
    <el-tooltip :content="legend" placement="bottom" :show-after="220">
      <div
        class="ruler__rail"
        role="img"
        :aria-label="`交易时段刻度尺：${state.statusText}`"
        tabindex="0"
      >
        <div class="ruler__ticks" aria-hidden="true">
          <span
            v-for="tick in ticks"
            :key="tick.label"
            class="ruler__tick"
            :class="{ 'is-last': tick.pct >= 100 }"
            :style="{ left: `${tick.pct}%` }"
          >
            {{ tick.label }}
          </span>
        </div>
        <div class="ruler__track">
          <span
            v-for="bar in bars"
            :key="bar.id"
            class="ruler__seg"
            :class="`is-${bar.kind}`"
            :style="{ left: `${bar.left}%`, width: `${bar.width}%` }"
          >
            <i class="ruler__fill" :style="{ width: `${bar.fill}%` }" />
          </span>
          <i
            v-if="state.markerPct != null"
            class="ruler__needle"
            :style="{ left: `${state.markerPct}%` }"
          />
        </div>
      </div>
    </el-tooltip>
    <span class="ruler__status">{{ state.statusText }}</span>
  </div>
</template>

<style scoped>
.ruler {
  display: flex;
  align-items: center;
  gap: var(--gap-2, 8px);
  flex: 0 0 auto;
  padding: 0 var(--gap-2, 8px) 2px;
}

.ruler__edge,
.ruler__status {
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--mist);
  white-space: nowrap;
  flex: 0 0 auto;
}

.ruler__status {
  min-width: 11rem;
  text-align: right;
  color: var(--muted);
}

.ruler__rail {
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
  padding-top: 13px;
}

.ruler__rail:focus-visible {
  outline: 1px solid var(--seal);
  outline-offset: 3px;
}

.ruler__ticks {
  position: absolute;
  inset: 0 0 auto 0;
  height: 12px;
}

.ruler__tick {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--mist);
}

.ruler__tick.is-last {
  transform: translateX(-100%);
}

.ruler__track {
  position: relative;
  height: 4px;
}

.ruler__seg {
  position: absolute;
  top: 0;
  height: 4px;
  background: var(--rule);
  overflow: hidden;
}

/* 竞价段比连续竞价薄一档：不靠颜色也能一眼分出「不是连续交易」 */
.ruler__seg.is-auction {
  top: 1px;
  height: 2px;
}

.ruler__fill {
  display: block;
  height: 100%;
  background: var(--seal);
}

.is-dim .ruler__fill {
  background: var(--rule);
}

.ruler__needle {
  position: absolute;
  top: -3px;
  width: 2px;
  height: 10px;
  margin-left: -1px;
  background: var(--stamp, var(--seal));
  animation: ruler-breathe 2.6s ease-in-out infinite;
}

@keyframes ruler-breathe {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ruler__needle {
    animation: none;
  }
}

@media (max-width: 900px) {
  .ruler__status {
    min-width: 0;
  }
}
</style>
