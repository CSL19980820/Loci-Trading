<script setup lang="ts">
import { computed } from 'vue'
import { Radar } from '@lucide/vue'
import type { IntelBrief } from '@/shared/api/quant_intel'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { Skeleton } from '@/shared/components/ui/skeleton'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { compactNumber } from '@/shared/lib/format'

const open = defineModel<boolean>({ default: false })
const props = defineProps<{ brief: IntelBrief | null; loading?: boolean; error?: string }>()
function percent(value: number | null | undefined): string { return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(2)}%` }
const metrics = computed(() => {
  const b = props.brief
  return [
    ['涨停', b?.emotion?.limit_up_count ?? '—'], ['跌停', b?.limit_down?.count ?? b?.emotion?.limit_down_count ?? '—'],
    ['晋级率', percent(b?.emotion?.promotion_rate)], ['炸板率', percent(b?.emotion?.broken_rate)],
    ['上涨 / 下跌', `${b?.emotion?.advancers ?? '—'} / ${b?.emotion?.decliners ?? '—'}`], ['连板高度', b?.ladder?.height ?? '—'],
    ['断板率', percent(b?.board_break?.break_rate)], ['市场情绪', b?.board_break?.sentiment_zh || '—'],
  ]
})
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="intel-detail sm:max-w-4xl">
      <DialogHeader class="intel-detail__head">
        <DialogTitle class="flex items-center gap-2"><Radar class="size-4 text-seal" />短线情报 <span class="text-aux font-normal text-mist">{{ brief?.trade_date }}</span></DialogTitle>
        <DialogDescription>{{ brief?.fetched_at ? `快照 ${brief.fetched_at.replace('T', ' ').slice(0, 19)}` : '暂无采集时间' }}<template v-if="brief?.source"> · {{ brief.source }}</template></DialogDescription>
      </DialogHeader>
      <div class="intel-detail__body">
        <div v-if="loading && !brief" class="grid grid-cols-2 gap-3" role="status" aria-label="读取情报"><Skeleton v-for="n in 6" :key="n" class="h-14" /></div>
        <EmptyState v-else-if="error || !brief?.available" compact :description="error || '暂无情报快照'" />
        <template v-else>
          <dl class="intel-detail__metrics"><div v-for="[label, value] in metrics" :key="String(label)"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl>
          <section v-if="brief.themes?.length"><h3>题材</h3><div v-for="row in brief.themes" :key="row.code" class="intel-detail__row"><strong>{{ row.name }}</strong><span>{{ percent(row.pct_chg) }}</span><span>主力净额 {{ row.main_net_amount_text || compactNumber(row.main_net_amount) }}</span></div></section>
          <section v-if="brief.auction_themes?.length"><h3>竞价主线</h3><div v-for="row in brief.auction_themes" :key="row.name" class="intel-detail__entry"><div class="intel-detail__row"><strong>{{ row.name }}</strong><span>一致性 {{ percent(row.consistency) }}</span><span>竞价额 {{ row.bid_amount_text || '—' }}</span><span>命中 {{ row.hit_count ?? '—' }} / {{ row.member_count ?? '—' }}</span></div><div class="intel-detail__stocks"><span v-for="leader in row.leaders" :key="leader.code"><StockLink :code="leader.code" :name="leader.name" :date="brief.trade_date" /> {{ percent(leader.change_pct) }}</span></div></div></section>
          <section v-if="brief.board_break?.high_board_broken?.length"><h3>高位断板</h3><div v-for="row in brief.board_break.high_board_broken" :key="row.code" class="intel-detail__row"><StockLink :code="row.code" :name="row.name" :date="brief.trade_date" /><span>此前 {{ row.prev_streak ?? '—' }} 板</span><span>{{ percent(row.pct_chg) }}</span></div></section>
          <section v-if="brief.limit_down?.rows?.length"><h3>跌停明细</h3><div v-for="row in brief.limit_down.rows" :key="row.code" class="intel-detail__entry"><StockLink :code="row.code" :name="row.name" :date="brief.trade_date" /><p>{{ row.reason || '暂无原因说明' }}</p></div></section>
          <section v-if="brief.catalysts?.length"><h3>催化日历</h3><div v-for="(row, i) in brief.catalysts" :key="`${row.date}-${i}`" class="intel-detail__row intel-detail__catalyst"><time>{{ row.date }} {{ row.time }}</time><span>{{ row.title }}</span><small>{{ row.type }}</small></div></section>
          <section v-if="brief.margin"><h3>融资融券 <small>{{ brief.margin.trade_date }}</small></h3><div class="intel-detail__row"><span>余额 <strong>{{ compactNumber(brief.margin.balance) }}</strong></span><span>净买入 <strong>{{ compactNumber(brief.margin.net_buy) }}</strong></span></div><div v-for="row in brief.margin.exchanges" :key="row.exchange" class="intel-detail__row"><strong>{{ row.exchange }}</strong><span>余额 {{ compactNumber(row.balance) }}</span><span>净买入 {{ compactNumber(row.net_buy) }}</span></div></section>
          <section v-if="brief.unlocks?.length"><h3>限售解禁</h3><div v-for="(row, i) in brief.unlocks" :key="`${row.code}-${i}`" class="intel-detail__entry"><div class="intel-detail__row"><StockLink :code="row.code" /><time>{{ row.float_date }}</time><span>{{ percent(row.float_ratio) }}</span><span>{{ row.share_type }}</span></div><p v-if="row.holder">{{ row.holder }}</p></div></section>
          <p v-if="brief.note" class="intel-detail__note">{{ brief.note }}</p>
        </template>
      </div>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.intel-detail { display:flex; flex-direction:column; max-height:86dvh; gap:0; padding:0; overflow:hidden; }
.intel-detail__head { flex:none; padding:16px 44px 12px 18px; border-bottom:1px solid var(--border-subtle); }
.intel-detail__body { min-height:0; padding:12px 18px 18px; overflow:auto; overscroll-behavior:contain; }
.intel-detail__metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:0; }
.intel-detail__metrics > div { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:6px; padding:8px 10px; border-radius:var(--radius); background:var(--seal-soft); }
dt, small, time { color:var(--text-tertiary); font-size:var(--fs-aux); }
dd { margin:0; font:600 var(--fs-ui)/1.5 var(--mono); }
section { padding:12px 0 4px; border-bottom:1px solid var(--border-subtle); }
h3 { display:flex; align-items:center; gap:10px; margin:0 0 6px; font-size:var(--fs-ui); font-weight:600; }
.intel-detail__row { display:flex; flex-wrap:wrap; align-items:baseline; gap:8px 20px; min-height:30px; padding:4px 0; font-size:var(--fs-ui); }
.intel-detail__entry { padding:5px 0; font-size:var(--fs-ui); }
.intel-detail__entry p,.intel-detail__note { margin:4px 0; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--text-tertiary); font-size:var(--fs-aux); }
.intel-detail__stocks { display:flex; flex-wrap:wrap; gap:8px 16px; color:var(--text-tertiary); }
.intel-detail__catalyst { display:grid; grid-template-columns:130px minmax(0,1fr) auto; align-items:start; }
@media(max-width:640px) { .intel-detail__metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } .intel-detail__catalyst { grid-template-columns:100px minmax(0,1fr); } .intel-detail__catalyst small { display:none; } }
</style>
