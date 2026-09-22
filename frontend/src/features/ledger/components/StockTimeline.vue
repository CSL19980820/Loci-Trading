<script setup lang="ts">
/**
 * 个股时间线：竖向轨道 + 节点（Linear activity 一路）。
 * 每个事件一张小行：日期（等宽）· 类型点 · 标题（战法名）+ 裁决徽标 · 理由（两行截断）· 评分。
 * `focusDate` 命中的事件高亮——从候选池带 ?date= 进档案时，一眼看到是哪一次。
 */
import { computed } from 'vue'

import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { decisionLabel, shortTime } from '@/shared/lib/format'
import type { TimelineEvent } from '@/shared/types/palace'

const props = defineProps<{
  events: TimelineEvent[]
  /** 高亮这一天的事件 */
  focusDate?: string
}>()

function typeLabel(type: TimelineEvent['type']): string {
  return { candidate: '候选', plan: '预案', review: '复盘' }[type] ?? type
}

function decisionVariant(decision: unknown): 'info' | 'warn' | 'secondary' {
  const label = decisionLabel(String(decision ?? ''))
  if (label === '精选') return 'info'
  if (label === '观察') return 'warn'
  return 'secondary'
}

function scoreText(value: unknown): string {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return ''
  const n = Number(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

function bodyText(event: TimelineEvent): string {
  const d = event.detail
  const parts = [d.timing, d.reason].filter((part) => typeof part === 'string' && part.trim())
  return parts.join(' · ')
}

/** 同一天多条事件只印一次日期 */
const rows = computed(() =>
  props.events.map((event, index) => ({
    event,
    showDate: index === 0 || props.events[index - 1]?.date !== event.date,
    isFocus: Boolean(props.focusDate) && event.date === props.focusDate,
  })),
)
</script>

<template>
  <ol class="sw-tl" aria-label="个股时间线">
    <li
      v-for="{ event, showDate, isFocus } in rows"
      :key="event.id"
      class="sw-tl__item"
      :class="[`is-${event.type}`, { 'is-focus': isFocus }]"
    >
      <span class="sw-tl__date" :class="{ 'is-muted': !showDate }">{{ event.date }}</span>
      <span class="sw-tl__track" aria-hidden="true">
        <span class="sw-tl__dot" />
      </span>
      <div class="sw-tl__card">
        <div class="sw-tl__head">
          <span class="sw-tl__type">{{ typeLabel(event.type) }}</span>
          <strong class="sw-tl__title">{{ event.label }}</strong>
          <UiBadge v-if="event.detail.decision" :variant="decisionVariant(event.detail.decision)">
            {{ decisionLabel(String(event.detail.decision)) }}
          </UiBadge>
          <span v-if="scoreText(event.detail.score)" class="sw-tl__score">{{ scoreText(event.detail.score) }}</span>
        </div>
        <p v-if="bodyText(event)" class="sw-tl__body" :title="bodyText(event)">{{ bodyText(event) }}</p>
        <span v-if="event.created_at" class="sw-tl__foot">{{ shortTime(event.created_at) }}</span>
      </div>
    </li>
  </ol>
</template>

<style scoped>
.sw-tl {
  list-style: none;
  margin: 0;
  padding: var(--gap-3) var(--gap-3) var(--gap-3) var(--gap-2);
  display: flex;
  flex-direction: column;
}

.sw-tl__item {
  display: grid;
  grid-template-columns: 5.4rem 16px minmax(0, 1fr);
  gap: 0 var(--gap-2);
  align-items: start;
}

.sw-tl__date {
  padding-top: 9px;
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  text-align: right;
  white-space: nowrap;
}

.sw-tl__date.is-muted {
  visibility: hidden;
}

/* 轨道：贯穿整项的竖线 + 居中的节点 */
.sw-tl__track {
  position: relative;
  display: flex;
  justify-content: center;
  align-self: stretch;
}

.sw-tl__track::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--border-subtle);
}

.sw-tl__item:first-child .sw-tl__track::before {
  top: 14px;
}

.sw-tl__item:last-child .sw-tl__track::before {
  bottom: calc(100% - 14px);
}

.sw-tl__dot {
  position: relative;
  z-index: 1;
  display: block;
  width: 10px;
  height: 10px;
  margin-top: 10px;
  border: 2px solid var(--surface);
  border-radius: 50%;
  background: var(--text-tertiary);
  box-shadow: 0 0 0 1px var(--border-default);
}

.is-candidate .sw-tl__dot {
  background: var(--seal);
  box-shadow: 0 0 0 1px var(--seal-border);
}

.is-plan .sw-tl__dot {
  background: var(--info);
}

.is-review .sw-tl__dot {
  background: var(--ok);
}

.sw-tl__card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  margin-bottom: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface);
  transition: border-color var(--dur-fast) var(--ease);
}

.sw-tl__item:last-child .sw-tl__card {
  margin-bottom: 0;
}

.sw-tl__card:hover {
  border-color: var(--border-default);
}

.is-focus .sw-tl__card {
  border-color: var(--seal-border);
  background: var(--seal-soft);
}

.sw-tl__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
}

.sw-tl__type {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  font-weight: 500;
  letter-spacing: 0.02em;
}

.sw-tl__title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
}

.sw-tl__score {
  margin-left: auto;
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-ui);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.sw-tl__body {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  line-height: 1.5;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.sw-tl__foot {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 640px) {
  .sw-tl {
    padding: var(--gap-3) var(--gap-3) var(--gap-3) var(--gap-1);
  }

  .sw-tl__item {
    grid-template-columns: 4.6rem 16px minmax(0, 1fr);
  }

  .sw-tl__date {
    font-size: 11px;
  }
}
</style>
