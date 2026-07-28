<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    value?: number | string | null
    digits?: number
    signed?: boolean
    pct?: boolean
    money?: boolean
    align?: 'left' | 'right' | 'center'
    tone?: boolean
  }>(),
  {
    digits: 2,
    signed: false,
    pct: false,
    money: false,
    align: 'right',
    tone: true,
  },
)

const numeric = computed(() => {
  if (props.value === null || props.value === undefined || props.value === '') return null
  const n = typeof props.value === 'number' ? props.value : Number(props.value)
  return Number.isFinite(n) ? n : null
})

const text = computed(() => {
  const n = numeric.value
  if (n === null) return '—'
  if (props.pct) {
    const sign = props.signed || n > 0 ? (n > 0 ? '+' : '') : ''
    return `${sign}${n.toFixed(props.digits)}%`
  }
  if (props.money) {
    const abs = Math.abs(n).toLocaleString('zh-CN', {
      minimumFractionDigits: props.digits,
      maximumFractionDigits: props.digits,
    })
    const sign = n < 0 ? '-' : props.signed && n > 0 ? '+' : ''
    return `${sign}¥${abs}`
  }
  const body = n.toLocaleString('zh-CN', {
    minimumFractionDigits: props.digits,
    maximumFractionDigits: props.digits,
  })
  if (props.signed && n > 0) return `+${body}`
  return body
})

const alignClass = computed(() => `num-text--${props.align}`)

const toneClass = computed(() => {
  if (!props.tone) return ''
  const n = numeric.value
  if (n == null || n === 0) return ''
  return n > 0 ? 'is-up' : 'is-down'
})
</script>

<template>
  <span class="num-text" :class="[alignClass, toneClass]">{{ text }}</span>
</template>

<style scoped>
.num-text {
  display: inline-block;
  width: 100%;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum';
  line-height: 1.35;
  vertical-align: middle;
}
.num-text--right {
  text-align: right;
}
.num-text--left {
  text-align: left;
}
.num-text--center {
  text-align: center;
}
.is-up {
  color: var(--up);
}
.is-down {
  color: var(--down);
}
</style>
