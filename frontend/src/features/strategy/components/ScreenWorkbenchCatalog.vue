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
  title: string
  category: string
  summary: string
  detail: string
  example?: string
  insertText?: string
  snippet?: ScreenSkillCatalogSnippet
  meta: string[]
}

const props = withDefaults(
  defineProps<{
    catalog: ScreenSkillCatalog | null
    runtime?: ScreenSkillRuntime
    loading?: boolean
  }>(),
  { runtime: 'formula', loading: false },
)

const emit = defineEmits<{
  insertText: [text: string]
  applySnippet: [snippet: ScreenSkillCatalogSnippet]
}>()

const activeTab = ref<CatalogTab>('functions')
const keyword = ref('')
const category = ref('')
const selectedKey = ref('')

function functionEntry(item: ScreenSkillCatalogFunction): CatalogEntry {
  return {
    key: `function:${item.name}`,
    title: item.name,
    category: item.category,
    summary: item.summary,
    detail: item.description,
    example: item.examples[0],
    insertText: item.insert_text,
    meta: [item.signature, item.dialects.join(' / '), item.source],
  }
}

function fieldEntry(item: ScreenSkillCatalogField): CatalogEntry {
  return {
    key: `field:${item.name}`,
    title: item.label,
    category: item.source,
    summary: item.summary,
    detail: item.name,
    insertText: item.name,
    meta: [item.name, item.source],
  }
}

function snippetEntry(item: ScreenSkillCatalogSnippet): CatalogEntry {
  return {
    key: `snippet:${item.id}`,
    title: item.title,
    category: item.runtime,
    summary: item.summary,
    detail: item.code,
    example: item.required_fields.length ? `所需字段：${item.required_fields.join(', ')}` : undefined,
    snippet: item,
    meta: [item.runtime, item.dialect, `${Object.keys(item.params).length} 个参数`],
  }
}

const entries = computed<CatalogEntry[]>(() => {
  if (!props.catalog) return []
  if (activeTab.value === 'functions') return props.catalog.functions.map(functionEntry)
  if (activeTab.value === 'fields') return props.catalog.fields.map(fieldEntry)
  return props.catalog.snippets.filter((item) => item.runtime === props.runtime).map(snippetEntry)
})

const categories = computed(() => [...new Set(entries.value.map((item) => item.category))])
const visibleEntries = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return entries.value.filter((item) => {
    if (category.value && item.category !== category.value) return false
    if (!text) return true
    return [item.title, item.summary, item.detail, item.meta.join(' ')].join('\n').toLowerCase().includes(text)
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
</script>

<template>
  <section class="catalog" aria-label="公式目录与常用片段">
    <div class="catalog__head">
      <div>
        <span class="catalog__eyebrow">编写工具</span>
        <strong>函数、字段与片段</strong>
      </div>
      <el-tag size="small" effect="plain">{{ runtime === 'python' ? 'Python' : '公式' }}</el-tag>
    </div>

    <el-tabs v-model="activeTab" class="catalog__tabs" stretch>
      <el-tab-pane label="函数" name="functions" />
      <el-tab-pane label="字段" name="fields" />
      <el-tab-pane label="片段" name="snippets" />
    </el-tabs>

    <div class="catalog__filters">
      <el-input v-model="keyword" clearable placeholder="搜索名称、说明或示例" aria-label="搜索函数、字段或片段">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="category" clearable placeholder="全部分类" aria-label="按分类筛选">
        <el-option v-for="item in categories" :key="item" :label="item" :value="item" />
      </el-select>
    </div>

    <div v-loading="loading" class="catalog__body">
      <div class="catalog__list" role="list" aria-label="目录条目">
        <el-button
          v-for="item in visibleEntries"
          :key="item.key"
          text
          class="catalog__row"
          :class="{ 'catalog__row--active': item.key === selectedKey }"
          @click="selectedKey = item.key"
        >
          <span class="catalog__row-title">{{ item.title }}</span>
          <span class="catalog__row-summary">{{ item.summary }}</span>
        </el-button>
        <el-empty v-if="!loading && !visibleEntries.length" :image-size="48" description="没有匹配的目录条目" />
      </div>

      <article v-if="selected" class="catalog__detail" aria-live="polite">
        <div class="catalog__detail-head">
          <div>
            <strong>{{ selected.title }}</strong>
            <div class="catalog__meta">{{ selected.meta.join(' · ') }}</div>
          </div>
          <el-button type="primary" size="small" @click="applySelected">
            {{ selected.snippet ? '应用片段' : '插入' }}
          </el-button>
        </div>
        <p>{{ selected.summary }}</p>
        <pre class="catalog__code">{{ selected.detail }}</pre>
        <div v-if="selected.example" class="catalog__example">{{ selected.example }}</div>
      </article>
      <div v-else class="catalog__placeholder">选择一个条目查看说明与示例。</div>
    </div>
  </section>
</template>

<style scoped>
.catalog { display: flex; flex-direction: column; min-width: 0; height: 100%; gap: .55rem; overflow: hidden; }
.catalog__head, .catalog__detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: .75rem; }
.catalog__head strong, .catalog__detail strong { display: block; font-size: .92rem; }
.catalog__eyebrow, .catalog__meta { color: var(--mist); font: .72rem/1.25 var(--mono); }
.catalog__meta { display: -webkit-box; overflow: hidden; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.catalog__filters { display: grid; grid-template-columns: minmax(0, 1fr) 8rem; gap: .45rem; }
.catalog__tabs :deep(.el-tabs__header) { margin: 0; }
.catalog__tabs :deep(.el-tabs__content) { display: none; }
.catalog__body { display: grid; grid-template-rows: minmax(8rem, 1fr) minmax(7rem, auto); flex: 1; min-height: 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.catalog__list { min-height: 0; overflow-x: hidden; overflow-y: auto; border-bottom: 1px solid var(--rule); padding: .2rem 0; }
.catalog__row { display: grid; grid-template-columns: minmax(3.3rem, auto) minmax(0, 1fr); gap: .5rem; width: 100%; height: auto; min-height: 2.8rem; margin-left: 0 !important; padding: .35rem .5rem; text-align: left; color: var(--ink); border-radius: 0; }
.catalog__row--active { background: var(--seal-soft); }
.catalog__row-title, .catalog__row-summary { display: block; min-width: 0; white-space: normal; }
.catalog__row-title { font: 600 .8rem/1.25 var(--mono); }
.catalog__row-summary { overflow: hidden; color: var(--mist); font-size: .76rem; line-height: 1.3; text-overflow: ellipsis; white-space: nowrap; }
.catalog__detail, .catalog__placeholder { min-width: 0; max-height: 10rem; overflow: auto; padding: .6rem; }
.catalog__detail-head > div { min-width: 0; }
.catalog__detail p { margin: .5rem 0; font-size: .82rem; }
.catalog__code { margin: .45rem 0; padding: .45rem; overflow: auto; border-left: 2px solid var(--seal); background: var(--sheet); color: var(--ink); font: .76rem/1.45 var(--mono); white-space: pre-wrap; }
.catalog__example { color: var(--mist); font-size: .78rem; }
.catalog__placeholder { display: grid; place-items: center; color: var(--mist); font-size: .82rem; }
@media (max-width: 640px) { .catalog__filters { grid-template-columns: 1fr; } .catalog__body { grid-template-rows: minmax(8rem, 1fr) auto; } }
</style>
