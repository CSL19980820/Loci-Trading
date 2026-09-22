<script setup lang="ts">
import { Item } from '@/shared/components/ui/item'
/**
 * 同批列表：桌面是左侧一张 240px 的卡（Linear 侧栏密度：36px 行 · 序号 · 名称 + 代码 · 涨跌）；
 * 窄屏是抽屉（≤640 由 SheetContent 自动贴底）。两种形态共用一份行模板。
 */
import { computed } from 'vue'

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/shared/components/ui/sheet'
import { batchItemLabel, formatBatchPct, parseBatchSource } from '@/shared/lib/batchBrowse'
import type { BatchItem } from '@/shared/stores/batchBrowse'

const props = defineProps<{
  source: string
  items: BatchItem[]
  activeCode: string
  /** 窄屏用抽屉；桌面用侧栏 */
  mode?: 'dock' | 'drawer'
  drawerOpen?: boolean
}>()

const emit = defineEmits<{
  select: [code: string]
  'update:drawerOpen': [open: boolean]
}>()

const parsed = computed(() => parseBatchSource(props.source))
const drawerTitle = computed(() => {
  const { title, date } = parsed.value
  return date ? `${title} · ${date}` : title
})

function pctClass(pct: number | null | undefined): string {
  if (pct == null || !Number.isFinite(pct) || pct === 0) return ''
  return pct > 0 ? 'is-up' : 'is-down'
}

function onSelect(code: string): void {
  emit('select', code)
  if (props.mode === 'drawer') emit('update:drawerOpen', false)
}
</script>

<template>
  <aside v-if="mode !== 'drawer'" class="batch-dock" :aria-label="parsed.full">
    <header class="batch-dock__head">
      <div class="batch-dock__meta">
        <strong class="batch-dock__title" :title="parsed.full">{{ parsed.title }}</strong>
        <span v-if="parsed.date" class="batch-dock__date">选股 {{ parsed.date }}</span>
      </div>
      <span class="batch-dock__count">{{ items.length }}</span>
    </header>
    <ol class="batch-dock__list">
      <li v-for="(item, i) in items" :key="item.code">
        <Item as="button"
          type="button"
          class="batch-dock__row"
          :class="{ 'is-active': item.code === activeCode }"
          :aria-current="item.code === activeCode ? 'true' : undefined"
          :title="item.name ? `${batchItemLabel(item)} ${item.code}` : item.code"
          @click="onSelect(item.code)"
        >
          <span class="batch-dock__n">{{ i + 1 }}</span>
          <span class="batch-dock__id">
            <span class="batch-dock__name">{{ batchItemLabel(item) }}</span>
            <span class="batch-dock__code">{{ item.code }}</span>
          </span>
          <span v-if="formatBatchPct(item.pct)" class="batch-dock__pct" :class="pctClass(item.pct)">
            {{ formatBatchPct(item.pct) }}
          </span>
        </Item>
      </li>
    </ol>
  </aside>

  <Sheet
    v-else
    :open="drawerOpen"
    @update:open="emit('update:drawerOpen', $event)"
  >
    <SheetContent side="left" class="batch-dock-sheet gap-0 p-0 sm:w-[22rem]">
      <SheetHeader class="batch-dock__head batch-dock__head--sheet text-left">
        <SheetTitle class="batch-dock__title">{{ drawerTitle }}</SheetTitle>
        <SheetDescription class="batch-dock__date">共 {{ items.length }} 只 · 点一只切换</SheetDescription>
      </SheetHeader>
      <ol class="batch-dock__list batch-dock__list--drawer">
        <li v-for="(item, i) in items" :key="item.code">
          <Item as="button"
            type="button"
            class="batch-dock__row"
            :class="{ 'is-active': item.code === activeCode }"
            :aria-current="item.code === activeCode ? 'true' : undefined"
            :title="item.name ? `${batchItemLabel(item)} ${item.code}` : item.code"
            @click="onSelect(item.code)"
          >
            <span class="batch-dock__n">{{ i + 1 }}</span>
            <span class="batch-dock__id">
              <span class="batch-dock__name">{{ batchItemLabel(item) }}</span>
              <span class="batch-dock__code">{{ item.code }}</span>
            </span>
            <span v-if="formatBatchPct(item.pct)" class="batch-dock__pct" :class="pctClass(item.pct)">
              {{ formatBatchPct(item.pct) }}
            </span>
          </Item>
        </li>
      </ol>
    </SheetContent>
  </Sheet>
</template>

<style scoped>
.batch-dock {
  display: flex;
  flex-direction: column;
  width: 240px;
  flex-shrink: 0;
  min-height: 0;
  margin-block: var(--gap-4) var(--gap-6);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
}

.batch-dock__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-2);
  padding: var(--gap-3) var(--gap-3);
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}

.batch-dock__head--sheet {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--gap-4) var(--gap-4) var(--gap-3);
  padding-right: calc(var(--gap-4) + 36px);
}

.batch-dock__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.batch-dock__title {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.batch-dock__date {
  margin: 0;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
}

.batch-dock__count {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  height: 18px;
  padding: 0 6px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.batch-dock__list {
  flex: 1 1 auto;
  min-height: 0;
  margin: 0;
  padding: var(--gap-1);
  list-style: none;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.batch-dock__list--drawer {
  max-height: none;
  padding: var(--gap-2);
}

.batch-dock__row {
  appearance: none;
  display: grid;
  grid-template-columns: 1.4rem minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  min-height: var(--row-h);
  padding: 4px var(--gap-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease);
}

.batch-dock__row:hover {
  background: var(--surface-hover);
}

.batch-dock__row:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

.batch-dock__row.is-active {
  background: var(--seal-soft);
}

.batch-dock__row.is-active .batch-dock__name {
  color: var(--seal-ink);
}

.batch-dock__n {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.batch-dock__id {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  gap: 1px;
  min-width: 0;
  line-height: 1.25;
}

.batch-dock__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 500;
}

.batch-dock__code {
  flex-shrink: 0;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  letter-spacing: 0.02em;
}

.batch-dock__pct {
  flex-shrink: 0;
  min-width: 3.4rem;
  text-align: right;
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.batch-dock__pct.is-up {
  color: var(--up);
}

.batch-dock__pct.is-down {
  color: var(--down);
}

@media (max-width: 640px) {
  .batch-dock__row {
    min-height: 44px;
  }
}
</style>
