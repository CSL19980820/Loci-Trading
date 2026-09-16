<script setup lang="ts">
/**
 * 报价带：本页字号最大的东西，且必须是数字。
 * 指数报价 26px 等宽 + tabular-nums；涨跌带符号并只在这里用红绿。
 * 槽位固定五个，缺报价只把数值换成「—」并降透明度，绝不塌成空带。
 */
import { computed } from 'vue'

import type { LiveTapeItem } from '@/shared/api/quant'
import { price as fmtPrice, signedPct } from '@/shared/lib/format'

import './pulseSkin.css'

const props = defineProps<{
  indices: LiveTapeItem[]
  alertCount: number
  /** 情报缓存里的涨停/跌停家数；读不到给 null，显示「—」不猜 */
  limitUp?: number | null
  limitDown?: number | null
  /** 情报缓存不可用时的说明，进 tooltip */
  breadthNote?: string
}>()

/** 与大屏 IndexBar 同一组主指数；位置恒定才能形成肌肉记忆 */
const SLOTS: ReadonlyArray<{ key: string; name: string; codes: readonly string[] }> = [
  { key: 'sh', name: '上证指数', codes: ['000001', 'sh000001'] },
  { key: 'sz', name: '深证成指', codes: ['399001', 'sz399001'] },
  { key: 'cyb', name: '创业板指', codes: ['399006', 'sz399006'] },
  { key: 'kc50', name: '科创50', codes: ['000688', 'sh000688'] },
  { key: 'hs300', name: '沪深300', codes: ['000300', 'sh000300'] },
]

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return 'pulse-flat'
  if (Number(value) > 0) return 'pulse-up'
  if (Number(value) < 0) return 'pulse-down'
  return 'pulse-flat'
}

function count(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return String(Math.round(Number(value)))
}

function matchIndex(item: LiveTapeItem, codes: readonly string[]): boolean {
  return codes.includes(item.code) || Boolean(item.symbol && codes.includes(item.symbol))
}

const cells = computed(() =>
  SLOTS.map((slot) => {
    const item = props.indices.find((row) => matchIndex(row, slot.codes)) ?? null
    return {
      key: slot.key,
      name: item?.name || item?.label || slot.name,
      price: item ? fmtPrice(item.price) : '—',
      pct: item ? signedPct(item.pct) : '—',
      tone: item ? tone(item.pct) : 'pulse-flat',
      void: !item,
    }
  }),
)

const allVoid = computed(() => cells.value.every((cell) => cell.void))

const breadthTip = computed(
  () => props.breadthNote || '涨停 / 跌停为最近一次情报快照',
)
</script>

<template>
  <div class="tape" :class="{ 'tape--void': allVoid }" aria-label="指数报价与盘面广度" tabindex="0">
    <div
      v-for="cell in cells"
      :key="cell.key"
      class="tape__cell"
      :class="{ 'tape__cell--void': cell.void }"
    >
      <span class="tape__k">{{ cell.name }}</span>
      <span class="tape__row">
        <strong class="tape__price" :class="cell.tone">{{ cell.price }}</strong>
        <span class="tape__pct" :class="cell.tone">{{ cell.pct }}</span>
      </span>
    </div>

    <el-tooltip :content="breadthTip" placement="bottom" :show-after="200">
      <div class="tape__cell tape__cell--aux">
        <span class="tape__k">涨停 / 跌停</span>
        <span class="tape__row">
          <strong class="tape__stat">{{ count(limitUp) }}</strong>
          <span class="tape__slash">/</span>
          <strong class="tape__stat">{{ count(limitDown) }}</strong>
        </span>
      </div>
    </el-tooltip>

    <div class="tape__cell tape__cell--aux">
      <span class="tape__k">触价提醒</span>
      <span class="tape__row">
        <strong class="tape__stat" :class="{ 'is-hot': alertCount > 0 }">{{ alertCount }}</strong>
      </span>
    </div>
  </div>
</template>

<style scoped>
.tape {
  /*
   * 指数格宽是「6 位报价 + 涨跌幅 + 中文简称」的实测占位，属于内容测量值而不是密度令牌，
   * 密度令牌里没有对应的一档，故就近声明；窄屏只需重指这一个值。
   */
  --tape-cell-w: 150px;
  --tape-cell-w-aux: 120px;
  flex: 0 0 auto;
  display: flex;
  align-items: stretch;
  border: 1px solid var(--rule);
  border-radius: var(--radius-lg);
  background: var(--sheet);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}
.tape--void {
  background: var(--sheet-alt);
}

.tape__cell--void .tape__price,
.tape__cell--void .tape__pct {
  color: var(--mist);
}


.tape__cell {
  flex: 1 1 0;
  min-width: var(--tape-cell-w);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--gap-1);
  padding: var(--pad-sheet-y) var(--gap-4);
  border-left: 1px solid var(--rule);
  transition: background-color 300ms ease;
}

.tape__cell:first-child {
  border-left: none;
}

/* 交互底走语义层第 5 档：四档外观自动跟随，深色档也看得见 */
.tape__cell:hover {
  background: var(--surface-hover);
}

.tape__cell--aux {
  flex: 0 0 auto;
  min-width: var(--tape-cell-w-aux);
}

.tape__k {
  font-family: var(--font);
  font-size: var(--fs-aux);
  font-weight: 500;
  line-height: 1.2;
  color: var(--muted);
  letter-spacing: 0.02em;
  white-space: nowrap;
}
/* 报价与涨跌幅同基线一行：span 默认 inline，不给 display 则 gap/align-items 全部失效 */
.tape__row {
  display: inline-flex;
  align-items: baseline;
  gap: var(--gap-2);
  min-width: 0;
}

.tape__price {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--fs-tape);
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -0.01em;
}

.tape__pct {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--fs-body);
  font-weight: 600;
}

.tape__stat {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--seal-ink);
  line-height: 1.3;
}

.tape__stat.is-hot {
  color: var(--warn);
}

.tape__slash {
  font-family: var(--font-mono);
  color: var(--mist);
}

@media (max-width: 900px) {
  .tape {
    --tape-cell-w: 132px;
  }
  .tape__cell {
    padding: var(--gap-2) var(--gap-3);
  }
}

/* 480 级窄屏：五位数报价 + 涨跌幅一行摆不下（13647.49 + -0.55% ≈ 150px），改上下叠放；
   格改不收缩（flex:0 0 auto），宽度不足走横滑，不再把格内字压叠 */
@media (max-width: 640px) {
  .tape {
    --tape-cell-w: 128px;
    --tape-cell-w-aux: 108px;
  }
  .tape__cell {
    flex: 0 0 auto;
    padding: var(--gap-1) var(--gap-2);
  }
  .tape__price {
    font-size: var(--fs-hero);
  }
  .tape__row {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }
}
</style>
