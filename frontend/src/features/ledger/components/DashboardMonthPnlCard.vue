<script setup lang="ts">
import { computed } from 'vue'

import Sparkline from '@/shared/components/charts/Sparkline.vue'
import type { MonthPnlPoint } from '@/shared/types/palace'

const props = defineProps<{
  asOf: string
  pnl: number
  pnlPct: number | null
  curve: MonthPnlPoint[]
  note?: string
}>()

const monthLabel = computed(() => {
  const m = Number(props.asOf.slice(5, 7))
  return Number.isFinite(m) && m >= 1 ? `${m}月参考盈亏` : '本月参考盈亏'
})

const curveValues = computed(() => {
  const vals = props.curve.map((p) => p.cumulative_pnl)
  // 无波动时也画一条平线，避免空图
  if (vals.length === 0) return [0, props.pnl]
  if (vals.every((v) => v === vals[0])) return [vals[0], vals[0]]
  return vals
})

const tone = computed(() => {
  if (props.pnl > 0) return 'is-up'
  if (props.pnl < 0) return 'is-down'
  return ''
})

const sparkColor = computed(() => {
  if (props.pnl > 0) return 'var(--up)'
  if (props.pnl < 0) return 'var(--down)'
  return 'var(--mist)'
})

const pctText = computed(() => {
  if (props.pnlPct == null) return null
  const sign = props.pnlPct > 0 ? '+' : ''
  return `${sign}${props.pnlPct.toFixed(2)}%`
})

/** 同花顺大数字：+495,812.58（不带 ¥） */
function fmtSignedAmount(value: number): string {
  const abs = Math.abs(value).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  if (value > 0) return `+${abs}`
  if (value < 0) return `-${abs}`
  return abs
}
</script>

<template>
  <RouterLink
    class="month-card"
    :class="tone"
    to="/reviews"
    :title="note || '查看绩效详情'"
  >
    <div class="month-card__main">
      <div class="month-card__copy">
        <span class="month-card__title">{{ monthLabel }}</span>
        <strong class="month-card__pnl">{{ fmtSignedAmount(pnl) }}</strong>
        <p class="month-card__meta">
          <template v-if="pctText">收益率 {{ pctText.replace(/^\+/, '') }}</template>
          <template v-else>已实现参考盈亏</template>
          <span class="month-card__hint"> · 不含浮盈</span>
        </p>
      </div>
      <div class="month-card__chart" aria-hidden="true">
        <Sparkline
          class="month-card__spark"
          :values="curveValues"
          :width="168"
          :height="56"
          :color="sparkColor"
          :show-end-dot="true"
          :label="monthLabel"
        />
        <span v-if="pctText" class="month-card__bubble" :class="tone">{{ pctText.replace(/^\+/, '') }}</span>
      </div>
    </div>
    <span class="month-card__chev" aria-hidden="true">›</span>
  </RouterLink>
</template>

<style scoped>
.month-card {
  display: flex;
  align-items: stretch;
  gap: 0.35rem;
  margin: 0;
  padding: 0.75rem 0.85rem 0.7rem;
  border-top: 1px solid var(--rule);
  background: color-mix(in srgb, var(--panel-2) 40%, var(--sheet));
  text-decoration: none;
  color: inherit;
  transition: background 0.15s ease;
}

.month-card:hover {
  background: color-mix(in srgb, var(--seal-soft) 35%, var(--sheet));
}

.month-card__main {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.month-card__copy {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.month-card__title {
  font-size: 0.82rem;
  color: var(--ink);
  font-weight: 550;
  letter-spacing: 0.02em;
}

.month-card__pnl {
  font-size: 1.55rem;
  font-weight: 700;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
  letter-spacing: 0;
  color: var(--ink);
}

.month-card.is-up .month-card__pnl,
.month-card.is-up .month-card__meta {
  color: var(--up);
}

.month-card.is-down .month-card__pnl,
.month-card.is-down .month-card__meta {
  color: var(--down);
}

.month-card__meta {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.35;
  color: var(--mist);
}

.month-card__hint {
  color: var(--mist);
  font-weight: 400;
}

.month-card__chart {
  position: relative;
  flex: 0 0 10.5rem;
  width: 10.5rem;
  height: 3.6rem;
  display: flex;
  align-items: flex-end;
}

.month-card__spark {
  width: 100%;
  height: 100%;
  display: block;
}

.month-card__bubble {
  position: absolute;
  top: 0;
  right: 0;
  padding: 0.1rem 0.35rem;
  border-radius: 0.25rem;
  font-size: 0.68rem;
  font-weight: 650;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  background: color-mix(in srgb, var(--sheet) 88%, transparent);
  border: 1px solid var(--rule);
  color: var(--ink);
  line-height: 1.2;
  white-space: nowrap;
}

.month-card__bubble.is-up {
  color: var(--up);
  border-color: color-mix(in srgb, var(--up) 35%, var(--rule));
}

.month-card__bubble.is-down {
  color: var(--down);
  border-color: color-mix(in srgb, var(--down) 35%, var(--rule));
}

.month-card__chev {
  flex-shrink: 0;
  align-self: center;
  font-size: 1.15rem;
  color: var(--mist);
  line-height: 1;
  padding-left: 0.15rem;
}

@media (max-width: 640px) {
  .month-card__main {
    flex-direction: column;
    align-items: stretch;
  }

  .month-card__chart {
    flex-basis: auto;
    width: 100%;
    height: 3.2rem;
  }

  .month-card__pnl {
    font-size: 1.35rem;
  }
}
</style>
