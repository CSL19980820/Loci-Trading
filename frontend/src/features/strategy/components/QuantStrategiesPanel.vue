<script setup lang="ts">
import { useVisitorMode } from '@/shared/composables/useAccess'
const visitor = useVisitorMode()
import { computed, ref, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { ChevronRight, Pencil, Play, Search, Settings2, SlidersHorizontal, Upload, X } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'

import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { strategyLabel } from '@/shared/lib/format'
import type { StrategyInfo } from '@/shared/types/quant'

import StrategyDetailDialog from './StrategyDetailDialog.vue'

/**
 * 名称列一律中文：后端 `name` 缺失、或它本身就是 slug 形状（`sanyuan-tail-v1`）时
 * 退回共享词表。搜索与 row-key 仍然用 slug，那是标识不是展示。
 */
function displayName(name: unknown, slug: unknown): string {
  const text = String(name || '').trim()
  if (text && !/^[a-z0-9][a-z0-9._-]*$/.test(text)) return text
  return strategyLabel(String(slug || '') || text)
}

function sourceKindLabel(kind: string | null | undefined): string {
  if (kind === 'builtin') return '内置'
  if (kind === 'formula') return '公式'
  return kind ? String(kind) : '—'
}

function revisionLabel(revision: string | null | undefined, sourceKind?: string | null): string {
  const raw = String(revision || '').trim()
  if (!raw) return '—'
  if (sourceKind === 'builtin' || raw.startsWith('builtin:')) return '内置'
  // 公式战法修订多为内容哈希
  if (/^[0-9a-f]{8,}$/i.test(raw)) return `公式 · ${raw.slice(0, 8)}`
  if (raw.startsWith('formula:')) return `公式 · ${raw.slice(8, 16) || '—'}`
  return raw.startsWith('公式') ? raw : `公式 · ${raw.slice(0, 8)}`
}

function entryLabel(value: StrategyInfo['entry_timing']): string {
  if (value === 'open') return '当日开盘'
  if (value === 'close') return '当日收盘'
  if (value === 'next_dip') return '次日低吸'
  return '次日开盘'
}

const props = defineProps<{
  strategies: StrategyInfo[]
  loading?: boolean
}>()

const emit = defineEmits<{
  openScreen: [slug: string]
  /** 打开「从克隆包导入」对话框；对话框由 QuantView 持有（它同时是刷新战法列表的人）。 */
  importBundle: []
}>()

const router = useRouter()
const route = useRoute()
const isMobile = useMediaQuery('(max-width: 640px)')
const query = ref('')
const detailOpen = ref(false)
const detail = ref<StrategyInfo | null>(null)

watch(
  () => [props.strategies, route.query.strategy] as const,
  ([list, raw]) => {
    const slug = String(raw || '').trim()
    if (!slug || !list.length) return
    const hit = list.find((s) => s.slug === slug)
    if (!hit) return
    openDetail(hit)
    const nextQuery = { ...route.query }
    delete nextQuery.strategy
    void router.replace({ query: nextQuery })
  },
  { immediate: true },
)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.strategies
  return props.strategies.filter(
    (row) =>
      row.name.toLowerCase().includes(q)
      || row.slug.toLowerCase().includes(q)
      || String(row.description || '').toLowerCase().includes(q),
  )
})

function openDetail(row: StrategyInfo): void {
  detail.value = row
  detailOpen.value = true
}

function openWorkbench(query: Record<string, string | undefined>): void {
  void router.push({
    path: '/strategy-converter',
    query,
  })
}

function openEditableStrategy(slug: string): void {
  openWorkbench({ slug })
}
</script>

<template>
  <div class="strategies-panel">
    <Card class="strategies-card">
      <div class="strategies-toolbar">
        <div class="strategies-search">
          <Search class="strategies-search__icon" aria-hidden="true" />
          <Input
            v-model="query"
            size="sm"
            class="strategies-search__input"
            placeholder="搜索战法名、slug 或说明"
            aria-label="搜索战法"
            maxlength="64"
          />
          <Button access="read" v-if="query" variant="ghost" size="icon-xs" class="strategies-search__clear" aria-label="清空搜索" @click="query = ''">
            <X aria-hidden="true" />
          </Button>
        </div>
        <span class="strategies-count">
          {{ query ? `${filtered.length} / ${strategies.length}` : strategies.length }} 个战法
        </span>
      </div>

      <div v-if="loading && !strategies.length" class="strategies-skeleton" aria-hidden="true">
        <Skeleton v-for="n in 5" :key="n" class="h-11 w-full" />
      </div>

      <EmptyState
        v-else-if="!filtered.length"
        :icon="SlidersHorizontal"
        :description="query ? '当前筛选下无结果' : '还没有量化选股战法'"
        :reason="query ? '换个关键字，或清空搜索' : '新建一个公式战法，或粘贴别人导出的克隆包'"
        class="strategies-empty"
      >
        <Button access="read" v-if="query" variant="outline" size="sm" @click="query = ''">清空搜索</Button>
        <template v-else>
          <Button size="sm" @click="openWorkbench({ source: 'blank' })">新建战法</Button>
          <Button variant="outline" size="sm" @click="emit('importBundle')">
            <Upload aria-hidden="true" />
            导入克隆包
          </Button>
        </template>
      </EmptyState>

      <!-- 手机：卡片列表 -->
      <ul v-else-if="isMobile" class="strategy-cards">
        <li v-for="row in filtered" :key="row.slug">
          <article class="strategy-card" role="button" tabindex="0" :aria-label="`查看${displayName(row.name, row.slug)}配置`" @click="openDetail(row)" @keydown.enter.prevent="openDetail(row)">
            <div class="strategy-card__head">
              <span class="name-inline">
                <strong class="name-inline__name">{{ displayName(row.name, row.slug) }}</strong>
                <span class="revision">{{ row.slug }}</span>
              </span>
              <ChevronRight class="strategy-card__chevron" aria-hidden="true" />
            </div>
            <div class="strategy-card__meta">
              <UiBadge :variant="row.source_kind === 'formula' ? 'info' : 'secondary'">{{ sourceKindLabel(row.source_kind) }}{{ row.editable ? ' · 可改' : '' }}</UiBadge>
              <span>入场 {{ entryLabel(row.entry_timing) }} · {{ row.min_bars }} 根</span>
              <span class="font-mono">{{ revisionLabel(row.strategy_revision, row.source_kind) }}</span>
            </div>
            <div class="strategy-card__actions">
              <Button access="read" size="sm" variant="outline" class="flex-1" @click.stop="emit('openScreen', row.slug)">
                <Play aria-hidden="true" />
                选股
              </Button>
              <Button access="read" size="sm" variant="ghost" @click.stop="openDetail(row)">
                <Settings2 aria-hidden="true" />
                {{ visitor ? '详情' : '配置' }}
              </Button>
              <Button access="read" v-if="row.editable" size="sm" variant="ghost" @click.stop="openEditableStrategy(row.slug)">
                <Pencil aria-hidden="true" />
                公式
              </Button>
            </div>
          </article>
        </li>
      </ul>

      <!-- 桌面：表格 -->
      <Table v-else class="strategies-table">
        <TableHeader>
          <TableRow>
            <TableHead class="text-center">战法</TableHead>
            <TableHead class="w-[112px] text-center">来源</TableHead>
            <TableHead class="w-[170px] text-center">入场 · 最少 K 线</TableHead>
            <TableHead class="w-[150px] text-center">编码 · 修订</TableHead>
            <TableHead class="w-[150px] text-center">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in filtered"
            :key="row.slug"
            class="strategy-row"
            tabindex="0"
            :aria-label="`查看${displayName(row.name, row.slug)}配置`"
            @click="openDetail(row)"
            @keydown.enter.prevent="openDetail(row)"
          >
            <TableCell class="text-center">
              <span class="name-inline" :title="`${displayName(row.name, row.slug)} · ${row.slug}`">
                <strong class="name-inline__name">{{ displayName(row.name, row.slug) }}</strong>
                <span class="revision">{{ row.slug }}</span>
              </span>
            </TableCell>
            <TableCell class="text-center">
              <UiBadge :variant="row.source_kind === 'formula' ? 'info' : 'secondary'">{{ sourceKindLabel(row.source_kind) }}{{ row.editable ? ' · 可改' : '' }}</UiBadge>
            </TableCell>
            <TableCell class="text-center text-ink-2">{{ entryLabel(row.entry_timing) }} · {{ row.min_bars }} 根</TableCell>
            <TableCell class="text-center revision">{{ revisionLabel(row.strategy_revision, row.source_kind) }}</TableCell>
            <TableCell class="text-center" @click.stop>
              <div class="row-actions row-actions--center">
                <Button access="read" size="xs" variant="outline" @click="emit('openScreen', row.slug)">
                  <Play aria-hidden="true" />
                  选股
                </Button>
                <Button access="read" v-if="row.editable" size="xs" variant="ghost" @click="openEditableStrategy(row.slug)">
                  <Pencil aria-hidden="true" />
                  公式
                </Button>
                <Button access="read" size="xs" variant="ghost" @click="openDetail(row)">
                  <Settings2 aria-hidden="true" />
                  {{ visitor ? '详情' : '配置' }}
                </Button>
              </div>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </Card>

    <StrategyDetailDialog v-model="detailOpen" :strategy="detail" />
  </div>
</template>

<style scoped>
.strategies-panel {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

.strategies-card {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
}

.strategies-toolbar {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2) var(--gap-3);
  padding: var(--gap-2) var(--gap-3);
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface);
}

.strategies-search {
  position: relative;
  display: flex;
  flex: 0 1 320px;
  align-items: center;
  min-width: 200px;
}

.strategies-search__icon {
  position: absolute;
  left: 9px;
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
  pointer-events: none;
}

.strategies-search__input {
  padding-left: 28px;
  padding-right: 28px;
}

.strategies-search__clear {
  position: absolute;
  right: 3px;
}

.strategies-count {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

.strategies-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  padding: var(--gap-3);
}

.strategies-empty {
  min-height: 260px;
}

/* 表格：表头内容全部居中，行高 40px 一行展示 */
.strategies-table :deep(th) {
  height: var(--head-h);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-weight: 500;
  white-space: nowrap;
  text-align: center;
}

.strategies-table :deep(td) {
  height: 40px;
  font-size: var(--fs-ui);
  text-align: center;
  white-space: nowrap;
}

.strategies-table :deep(th:first-child),
.strategies-table :deep(td:first-child) {
  padding-left: var(--gap-4);
}

.strategies-table :deep(th:last-child),
.strategies-table :deep(td:last-child) {
  padding-right: var(--gap-3);
}

.strategy-row {
  cursor: pointer;
}

.strategy-row:focus-visible {
  outline: 2px solid var(--focus-ring, var(--seal));
  outline-offset: -2px;
}

/* 名称一行展示：名称 + 编码单行，超出省略 */
.name-inline {
  display: inline-flex;
  align-items: baseline;
  gap: var(--gap-2);
  min-width: 0;
  max-width: 100%;
}

.name-inline__name {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.revision {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  white-space: nowrap;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 2px;
}

.row-actions--center {
  justify-content: center;
}

/* 手机卡片 */
.strategy-cards {
  margin: 0;
  padding: 0;
  list-style: none;
}

.strategy-card {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  padding: var(--gap-3);
  border-top: 1px solid var(--border-subtle);
  cursor: pointer;
}

.strategy-card:focus-visible {
  outline: 2px solid var(--focus-ring, var(--seal));
  outline-offset: -2px;
}

.strategy-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
}

.strategy-card__chevron {
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  color: var(--text-tertiary);
}

.strategy-card__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px var(--gap-3);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.strategy-card__actions {
  display: flex;
  gap: var(--gap-2);
  padding-top: 2px;
}

.strategy-card__actions :deep(button) {
  min-height: 40px;
}
</style>
