<script setup lang="ts">
import { Command, CommandList, CommandItem } from '@/shared/components/ui/command'
import { computed, ref } from 'vue'
import { Cpu, Search, SlidersHorizontal, X } from '@lucide/vue'

import { pct } from '@/shared/lib/format'
import { sampleConfidence, winRateDisplayTone, winRateText } from '@/shared/lib/winrate'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Skeleton } from '@/shared/components/ui/skeleton'

import type { ScreenCatalogItem } from '../composables/useScreenCatalog'

/**
 * 目录栏（Linear 侧栏一路）：类型药片 + 搜索在上，下面一行一条——
 *   [图标] 名称       57.1%  +1.2%
 * 右侧只在样本够数时出胜率·均收益，不够就一个 —；选中行仅用柔和主题底色，不加边框或竖线。
 */
const props = defineProps<{
  rows: ScreenCatalogItem[]
  selectedId: string
  kindFilter: 'all' | 'engine' | 'skill'
  loading?: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  'update:kindFilter': [value: 'all' | 'engine' | 'skill']
}>()

const query = ref('')

const kindItems = [
  { name: 'all', label: '全部' },
  { name: 'engine', label: '战法' },
  { name: 'skill', label: '技能' },
]

const visible = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.rows
  return props.rows.filter(
    (row) =>
      row.name.toLowerCase().includes(q) ||
      row.slug.toLowerCase().includes(q),
  )
})

/** 战法目录用一位小数，够看趋势即可。 */
function fmtPct(value: number | null | undefined): string {
  return pct(value, 1)
}

/** 样本不足时不刷文案，右侧只留 —；够数才出胜率·均收益。 */
function hasCredibleStats(row: ScreenCatalogItem): boolean {
  return sampleConfidence(row.sample) !== 'low' && row.winRate != null
}
</script>

<template>
  <div class="catalog-rail" aria-label="选股能力目录">
    <div class="catalog-rail__tools">
      <PageTabs
        :model-value="kindFilter"
        :items="kindItems"
        variant="pill"
        dense
        :sticky="false"
        aria-label="选股能力类型"
        class="catalog-rail__kinds"
        @update:model-value="emit('update:kindFilter', $event as 'all' | 'engine' | 'skill')"
      />
      <div class="rail-search">
        <Search class="rail-search__icon" aria-hidden="true" />
        <Input
          v-model="query"
          size="sm"
          class="rail-search__input"
          placeholder="搜名称或 slug"
          aria-label="搜索战法或技能"
        />
        <Button access="read"
          v-if="query"
          variant="ghost"
          size="icon-xs"
          class="rail-search__clear"
          aria-label="清空搜索"
          @click="query = ''"
        >
          <X aria-hidden="true" />
        </Button>
      </div>
    </div>

    <div v-if="loading && !rows.length" class="rail-skeleton" aria-hidden="true">
      <Skeleton v-for="n in 6" :key="n" class="h-9 w-full" />
    </div>
    <EmptyState
      v-else-if="!visible.length"
      compact
      :description="query ? '没有匹配项' : '暂无战法或技能'"
      :reason="query ? '清空搜索后重试' : '前往工坊创建'"
    />
    <Command v-else :model-value="selectedId" class="catalog-rail__command" :selection-follows-focus="false">
    <CommandList class="catalog-rail__list" aria-label="战法与技能">
      <CommandItem
        v-for="row in visible"
        :key="row.id"
        :value="row.id"
        :text-value="row.name"
        class="p-0"
        @select="emit('select', row.id)"
        :class="{ 'is-selected': row.id === selectedId, 'is-disabled': row.kind === 'skill' && !row.enabled }"
      >
        <div
          class="catalog-row"
          :title="`${row.name} · ${row.sample || 0} 样本`"
          :aria-label="`${row.name}，${row.kind === 'engine' ? '战法' : '技能'}${row.kind === 'skill' && !row.enabled ? '，已停用' : ''}`"

        >
          <span class="catalog-row__icon" :class="row.kind" aria-hidden="true">
            <component :is="row.kind === 'engine' ? SlidersHorizontal : Cpu" />
          </span>
          <span class="catalog-row__main">
            <strong class="catalog-row__name">{{ row.name }}</strong>
            <span class="catalog-row__sub">{{ row.kind === 'engine' ? '战法' : '技能' }}<template v-if="row.kind === 'skill' && !row.enabled"> · 已停用</template><template v-else-if="row.sample"> · {{ row.sample }} 样本</template></span>
          </span>
          <span
            v-if="hasCredibleStats(row)"
            class="catalog-row__stat"
            :class="winRateDisplayTone(row.winRate, row.sample)"
          >
            <b>{{ winRateText(row.winRate) }}</b>
            <small>{{ fmtPct(row.avgReturn) }}</small>
          </span>
          <span v-else class="catalog-row__stat is-empty"><b>—</b></span>
        </div>
      </CommandItem>
    </CommandList>
    </Command>
  </div>
</template>

<style scoped>
.catalog-rail {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  height: 100%;
  min-height: 0;
  padding: var(--gap-3) var(--gap-2) var(--gap-2);
}

.catalog-rail__tools {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  gap: var(--gap-2);
  padding: 0 var(--gap-1);
}

.catalog-rail__kinds :deep(.page-tabs__list) {
  width: 100%;
}

.catalog-rail__kinds :deep(.page-tabs__item) {
  flex: 1 1 0;
  justify-content: center;
}

.rail-search {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 0;
}

.rail-search__icon {
  position: absolute;
  left: 9px;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.rail-search__input {
  padding-left: 28px;
  padding-right: 28px;
}

.rail-search__clear {
  position: absolute;
  right: 3px;
}

.rail-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  padding: 0 var(--gap-1);
}

.catalog-rail__command { flex: 1; min-height: 0; background: transparent; }
.catalog-rail__list {
  max-height: none;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-height: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  overflow: auto;
  overscroll-behavior: contain;
}

.catalog-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  min-height: 44px;
  padding: 6px var(--gap-2) 6px 10px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease);
}

.catalog-row:hover {
  background: var(--surface-hover);
}

.catalog-rail__list :deep([data-highlighted]) .catalog-row {
  outline: 2px solid var(--focus-ring, var(--seal));
  outline-offset: -2px;
}


.is-selected .catalog-row {
  background: var(--seal-soft);
}


.is-selected .catalog-row__name {
  color: var(--seal-ink);
}

.is-disabled .catalog-row {
  opacity: 0.6;
}

.catalog-row__icon {
  display: grid;
  flex-shrink: 0;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--text-secondary);
}

.catalog-row__icon.engine {
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.catalog-row__icon :deep(svg) {
  width: 13px;
  height: 13px;
}

.catalog-row__main {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.catalog-row__name {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog-row__sub {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog-row__stat {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.catalog-row__stat b {
  font-size: var(--fs-aux);
  font-weight: 600;
}

.catalog-row__stat small {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.catalog-row__stat.is-empty b {
  color: var(--text-tertiary);
  font-weight: 400;
}

.wr-muted b {
  color: var(--text-tertiary);
}

.wr-mid b {
  color: var(--text-secondary);
}

.wr-high b {
  color: var(--up);
}

.wr-low b {
  color: var(--down);
}
</style>
