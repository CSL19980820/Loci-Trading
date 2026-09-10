<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    values: number[]
    width?: number
    height?: number
    /** 默认中性色（品牌色）；要表达涨跌由调用方显式传 var(--up) / var(--down) */
    color?: string
    label?: string
    /** 同花顺式：末端圆点 */
    showEndDot?: boolean
  }>(),
  {
    width: 320,
    height: 96,
    color: 'var(--seal)',
    label: '图',
    showEndDot: false,
  },
)

const gradientId = `sp-${Math.random().toString(36).slice(2, 8)}`

const points = computed(() => {
  if (!props.values.length) return [] as Array<{ x: number; y: number }>
  const min = Math.min(...props.values)
  const max = Math.max(...props.values)
  const span = max - min || 1
  const pad = props.showEndDot ? 6 : 4
  return props.values.map((value, index) => {
    const x =
      props.values.length === 1
        ? props.width / 2
        : pad + (index / (props.values.length - 1)) * (props.width - pad * 2)
    const y = props.height - pad - ((value - min) / span) * (props.height - pad * 2)
    return { x, y }
  })
})

const endPoint = computed(() => {
  if (!points.value.length) return null
  return points.value[points.value.length - 1]
})

const linePath = computed(() => {
  if (!points.value.length) return ''
  return points.value.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
})

const areaPath = computed(() => {
  if (!points.value.length) return ''
  const first = points.value[0]
  const last = points.value[points.value.length - 1]
  return `${linePath.value} L${last.x.toFixed(1)} ${props.height} L${first.x.toFixed(1)} ${props.height} Z`
})
</script>

<template>
  <svg
    class="sparkline"
    :viewBox="`0 0 ${width} ${height}`"
    role="img"
    :aria-label="label"
    preserveAspectRatio="none"
  >
    <defs>
      <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity="0.22" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
    </defs>
    <path v-if="areaPath" :d="areaPath" :fill="`url(#${gradientId})`" />
    <path
      v-if="linePath"
      :d="linePath"
      fill="none"
      :stroke="color"
      stroke-width="1.6"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <circle
      v-if="showEndDot && endPoint"
      :cx="endPoint.x"
      :cy="endPoint.y"
      r="3.2"
      :fill="color"
    />
  </svg>
</template>
