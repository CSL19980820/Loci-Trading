<script setup lang="ts">
import { computed } from 'vue'

/**
 * 读数卡 —— 数字主导版式（D2）：数值是卡上最大的字，等宽 + tabular-nums；
 * 标签 11px/--mist，副信息 12px。无阴影、1px hairline、圆角 3px（D3）。
 *
 * 卡高由内容决定：不写 min-height —— 一排卡里只有一张有副信息时，靠 grid 的
 * `align-items: start` 收边，不要用定高把空卡撑成死白。
 * D1：涨跌色只上到数值那一行，标签与副信息永远是墨色梯度。
 */
const props = withDefaults(
  defineProps<{
    label: string
    value?: string | number
    hint?: string
    tone?: 'up' | 'down' | 'neutral' | ''
    /** stack=上下（默认，数值 26px）；row=左右一行（标签左、数值右，17px） */
    layout?: 'stack' | 'row'
  }>(),
  { layout: 'stack' },
)

const toneClass = computed(() => {
  if (props.tone === 'up') return 'tone-up'
  if (props.tone === 'down') return 'tone-down'
  if (props.tone === 'neutral') return 'tone-neutral'
  return ''
})
</script>

<template>
  <div class="stat-card" :class="layout === 'row' ? 'stat-card--row' : ''">
    <span class="stat-k">{{ label }}</span>
    <span class="stat-v" :class="toneClass"><slot>{{ value }}</slot></span>
    <span v-if="hint" class="stat-x">{{ hint }}</span>
  </div>
</template>

<style scoped>
.stat-card {
  display: grid;
  gap: 1px;
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  box-shadow: none;
}

.stat-card--row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 1px var(--gap-2);
  padding: var(--gap-1) var(--gap-2);
}

.stat-k {
  color: var(--mist);
  font-size: var(--fs-kicker);
  font-weight: 500;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

/* 数值：全站最大的字只给数字（D2），字号走 --fs-tape(26px) */
.stat-v {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--gap-1);
  font: 700 var(--fs-tape) / 1.05 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.stat-card--row .stat-v {
  font-size: var(--fs-hero);
  line-height: 1.2;
}

.stat-x {
  color: var(--mist);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

.stat-card--row .stat-x {
  flex-basis: 100%;
}
</style>
