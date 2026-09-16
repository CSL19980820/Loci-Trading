<script setup lang="ts">
/*
 * 榜单列。四张卡以前长得一模一样，只能靠读标题区分；现在列头左侧一根 2px 色条：
 *   涨幅榜 = --up、跌幅榜 = --down（价格语义，D1 允许）
 *   换手率 = --info、成交额 = --warn（**非价格**语义，绝不允许用红绿）
 * 行结构固定四列：序号 / 名称 / 代码 / 数值，行高 26px，数值右对齐等宽（D2）。
 */
import { computed, ref, watch } from 'vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import LiveEmptyState from './LiveEmptyState.vue'
import { compactNumber, price, signedPct } from '@/shared/lib/format'
import type { QuoteRow } from '@/shared/api/marketStream'
import type { ConnectionStatus } from '../composables/useLiveBoard'

const props = withDefaults(
  defineProps<{
    title: string
    rows: QuoteRow[]
    valueType?: 'pct' | 'turnover' | 'amount'
    /** 列头标识色：price 语义走涨跌，其余走信息/警示色 */
    accent?: 'up' | 'down' | 'info' | 'warn'
    status?: ConnectionStatus
    /** 空态短语，≤8 字 */
    emptyHint?: string
  }>(),
  {
    valueType: 'pct',
    accent: 'info',
    status: undefined,
    emptyHint: '榜单待开盘',
  },
)

// 价格跳动的 300ms 闪烁：只记上一轮价，不深拷行
const flashMap = ref<Record<string, 'up' | 'down'>>({})
/**
 * 上一轮价格。**刻意不进响应式**：它只是判涨跌方向的中间量，没有任何模板读它，
 * 包成 `ref` 只会让每帧 10 次写入白白走一遍 Proxy 的 set 拦截与依赖通知。
 */
let prevPrices = new Map<string, number>()
let flashTimer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.rows,
  (rows) => {
    const next: Record<string, 'up' | 'down'> = {}
    // 每轮按当前榜单重建：掉出榜的 code 顺带淘汰。旧版只写不删，挂机一天
    // 这张表会攒下所有曾经上过榜的票。
    const prices = new Map<string, number>()
    for (const row of rows) {
      const prev = prevPrices.get(row.code)
      if (prev !== undefined && prev !== row.price) {
        next[row.code] = row.price > prev ? 'up' : 'down'
      }
      prices.set(row.code, row.price)
    }
    prevPrices = prices
    flashMap.value = next
    if (flashTimer) clearTimeout(flashTimer)
    flashTimer = setTimeout(() => {
      flashMap.value = {}
      flashTimer = null
    }, 320)
  },
)

function toneClass(value: number): string {
  if (value > 0) return 'live-tone-up'
  if (value < 0) return 'live-tone-down'
  return 'live-tone-flat'
}

interface RankItem {
  code: string
  name: string
  value: string
  /** 换手/成交额不着涨跌色（D1）：只有 pct 榜给语义色 */
  valueClass: string
}

const items = computed<RankItem[]>(() =>
  (props.rows ?? []).map((row) => {
    if (props.valueType === 'turnover') {
      // 换手率是「无向量级」，不该带 +/-：pct() 会给正数加号，这里用 price() 拼单位
      return {
        code: row.code,
        name: row.name,
        value: row.turnover ? `${price(row.turnover)}%` : '—',
        valueClass: 'rank__val--plain',
      }
    }
    if (props.valueType === 'amount') {
      return {
        code: row.code,
        name: row.name,
        value: compactNumber(row.amount),
        valueClass: 'rank__val--plain',
      }
    }
    return {
      code: row.code,
      name: row.name,
      value: signedPct(row.pct),
      valueClass: toneClass(row.pct),
    }
  }),
)
</script>

<template>
  <section class="rank live-block" :class="`rank--${accent}`" :aria-label="title">
    <header class="live-block__head">
      <span class="live-block__title">
        <i class="rank__mark" aria-hidden="true" />
        {{ title }}
      </span>
      <span class="rank__count live-num">{{ rows.length }}</span>
    </header>

    <div class="live-block__body rank__list">
      <div
        v-for="(item, idx) in items"
        :key="item.code"
        class="rank__row"
        :class="{
          'live-flash-up': flashMap[item.code] === 'up',
          'live-flash-down': flashMap[item.code] === 'down',
        }"
      >
        <span class="rank__idx live-num">{{ idx + 1 }}</span>
        <el-tooltip :content="item.name ? `${item.name} ${item.code}` : item.code" placement="top" :show-after="300">
          <StockLink :code="item.code" :name="item.name" :show-code="false" class="rank__name" />
        </el-tooltip>
        <span class="rank__code live-num">{{ item.code }}</span>
        <span class="rank__val live-num" :class="item.valueClass">{{ item.value }}</span>
      </div>

      <LiveEmptyState v-if="!items.length" :hint="emptyHint" :status="status" />
    </div>
  </section>
</template>

<style scoped>
.rank {
  height: 100%;
}

/* 圆点区分报价方向与榜单口径，不占用标题宽度。 */
.rank__mark {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: var(--gap-1);
  background-color: var(--live-flat);
}

.rank--up .rank__mark {
  background-color: var(--live-up);
}

.rank--down .rank__mark {
  background-color: var(--live-down);
}

.rank--info .rank__mark {
  background-color: var(--live-info);
}

.rank--warn .rank__mark {
  background-color: var(--live-warn);
}

.rank__count {
  font-size: var(--fs-kicker);
  color: var(--live-dim);
}

.rank__list {
  overflow-y: auto;
  overscroll-behavior: contain;
}

.rank__row {
  display: grid;
  grid-template-columns: 1.5rem minmax(0, 1fr) auto auto;
  align-items: center;
  gap: var(--gap-1);
  height: var(--live-rank-row-h);
  padding: 0 var(--gap-2);
  border-bottom: 1px solid var(--live-rule-soft);
}

.rank__row:hover,
.rank__row:focus-within {
  background-color: var(--surface-hover);
}

.rank__idx {
  font-size: var(--fs-kicker);
  color: var(--live-dim);
  text-align: right;
}

:deep(.rank__name) {
  font-size: var(--fs-aux);
  color: var(--live-text);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

:deep(.rank__name:hover) {
  color: var(--live-accent);
}

.rank__code {
  font-size: var(--fs-kicker);
  color: var(--live-dim);
  white-space: nowrap;
}

.rank__val {
  min-width: 4.25rem;
  font-size: var(--fs-aux);
  font-weight: 700;
  text-align: right;
  white-space: nowrap;
}

.rank__val--plain {
  color: var(--live-text);
}

@media (max-width: 1100px) {
  .rank__row { grid-template-columns: 1.5rem minmax(0, 1fr) auto; }
  .rank__code {
    display: none;
  }
}
</style>
