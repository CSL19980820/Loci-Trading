<script setup lang="ts">
/**
 * 情报 tape：一行，截断，全文进 tooltip。
 * 以前这里是一整块「监控带」卡片，把主区推到屏幕下半页；现在它只有 20px。
 */
import { computed } from 'vue'

import type { IntelBrief } from '@/shared/api/quant_intel'

const props = defineProps<{
  brief: IntelBrief | null
  briefLoading?: boolean
  briefError?: string
}>()

function pctText(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  // 后端已统一 0–100；兼容旧缓存里偶发 0–1 比例
  return `${(n >= 0 && n <= 1.5 ? n * 100 : n).toFixed(0)}%`
}

const chips = computed(() => {
  const brief = props.brief
  if (!brief?.available) return []
  const emotion = brief.emotion
  const items: string[] = []
  if (emotion) {
    const basis = emotion.promotion_rate_basis
    items.push(`${basis ? `晋级(${basis})` : '晋级'} ${pctText(emotion.promotion_rate)}`)
    items.push(`炸板 ${pctText(emotion.broken_rate)}`)
    if (emotion.advancers != null || emotion.decliners != null) {
      items.push(`涨跌家 ${emotion.advancers ?? '—'}/${emotion.decliners ?? '—'}`)
    }
  }
  if (brief.ladder?.height != null) items.push(`高度 ${brief.ladder.height}`)
  // 断板分析（悟道 board_break_analysis）：短线复盘最直接的一行。sentiment_zh 由
  // 后端翻译，前端不再自己映射 cooling/warming。
  const bb = brief.board_break
  if (bb) {
    const parts: string[] = []
    if (bb.break_rate != null) parts.push(`断板 ${pctText(bb.break_rate)}`)
    if (bb.sealed_again != null && bb.prev_limit_ups != null) {
      parts.push(`续板 ${bb.sealed_again}/${bb.prev_limit_ups}`)
    }
    if (bb.sentiment_zh) parts.push(bb.sentiment_zh)
    if (parts.length) items.push(parts.join(' '))
  }
  const down = brief.limit_down
  if (down?.count != null) {
    items.push(`跌停 ${down.count}${down.reopened != null ? `·炸板 ${down.reopened}` : ''}`)
  }
  // 竞价主线只占一格：题材 + 一致性，明细进 tooltip 不进版面
  const auction = brief.auction_themes?.[0]
  if (auction) {
    const consistency = auction.consistency != null ? ` 一致 ${pctText(auction.consistency)}` : ''
    items.push(`竞价 ${auction.name}${consistency}`)
  }
  for (const theme of brief.themes.slice(0, 3)) {
    const pct =
      theme.pct_chg != null && Number.isFinite(Number(theme.pct_chg))
        ? ` ${Number(theme.pct_chg) > 0 ? '+' : ''}${Number(theme.pct_chg).toFixed(1)}%`
        : ''
    items.push(`${theme.name}${pct}`)
  }
  const catalyst = brief.catalysts?.[0]
  if (catalyst) items.push(`催化 ${catalyst.date.slice(5)} ${catalyst.title.slice(0, 12)}`)
  return items
})

const line = computed(() => {
  if (props.briefLoading) return '情报读取中…'
  if (props.briefError) return '情报暂不可用（不影响盘面）'
  if (!chips.value.length) return ''
  const day = props.brief?.trade_date || ''
  return [day, ...chips.value].filter(Boolean).join(' · ')
})

const tip = computed(() => {
  if (props.briefError) return `短线情报读不到：${props.briefError}`
  const brief = props.brief
  const fetched = brief?.fetched_at
  const cached = fetched ? `缓存 ${fetched.replace('T', ' ').slice(0, 16)} · ` : ''
  // 明细只进 tooltip，不占版面：高标杀名单、解禁排雷、两融净额。
  const extra: string[] = []
  const killed = (brief?.board_break?.high_board_broken ?? [])
    .map((row) => `${row.name}(${row.prev_streak ?? '?'}板)`)
    .slice(0, 3)
  if (killed.length) extra.push(`高标杀：${killed.join('、')}`)
  const margin = brief?.margin
  if (margin?.balance != null) {
    const yi = (value: number) => `${(value / 1e8).toFixed(0)}亿`
    const net = margin.net_buy != null ? `，净${margin.net_buy >= 0 ? '买' : '卖'} ${yi(Math.abs(margin.net_buy))}` : ''
    extra.push(`两融 ${yi(margin.balance)}${net}（${margin.exchange_count} 所合计）`)
  }
  const unlock = brief?.unlocks?.[0]
  if (unlock) {
    extra.push(`最大解禁 ${unlock.code} ${unlock.float_date.slice(4)} ${(unlock.float_ratio ?? 0).toFixed(1)}%`)
  }
  const head = `${cached}只读 intel_snapshots，不现场调 MCP`
  return extra.length ? `${head}\n${extra.join('\n')}` : head
})

const visible = computed(() => Boolean(line.value))
</script>

<template>
  <el-tooltip v-if="visible" :content="tip" placement="bottom" :show-after="200">
    <div class="intel-tape" aria-label="短线情报">
      <span class="intel-tape__k">情报</span>
      <span class="intel-tape__line">{{ line }}</span>
    </div>
  </el-tooltip>
</template>

<style scoped>
.intel-tape {
  flex: 0 0 auto;
  display: flex;
  align-items: baseline;
  gap: var(--gap-2, 8px);
  min-width: 0;
  padding: 1px var(--gap-2, 8px) 2px;
  border: 1px solid var(--rule);
  border-radius: var(--radius, 3px);
  background: var(--sheet);
}

.intel-tape__k {
  flex: 0 0 auto;
  font-size: var(--fs-kicker, 11px);
  color: var(--mist);
  letter-spacing: 0.02em;
}

.intel-tape__line {
  min-width: 0;
  flex: 1 1 auto;
  font-family: var(--mono);
  font-size: var(--fs-aux, 12px);
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
