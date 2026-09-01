<script setup lang="ts">
/*
 * 全市场涨跌分布 —— 定高 110px 的紧凑分布条。
 *
 * 旧版是占半屏的 11 根柱子：收盘无数据时就是 11 个空白灰框，是整屏最刺眼的败笔。
 * 新版换成两层结构：
 *   1. 一条 stacked bar（跌停→涨停 11 档按**数量占比**分配宽度，浓淡色阶），
 *      一眼看多空力量对比；
 *   2. 下面一排 11 档刻度（档位标签 + 数量），提供精读。
 * 无数据时 stacked bar 压成一条 hairline（表示「没有分布」），刻度值显示「—」，
 * 高度不变、位置不变。
 */
import { computed } from 'vue'
import type { QuoteRow } from '@/shared/api/marketStream'
import type { MarketDistribution } from '@/shared/api/quant_market'
import { computeHeatBuckets, type HeatBucket } from '@/shared/lib/tape'

const props = defineProps<{
  rows?: QuoteRow[]
  distribution?: MarketDistribution | null
}>()

/** 11 档色阶：由中间向两端加深，全部派生自 --up / --down（见 live-theme.css） */
const SHADE: Record<string, string> = {
  limitDown: 'var(--live-down-5)',
  down7: 'var(--live-down-4)',
  down5: 'var(--live-down-3)',
  down3: 'var(--live-down-2)',
  down1: 'var(--live-down-1)',
  flat: 'var(--live-flat)',
  up1: 'var(--live-up-1)',
  up3: 'var(--live-up-2)',
  up5: 'var(--live-up-3)',
  up7: 'var(--live-up-4)',
  limitUp: 'var(--live-up-5)',
}

/*
 * 刻度数字的颜色**不能直接用色阶**（SHADE）。
 *
 * 色阶 1-2 档是刻意做淡的——它们是给色条填充用的，浅色底上和背景只有 1.3:1，
 * 数字印上去等于看不见（观感自查实测 1.34:1 / 1.56:1，AA 要求 4.5:1）。
 * 色条已经把「浓淡」这层信息表达完了，数字只需要交代**方向**：涨红 / 跌绿 / 平灰。
 * 所以这里只分三档，全部用 *-ink 深文字态，保证任何外观下都读得出来。
 */
const TICK_INK: Record<string, string> = {
  limitDown: 'var(--down-ink)',
  down7: 'var(--down-ink)',
  down5: 'var(--down-ink)',
  down3: 'var(--down-ink)',
  down1: 'var(--down-ink)',
  flat: 'var(--live-muted)',
  up1: 'var(--up-ink)',
  up3: 'var(--up-ink)',
  up5: 'var(--up-ink)',
  up7: 'var(--up-ink)',
  limitUp: 'var(--up-ink)',
}

const buckets = computed<HeatBucket[]>(() => {
  if (props.distribution?.buckets?.length) return props.distribution.buckets
  return computeHeatBuckets(props.rows ?? [])
})

const totalCount = computed<number>(() => {
  const fromApi = props.distribution?.total_count
  if (fromApi != null && fromApi > 0) return fromApi
  return buckets.value.reduce((sum, b) => sum + b.count, 0)
})

const hasData = computed(() => totalCount.value > 0)

const upCount = computed<number>(() => {
  if (props.distribution?.total_count && props.distribution.up_count != null) {
    return props.distribution.up_count
  }
  return (props.rows ?? []).filter((r) => r.pct > 0).length
})

const downCount = computed<number>(() => {
  if (props.distribution?.total_count && props.distribution.down_count != null) {
    return props.distribution.down_count
  }
  return (props.rows ?? []).filter((r) => r.pct < 0).length
})

const flatCount = computed<number>(() => {
  if (props.distribution?.total_count && props.distribution.flat_count != null) {
    return props.distribution.flat_count
  }
  return (props.rows ?? []).filter((r) => r.pct === 0).length
})

interface Segment extends HeatBucket {
  shade: string
  widthPct: number
}

/** 只有 count>0 的档进 stacked bar；0 档不占宽度（这才是「分布」的语义） */
const segments = computed<Segment[]>(() => {
  const total = buckets.value.reduce((sum, b) => sum + b.count, 0)
  if (total <= 0) return []
  return buckets.value
    .filter((b) => b.count > 0)
    .map((b) => ({
      ...b,
      shade: SHADE[b.key] ?? 'var(--live-flat)',
      widthPct: (b.count / total) * 100,
    }))
})

const ticks = computed(() =>
  buckets.value.map((b) => ({
    key: b.key,
    label: b.label,
    count: hasData.value ? String(b.count) : '—',
    shade: TICK_INK[b.key] ?? 'var(--live-muted)',
    strong: b.key === 'limitUp' || b.key === 'limitDown',
  })),
)
</script>

<template>
  <section class="heat live-block" aria-label="全市场涨跌分布">
    <header class="live-block__head">
      <span class="live-block__title">涨跌分布</span>
      <div class="heat__readout live-num">
        <span class="heat__stat heat__stat--up">涨 {{ hasData ? upCount : '—' }}</span>
        <span class="heat__stat heat__stat--flat">平 {{ hasData ? flatCount : '—' }}</span>
        <span class="heat__stat heat__stat--down">跌 {{ hasData ? downCount : '—' }}</span>
        <span class="heat__total">/ {{ hasData ? totalCount : 0 }} 家</span>
      </div>
    </header>

    <div class="heat__body">
      <div class="heat__bar" :class="{ 'heat__bar--void': !hasData }">
        <div
          v-for="seg in segments"
          :key="seg.key"
          class="heat__seg"
          :style="{ width: `${seg.widthPct}%`, backgroundColor: seg.shade }"
          :title="`${seg.label} ${seg.count} 家`"
        />
      </div>

      <div class="heat__ticks">
        <div v-for="tick in ticks" :key="tick.key" class="heat__tick">
          <span
            class="heat__tick-count live-num"
            :class="{ 'heat__tick-count--void': !hasData }"
            :style="hasData ? { color: tick.shade } : undefined"
          >
            {{ tick.count }}
          </span>
          <span class="heat__tick-label" :class="{ 'heat__tick-label--strong': tick.strong }">
            {{ tick.label }}
          </span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.heat {
  flex: none;
  height: var(--live-heat-h);
}

.heat__readout {
  display: flex;
  align-items: baseline;
  gap: var(--gap-2);
  font-size: var(--fs-body);
  font-weight: 700;
}

.heat__stat--up {
  color: var(--live-up);
}

.heat__stat--down {
  color: var(--live-down);
}

.heat__stat--flat {
  color: var(--live-flat);
}

.heat__total {
  font-size: var(--fs-kicker);
  font-weight: 500;
  color: var(--live-dim);
}

.heat__body {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--gap-2);
  padding: 0 var(--gap-3);
}

.heat__bar {
  display: flex;
  width: 100%;
  height: 14px;
  background-color: var(--live-head);
  overflow: hidden;
}

/* 无数据 = 没有分布：压成一条 hairline，不画 11 个空盒子 */
.heat__bar--void {
  height: 1px;
  background-color: var(--live-rule-strong);
}

.heat__seg {
  height: 100%;
  min-width: 1px;
  transition: width 320ms ease;
}

.heat__ticks {
  display: grid;
  grid-template-columns: repeat(11, minmax(0, 1fr));
  align-items: end;
}

.heat__tick {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  min-width: 0;
}

.heat__tick-count {
  font-size: var(--fs-aux);
  font-weight: 600;
  line-height: 1.2;
  color: var(--live-text);
}

.heat__tick-count--void {
  color: var(--live-dim);
}

.heat__tick-label {
  font-size: var(--fs-kicker);
  line-height: 1.2;
  color: var(--live-dim);
  white-space: nowrap;
}

.heat__tick-label--strong {
  color: var(--live-muted);
}

@media (max-width: 960px) {
  .heat__readout .heat__total {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .heat__seg {
    transition: none;
  }
}
</style>
