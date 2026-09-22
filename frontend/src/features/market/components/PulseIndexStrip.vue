<script setup lang="ts">
/**
 * 指数卡带：四个主指数一排 KPI 卡（Robinhood / Vercel 一路）。
 * 报价 24px 等宽 tabular；涨跌做成带箭头的 chip；缺报价把数值换成「—」并降透明度，绝不塌成空带。
 * 手机端横向滑动，卡片定宽 150px，不换行。
 */
import { ArrowDownRight, ArrowUpRight, ChartNoAxesCombined, Minus } from '@lucide/vue'
import { computed } from 'vue'

import type { LiveTapeItem } from '@/shared/api/quant'
import { price as fmtPrice, signedPct } from '@/shared/lib/format'

import './pulseSkin.css'

const props = defineProps<{
  indices: LiveTapeItem[]
}>()

/** 与大屏 IndexBar 同一组主指数；位置恒定才能形成肌肉记忆 */
const SLOTS: ReadonlyArray<{ key: string; name: string; codes: readonly string[] }> = [
  { key: 'sh', name: '上证指数', codes: ['000001', 'sh000001'] },
  { key: 'sz', name: '深证成指', codes: ['399001', 'sz399001'] },
  { key: 'cyb', name: '创业板指', codes: ['399006', 'sz399006'] },
  { key: 'kc50', name: '科创50', codes: ['000688', 'sh000688'] },
]

function toneOf(value: number | null | undefined): 'pulse-up' | 'pulse-down' | 'pulse-flat' {
  if (value == null || !Number.isFinite(Number(value))) return 'pulse-flat'
  if (Number(value) > 0) return 'pulse-up'
  if (Number(value) < 0) return 'pulse-down'
  return 'pulse-flat'
}

function iconOf(tone: string) {
  if (tone === 'pulse-up') return ArrowUpRight
  if (tone === 'pulse-down') return ArrowDownRight
  return Minus
}

function matchIndex(item: LiveTapeItem, codes: readonly string[]): boolean {
  return codes.includes(item.code) || Boolean(item.symbol && codes.includes(item.symbol))
}

const cells = computed(() =>
  SLOTS.map((slot) => {
    const item = props.indices.find((row) => matchIndex(row, slot.codes)) ?? null
    const tone = item ? toneOf(item.pct) : 'pulse-flat'
    return {
      key: slot.key,
      name: item?.name || item?.label || slot.name,
      price: item ? fmtPrice(item.price) : '—',
      pct: item ? signedPct(item.pct) : '—',
      tone,
      icon: iconOf(tone),
      void: !item,
    }
  }),
)

const allVoid = computed(() => cells.value.every((cell) => cell.void))
</script>

<template>
  <div class="tape" :class="{ 'tape--void': allVoid }" aria-label="指数报价" tabindex="0">
    <div
      v-for="cell in cells"
      :key="cell.key"
      class="tape__cell"
      :class="[{ 'tape__cell--void': cell.void }, `is-${cell.tone.replace('pulse-', '')}`]"
    >
      <ChartNoAxesCombined class="tape__watermark" aria-hidden="true" />
      <span class="tape__k">{{ cell.name }}</span>
      <span class="tape__row">
        <strong class="tape__price" :class="cell.tone">{{ cell.price }}</strong>
      </span>
      <span class="tape__pct pulse-chip" :class="cell.tone">
        <component :is="cell.icon" class="tape__arrow" aria-hidden="true" />
        {{ cell.pct }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.tape { flex:none; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; min-width:0; }
.tape__cell { position:relative; display:flex; align-items:center; gap:10px; min-width:0; min-height:54px; padding:10px 12px; border:1px solid var(--border-subtle); border-radius:var(--radius-md); background:linear-gradient(115deg,var(--surface),color-mix(in oklab,var(--seal) 4%,var(--surface))); overflow:hidden; }
.tape__watermark { position:absolute; right:2px; bottom:-7px; width:70px; height:50px; color:var(--seal); opacity:.065; pointer-events:none; }
.tape__k { position:relative; min-width:0; color:var(--text-tertiary); font-size:var(--fs-aux); white-space:nowrap; }
.tape__row { position:relative; margin-left:auto; white-space:nowrap; }
.tape__price { font:600 clamp(17px,1.35vw,22px)/1.2 var(--mono); font-variant-numeric:tabular-nums; letter-spacing:-.025em; color:var(--text-primary); }
.tape__price.pulse-up,.tape__price.pulse-down { color:var(--text-primary); }
.tape__pct { position:relative; flex:none; gap:2px; height:23px; padding:2px 5px; font:500 var(--fs-aux)/1 var(--mono); white-space:nowrap; }
.tape__arrow { width:12px; height:12px; }
.tape__cell--void .tape__price,.tape__cell--void .tape__pct { color:var(--text-disabled); background:transparent; }
@media(max-width:1180px) { .tape { display:flex; overflow-x:auto; scrollbar-width:thin; scroll-snap-type:x proximity; padding-bottom:2px; } .tape__cell { flex:1 0 260px; scroll-snap-align:start; } .tape__price { font-size:20px; } }
@media(max-width:767px) {
 .tape { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; overflow:visible; padding:0; }
 .tape__cell { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:5px 3px; min-height:68px; padding:10px 11px; }
 .tape__k { grid-column:1; font-size:11px; }.tape__pct { grid-column:2; grid-row:1; background:transparent; padding:0; font-size:10px; height:auto; }
 .tape__row { grid-row:2; grid-column:1/-1; margin:0; }.tape__price { font-size:20px; font-family:var(--font); letter-spacing:-.02em; }
 .tape__watermark { width:55px; height:44px; opacity:.055; }.tape__arrow { display:none; }
}
</style>
