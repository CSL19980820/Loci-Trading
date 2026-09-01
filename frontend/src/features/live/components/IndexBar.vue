<script setup lang="ts">
/*
 * 高密度指数带（替代旧的「三张带分时图的大卡片」）。
 *
 * 设计取向对标同花顺顶栏 / Bloomberg 的 index strip：
 *   · 定高 64px，不吃弹性高度——指数是**参照系**，不是主角，不该占屏幕 1/4；
 *   · 槽位固定五个，缺数据只把数值位换成「—」并降透明度，**绝不塌成大空态卡**。
 *     专业终端从不因为某个标的没报价就把版面重排，位置恒定才能形成肌肉记忆；
 *   · 单元之间 1px hairline，不卡片化、不圆角、不投影（D3）；
 *   · 单元里最大的字是点位（--fs-hero 等宽 tabular-nums，D2）。
 */
import { computed } from 'vue'
import type { QuoteRow } from '@/shared/api/marketStream'
import { price, signedPct } from '@/shared/lib/format'
import IndexSparkline from './IndexSparkline.vue'

const props = withDefaults(
  defineProps<{
    rows?: QuoteRow[]
    /** code → 分时点列；由 useLiveBoard.indexTrails 提供 */
    trails?: Map<string, number[]>
  }>(),
  { rows: () => [], trails: () => new Map<string, number[]>() },
)

/** 固定槽位：一个代码两种写法（裸码 / 带市场前缀）都认 */
const SLOTS: ReadonlyArray<{ key: string; name: string; codes: readonly string[] }> = [
  { key: 'sh', name: '上证指数', codes: ['000001', 'sh000001'] },
  { key: 'sz', name: '深证成指', codes: ['399001', 'sz399001'] },
  { key: 'cyb', name: '创业板指', codes: ['399006', 'sz399006'] },
  { key: 'kc50', name: '科创50', codes: ['000688', 'sh000688'] },
  { key: 'hs300', name: '沪深300', codes: ['000300', 'sh000300'] },
]

interface IndexCell {
  key: string
  name: string
  code: string
  row: QuoteRow | null
  tone: 'up' | 'down' | 'flat'
  priceText: string
  changeText: string
  pctText: string
  trail: number[]
}

function toneOf(pct: number | undefined): 'up' | 'down' | 'flat' {
  if (pct == null || !Number.isFinite(pct) || pct === 0) return 'flat'
  return pct > 0 ? 'up' : 'down'
}

/** 涨跌点数：优先用推送的 change，缺失时由 price − prevClose 推 */
function changeOf(row: QuoteRow): number | null {
  if (Number.isFinite(row.change) && row.change !== 0) return row.change
  if (Number.isFinite(row.prevClose) && row.prevClose > 0 && Number.isFinite(row.price)) {
    return row.price - row.prevClose
  }
  return Number.isFinite(row.change) ? row.change : null
}

const cells = computed<IndexCell[]>(() =>
  SLOTS.map((slot) => {
    const row = (props.rows ?? []).find((r) => slot.codes.includes(r.code)) ?? null
    const delta = row ? changeOf(row) : null
    const trail = row ? (props.trails?.get(row.code) ?? []) : []
    return {
      key: slot.key,
      name: slot.name,
      code: row?.code ?? slot.codes[0],
      row,
      tone: toneOf(row?.pct),
      priceText: row ? price(row.price) : '—',
      changeText: delta == null ? '—' : `${delta > 0 ? '+' : ''}${price(delta)}`,
      pctText: row ? signedPct(row.pct) : '—',
      trail,
    }
  }),
)

/** 一个指数都没报价时整条带压暗——降透明度即可，不改结构 */
const allVoid = computed(() => cells.value.every((c) => c.row === null))
</script>

<template>
  <section class="index-bar" :class="{ 'index-bar--void': allVoid }" aria-label="主要指数">
    <div
      v-for="cell in cells"
      :key="cell.key"
      class="idx"
      :class="[`idx--${cell.tone}`, { 'idx--void': !cell.row }]"
    >
      <div class="idx__id">
        <span class="idx__name">{{ cell.name }}</span>
        <span class="idx__code live-num">{{ cell.code }}</span>
      </div>

      <div class="idx__nums">
        <span class="idx__px live-num">{{ cell.priceText }}</span>
        <span class="idx__delta live-num">
          <span class="idx__chg">{{ cell.changeText }}</span>
          <span class="idx__pct">{{ cell.pctText }}</span>
        </span>
      </div>

      <IndexSparkline
        class="idx__spark"
        :points="cell.trail"
        :baseline="cell.row?.prevClose ?? null"
        :tone="cell.tone"
      />
    </div>
  </section>
</template>

<style scoped>
.index-bar {
  flex: none;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  height: var(--live-indexbar-h);
  background-color: var(--live-panel);
  border-bottom: 1px solid var(--live-rule);
  transition: opacity 200ms ease;
}

/* 无数据不是「消失」，只是「暗下来」 */
.index-bar--void {
  opacity: 0.62;
}

.idx {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: auto auto;
  align-content: center;
  gap: 0 var(--gap-2);
  min-width: 0;
  padding: 0 var(--gap-3);
  border-left: 1px solid var(--live-rule-soft);
  /*
   * 容器查询锚点：指数带是定宽 5 等分，窗口一窄单元格就只有 ~200px，
   * 「点位 + 涨跌点数 + 涨跌幅」三段并排放不下。宽度由容器决定而不是视口
   * （侧栏收起/展开也会改列宽），所以只能用 container query，不能用 media。
   */
  container-type: inline-size;
  overflow: hidden;
}

.idx:first-child {
  border-left: none;
}

.idx__id {
  grid-column: 1;
  display: flex;
  align-items: baseline;
  gap: var(--gap-1);
  min-width: 0;
}

.idx__name {
  font-size: var(--fs-aux);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--live-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.idx__code {
  font-size: var(--fs-kicker);
  color: var(--live-dim);
  white-space: nowrap;
}

.idx__nums {
  grid-column: 1;
  display: flex;
  align-items: baseline;
  gap: var(--gap-2);
  min-width: 0;
  /* 关键：不给这一行留任何溢出余地，两个子项都必须能收缩 */
  overflow: hidden;
}

/* D2：全屏最大的字之一。可收缩但不换行——点位截断也比把涨跌顶出去好 */
.idx__px {
  flex: 0 1 auto;
  min-width: 0;
  font-size: var(--fs-hero);
  font-weight: 700;
  line-height: 1.15;
  color: var(--live-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.idx__delta {
  flex: 0 0 auto;
  display: flex;
  align-items: baseline;
  gap: var(--gap-1);
  min-width: 0;
  font-size: var(--fs-aux);
  font-weight: 600;
  color: var(--live-flat);
  white-space: nowrap;
}

/*
 * 窄列取舍：先丢「涨跌点数」，保「涨跌幅」——百分比是跨指数可比的，点数不是
 * （上证 3000 点涨 10 点和创业板 2000 点涨 10 点完全不是一回事）。
 */
@container (max-width: 232px) {
  .idx__chg {
    display: none;
  }
}

/* 再窄就连代码也让位，只留名称 + 点位 + 涨跌幅 */
@container (max-width: 188px) {
  .idx__code {
    display: none;
  }
}

.idx--up .idx__px,
.idx--up .idx__delta {
  color: var(--live-up);
}

.idx--down .idx__px,
.idx--down .idx__delta {
  color: var(--live-down);
}

.idx--void .idx__px,
.idx--void .idx__delta {
  color: var(--live-dim);
}

.idx__spark {
  grid-column: 2;
  grid-row: 1 / span 2;
  align-self: center;
  width: 4.5rem;
  height: 30px;
}

/* 窄屏依次折叠尾部槽位，剩下的仍保持同一套排版 */
@media (max-width: 1280px) {
  .index-bar {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .idx:nth-child(5) {
    display: none;
  }
}

@media (max-width: 960px) {
  .index-bar {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .idx:nth-child(4) {
    display: none;
  }
  .idx__spark {
    display: none;
  }
}
</style>
