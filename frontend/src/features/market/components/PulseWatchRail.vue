<script setup lang="ts">
/**
 * 情报带：一排 chip（横向可滑），全文与明细进 tooltip。
 * 以前是一整块「监控带」卡片，再后来压成一行 12px 文本；现在是可读的 chip 行——
 * 每个口径一枚，带涨跌色，眼睛能直接扫。
 */
import { Radar } from '@lucide/vue'
import { computed, onDeactivated, ref } from 'vue'
import IntelDetailDialog from './IntelDetailDialog.vue'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import type { IntelBrief } from '@/shared/api/quant_intel'

const props = defineProps<{
  brief: IntelBrief | null
  briefLoading?: boolean
  briefError?: string
}>()

type Chip = { key: string; label: string; value?: string; tone?: 'up' | 'down' | 'warn' | '' }
const detailOpen = ref(false)
onDeactivated(() => { detailOpen.value = false })

function pctText(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  // 后端契约已是 0–100，不能把真实的 1% 再乘以 100。
  return `${n.toFixed(n < 2 && n > 0 ? 1 : 0)}%`
}

function pctTone(value: number | null | undefined): 'up' | 'down' | '' {
  if (value == null || !Number.isFinite(Number(value))) return ''
  return Number(value) > 0 ? 'up' : Number(value) < 0 ? 'down' : ''
}

const chips = computed<Chip[]>(() => {
  const brief = props.brief
  if (!brief?.available) return []
  const emotion = brief.emotion
  const items: Chip[] = []
  if (emotion) {
    const basis = emotion.promotion_rate_basis
    items.push({ key: 'promo', label: basis ? `晋级 ${basis}` : '晋级', value: pctText(emotion.promotion_rate) })
    items.push({ key: 'broken', label: '炸板', value: pctText(emotion.broken_rate), tone: 'warn' })
    if (emotion.advancers != null || emotion.decliners != null) {
      items.push({ key: 'ad', label: '涨跌家', value: `${emotion.advancers ?? '—'} / ${emotion.decliners ?? '—'}` })
    }
  }
  if (brief.ladder?.height != null) items.push({ key: 'ladder', label: '连板高度', value: String(brief.ladder.height) })
  const bb = brief.board_break
  if (bb) {
    if (bb.break_rate != null) items.push({ key: 'bb', label: '断板', value: pctText(bb.break_rate) })
    if (bb.sealed_again != null && bb.prev_limit_ups != null) {
      items.push({ key: 'seal', label: '续板', value: `${bb.sealed_again}/${bb.prev_limit_ups}` })
    }
    if (bb.sentiment_zh) items.push({ key: 'senti', label: bb.sentiment_zh })
  }
  const down = brief.limit_down
  if (down?.count != null) {
    items.push({
      key: 'down',
      label: '跌停',
      value: `${down.count}${down.reopened != null ? ` · 炸 ${down.reopened}` : ''}`,
      tone: 'down',
    })
  }
  const auction = brief.auction_themes?.[0]
  if (auction) {
    const consistency = auction.consistency != null ? ` 一致 ${pctText(auction.consistency)}` : ''
    items.push({ key: 'auction', label: '竞价主线', value: `${auction.name}${consistency}` })
  }
  for (const theme of brief.themes.slice(0, 3)) {
    const has = theme.pct_chg != null && Number.isFinite(Number(theme.pct_chg))
    const pct = has ? `${Number(theme.pct_chg) > 0 ? '+' : ''}${Number(theme.pct_chg).toFixed(1)}%` : ''
    items.push({ key: `theme-${theme.code}`, label: theme.name, value: pct, tone: has ? pctTone(theme.pct_chg) : '' })
  }
  const catalyst = brief.catalysts?.[0]
  if (catalyst) {
    items.push({ key: 'cat', label: `催化 ${catalyst.date.slice(5)}`, value: catalyst.title.slice(0, 14) })
  }
  return items
})

const statusText = computed(() => {
  if (props.briefLoading) return '情报读取中…'
  if (props.briefError) return '情报暂不可用'
  return ''
})

const dateText = computed(() => props.brief?.trade_date || '')

const tip = computed(() => {
  if (props.briefError) return `短线情报读不到：${props.briefError}`
  const brief = props.brief
  const fetched = brief?.fetched_at
  const cached = fetched ? `缓存 ${fetched.replace('T', ' ').slice(0, 16)} · ` : ''
  const extra: string[] = []
  const killed = (brief?.board_break?.high_board_broken ?? [])
    .map((row) => `${row.name}(${row.prev_streak ?? '?'}板)`)
    .slice(0, 3)
  if (killed.length) extra.push(`高标杀：${killed.join('、')}`)
  const margin = brief?.margin
  if (margin?.balance != null) {
    const yi = (value: number) => `${(value / 1e8).toFixed(0)}亿`
    const net =
      margin.net_buy != null ? `，净${margin.net_buy >= 0 ? '买' : '卖'} ${yi(Math.abs(margin.net_buy))}` : ''
    extra.push(`两融 ${yi(margin.balance)}${net}（${margin.exchange_count} 所合计）`)
  }
  const unlock = brief?.unlocks?.[0]
  if (unlock) {
    extra.push(`最大解禁 ${unlock.code} ${unlock.float_date.slice(4)} ${(unlock.float_ratio ?? 0).toFixed(1)}%`)
  }
  const head = `${cached}最近一次情报快照`
  return extra.length ? `${head}\n${extra.join('\n')}` : head
})

const visible = computed(() => Boolean(statusText.value) || chips.value.length > 0)
</script>

<template>
  <Tooltip v-if="visible">
    <TooltipTrigger as-child>
      <div class="intel" role="button" aria-label="查看短线情报详情" tabindex="0" aria-haspopup="dialog" :aria-expanded="detailOpen" @click="detailOpen = true" @keydown.enter.prevent="detailOpen = true" @keydown.space.prevent="detailOpen = true">
        <span class="intel__lead">
          <Radar class="intel__icon" aria-hidden="true" />
          <span class="intel__k">情报</span>
          <span v-if="dateText" class="intel__date">{{ dateText }}</span>
        </span>
        <span v-if="statusText" class="intel__status">{{ statusText }}</span>
        <span v-else class="intel__chips">
          <span
            v-for="chip in chips"
            :key="chip.key"
            class="intel__chip"
            :class="chip.tone ? `is-${chip.tone}` : ''"
          >
            <span class="intel__chip-k">{{ chip.label }}</span>
            <span v-if="chip.value" class="intel__chip-v">{{ chip.value }}</span>
          </span>
        </span>
      </div>
    </TooltipTrigger>
    <TooltipContent class="whitespace-pre-line">{{ tip }}</TooltipContent>
  </Tooltip>
  <IntelDetailDialog v-model="detailOpen" :brief="brief" :loading="briefLoading" :error="briefError" />
</template>

<style scoped>
.intel {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: var(--gap-3);
  min-width: 0;
  height: 40px;
  padding: 0 var(--gap-3) 0 var(--gap-4);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
}

.intel:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}

.intel__lead {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  padding-right: var(--gap-3);
  border-right: 1px solid var(--border-subtle);
}

.intel__icon {
  width: 14px;
  height: 14px;
  color: var(--seal);
}

.intel__k {
  font-size: var(--fs-aux);
  font-weight: 600;
  color: var(--text-secondary);
}

.intel__date {
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  color: var(--text-tertiary);
  font-variant-numeric: tabular-nums;
}

.intel__status {
  font-size: var(--fs-aux);
  color: var(--text-tertiary);
}

.intel__chips {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
  mask-image: linear-gradient(90deg, #000 calc(100% - 28px), transparent);
}

.intel__chips::-webkit-scrollbar {
  display: none;
}

.intel__chip {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  height: 24px;
  padding: 0 8px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  white-space: nowrap;
}

.intel__chip-k {
  color: var(--text-tertiary);
}

.intel__chip-v {
  font-family: var(--mono);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}

.intel__chip.is-up {
  background: var(--up-soft);
}

.intel__chip.is-up .intel__chip-v {
  color: var(--up);
}

.intel__chip.is-down {
  background: var(--down-soft);
}

.intel__chip.is-down .intel__chip-v {
  color: var(--down);
}

.intel__chip.is-warn .intel__chip-v {
  color: var(--warn-ink);
}

@media (max-width: 640px) {
  .intel {
    height: 38px;
    padding-left: var(--gap-3);
  }

  .intel__date {
    display: none;
  }
}
</style>
