<script setup lang="ts">
/*
 * 实时策略信号流 —— 主区右列，整列吃满高度。
 *
 * 两处改动：
 *   1. 头部那枚红框「盘中信号未定稿」下线（违反 D1：非价格语义不得用红），
 *      合规声明整体并入底部 LiveStatusBar，全屏只留一处；
 *   2. 空态换成 ≤8 字短语「无信号」，不再复述会话级长句。
 *
 * 列表内容一律来自真规则引擎（推流 + /market/signals/recent 历史）。这里曾经
 * 会显示由涨幅/成交额/换手榜「换个标签」造出来的条目，已整块删除：榜单就在
 * 左边，没必要把同一份数据伪装成策略再说一遍。
 */
import { Bell } from '@element-plus/icons-vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import LiveEmptyState from './LiveEmptyState.vue'
import { price, signedPct } from '@/shared/lib/format'
import type { SignalItem } from '@/shared/api/marketStream'
import { SIGNAL_MAX_ITEMS, type ConnectionStatus } from '../composables/useLiveBoard'

defineProps<{
  signals: SignalItem[]
  newSignalIds: Set<string>
  status?: ConnectionStatus
}>()

function formatTime(iso: string): string {
  if (!iso) return '--:--'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso.slice(11, 16) || '--:--'
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function directionLabel(dir: SignalItem['direction']): string {
  if (dir === 'long') return '买入'
  if (dir === 'exit') return '卖出'
  return '观察'
}
</script>

<template>
  <section class="signals live-block" aria-label="实时策略信号">
    <header class="live-block__head">
      <span class="live-block__title">
        <el-icon class="signals__mark" aria-hidden="true"><Bell /></el-icon>
        实时策略信号
      </span>
      <span class="signals__count live-num">{{ signals.length }}/{{ SIGNAL_MAX_ITEMS }}</span>
    </header>

    <div class="live-block__body signals__list">
      <TransitionGroup name="signal-fade">
        <article
          v-for="item in signals"
          :key="item.id"
          class="sig"
          :class="{ 'sig--new': newSignalIds.has(item.id) }"
        >
          <span class="sig__time live-num">{{ formatTime(item.triggeredAt) }}</span>
          <span class="sig__dir" :class="`sig__dir--${item.direction}`">
            {{ directionLabel(item.direction) }}
          </span>
          <StockLink :code="item.code" :name="item.name" :show-code="false" class="sig__name" />
          <el-tooltip :content="item.strategyName || item.strategy" placement="top" :show-after="300">
            <span class="sig__strat" tabindex="0">{{ item.strategyName || item.strategy }}</span>
          </el-tooltip>
          <span class="sig__title" :title="item.detail || item.title" tabindex="0">{{ item.title }}</span>
          <span class="sig__px live-num">{{ price(item.price) }}</span>
          <span
            class="sig__pct live-num"
            :class="item.pct > 0 ? 'live-tone-up' : item.pct < 0 ? 'live-tone-down' : 'live-tone-flat'"
          >
            {{ signedPct(item.pct) }}
          </span>
        </article>
      </TransitionGroup>

      <LiveEmptyState v-if="!signals.length" hint="无信号" :status="status" />
    </div>
  </section>
</template>

<style scoped>
.signals {
  height: 100%;
}

.signals__mark {
  color: var(--seal-ink);
}

.signals__count {
  font-size: var(--fs-kicker);
  color: var(--live-dim);
}

.signals__list {
  overflow-y: auto;
  overscroll-behavior: contain;
}

.sig {
  display: grid;
  grid-template-columns: 3rem 2.6rem minmax(0, 1fr) auto auto;
  align-items: center;
  gap: var(--gap-1) var(--gap-2);
  min-height: calc(var(--live-signal-row-h) * 2);
  padding: var(--gap-1) var(--gap-2);
  border-bottom: 1px solid var(--live-rule-soft);
  font-size: var(--fs-aux);
  transition: background-color 1.2s ease-out;
}

.sig--new {
  background-color: var(--live-accent-soft);
}

.sig__time {
  font-size: var(--fs-kicker);
  color: var(--live-dim);
}

.sig__dir {
  padding: 0 3px;
  font-size: var(--fs-kicker);
  font-weight: 700;
  white-space: nowrap;
  border-radius: var(--radius);
}

/* 交易意图与实际涨跌分开；红绿只留给报价。 */
.sig__dir--long {
  color: var(--info-ink);
  background-color: var(--live-info-soft);
}

.sig__dir--exit {
  color: var(--warn-ink);
  background-color: var(--live-warn-soft);
}

.sig__dir--watch {
  color: var(--live-muted);
  background-color: var(--live-flat-soft);
}

:deep(.sig__name) {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--live-text);
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
}

:deep(.sig__name:hover) {
  color: var(--live-accent);
}

.sig__strat {
  grid-column: 1 / 3;
  grid-row: 2;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: var(--fs-kicker);
  color: var(--seal-ink);
  white-space: nowrap;
}

.sig__title {
  grid-column: 3 / -1;
  grid-row: 2;
  min-width: 0;
  color: var(--live-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sig__px {
  grid-column: 4;
  grid-row: 1;
  color: var(--live-text);
  font-weight: 600;
  text-align: right;
}

.sig__pct {
  grid-column: 5;
  grid-row: 1;
  min-width: 3.75rem;
  font-weight: 700;
  text-align: right;
}

.signal-fade-enter-active,
.signal-fade-leave-active {
  transition:
    opacity 240ms ease,
    transform 240ms ease;
}

.signal-fade-enter-from {
  opacity: 0;
  transform: translateY(-6px);
}

.signal-fade-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .sig,
  .signal-fade-enter-active,
  .signal-fade-leave-active {
    transition: none;
  }
  .signal-fade-enter-from {
    transform: none;
  }
}
</style>
