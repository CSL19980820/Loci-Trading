<script setup lang="ts">
/** 候选池：筛选、分页与档案浏览；没有额外统计区。 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import {
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Layers,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  X,
} from '@lucide/vue'
import { toast } from 'vue-sonner'

import { batchDeleteCandidates, deleteCandidate } from '@/shared/api/palace'
import { getStrategies } from '@/shared/api/quant'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
import RecordDialog from '@/shared/components/dialogs/RecordDialog.vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import { Checkbox } from '@/shared/components/ui/checkbox'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/shared/components/ui/sheet'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import { decisionLabel } from '@/shared/lib/format'
import { useUserStore } from '@/shared/stores/user'
import { useBatchBrowseStore } from '@/shared/stores/batchBrowse'
import type { Candidate } from '@/shared/types/palace'
import type { StrategyInfo } from '@/shared/types/quant'

import PoolCandidateDialog from './components/PoolCandidateDialog.vue'
import PoolMobileView from './components/PoolMobileView.vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { useCandidatesQuery } from './composables/useCandidatesQuery'
import { sourceLabel, usePoolLabels } from './composables/poolLabels'
import { usePoolFilters } from './composables/usePoolFilters'

const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const batchStore = useBatchBrowseStore()
const fitDesktop = useMediaQuery('(min-width: 1024px) and (min-height: 600px)')
const isMobile = useMobileLayout()
const strategies = ref<StrategyInfo[]>([])
const error = ref('')
const detailOpen = ref(false)
const detail = ref<Candidate | null>(null)
const recordOpen = ref(false)
const selectedIds = ref<string[]>([])
const selectionMode = ref(false)
function toggleSelectionMode(): void { selectionMode.value = !selectionMode.value; selectedIds.value = [] }
const basicFormRef = ref<InstanceType<typeof BasicForm>>()
const basicTableRef = ref<InstanceType<typeof BasicTable>>()
/** 前端分页：后端一次返回筛选全量（limit 1000），本地按页切片展示 */
const page = ref(1)
const PAGE_SIZE = 20

const { filters, filterModel, filterSchemas, queryFilters } = usePoolFilters(strategies)
const { strategyLabel, poolLabel } = usePoolLabels(strategies)

/*
 * 手机端筛选：裁决做药片分段（最常切的那个），战法 / 日期进贴底 Sheet。
 * Sheet 里的表单只绑这两个字段：BasicForm 首次回写只带自己认识的字段，
 * 若共用整份 filterModel，会把裁决清成空串。
 */
const DECISION_TABS: PageTabItem[] = [
  { name: '', label: '全部' },
  { name: '精选', label: '精选' },
  { name: '观察', label: '观察' },
  { name: '落选', label: '落选' },
]
const decisionTab = computed({
  get: () => filters.decision,
  set: (next: string) => {
    filters.decision = next
    page.value = 1
  },
})
const moreOpen = ref(false)
const moreDraft = ref<Record<string, unknown>>({ strategy: '', dateRange: null })
watch(moreOpen, value => {
  if (value) moreDraft.value = { strategy: filters.strategy, dateRange: filters.dateRange ? [...filters.dateRange] : null }
})
const moreSchemas = computed(() => filterSchemas.value.filter((schema) => schema.field !== 'decision'))
const moreModel = computed({
  get: () => moreDraft.value,
  set: (value: Record<string, unknown>) => {
    moreDraft.value = value
  },
})
const moreCount = computed(() => Number(Boolean(filters.strategy)) + Number(Boolean(filters.dateRange)))

const {
  rows: cachedRows,
  isPending,
  error: queryError,
  refetch,
} = useCandidatesQuery(queryFilters)

const rows = cachedRows
/** 全量行（colada 缓存）→ 当前页切片；切页回顶由 BasicTable 内部分页器接管 */
const tableRows = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return rows.value.slice(start, start + PAGE_SIZE) as unknown as Record<string, unknown>[]
})
const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / PAGE_SIZE) || 1))
const pager = computed(() => ({
  pageSize: PAGE_SIZE,
  currentPage: page.value,
  total: rows.value.length,
  layout: 'total, prev, pager, next',
}))

const poolBatch = computed(() => {
  const seen = new Set<string>()
  const items = toBatchItems(
    rows.value.flatMap((row) => {
      if (seen.has(row.code)) return []
      seen.add(row.code)
      return [{ code: row.code, name: row.name }]
    }),
  )
  if (items.length < 2) return null
  return {
    source: '候选池',
    sourcePath: route.fullPath || '/pool',
    items,
  }
})
const busy = isPending

watch(queryError, (err) => {
  error.value = err ? toErrorMessage(err, '加载候选失败') : ''
})

const columns = ref<BasicTableColumn[]>([
  { type: 'selection', width: 40, fixed: 'left' },
  { prop: 'code', label: '标的', minWidth: 168, align: 'center', headerAlign: 'center', slotName: 'stock' },
  { prop: 'rule_version', label: '战法', minWidth: 168, align: 'center', headerAlign: 'center', slotName: 'strategy' },
  { prop: 'date', label: '选出日', width: 108, align: 'center', headerAlign: 'center', slotName: 'date' },
  { prop: 'decision', label: '裁决', width: 84, align: 'center', headerAlign: 'center', slotName: 'decision' },
  { prop: 'score', label: '评分', width: 72, align: 'center', headerAlign: 'center', slotName: 'score' },
  { prop: 'reason', label: '理由', minWidth: 180, align: 'center', headerAlign: 'center', slotName: 'reason' },
  { prop: 'actions', label: '', width: 44, align: 'center', headerAlign: 'center', slotName: 'actions' },
])

const visibleColumns = computed({
  get: () => userStore.canWrite ? columns.value : columns.value.filter((column) => column.type !== 'selection' && column.prop !== 'actions'),
  set: (next: BasicTableColumn[]) => { if (userStore.canWrite) columns.value = next },
})

function decisionVariant(decision: string): 'info' | 'warn' | 'secondary' {
  const label = decisionLabel(decision)
  if (label === '精选') return 'info'
  if (label === '观察') return 'warn'
  return 'secondary'
}

function fmtScore(value: unknown): string {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(1)
}

async function load(): Promise<void> {
  error.value = ''
  selectedIds.value = []
  basicTableRef.value?.clearSelection()
  try {
    await refetch()
  } catch (e: unknown) {
    error.value = toErrorMessage(e, '加载失败')
  }
}

function handleSubmit(): void {
  page.value = 1
  void load()
}

function handleReset(): void {
  basicFormRef.value?.resetForm()
  filters.strategy = ''
  filters.decision = ''
  filters.dateRange = null
  page.value = 1
  void nextTick(() => load())
}

function applyMore(): void {
  filterModel.value = { ...filterModel.value, strategy: moreDraft.value.strategy, dateRange: moreDraft.value.dateRange }
  moreOpen.value = false
  handleSubmit()
}

function resetMore(): void {
  moreOpen.value = false
  handleReset()
}

function onSelectionChange(selection: Record<string, unknown>[]): void {
  selectedIds.value = selection.map((row) => String(row.id ?? '')).filter(Boolean)
}

/** 手机卡片列表没有表格的勾选列：卡片左侧的复选框直接维护同一份 selectedIds */
function toggleSelected(id: string, next: boolean | 'indeterminate'): void {
  const set = new Set(selectedIds.value)
  if (next === true) set.add(id)
  else set.delete(id)
  selectedIds.value = [...set]
}

/** 翻页时清空跨页勾选：与管理后台一致，已选只表示当前页，避免批量删错范围 */
function onPageChange(next: number): void {
  page.value = Math.min(Math.max(1, next), pageCount.value)
  selectedIds.value = []
  basicTableRef.value?.clearSelection()
}

function openDetail(row: Record<string, unknown>): void {
  detail.value = row as unknown as Candidate
  detailOpen.value = true
}

function goArchive(): void {
  if (!detail.value) return
  detailOpen.value = false
  const seen = new Set<string>()
  const uniq: Candidate[] = []
  for (const row of rows.value) {
    if (seen.has(row.code)) continue
    seen.add(row.code)
    uniq.push(row)
  }
  if (uniq.length >= 2) {
    batchStore.openBatch({
      source: '候选池',
      sourcePath: route.fullPath || '/pool',
      focusCode: detail.value.code,
      items: toBatchItems(uniq.map((row) => ({ code: row.code, name: row.name }))),
    })
  }
  const date = String(detail.value.date || '').trim()
  void router.push({
    path: `/archive/${detail.value.code}`,
    query: /^\d{4}-\d{2}-\d{2}$/.test(date) ? { date } : undefined,
  })
}

function onRecorded(): void {
  void load()
}

async function confirmDelete(row: Candidate): Promise<void> {
  if (!userStore.canWrite) return
  if (!(await confirmDangerous(
    `确定删除 ${row.name}（${row.date}）这条候选记录？`,
    '删除候选',
    '删除',
  ))) return
  try {
    await deleteCandidate(row.id)
    toast.success('已删除')
    if (detail.value?.id === row.id) {
      detailOpen.value = false
      detail.value = null
    }
    await load()
  } catch (e: unknown) {
    toast.error(e instanceof Error ? e.message : '删除失败')
  }
}

async function confirmBatchDelete(): Promise<void> {
  if (!userStore.canWrite) return
  const ids = [...selectedIds.value]
  if (!ids.length) return
  if (!(await confirmDangerous(`确定删除选中的 ${ids.length} 条候选记录？`, '批量删除', '删除'))) return
  try {
    const result = await batchDeleteCandidates(ids)
    toast.success(`已删除 ${result.removed} 条`)
    if (detail.value && ids.includes(detail.value.id)) {
      detailOpen.value = false
      detail.value = null
    }
    await load()
  } catch (e: unknown) {
    toast.error(e instanceof Error ? e.message : '批量删除失败')
  }
}

watch(rows, () => {
  const alive = new Set(rows.value.map((r) => r.id))
  selectedIds.value = selectedIds.value.filter((id) => alive.has(id))
  // 删到只剩半页时别把用户留在空页上
  if (page.value > pageCount.value) page.value = pageCount.value
})

onMounted(async () => {
  try {
    strategies.value = await getStrategies()
  } catch {
    strategies.value = []
  }
  await load()
})
</script>

<template>
  <PoolMobileView v-if="isMobile" :rows="rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)" :page="page" :pages="pageCount" :total="rows.length" :decision="decisionTab" :filter-count="moreCount" :busy="!!busy" :error="error" :can-write="userStore.canWrite" :selection-mode="selectionMode" :selected-ids="selectedIds" :strategy-label="strategyLabel"
    @decision="value => decisionTab = value" @detail="row => openDetail(row as unknown as Record<string, unknown>)" @filter="moreOpen = true" @refresh="load" @record="recordOpen = true" @multi="toggleSelectionMode" @select="toggleSelected" @delete="confirmBatchDelete" @page="onPageChange" />
  <Sheet v-if="isMobile" v-model:open="moreOpen"><SheetContent side="right" class="pool-more-sheet"><SheetHeader><SheetTitle>筛选候选</SheetTitle><SheetDescription class="sr-only">选择战法与选出日期</SheetDescription></SheetHeader><BasicForm v-model="moreModel" :schemas="moreSchemas" :columns="1" label-position="top" class="pool-more-sheet__form" /><SheetFooter class="pool-more-sheet__foot"><Button access="read" variant="outline" @click="moreOpen = false">取消</Button><Button access="read" @click="applyMore">应用筛选</Button><Button access="read" variant="ghost" @click="resetMore">重置全部</Button></SheetFooter></SheetContent></Sheet>
  <div v-else class="page-fill pool-page">
    <h1 class="sr-only">候选池</h1>

    <div class="page-scroll pool-body">
      <Alert v-if="error" variant="destructive" class="shrink-0">
        <CircleAlert aria-hidden="true" />
        <div class="flex w-full min-w-0 items-start justify-between gap-2">
          <AlertTitle class="line-clamp-none min-w-0">{{ error }}</AlertTitle>
          <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="error = ''">
            <X class="size-3.5" aria-hidden="true" />
          </Button>
        </div>
      </Alert>

      <PageToolbar dense class="pool-filters">
        <!-- 手机：裁决药片分段 + 「筛选」（战法 / 日期进贴底 Sheet） -->
        <template v-if="isMobile">
          <PageTabs
            v-model="decisionTab"
            :items="DECISION_TABS"
            variant="pill"
            :sticky="false"
            aria-label="按裁决筛选"
            class="pool-decision-tabs"
          />
          <Sheet v-model:open="moreOpen">
            <SheetTrigger as-child>
              <Button access="read" variant="outline" size="sm" class="pool-more-btn" aria-label="更多筛选">
                <SlidersHorizontal aria-hidden="true" />
                筛选
                <span v-if="moreCount" class="pool-more-btn__count">{{ moreCount }}</span>
              </Button>
            </SheetTrigger>
            <SheetContent side="right" class="pool-more-sheet">
              <SheetHeader class="text-left">
                <SheetTitle>筛选候选</SheetTitle>
                <SheetDescription>按战法与选出日区间过滤；应用后立即刷新</SheetDescription>
              </SheetHeader>
              <BasicForm
                v-model="moreModel"
                :schemas="moreSchemas"
                :columns="1"
                label-position="top"
                size="default"
                class="pool-more-sheet__form"
              />
              <SheetFooter class="pool-more-sheet__foot">
                <Button access="read" variant="ghost" size="lg" @click="resetMore">重置</Button>
                <Button access="read" size="lg" @click="applyMore">应用</Button>
              </SheetFooter>
            </SheetContent>
          </Sheet>
        </template>

        <!-- 桌面：三项一行 -->
        <BasicForm
          v-else
          ref="basicFormRef"
          v-model="filterModel"
          :schemas="filterSchemas"
          :columns="3"
          label-position="left"
          label-width="3.5em"
          size="default"
          class="pool-filters__form"
        />
        <template #actions>
          <template v-if="!isMobile">
          <Button access="read" :disabled="!!busy" @click="handleSubmit">
            <LoaderCircle v-if="busy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
            <Search v-else aria-hidden="true" />
            查询
          </Button>
          <Button access="read" variant="ghost" :disabled="!!busy" @click="handleReset">重置</Button>
          </template>

        <Button v-if="isMobile && userStore.canWrite" access="read" variant="ghost" size="sm" @click="toggleSelectionMode">{{ selectionMode ? '取消多选' : '多选' }}</Button>
        <Button
          v-if="userStore.canWrite && selectedIds.length"
          variant="soft-destructive"
          size="sm"
          :disabled="!!busy"
          @click="confirmBatchDelete"
        >
          <Trash2 aria-hidden="true" />
          删除已选 {{ selectedIds.length }}
        </Button>
        <Button access="read" variant="outline" size="sm" :disabled="!!busy" aria-label="刷新候选" @click="load">
          <LoaderCircle v-if="busy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <RefreshCw v-else aria-hidden="true" />
          刷新
        </Button>
        <Button v-if="userStore.canWrite" size="sm" @click="recordOpen = true">
          <Plus aria-hidden="true" />
          记一条候选
        </Button>
              </template>
      </PageToolbar>

      <div class="pool-grid">
        <Card class="pool-records">


          <!-- 手机：卡片列表（名称 + 评分大数 + 一行次要信息，整卡可点） -->
          <template v-if="isMobile">
            <ul v-if="tableRows.length" class="pool-cards" aria-label="候选记录">
              <li
                v-for="row in tableRows"
                :key="String(row.id)"
                class="pool-card"
                tabindex="0"
                role="button"
                :aria-label="`查看 ${row.name} ${row.date} 候选详情`"
                @click="openDetail(row)"
                @keydown.enter.self.prevent="openDetail(row)"
                @keydown.space.self.prevent="openDetail(row)"
              >
                <Checkbox
                  v-if="userStore.canWrite && selectionMode"
                  class="pool-card__check"
                  :model-value="selectedIds.includes(String(row.id))"
                  :aria-label="`选择 ${row.name}`"
                  @update:model-value="toggleSelected(String(row.id), $event)"
                  @click.stop
                />
                <div class="pool-card__main">
                  <div class="pool-card__name">
                    <strong>{{ row.name }}</strong>
                    <span class="pool-code">{{ row.code }}</span>
                  </div>
                  <div class="pool-card__sub">
                    <UiBadge :variant="decisionVariant(String(row.decision ?? ''))">{{ decisionLabel(String(row.decision ?? '')) }}</UiBadge>
                    <span class="pool-num">{{ row.date }}</span>
                    <span class="pool-clip" :title="strategyLabel(String(row.rule_version ?? ''))">{{ strategyLabel(String(row.rule_version ?? '')) }}</span>
                  </div>
                </div>
                <div class="pool-card__num">
                  <span class="pool-card__big">{{ fmtScore(row.score) }}</span>
                  <span class="pool-card__small">评分</span>
                </div>
              </li>
            </ul>
            <EmptyState
              v-else
              class="pool-empty"
              description="暂无候选"
              reason="当前筛选下没有记录；跑一次选股，或手动写入一条"
              :icon="Layers"
            >
              <Button v-if="userStore.canWrite" size="sm" @click="recordOpen = true">记一条候选</Button>
            </EmptyState>
            <div v-if="rows.length > PAGE_SIZE" class="pool-pager">
              <Button access="read" variant="outline" size="sm" :disabled="page <= 1" aria-label="上一页" @click="onPageChange(page - 1)">
                <ChevronLeft aria-hidden="true" />
              </Button>
              <span class="pool-pager__text">第 {{ page }} / {{ pageCount }} 页 · 共 {{ rows.length }} 条</span>
              <Button access="read"
                variant="outline"
                size="sm"
                :disabled="page >= pageCount"
                aria-label="下一页"
                @click="onPageChange(page + 1)"
              >
                <ChevronRight aria-hidden="true" />
              </Button>
            </div>
          </template>

          <!-- 桌面：密度表（勾选 / 标的两行 / 选出日 / 战法 / 裁决 / 评分 / 理由 / 删） -->
          <BasicTable
            v-else
            ref="basicTableRef"
            class="pool-stock-table"
            :height="fitDesktop ? '100%' : undefined"
            v-model:columns="visibleColumns"
            :data-source="tableRows"
            :pagination="pager"
            :loading="!!busy"
            row-key="id"
            empty-text="暂无候选"
            empty-reason="当前筛选下没有记录；跑一次选股，或手动写入一条"
            @row-click="openDetail"
            @selection-change="onSelectionChange"
            @current-change="onPageChange"
          >
            <template #stock="{ row }">
              <span class="pool-cell-inline" :title="`${row.name} ${row.code}`">
                <StockLink
                  :code="String(row.code)"
                  :name="String(row.name ?? '')"
                  :date="String(row.date ?? '')"
                  :batch="poolBatch"
                  :show-code="false"
                  stop
                  class="pool-name"
                />
                <span class="pool-code">{{ row.code }}</span>
              </span>
            </template>
            <template #strategy="{ row }">
              <span class="pool-cell-inline pool-strategy" :title="strategyLabel(String(row.rule_version ?? ''))">{{ strategyLabel(String(row.rule_version ?? '')) }}</span>
            </template>
            <template #date="{ row }">
              <span class="pool-num">{{ row.date }}</span>
            </template>
            <template #decision="{ row }">
              <UiBadge :variant="decisionVariant(String(row.decision ?? ''))">
                {{ decisionLabel(String(row.decision ?? '')) }}
              </UiBadge>
            </template>
            <template #score="{ row }">
              <span class="pool-num pool-score">{{ fmtScore(row.score) }}</span>
            </template>
            <template #reason="{ row }">
              <Tooltip :disabled="!row.reason" :delay-duration="150">
                <TooltipTrigger as-child>
                  <span class="pool-reason-text" tabindex="0">{{ String(row.reason || '—') }}</span>
                </TooltipTrigger>
                <TooltipContent class="pool-reason-popper">{{ String(row.reason || '—') }}</TooltipContent>
              </Tooltip>
            </template>
            <template #actions="{ row }">
              <Button
                variant="ghost"
                size="icon-xs"
                class="pool-row-delete"
                :aria-label="`删除 ${row.name} 这条候选`"
                @click.stop="confirmDelete(row as unknown as Candidate)"
              >
                <Trash2 aria-hidden="true" />
              </Button>
            </template>
            <template #empty>
              <EmptyState
                class="pool-empty"
                description="暂无候选"
                reason="当前筛选下没有记录；跑一次选股，或手动写入一条"
                :icon="Layers"
              >
                <Button v-if="userStore.canWrite" size="sm" @click="recordOpen = true">记一条候选</Button>
              </EmptyState>
            </template>
          </BasicTable>
        </Card>


      </div>
    </div>
  </div>

  <PoolCandidateDialog
    v-model="detailOpen"
    :candidate="detail"
    :strategy-text="detail ? strategyLabel(detail.rule_version) : '—'"
    :pool-text="poolLabel(detail?.pool_id)"
    :source-text="sourceLabel(detail?.source)"
    :batch="poolBatch"
    @delete="confirmDelete"
    @archive="goArchive"
  />

  <RecordDialog v-if="userStore.canWrite" v-model="recordOpen" kind="candidate" @saved="onRecorded" />
</template>

<style scoped>
.pool-body {
  padding-top: 4px;
  gap: var(--gap-4);
}

/* .page-scroll 是可滚的 flex 列：子项默认会被压扁而不是溢出滚动，这里全部定为不收缩 */
.pool-body > * {
  flex: 0 0 auto;
}

.pool-filters__form {
  flex: 1 1 auto;
  min-width: 0;
}

/* 手机：裁决分段 + 筛选按钮同一行 */
.pool-decision-tabs {
  flex: 1 1 auto;
  min-width: 0;
}

.pool-decision-tabs :deep(.page-tabs__list) {
  width: 100%;
}

.pool-decision-tabs :deep(.page-tabs__item) {
  flex: 1 1 0;
  justify-content: center;
  height: 32px;
}

.pool-more-btn {
  flex-shrink: 0;
}

.pool-more-btn__count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-pill);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-weight: 600;
}

.pool-more-sheet__form {
  padding: 0 var(--gap-4);
}

.pool-more-sheet__foot {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: var(--gap-2);
  margin-top: auto;
  padding: var(--gap-3) var(--gap-4) 0;
}

/* bento：记录（弹性）| 侧栏 300px；≤1280 侧栏落到下方两列 */
.pool-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  gap: var(--gap-4);
  min-width: 0;
}

.pool-records {
  padding:0; gap:0;
  min-width: 0;
  overflow: hidden;
}

.pool-records :deep(.basic-table) {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.pool-records__selected {
  color: var(--seal-ink);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* 表格里的文字工具类 */
.pool-num {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.pool-dim {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.pool-clip {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

/* 表格单行：标的 / 战法一行展示，超出省略 */
.pool-cell-inline {
  display: inline-flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  min-width: 0;
  max-width: 100%;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pool-strategy {
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pool-name {
  color: var(--text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pool-name :deep(.stock-link) {
  color: inherit;
}

.pool-code {
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  color: var(--text-tertiary);
  letter-spacing: 0.02em;
}

.pool-score {
  font-weight: 600;
  color: var(--text-primary);
}

/* 理由单行截断：全文进 tooltip 气泡（气泡限宽在下面全局层） */
.pool-reason-text {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
  color: var(--text-secondary);
}

.pool-row-delete {
  color: var(--text-tertiary);
  opacity: 0;
  transition:
    opacity var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease);
}

.pool-row-delete:hover {
  color: var(--stamp);
}

:deep(.pool-stock-table tbody tr:hover) .pool-row-delete,
.pool-row-delete:focus-visible {
  opacity: 1;
}

@media (hover: none) {
  .pool-row-delete {
    opacity: 1;
  }
}

/* 点行开详情：前缀限本页，裸 deep 会命中全站所有表 */
:deep(.pool-stock-table tbody tr) {
  cursor: pointer;
}

.pool-empty {
  min-height: 220px;
}

/* ─── 手机：卡片列表 ─── */
.pool-cards {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.pool-card {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap:8px;
  padding:10px 12px;
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.pool-card:not(:has(.pool-card__check)) { grid-template-columns: minmax(0, 1fr) auto; }

.pool-card:last-child {
  border-bottom: 0;
}

.pool-card:active {
  background: var(--surface-hover);
}

.pool-card:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

.pool-card__check {
  width:16px;
  height:16px;
}

.pool-card__main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.pool-card__name {
  display:flex; flex-wrap:wrap;
  align-items:baseline;
  gap:4px 6px;
  min-width: 0;
  color: var(--text-primary);
  font-size: var(--fs-body);
}

.pool-card__sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-2);
  min-width: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.pool-card__num {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
}

.pool-card__big {
  font-family: var(--mono);
  font-size:18px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.1;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.pool-card__small {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.pool-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  border-top: 1px solid var(--border-subtle);
}

.pool-pager__text {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 1280px) {
  .pool-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 640px) {

  .pool-body { gap:5px; padding-bottom:8px; }
  .pool-decision-tabs { margin-bottom:0; }
  .pool-card__name { font-size:14px; }
  .pool-card__sub { gap:4px 6px; flex-wrap:nowrap; font-size:11px; }
  .pool-card__sub>.pool-num { flex:none; font-size:10px; }
  .pool-card__sub>.pool-clip { flex:1; min-width:0; }
  .pool-card__num { min-width:42px; }
  .pool-filters :deep(.page-toolbar__filters) { flex-basis:100%; }
  .pool-filters :deep(.page-toolbar__actions) { gap:5px; width:100%; justify-content:flex-end; }
}
@media (min-width: 1024px) and (min-height: 600px) {
  .pool-body { overflow: hidden; gap: 10px; padding-block: 6px 10px; }
  .pool-body > .pool-grid { flex: 1 1 0%; min-height: 0; align-items: stretch; grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .pool-records { display: flex; flex-direction: column; min-height: 0; gap: 0; }
  .pool-records > :deep([data-slot=card-header]) { flex: none; padding-block: 10px; }
  .pool-records :deep(.basic-table--fill) { flex: 1 1 0%; height: 0; }
  .pool-bar { padding-block: 6px; }
  .pool-day { min-height: 30px; }
}
</style>

<style>
/* 理由全文气泡经 teleport 挂到 body，scoped 够不着；限宽换行 */
.pool-reason-popper {
  max-width: 26rem;
  white-space: normal;
  word-break: break-word;
}
</style>
