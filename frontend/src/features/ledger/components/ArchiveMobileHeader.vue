<script setup lang="ts">
import { ArrowLeft, ChevronLeft, ChevronRight, History, List, MessageCircle } from '@lucide/vue'
import { Button } from '@/shared/components/ui/button'
import { chgClass, fmtChange, fmtPct } from '@/features/market/composables/dataQueryFormat'
defineProps<{ name: string; code: string; board: string; industry: string; price: string; pct: number | null; change: number | null; historyCount: number; batchPosition?: string; canPrev: boolean; canNext: boolean }>()
const emit = defineEmits<{ back: []; history: []; prev: []; next: []; batch: []; chat: [] }>()
</script>
<template>
 <header class="mobile-stock-header">
  <div class="mobile-stock-identity">
   <Button access="read" variant="ghost" size="icon-sm" aria-label="返回" @click="emit('back')"><ArrowLeft /></Button>
   <div class="mobile-stock-name"><h1 :title="name">{{ name }}</h1><span>{{ code }}<small v-if="board"> · {{ board }}</small><small v-if="industry" :title="industry"> · {{ industry }}</small></span></div>
   <Button access="read" variant="outline" size="icon-sm" aria-label="选股记录" :title="`${historyCount} 条选股记录`" @click="emit('history')"><History /><span v-if="historyCount" class="mobile-stock-count">{{ historyCount }}</span></Button>
   <Button access="read" variant="outline" size="icon-sm" aria-label="打开AI助手" @click="emit('chat')"><MessageCircle /></Button>
  </div>
  <div class="mobile-stock-quote">
   <div class="mobile-stock-price" :class="chgClass(pct)"><strong>{{ price }}</strong><span>{{ fmtChange(change) }}<small>{{ fmtPct(pct) }}</small></span></div>
   <nav v-if="batchPosition" class="mobile-batch" aria-label="本批股票">
    <Button access="read" variant="ghost" size="icon-sm" :disabled="!canPrev" aria-label="上一只" @click="emit('prev')"><ChevronLeft /></Button><span>{{ batchPosition }}</span><Button access="read" variant="ghost" size="icon-sm" :disabled="!canNext" aria-label="下一只" @click="emit('next')"><ChevronRight /></Button><Button access="read" variant="outline" size="icon-sm" aria-label="本批列表" @click="emit('batch')"><List /></Button>
   </nav>
  </div>
 </header>
</template>
<style scoped>
.mobile-stock-header { padding:5px 10px 6px; flex:none; border-bottom:1px solid var(--border-subtle); background:var(--surface); }
.mobile-stock-identity { display:grid; grid-template-columns:30px minmax(0,1fr) 36px 36px; gap:7px; align-items:center; min-height:42px; }
.mobile-stock-identity button { position:relative; width:36px; height:36px; padding:0; }
.mobile-stock-identity button:first-child { width:30px; }
.mobile-stock-name { min-width:0; }
.mobile-stock-name h1 { margin:0; font-size:16px; line-height:22px; font-weight:650; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mobile-stock-name > span { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font:11px/17px var(--mono); color:var(--text-tertiary); }
.mobile-stock-name small { font:10px var(--font); }
.mobile-stock-count { position:absolute; right:-3px; top:-3px; min-width:13px; height:13px; display:grid; place-items:center; font-size:9px; border-radius:8px; background:var(--surface-sunken); }
.mobile-stock-quote { display:flex; align-items:center; justify-content:space-between; gap:6px; min-height:42px; }
.mobile-stock-price { display:flex; align-items:center; gap:7px; min-width:0; }
.mobile-stock-price strong { font:650 25px/1.3 var(--mono); }
.mobile-stock-price > span { display:flex; flex-direction:column; gap:1px; font:12px/1.35 var(--mono); }
.mobile-stock-price small { font:11px var(--mono); }
.mobile-batch { display:flex; align-items:center; gap:2px; flex:none; }
.mobile-batch button { width:32px; height:36px; padding:0; }
.mobile-batch > span { min-width:31px; text-align:center; font:11px var(--mono); color:var(--text-secondary); }
.mobile-stock-price.up { color:var(--up); }.mobile-stock-price.down { color:var(--down); }
</style>
