<script setup lang="ts">
import { Search } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

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
      <el-tabs v-model="activeTab" class="catalog__tabs">
        <el-tab-pane label="函数" name="functions" />
        <el-tab-pane label="字段" name="fields" />
        <el-tab-pane label="片段" name="snippets" />
      </el-tabs>
      <el-input
        v-model="keyword"
        clearable
        placeholder="搜索中文名、符号或说明"
        aria-label="搜索函数、字段或片段"
        class="catalog__search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
    </div>

    <div v-loading="loading" class="catalog__body">
      <aside class="catalog__cats" aria-label="分类">
        <el-button
          text
          class="catalog__cat"
          :class="{ 'catalog__cat--active': !category }"
          @click="category = ''"
        >
          <span class="catalog__cat-name">全部</span>
          <span class="catalog__cat-count">{{ entries.length }}</span>
        </el-button>
        <el-button
          v-for="item in categories"
          :key="item"
          text
          class="catalog__cat"
          :class="{ 'catalog__cat--active': category === item }"
          @click="category = item"
        >
          <span class="catalog__cat-name">{{ item }}</span>
          <span class="catalog__cat-count">{{ categoryCounts.get(item) ?? 0 }}</span>
        </el-button>
      </aside>

      <div class="catalog__list" role="list" aria-label="目录条目">
        <el-button
          v-for="item in visibleEntries"
          :key="item.key"
          text
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
        </el-button>
        <el-empty
          v-if="!loading && !visibleEntries.length"
          :image-size="48"
          description="无匹配项，试试别的关键词"
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
        <el-button type="primary" class="catalog__insert" @click="applySelected">
          {{ selected.snippet ? '应用片段' : '插入到光标' }}
        </el-button>
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
}

.catalog__tabs :deep(.el-tabs__header) {
  margin: 0;
}

.catalog__tabs :deep(.el-tabs__content) {
  display: none;
}

.catalog__search {
  width: min(16rem, 100%);
}

.catalog__body {
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
  border-right: 1px solid var(--rule);
  background: color-mix(in srgb, var(--panel-2) 70%, transparent);
}

.catalog--dialog .catalog__cats {
  grid-row: 1;
}

.catalog__cat {
  width: 100%;
  height: auto !important;
  margin-left: 0 !important;
  padding: 0.4rem 0.45rem !important;
  border-radius: 2px;
  color: var(--ink);
  font-size: 0.78rem;
}

.catalog__cat :deep(.el-button__content) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.65rem;
  width: 100%;
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
  border-right: 1px solid var(--rule);
  border-bottom: 0;
}

.catalog__row {
  display: flex !important;
  flex-direction: column;
  align-items: stretch !important;
  gap: 0.12rem;
  width: 100%;
  height: auto !important;
  min-height: 2.4rem;
  margin-left: 0 !important;
  padding: 0.4rem 0.65rem !important;
  text-align: left;
  color: var(--ink);
  border-radius: 0;
}

.catalog__row :deep(.el-button__content) {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.12rem;
  width: 100%;
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
  font-size: 0.74rem;
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
  font-size: 0.95rem;
  line-height: 1.35;
}

.catalog__detail-head code {
  color: var(--mist);
  font: 0.76rem/1.35 var(--mono);
}

.catalog__desc {
  margin: 0;
  color: var(--muted);
  font-size: 0.82rem;
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
  font-size: 0.82rem;
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
