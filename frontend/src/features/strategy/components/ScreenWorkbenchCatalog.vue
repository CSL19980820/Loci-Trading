<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Search, X } from '@lucide/vue'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { Button } from '@/shared/components/ui/button'
import { Input } from '@/shared/components/ui/input'
import { Tabs, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import type {
  ScreenSkillCatalog,
  ScreenSkillCatalogField,
  ScreenSkillCatalogFunction,
  ScreenSkillCatalogSnippet,
  ScreenSkillRuntime,
} from '@/shared/types/quant'

type CatalogTab = 'functions' | 'fields' | 'snippets'
type CatalogEntry = {
  key: string
  /** 列表主标题（中文） */
  title: string
  /** 列表副标（符号名 / 插入名） */
  symbol: string
  category: string
  summary: string
  detail: string
  example?: string
  insertText?: string
  snippet?: ScreenSkillCatalogSnippet
  signature?: string
}

const props = withDefaults(
  defineProps<{
    catalog: ScreenSkillCatalog | null
    runtime?: ScreenSkillRuntime
    loading?: boolean
    layout?: 'rail' | 'dialog'
  }>(),
  { runtime: 'formula', loading: false, layout: 'rail' },
)

const emit = defineEmits<{
  insertText: [text: string]
  applySnippet: [snippet: ScreenSkillCatalogSnippet]
}>()

const activeTab = ref<CatalogTab>('functions')
const keyword = ref('')
const category = ref('')
const selectedKey = ref('')

const FIELD_SOURCE_LABELS: Record<string, string> = {
  'market.daily': '日线行情',
}

const FIELD_NAME_LABELS: Record<string, string> = {
  open: '开盘价',
  high: '最高价',
  low: '最低价',
  close: '收盘价',
  volume: '成交量',
  amount: '成交额',
  turnover: '换手率',
}

function fieldCategory(source: string): string {
  if (source.startsWith('market.daily')) return FIELD_SOURCE_LABELS['market.daily']!
  if (source.startsWith('market.')) return '行情'
  return '其他'
}

function runtimeLabel(runtime: string): string {
  if (runtime === 'python') return '脚本'
  return '公式'
}

function functionEntry(item: ScreenSkillCatalogFunction): CatalogEntry {
  return {
    key: `function:${item.name}`,
    title: item.summary || item.name,
    symbol: item.name,
    category: item.category,
    summary: item.summary,
    detail: item.description,
    example: item.examples[0],
    insertText: item.insert_text,
    signature: item.signature,
  }
}

function fieldEntry(item: ScreenSkillCatalogField): CatalogEntry {
  const label = item.label || FIELD_NAME_LABELS[item.name] || item.name
  return {
    key: `field:${item.name}`,
    title: label,
    symbol: item.name.toUpperCase(),
    category: fieldCategory(item.source),
    summary: item.summary,
    detail: item.summary,
    insertText: item.name,
    signature: item.name.toUpperCase(),
  }
}

function snippetEntry(item: ScreenSkillCatalogSnippet): CatalogEntry {
  const paramCount = Object.keys(item.params).length
  return {
    key: `snippet:${item.id}`,
    title: item.title,
    symbol: runtimeLabel(item.runtime),
    category: runtimeLabel(item.runtime),
    summary: item.summary || item.title,
    detail: item.code.trim(),
    example: item.required_fields.length
      ? `所需字段：${item.required_fields.map((f) => FIELD_NAME_LABELS[f] || f).join('、')}`
      : paramCount
        ? `${paramCount} 个参数`
        : undefined,
    snippet: item,
  }
}

const entries = computed<CatalogEntry[]>(() => {
  if (!props.catalog) return []
  if (activeTab.value === 'functions') return props.catalog.functions.map(functionEntry)
  if (activeTab.value === 'fields') return props.catalog.fields.map(fieldEntry)
  return props.catalog.snippets.filter((item) => item.runtime === props.runtime).map(snippetEntry)
})

const categories = computed(() => [...new Set(entries.value.map((item) => item.category))])
const categoryCounts = computed(() => {
  const counts = new Map<string, number>()
  for (const item of entries.value) {
    counts.set(item.category, (counts.get(item.category) ?? 0) + 1)
  }
  return counts
})
const visibleEntries = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return entries.value.filter((item) => {
    if (category.value && item.category !== category.value) return false
    if (!text) return true
    return [item.title, item.symbol, item.summary, item.detail, item.signature ?? '']
      .join('\n')
      .toLowerCase()
      .includes(text)
  })
})
const selected = computed(() => visibleEntries.value.find((item) => item.key === selectedKey.value) ?? null)

/** `Tabs` 的 v-model 走 reka-ui 的 `AcceptableValue`，这里收成目录自己的三档。 */
function onTabChange(value: unknown): void {
  activeTab.value = String(value) as CatalogTab
}

watch(activeTab, () => {
  category.value = ''
})
watch(
  visibleEntries,
  (items) => {
    if (!items.some((item) => item.key === selectedKey.value)) selectedKey.value = items[0]?.key ?? ''
  },
  { immediate: true },
)

function applySelected(): void {
  if (!selected.value) return
  if (selected.value.snippet) {
    emit('applySnippet', selected.value.snippet)
    return
  }
  if (selected.value.insertText) emit('insertText', selected.value.insertText)
}

function onRowDblClick(item: CatalogEntry): void {
  selectedKey.value = item.key
  if (item.snippet) emit('applySnippet', item.snippet)
  else if (item.insertText) emit('insertText', item.insertText)
}
</script>

<template>
  <section
    class="catalog"
    :class="{ 'catalog--dialog': layout === 'dialog' }"
    aria-label="公式目录与常用片段"
  >
    <div class="catalog__toolbar">
      <Tabs :model-value="activeTab" class="catalog__tabs" @update:model-value="onTabChange">
        <TabsList>
          <TabsTrigger value="functions">函数</TabsTrigger>
          <TabsTrigger value="fields">字段</TabsTrigger>
          <TabsTrigger value="snippets">片段</TabsTrigger>
        </TabsList>
      </Tabs>
      <div class="catalog__search">
        <Search class="catalog__search-icon" aria-hidden="true" />
        <Input
          v-model="keyword"
          class="catalog__search-input"
          placeholder="搜索中文名、符号或说明"
          aria-label="搜索函数、字段或片段"
        />
        <Button access="read"
          v-if="keyword"
          variant="ghost"
          size="icon-xs"
          class="catalog__search-clear"
          aria-label="清空搜索"
          @click="keyword = ''"
        >
          <X class="size-3.5" />
        </Button>
      </div>
    </div>

    <div class="catalog__body">
      <PageBusy :busy="loading" overlay />
      <aside class="catalog__cats" aria-label="分类">
        <Button access="read"
          variant="ghost"
          class="catalog__cat"
          :class="{ 'catalog__cat--active': !category }"
          @click="category = ''"
        >
          <span class="catalog__cat-name">全部</span>
          <span class="catalog__cat-count">{{ entries.length }}</span>
        </Button>
        <Button access="read"
          v-for="item in categories"
          :key="item"
          variant="ghost"
          class="catalog__cat"
          :class="{ 'catalog__cat--active': category === item }"
          @click="category = item"
        >
          <span class="catalog__cat-name">{{ item }}</span>
          <span class="catalog__cat-count">{{ categoryCounts.get(item) ?? 0 }}</span>
        </Button>
      </aside>

      <div class="catalog__list" role="list" aria-label="目录条目">
        <Button
          v-for="item in visibleEntries"
          :key="item.key"
          variant="ghost"
          class="catalog__row"
          :class="{ 'catalog__row--active': item.key === selectedKey }"
          @click="selectedKey = item.key"
          @dblclick="onRowDblClick(item)"
        >
          <span class="catalog__row-main">
            <span class="catalog__row-title">{{ item.title }}</span>
            <span class="catalog__row-symbol">{{ item.symbol }}</span>
          </span>
          <span v-if="item.summary !== item.title" class="catalog__row-summary">{{ item.summary }}</span>
        </Button>
        <EmptyState
          v-if="!loading && !visibleEntries.length"
          description="无匹配项"
          reason="试试别的关键词"
        />
      </div>

      <article v-if="selected" class="catalog__detail" aria-live="polite">
        <header class="catalog__detail-head">
          <strong>{{ selected.title }}</strong>
          <code v-if="selected.signature">{{ selected.signature }}</code>
        </header>
        <p
          v-if="!selected.snippet && selected.detail && selected.detail !== selected.title"
          class="catalog__desc"
        >
          {{ selected.detail }}
        </p>
        <p
          v-else-if="selected.snippet && selected.summary && selected.summary !== selected.title"
          class="catalog__desc"
        >
          {{ selected.summary }}
        </p>
        <pre v-if="selected.snippet" class="catalog__code">{{ selected.detail }}</pre>
        <div v-if="selected.example" class="catalog__example">{{ selected.example }}</div>
        <Button class="catalog__insert" @click="applySelected">
          {{ selected.snippet ? '应用片段' : '插入到光标' }}
        </Button>
      </article>
      <div v-else class="catalog__placeholder">选择一项查看用法</div>
    </div>
  </section>
</template>

<style scoped>
.catalog {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.catalog__toolbar {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}

.catalog__tabs {
  flex: 1 1 auto;
  min-width: 12rem;
  gap: 0;
}

.catalog__search {
  position: relative;
  display: flex;
  align-items: center;
  width: min(16rem, 100%);
  min-width: 0;
}

.catalog__search-icon {
  position: absolute;
  left: 0.4rem;
  width: 0.85rem;
  height: 0.85rem;
  color: var(--mist);
  pointer-events: none;
}

.catalog__search-input {
  padding-left: 1.6rem;
  padding-right: 1.6rem;
}

.catalog__search-clear {
  position: absolute;
  right: 0.2rem;
}

.catalog__body {
  position: relative;
  display: grid;
  grid-template-columns: 7.8rem minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr) minmax(7rem, 38%);
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--rule);
}

.catalog--dialog .catalog__body {
  grid-template-columns: 8.75rem minmax(0, 1.15fr) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
}

.catalog__cats,
.catalog__list,
.catalog__detail,
.catalog__placeholder {
  min-width: 0;
  min-height: 0;
  overflow: auto;
}

.catalog__cats {
  grid-row: 1 / span 2;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.4rem;
  border-right: none;
  background: color-mix(in oklab, var(--panel-2) 70%, transparent);
}

.catalog--dialog .catalog__cats {
  grid-row: 1;
}

.catalog__cat {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  width: 100%;
  height: auto;
  padding: 0.4rem 0.45rem;
  border-radius: 2px;
  color: var(--ink);
  font-size: var(--fs-aux);
}

.catalog__cat-name {
  min-width: 0;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog__cat-count {
  flex: 0 0 auto;
  color: var(--mist);
  font: 0.72rem/1 var(--mono);
}

.catalog__cat--active {
  background: var(--seal-soft);
}

.catalog__list {
  padding: 0.25rem 0;
  border-bottom: 1px solid var(--rule);
}

.catalog--dialog .catalog__list {
  border-right: none;
  border-bottom: 0;
}

.catalog__row {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.12rem;
  width: 100%;
  height: auto;
  min-height: 2.4rem;
  padding: 0.4rem 0.65rem;
  text-align: left;
  color: var(--ink);
  border-radius: 0;
}

.catalog__row--active {
  background: var(--seal-soft);
}

.catalog__row-main {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.65rem;
  min-width: 0;
}

.catalog__row-title {
  min-width: 0;
  overflow: hidden;
  font-size: 0.84rem;
  font-weight: 600;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog__row-symbol {
  flex: 0 0 auto;
  color: var(--mist);
  font: 0.72rem/1.3 var(--mono);
}

.catalog__row-summary {
  overflow: hidden;
  color: var(--mist);
  font-size: var(--fs-aux);
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.catalog__detail,
.catalog__placeholder {
  padding: 0.75rem 0.85rem;
}

.catalog__detail {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.catalog__detail-head {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.catalog__detail-head strong {
  font-size: var(--fs-body);
  line-height: 1.35;
}

.catalog__detail-head code {
  color: var(--mist);
  font: 0.76rem/1.35 var(--mono);
}

.catalog__desc {
  margin: 0;
  color: var(--muted);
  font-size: var(--fs-aux);
  line-height: 1.5;
}

.catalog__code {
  margin: 0;
  padding: 0.55rem 0.65rem;
  overflow: auto;
  border: 1px solid var(--rule);
  background: var(--sheet);
  color: var(--ink);
  font: 0.76rem/1.45 var(--mono);
  white-space: pre-wrap;
}

.catalog__example {
  color: var(--mist);
  font: 0.76rem/1.4 var(--mono);
}

.catalog__insert {
  align-self: flex-start;
  margin-top: auto;
}

.catalog__placeholder {
  display: grid;
  place-items: center;
  color: var(--mist);
  font-size: var(--fs-aux);
}

@media (max-width: 720px) {
  .catalog--dialog .catalog__body {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr) minmax(0, 1fr);
  }

  .catalog--dialog .catalog__cats {
    flex-direction: row;
    flex-wrap: wrap;
    border-right: 0;
    border-bottom: 1px solid var(--rule);
  }

  .catalog--dialog .catalog__list {
    border-right: 0;
    border-bottom: 1px solid var(--rule);
  }
}
</style>
