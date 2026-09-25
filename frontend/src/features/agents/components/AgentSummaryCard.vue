<script setup lang="ts">
import { Progress } from '@/shared/components/ui/progress'
import { Spinner } from '@/shared/components/ui/spinner'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowUpRight, BookOpen, Compass, Cpu, Flag, Receipt } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import { Skeleton } from '@/shared/components/ui/skeleton'
import UiBadge from '@/shared/components/ui/UiBadge.vue'

import { cardAllocationPct, cardReturnPct, type AgentCardData } from '../agentCards'
import { actionName, agentMoney, agentTime } from '../agentFormat'

/**
 * 智能体总览卡（bento 一格）。
 *
 *   头像 · 名称 / 职责        ● 运行中
 *   模拟净资产
 *   212,340.00 元          ↗ +5.94%  累计盈亏 +11,870.00
 *   ▇▇▇▇▇▇▇▁▁▁▁  仓位 54% · 持仓 3 · 观察 2
 *   [盘中管理 · 08/27 10:30]  两行摘要……
 *   deepseek-chat · 86 轮      日记  成交  进入 →
 *
 * 整卡可点进工作室；底部快捷动作 `@click.stop`，触控设备上常显。
 */
const router = useRouter()
const props = defineProps<{ card?: AgentCardData; loading?: boolean }>()

const target = computed(() => (props.card ? `/agents/${props.card.id}` : ''))
const returnPct = computed(() => (props.card ? cardReturnPct(props.card) : null))
const allocation = computed(() => (props.card ? cardAllocationPct(props.card) : null))
const pnlTone = computed(() => {
  const pnl = props.card?.pnl ?? 0
  return pnl > 0 ? 'is-up' : pnl < 0 ? 'is-down' : ''
})
const statusVariant = computed(() => {
  const card = props.card
  if (!card) return 'secondary' as const
  if (card.running) return 'info' as const
  if (card.failed) return 'stamp' as const
  return card.enabled ? ('ok' as const) : ('secondary' as const)
})

function signedMoney(cents: number): string {
  const text = agentMoney(Math.abs(cents))
  if (text === '—') return text
  return `${cents > 0 ? '+' : cents < 0 ? '−' : ''}${text}`
}

function fmtPct(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : ''
  return `${sign}${Math.abs(value).toFixed(2)}%`
}

function open(query?: Record<string, string>): void {
  if (!target.value) return
  void router.push(query ? { path: target.value, query } : target.value)
}
</script>

<template>
  <Card
    class="agent-card"
    :class="{ 'agent-card--guardian': card?.kind === 'guardian', 'agent-card--leader': card?.kind === 'leader' }"
    :interactive="Boolean(card)"
    :aria-busy="loading"
    :data-agent-id="card?.id"
    :tabindex="card ? 0 : undefined"
    :role="card ? 'link' : undefined"
    :aria-label="card ? `进入 ${card.name} 工作室` : undefined"
    @click="open()"
    @keydown.enter="open()"
  >
    <template v-if="loading">
      <div class="agent-card__head">
        <Skeleton class="size-10 rounded-lg" />
        <div class="flex-1 space-y-2"><Skeleton class="h-4 w-28" /><Skeleton class="h-3 w-40" /></div>
      </div>
      <Skeleton class="mt-4 h-8 w-44" />
      <Skeleton class="mt-3 h-1.5 w-full" />
      <Skeleton class="mt-4 h-14 w-full rounded-md" />
      <span class="sr-only">正在加载智能体</span>
    </template>

    <template v-else-if="card">
      <header class="agent-card__head">
        <span class="agent-card__avatar" aria-hidden="true">
          <Compass v-if="card.kind === 'guardian'" />
          <Flag v-else-if="card.kind === 'leader'" />
          <Cpu v-else />
        </span>
        <div class="agent-card__identity">
          <h2 class="agent-card__name">{{ card.name }}</h2>
          <p class="agent-card__subtitle" :title="card.subtitle">{{ card.subtitle }}</p>
        </div>
        <UiBadge :variant="statusVariant" :dot="!card.running" class="agent-card__status">
          <Spinner v-if="card.running" class="size-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
          {{ card.status }}
        </UiBadge>
      </header>

      <section class="agent-card__equity" :aria-label="`${card.name} 模拟账户`">
        <span class="agent-card__label">模拟净资产</span>
        <strong class="agent-card__value">{{ agentMoney(card.equity) }}<small>元</small></strong>
        <div class="agent-card__pnl">
          <span v-if="returnPct != null" class="agent-card__delta" :class="pnlTone">
            <ArrowUpRight class="size-3" :class="{ 'rotate-90': card.pnl < 0 }" aria-hidden="true" />
            {{ fmtPct(returnPct) }}
          </span>
          <span class="agent-card__pnl-text">
            累计盈亏
            <b :class="pnlTone">{{ signedMoney(card.pnl) }}</b>
          </span>
        </div>
      </section>

      <div
        class="agent-card__alloc"
        :aria-label="allocation != null ? `仓位 ${Math.round(allocation)}%` : '仓位未知'"
      >
        <Progress v-if="allocation != null" class="agent-card__alloc-track" :model-value="Math.max(0, Math.min(100, allocation))" aria-label="仓位占比" />
        <span class="agent-card__alloc-caption">
          <template v-if="allocation != null">仓位 {{ Math.round(allocation) }}% · </template>
          持仓 {{ card.positions }} 只
          <template v-if="card.watchCount"> · 观察 {{ card.watchCount }}</template>
        </span>
      </div>

      <section class="agent-card__work" :aria-label="`${card.name} 最近工作`">
        <div class="agent-card__work-meta">
          <span class="agent-card__phase">{{ card.phase }}</span>
          <time class="agent-card__time">{{ agentTime(card.at) }}</time>
        </div>
        <p class="agent-card__summary">{{ card.summary }}</p>
        <div v-if="card.actions.length" class="agent-card__chips">
          <span v-for="(action, index) in card.actions.slice(0, 3)" :key="index" class="agent-card__chip">
            {{ actionName(action.action) }} {{ action.name || action.code }}
          </span>
          <span v-if="card.actions.length > 3" class="agent-card__chip agent-card__chip--more">
            +{{ card.actions.length - 3 }}
          </span>
        </div>
      </section>

      <footer class="agent-card__foot">
        <span class="agent-card__model" :title="card.model || '未配置模型'">
          {{ card.model || '未配置模型' }}<template v-if="card.totalRuns != null"> · {{ card.totalRuns }} 轮</template>
        </span>
        <div class="agent-card__actions">
          <Button access="read" v-if="card.kind !== 'guardian'" variant="ghost" size="xs" @click.stop="open({ tab: 'runs' })">
            <BookOpen aria-hidden="true" />
            日记
          </Button>
          <Button access="read" v-if="card.kind !== 'guardian'" variant="ghost" size="xs" @click.stop="open({ tab: 'trades' })">
            <Receipt aria-hidden="true" />
            成交
          </Button>
          <Button access="read" variant="ghost" size="xs" class="agent-card__enter" @click.stop="open()">
            进入
            <ArrowUpRight aria-hidden="true" />
          </Button>
        </div>
      </footer>
    </template>
  </Card>
</template>

<style scoped>
.agent-card {
  gap: 0;
  padding: var(--gap-4);
  min-width: 0;
  min-height: 300px;
}

.agent-card:focus-visible {
  outline: 2px solid var(--focus-ring, var(--seal));
  outline-offset: 2px;
}

.agent-card__head {
  display: flex;
  align-items: flex-start;
  gap: var(--gap-3);
  min-width: 0;
}

.agent-card__avatar {
  display: grid;
  flex-shrink: 0;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  color: var(--text-secondary);
}

.agent-card__avatar :deep(svg) {
  width: 18px;
  height: 18px;
}

.agent-card--guardian .agent-card__avatar,
.agent-card--leader .agent-card__avatar {
  border-color: var(--seal-border);
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.agent-card__identity {
  flex: 1 1 auto;
  min-width: 0;
}

.agent-card__name {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-card__subtitle {
  margin: 2px 0 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-card__status {
  flex-shrink: 0;
  margin-top: 2px;
}

.agent-card__equity {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: var(--gap-4);
}

.agent-card__label {
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-weight: 500;
}

.agent-card__value {
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: var(--fs-display);
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.agent-card__value small {
  margin-left: 4px;
  color: var(--text-tertiary);
  font-family: var(--font);
  font-size: var(--fs-ui);
  font-weight: 500;
  letter-spacing: 0;
}

.agent-card__pnl {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  margin-top: 2px;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.agent-card__delta {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 7px 1px 4px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.agent-card__delta.is-up {
  background: var(--up-soft);
  color: var(--up);
}

.agent-card__delta.is-down {
  background: var(--down-soft);
  color: var(--down);
}

.agent-card__pnl-text b {
  font-family: var(--mono);
  font-weight: 600;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.agent-card__pnl-text b.is-up {
  color: var(--up);
}

.agent-card__pnl-text b.is-down {
  color: var(--down);
}

.agent-card__alloc {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: var(--gap-3);
}

.agent-card__alloc-track {
  display: block;
  height: 6px;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
}

.agent-card__alloc-track :deep([data-slot=progress-indicator]) {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--seal), color-mix(in oklab, var(--seal) 70%, var(--info)));
  transition: transform var(--dur) var(--ease);
}

.agent-card__alloc-caption {
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

.agent-card__work {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: var(--gap-3);
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}

.agent-card__work-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  font-size: var(--fs-kicker);
}

.agent-card__phase {
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-weight: 600;
}

.agent-card__time {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.agent-card__summary {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  line-height: 1.55;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow-wrap: anywhere;
}

.agent-card__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.agent-card__chip {
  padding: 1px 6px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-xs);
  background: var(--surface);
  color: var(--text-primary);
  font-size: var(--fs-kicker);
  white-space: nowrap;
}

.agent-card__chip--more {
  color: var(--text-tertiary);
}

.agent-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  margin-top: auto;
  padding-top: var(--gap-3);
}

.agent-card__model {
  min-width: 0;
  overflow: hidden;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-card__actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 2px;
  margin-right: -6px;
}

.agent-card__enter {
  color: var(--seal-ink);
}

@media (max-width: 640px) {
  .agent-card {
    padding: var(--gap-3);
    min-height: 0;
  }

  .agent-card__value {
    font-size: var(--fs-tape);
  }
}
</style>
