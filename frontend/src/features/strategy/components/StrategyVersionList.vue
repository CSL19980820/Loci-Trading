<script setup lang="ts">
/** 版本列表：当前版本置顶高亮，其余可回滚 / 删除；回测读数跟着版本走。 */
import { Spinner } from '@/shared/components/ui/spinner'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Skeleton } from '@/shared/components/ui/skeleton'
import type { StrategyVersion } from '@/shared/types/quant'

import { formatPercent, isActiveVersion } from './strategyDetailFormat'

const props = defineProps<{
  rows: StrategyVersion[]
  currentVersion?: string
  loading: boolean
  canManage: boolean
  acting: string
}>()

const emit = defineEmits<{
  rollback: [version: string]
  remove: [version: string]
}>()

function active(row: StrategyVersion): boolean {
  return isActiveVersion(row, props.currentVersion)
}

function stamp(raw?: string): string {
  const text = String(raw || '').trim()
  return text ? text.replace('T', ' ').slice(0, 16) : '—'
}
</script>

<template>
  <div class="vl">
    <div v-if="loading && !rows.length" class="vl__skeleton" aria-hidden="true">
      <Skeleton v-for="n in 3" :key="n" class="h-12 w-full" />
    </div>
    <EmptyState v-else-if="!rows.length" compact description="暂无历史版本" />
    <ol v-else class="vl__list">
      <li v-for="row in rows" :key="row.id || row.version" class="vl__row" :class="{ 'is-active': active(row) }">
        <div class="vl__main">
          <div class="vl__head">
            <strong class="vl__ver">{{ row.version }}</strong>
            <span v-if="active(row)" class="vl__tag">当前</span>
            <span v-else-if="row.status" class="vl__status">{{ row.status }}</span>
            <time class="vl__time">{{ stamp(row.created_at) }}</time>
          </div>
          <dl v-if="row.backtest_metrics" class="vl__metrics">
            <div><dt>交易</dt><dd>{{ row.backtest_metrics.trades ?? '—' }}</dd></div>
            <div><dt>胜率</dt><dd>{{ formatPercent(row.backtest_metrics.win_rate) }}</dd></div>
            <div><dt>均净</dt><dd>{{ formatPercent(row.backtest_metrics.avg_net_return) }}</dd></div>
          </dl>
        </div>
        <div v-if="canManage && !active(row)" class="vl__actions">
          <Button variant="ghost" size="xs" :disabled="Boolean(acting)" @click="emit('rollback', row.version)">
            <Spinner v-if="acting === row.version" class="size-3 animate-spin" aria-hidden="true" />
            回滚
          </Button>
          <Button variant="ghost" size="xs" class="vl__remove" :disabled="Boolean(acting)" @click="emit('remove', row.version)">
            删除
          </Button>
        </div>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.vl__skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.vl__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.vl__row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: var(--radius-lg);
}

.vl__row + .vl__row {
  margin-top: 2px;
}

.vl__row:hover {
  background: var(--surface-hover);
}

.vl__row.is-active {
  background: color-mix(in oklab, var(--seal) 7%, var(--surface));
  box-shadow: inset 0 0 0 1px var(--seal-border);
}

.vl__main {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.vl__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
}

.vl__ver {
  color: var(--text-primary);
  font: 600 var(--fs-ui) / 1.2 var(--mono);
}

.vl__tag {
  padding: 0 7px;
  border-radius: var(--radius-pill);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-size: var(--fs-kicker);
  font-weight: 600;
  line-height: 18px;
}

.vl__status {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.vl__time {
  color: var(--text-tertiary);
  font: var(--fs-kicker) / 1 var(--mono);
}

.vl__metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin: 0;
}

.vl__metrics > div {
  display: flex;
  gap: 5px;
  font-size: var(--fs-kicker);
}

.vl__metrics dt {
  color: var(--text-tertiary);
}

.vl__metrics dd {
  margin: 0;
  color: var(--text-secondary);
  font-family: var(--mono);
}

.vl__actions {
  display: flex;
  gap: 2px;
  opacity: 0.6;
  transition: opacity var(--dur-fast) var(--ease);
}

.vl__row:hover .vl__actions,
.vl__actions:focus-within {
  opacity: 1;
}

.vl__remove:hover {
  color: var(--stamp);
}
</style>
