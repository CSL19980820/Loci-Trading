<script setup lang="ts">
import { computed } from 'vue'

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
    <el-tooltip :content="parsed.full" placement="right" :show-after="200">
      <header class="batch-dock__head">
        <div class="batch-dock__meta">
          <strong class="batch-dock__title">{{ parsed.title }}</strong>
          <span v-if="parsed.date" class="batch-dock__date mono">选股 {{ parsed.date }}</span>
        </div>
        <span class="batch-dock__count mono">{{ items.length }}</span>
      </header>
    </el-tooltip>
    <div class="batch-dock__list page-scroll">
      <el-button
        v-for="(item, i) in items"
        :key="item.code"
        native-type="button"
        class="batch-dock__row"
        :class="{ 'is-active': item.code === activeCode }"
        :title="item.name ? `${batchItemLabel(item)} ${item.code}` : item.code"
        @click="onSelect(item.code)"
      >
        <span class="batch-dock__n mono">{{ i + 1 }}</span>
        <span class="batch-dock__name">{{ batchItemLabel(item) }}</span>
        <span v-if="formatBatchPct(item.pct)" class="batch-dock__pct mono" :class="pctClass(item.pct)">
          {{ formatBatchPct(item.pct) }}
        </span>
      </el-button>
    </div>
  </aside>

  <el-drawer
    v-else
    :model-value="drawerOpen"
    :title="`${drawerTitle} · ${items.length}`"
    direction="ltr"
    size="78%"
    append-to-body
    @update:model-value="emit('update:drawerOpen', $event)"
  >
    <div class="batch-dock__list batch-dock__list--drawer">
      <el-button
        v-for="(item, i) in items"
        :key="item.code"
        native-type="button"
        class="batch-dock__row"
        :class="{ 'is-active': item.code === activeCode }"
        :title="item.name ? `${batchItemLabel(item)} ${item.code}` : item.code"
        @click="onSelect(item.code)"
      >
        <span class="batch-dock__n mono">{{ i + 1 }}</span>
        <span class="batch-dock__name">{{ batchItemLabel(item) }}</span>
        <span v-if="formatBatchPct(item.pct)" class="batch-dock__pct mono" :class="pctClass(item.pct)">
          {{ formatBatchPct(item.pct) }}
        </span>
      </el-button>
    </div>
  </el-drawer>
</template>

<style scoped>
.batch-dock {
  display: flex;
  flex-direction: column;
  width: 12.25rem;
  flex-shrink: 0;
  min-height: 0;
  border-right: 1px solid var(--rule);
  background: var(--sheet);
}

.batch-dock__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-1);
  padding: var(--gap-1) var(--gap-2);
  border-bottom: 1px solid var(--rule);
  flex-shrink: 0;
  cursor: default;
}

.batch-dock__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.batch-dock__title {
  font-size: var(--fs-body);
  font-weight: 700;
  letter-spacing: 0.02em;
  line-height: 1.25;
  word-break: break-word;
}

.batch-dock__date {
  font-size: var(--fs-kicker);
  font-weight: 600;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
}

.batch-dock__count {
  font-size: var(--fs-kicker);
  color: var(--mist);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  padding-top: 0.1rem;
}

.batch-dock__list {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.batch-dock__list--drawer {
  max-height: none;
}

.batch-dock__row {
  appearance: none;
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--gap-1);
  padding: 0 var(--gap-2);
  min-height: var(--row-h);
  border: 0;
  border-bottom: 1px solid var(--rule);
  background: transparent;
  text-align: left;
  cursor: pointer;
  font-family: inherit;
  color: inherit;
}

.batch-dock__row.el-button {
  height: auto;
  margin: 0;
  border-radius: 0;
  justify-content: flex-start;
  --el-button-text-color: var(--ink);
  --el-button-hover-text-color: var(--ink);
  --el-button-bg-color: transparent;
  --el-button-hover-bg-color: color-mix(in srgb, var(--seal) 8%, transparent);
  --el-button-border-color: transparent;
  --el-button-hover-border-color: transparent;
}

.batch-dock__row.is-active {
  background: var(--seal-soft);
  font-weight: 600;
}

.batch-dock__n {
  width: 1.1rem;
  flex-shrink: 0;
  font-size: var(--fs-kicker);
  color: var(--mist);
}

.batch-dock__name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-aux);
}

.batch-dock__pct {
  flex-shrink: 0;
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
  min-width: 3.2rem;
  text-align: right;
}

.batch-dock__pct.is-up {
  color: var(--up);
}

.batch-dock__pct.is-down {
  color: var(--down);
}
</style>
