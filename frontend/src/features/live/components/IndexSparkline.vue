<script setup lang="ts">
/*
 * 极窄分时微图 —— 纯 SVG polyline，不引 ECharts。
 *
 * 为什么不用 ECharts：这块图高 28px、宽 ~72px，一条折线而已。旧版给每张指数卡
 * 起一个 canvas 实例 + resize 监听 + 主题 watch，五个指数就是五个实例，
 * 而且 ECharts 在没有数据时会画出一条「假基线」（旧代码真的用 sin() 造过波形，
 * 那是在骗人）。SVG 版本：有点画线，没点画一条 hairline，绝不编数据。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 分时点列（收盘价序列），少于 2 个点视为无数据 */
    points?: number[]
    /** 昨收基准线，给出时画一条虚线 */
    baseline?: number | null
    /** 价格语义：涨红跌绿（D1） */
    tone?: 'up' | 'down' | 'flat'
  }>(),
  { points: () => [], baseline: null, tone: 'flat' },
)

const W = 100
const H = 32
const PAD = 2

const series = computed<number[]>(() => (props.points ?? []).filter((n) => Number.isFinite(n)))

/*
 * 只有 1 个点时也算「有数据」：画一条位于当前点位高度的水平线，配合昨收虚线，
 * 读者立刻看出「现在比昨收高/低」。这不是编造走势——两个值都是真实数字，
 * 中间没有任何被臆造的路径。0 个点才退化成灰色 hairline。
 */
const hasData = computed(() => series.value.length >= 1)

/** 上下界包含昨收基准，保证基准线永远落在可视区内 */
const bounds = computed(() => {
  const values = [...series.value]
  if (props.baseline != null && Number.isFinite(props.baseline)) values.push(props.baseline)
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1 }
  if (max === min) return { min: min - 1, max: max + 1 }
  return { min, max }
})

function toY(value: number): number {
  const { min, max } = bounds.value
  const ratio = (value - min) / (max - min)
  return H - PAD - ratio * (H - PAD * 2)
}

const linePoints = computed<string>(() => {
  const list = series.value
  if (!list.length) return ''
  if (list.length === 1) return `0,${toY(list[0]).toFixed(2)} ${W},${toY(list[0]).toFixed(2)}`
  const step = W / (list.length - 1)
  return list.map((v, i) => `${(i * step).toFixed(2)},${toY(v).toFixed(2)}`).join(' ')
})

const areaPoints = computed<string>(() => {
  if (!linePoints.value) return ''
  return `0,${H} ${linePoints.value} ${W},${H}`
})

const baselineY = computed<number | null>(() => {
  if (props.baseline == null || !Number.isFinite(props.baseline)) return null
  if (!hasData.value) return null
  return toY(props.baseline)
})
</script>

<template>
  <svg
    class="spark"
    :class="`spark--${tone}`"
    :viewBox="`0 0 ${W} ${H}`"
    preserveAspectRatio="none"
    aria-hidden="true"
    focusable="false"
  >
    <template v-if="hasData">
      <polygon class="spark__area" :points="areaPoints" />
      <polyline class="spark__line" :points="linePoints" />
      <line
        v-if="baselineY !== null"
        class="spark__base"
        x1="0"
        :y1="baselineY"
        :x2="W"
        :y2="baselineY"
      />
    </template>
    <!-- 无数据：一条扫平的 hairline，不编造走势 -->
    <line v-else class="spark__void" x1="0" :y1="H / 2" :x2="W" :y2="H / 2" />
  </svg>
</template>

<style scoped>
.spark {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}

.spark__line {
  fill: none;
  stroke: var(--live-flat);
  stroke-width: 1.2;
  vector-effect: non-scaling-stroke;
  stroke-linejoin: round;
}

.spark__area {
  fill: var(--live-flat-soft);
  stroke: none;
}

.spark--up .spark__line {
  stroke: var(--live-up);
}

.spark--up .spark__area {
  fill: var(--live-up-soft);
}

.spark--down .spark__line {
  stroke: var(--live-down);
}

.spark--down .spark__area {
  fill: var(--live-down-soft);
}

.spark__base {
  stroke: var(--live-rule-strong);
  stroke-width: 1;
  stroke-dasharray: 2 3;
  vector-effect: non-scaling-stroke;
}

.spark__void {
  stroke: var(--live-rule);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
</style>
