<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
/**
 * 行情台（路由 `/data`）：全市场日线列表，盘中叠实时价；点一行进个股档案。
 *
 * 版面：
 *   页头（标题 + 实时状态徽标 / 动作：实时开关 · 刷新）
 *   筛选行（关键词 / 行业 / 换手 / 排序 + 查询 · 重置）
 *   列表卡：桌面密度表（名称两行 · 行业 · 最新 · 涨跌幅 chip · 涨跌 · 换手 · 成交额 · 区间 · 来源）
 *    手机卡片列表（名称 + 最新价大数 + 涨跌 chip + 一行次要信息）
 *
 * 原来这里还有一排 KPI 卡（证券数 / 日线行数 / 最新日线 / 本页涨跌）和列表卡头
 * （全市场 · 第 N 页 · 快照时间）——两处都在占版面，已删；分页与总数在表底分页器上。
 */
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMediaQuery } from '@vueuse/core'
import {
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Database,
  RotateCw,
  Search,
  SlidersHorizontal,
  TriangleAlert,
  X,
} from '@lucide/vue'

import { getMarketCoverage, getMarketIndustries } from '@/shared/api/quant'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import BasicForm, { type BasicFormSchema } from '@/shared/components/ui/BasicForm.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Input } from '@/shared/components/ui/input'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
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
import { Switch } from '@/shared/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import type { BoardRow, MarketCoverage } from '@/shared/types/quant'

import {
  chgClass,
  fmtAmount,
  fmtChange,
  fmtPct,
  fmtPrice,
  fmtTurnover,
  formatCount,
} from './composables/dataQueryFormat'
import { useDataQueryMarket, type BoardSort } from './composables/useDataQueryMarket'

const route = useRoute()
const router = useRouter()
const isMobile = useMediaQuery('(max-width: 640px)')

const busy = ref(false)
const error = ref('')
const liveError = ref('')
const liveDetailOpen = ref(false)
const coverage = ref<MarketCoverage | null>(null)
const coverageLoaded = ref(false)
const basicFormRef = ref<InstanceType<typeof BasicForm>>()
const filtersReady = ref(false)
const industryOptions = ref<{ label: string; value: string }[]>([])

const filters = reactive({
  keyword: '',
  industry: '',
  turnoverMin: null as number | null,
  sort: 'code' as BoardSort,
})

const {
  marketQ,
  liveOn,
  industryFilter,
  turnoverMin,
  boardSort,
  liveEnriching,
  page,
  pageSize,
  boardRows,
  boardTotal,
  loadBoard,
  openDetail,
} = useDataQueryMarket({ route, router, busy, error, liveError })

const filterModel = computed({
  get: () =>
    ({
      keyword: filters.keyword,
      industry: filters.industry,
      turnoverMin: filters.turnoverMin,
      sort: filters.sort,
    }) as Record<string, unknown>,
  set: (value: Record<string, unknown>) => {
    filters.keyword = String(value.keyword ?? '')
    filters.industry = String(value.industry ?? '')
    const rawMin = value.turnoverMin
    filters.turnoverMin =
      rawMin === '' || rawMin == null || Number.isNaN(Number(rawMin)) ? null : Number(rawMin)
    filters.sort = (String(value.sort || 'code') as BoardSort) || 'code'
    syncFiltersToQuery()
  },
})

const filterSchemas = computed<BasicFormSchema[]>(() => [
  {
    field: 'keyword',
    label: '关键词',
    component: 'input',
    componentProps: { placeholder: '代码 / 名称', clearable: true },
  },
  {
    field: 'industry',
    label: '行业',
    component: 'select',
    componentProps: {
      clearable: true,
      filterable: true,
      allowCreate: true,
      defaultFirstOption: true,
      placeholder: industryOptions.value.length ? '半导体 / 电力…' : '先同步证券列表',
      options: industryOptions.value,
    },
  },
  {
    field: 'turnoverMin',
    label: '换手≥%',
    component: 'input-number',
    componentProps: {
      min: 0,
      max: 100,
      step: 0.5,
      controlsPosition: 'right',
      placeholder: '不限',
    },
  },
  {
    field: 'sort',
    label: '排序',
    component: 'select',
    componentProps: {
      options: [
        { label: '代码', value: 'code' },
        { label: '换手率高→低', value: 'turnover_desc' },
        { label: '换手率低→高', value: 'turnover_asc' },
      ],
    },
  },
])

/*
 * 手机端：一行「关键词 + 筛选」，其余三项进贴底 Sheet。
 * Sheet 里的表单只绑这三个字段：BasicForm 首次回写只带自己认识的字段，
 * 若共用整份 filterModel，会把关键词清成空串。
 */
const moreOpen = ref(false)
const moreSchemas = computed(() => filterSchemas.value.filter((schema) => schema.field !== 'keyword'))
const moreModel = computed({
  get: () =>
    ({
      industry: filters.industry,
      turnoverMin: filters.turnoverMin,
      sort: filters.sort,
    }) as Record<string, unknown>,
  set: (value: Record<string, unknown>) => {
    filters.industry = String(value.industry ?? '')
    const rawMin = value.turnoverMin
    filters.turnoverMin =
      rawMin === '' || rawMin == null || Number.isNaN(Number(rawMin)) ? null : Number(rawMin)
    filters.sort = (String(value.sort || 'code') as BoardSort) || 'code'
    syncFiltersToQuery()
  },
})
const moreCount = computed(
  () => Number(Boolean(filters.industry)) + Number(filters.turnoverMin != null) + Number(filters.sort !== 'code'),
)

function applyMore(): void {
  moreOpen.value = false
  handleSubmit()
}

function resetMore(): void {
  moreOpen.value = false
  handleReset()
}

const columns = ref<BasicTableColumn[]>([
  { prop: 'name', label: '名称 · 编码', minWidth: 168, align: 'center', headerAlign: 'center', slotName: 'name' },
  {
    prop: 'industry',
    label: '行业',
    minWidth: 100,
    align: 'center',
    headerAlign: 'center',
    showOverflowTooltip: true,
    formatter: (row) => String(row.industry || '—'),
  },
  { prop: 'price', label: '最新', width: 96, align: 'center', headerAlign: 'center', slotName: 'price' },
  { prop: 'pct', label: '涨跌幅', width: 104, align: 'center', headerAlign: 'center', slotName: 'pct' },
  { prop: 'change', label: '涨跌', width: 84, align: 'center', headerAlign: 'center', slotName: 'change' },
  {
    prop: 'turnover',
    label: '换手率',
    width: 92,
    align: 'center',
    headerAlign: 'center',
    slotName: 'turnover',
  },
  {
    prop: 'amount',
    label: '成交额',
    width: 104,
    align: 'center',
    headerAlign: 'center',
    slotName: 'amount',
  },
  { prop: 'high', label: '日内区间', width: 150, align: 'center', headerAlign: 'center', slotName: 'range' },
  { prop: 'ok', label: '来源', width: 120, align: 'center', headerAlign: 'center', slotName: 'source' },
])

const tableRows = computed(() => boardRows.value as unknown as Record<string, unknown>[])
const batch = computed(() => ({
  source: '行情台',
  sourcePath: route.fullPath || '/data',
  items: toBatchItems(
    boardRows.value.map((row) => ({
      code: row.code,
      name: row.name,
      pct: row.pct ?? row.local_pct ?? null,
    })),
  ),
}))
const hasMarket = computed(() => (coverage.value?.rows ?? 0) > 0)
/** 是否挂了筛选条件：空表时区分“没数据”与“筛得太狠” */
const hasFilter = computed(
  () => Boolean(filters.keyword.trim() || filters.industry || filters.turnoverMin != null),
)

const pageCount = computed(() => Math.max(1, Math.ceil(boardTotal.value / pageSize.value) || 1))

const liveCount = computed(() => boardRows.value.filter((row) => row.ok).length)

const liveStatus = computed(() => {
  if (!liveOn.value) return { label: '实时关', variant: 'secondary' as const }
  if (liveError.value) return { label: '实时降级', variant: 'warn' as const }
  if (liveEnriching.value) return { label: '刷新中', variant: 'info' as const }
  if (liveCount.value) return { label: '实时', variant: 'ok' as const }
  return { label: '实时待取', variant: 'secondary' as const }
})

function syncFiltersToQuery(): void {
  marketQ.value = filters.keyword.trim()
  industryFilter.value = filters.industry
  turnoverMin.value = filters.turnoverMin
  boardSort.value = filters.sort
}

async function loadCoverage(): Promise<void> {
  try {
    coverage.value = await getMarketCoverage()
  } catch (caught: unknown) {
    error.value = (caught as Error).message || '读覆盖失败'
  } finally {
    coverageLoaded.value = true
  }
}

async function loadIndustries(): Promise<void> {
  try {
    const res = await getMarketIndustries()
    industryOptions.value = (res.items ?? []).map((name) => ({ label: name, value: name }))
  } catch {
    industryOptions.value = []
  }
}

function handleSubmit(): void {
  syncFiltersToQuery()
  page.value = 1
  void loadBoard()
}

function handleReset(): void {
  basicFormRef.value?.resetForm()
  void nextTick(() => {
    filters.keyword = ''
    filters.industry = ''
    filters.turnoverMin = null
    filters.sort = 'code'
    syncFiltersToQuery()
    liveOn.value = true
    page.value = 1
    void loadBoard()
  })
}

function onPageChange(next: number): void {
  page.value = Math.min(Math.max(1, next), pageCount.value)
  void loadBoard()
}

function onSizeChange(size: number): void {
  pageSize.value = size
  page.value = 1
  void loadBoard()
}

function onRowClick(row: Record<string, unknown>): void {
  void openDetail(row as unknown as BoardRow)
}

function goBootstrapHint(): void {
  void router.push({ path: '/ops', query: { tab: 'system' }, hash: '#sys-sync' })
}

function rangeText(row: Record<string, unknown>): string {
  const low = fmtPrice(row.low as number | null)
  const high = fmtPrice(row.high as number | null)
  if (low === '—' && high === '—') return '—'
  return `${low} – ${high}`
}

function pctOf(row: Record<string, unknown>): number | null {
  const pct = (row.pct ?? row.local_pct) as number | null | undefined
  return pct == null ? null : Number(pct)
}

watch(
  filters,
  () => {
    if (!filtersReady.value) return
    syncFiltersToQuery()
  },
  { deep: true },
)

onMounted(async () => {
  liveOn.value = true
  filters.keyword = marketQ.value
  filters.industry = industryFilter.value
  filters.turnoverMin = turnoverMin.value
  filters.sort = boardSort.value
  void nextTick(() => {
    filtersReady.value = true
  })
  const code = String(route.query.code || '').trim()
  if (code) {
    await router.replace({ path: `/archive/${code}`, query: { view: 'quote' } })
    return
  }
  void loadIndustries()
  await Promise.all([loadCoverage(), loadBoard()])
  // loadBoard 在 live 闸门允许时会自行 startRefresh；此处勿再调，以免 stopRefresh 作废刚发起的叠价
})
</script>

<template>
  <div class="page-fill dq-page">
    <PageHeader title="行情" seamless>
      <template #title>
        <span class="dq-title">
          行情
          <UiBadge :variant="liveStatus.variant" dot class="dq-title__badge">{{ liveStatus.label }}</UiBadge>
        </span>
      </template>
      <template #actions>
        <Tooltip>
          <TooltipTrigger as-child>
            <Label class="dq-live">
              <Switch v-model="liveOn" aria-label="盘中叠实时价" />
              <span>实时</span>
            </Label>
          </TooltipTrigger>
          <TooltipContent side="bottom">盘中每 12 秒把当前页叠一次实时价；非交易时段自动停</TooltipContent>
        </Tooltip>
        <Button access="read" size="sm" :disabled="busy" @click="loadBoard">
          <RotateCw class="size-4" :class="busy && 'animate-spin motion-reduce:animate-none'" aria-hidden="true" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <div class="page-scroll dq-body">
      <Alert v-if="error" variant="destructive" class="shrink-0">
        <CircleAlert aria-hidden="true" />
        <div class="flex w-full min-w-0 items-start justify-between gap-2">
          <AlertTitle class="line-clamp-none min-w-0">{{ error }}</AlertTitle>
          <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="error = ''">
            <X class="size-3.5" aria-hidden="true" />
          </Button>
        </div>
      </Alert>
      <!-- 实时行情降级：标题一行，原文进可展开详情（tooltip 触屏不可达） -->
      <Alert v-if="liveError" class="text-warn shrink-0">
        <TriangleAlert aria-hidden="true" />
        <div class="flex w-full min-w-0 flex-wrap items-center justify-between gap-2">
          <AlertTitle class="line-clamp-none min-w-0">实时行情不可用，改显日线</AlertTitle>
          <div class="flex shrink-0 items-center gap-1">
            <Button access="read"
              variant="link"
              size="xs"
              :aria-expanded="liveDetailOpen"
              aria-controls="market-live-error"
              @click="liveDetailOpen = !liveDetailOpen"
            >
              {{ liveDetailOpen ? '收起原文' : '看原文' }}
            </Button>
            <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" @click="liveError = ''">
              <X class="size-3.5" aria-hidden="true" />
            </Button>
          </div>
        </div>
        <p
          v-if="liveDetailOpen"
          id="market-live-error"
          class="text-aux text-mist col-span-full m-0 max-h-32 overflow-auto break-words leading-snug"
        >
          {{ liveError }}
        </p>
      </Alert>

      <PageToolbar dense class="dq-filters">
        <!-- 手机：一行关键词 + 「筛选」（其余进贴底 Sheet） -->
        <template v-if="isMobile">
          <div class="dq-search">
            <Search class="dq-search__icon" aria-hidden="true" />
            <Input
              v-model="filters.keyword"
              class="dq-search__input"
              placeholder="代码 / 名称"
              aria-label="关键词"
              inputmode="search"
              @keyup.enter="handleSubmit"
            />
          </div>
          <Sheet v-model:open="moreOpen">
            <SheetTrigger as-child>
              <Button access="read" variant="outline" size="lg" class="dq-more-btn" aria-label="更多筛选">
                <SlidersHorizontal aria-hidden="true" />
                筛选
                <span v-if="moreCount" class="dq-more-btn__count">{{ moreCount }}</span>
              </Button>
            </SheetTrigger>
            <SheetContent side="right" class="dq-more-sheet">
              <SheetHeader class="text-left">
                <SheetTitle>筛选</SheetTitle>
                <SheetDescription>行业、换手与排序；应用后立即刷新列表</SheetDescription>
              </SheetHeader>
              <BasicForm
                v-model="moreModel"
                :schemas="moreSchemas"
                :columns="1"
                label-position="top"
                size="default"
                class="dq-more-sheet__form"
              />
              <SheetFooter class="dq-more-sheet__foot">
                <Button access="read" variant="ghost" size="lg" @click="resetMore">重置</Button>
                <Button access="read" size="lg" @click="applyMore">应用</Button>
              </SheetFooter>
            </SheetContent>
          </Sheet>
        </template>

        <!-- 桌面：四项一行 -->
        <BasicForm
          v-else
          ref="basicFormRef"
          v-model="filterModel"
          :schemas="filterSchemas"
          :columns="4"
          label-position="left"
          label-width="4em"
          size="default"
          class="dq-filters__form"
        />
        <template v-if="!isMobile" #actions>
          <Button access="read" :disabled="busy" @click="handleSubmit">
            <Search class="size-4" aria-hidden="true" />
            查询
          </Button>
          <Button access="read" variant="ghost" :disabled="busy" @click="handleReset">重置</Button>
        </template>
      </PageToolbar>

      <EmptyState
        v-if="coverageLoaded && !hasMarket"
        class="dq-empty-market"
        description="还没有历史日 K"
        reason="同步行情后即可查询"
        :icon="Database"
      >
        <Button @click="goBootstrapHint">去同步行情</Button>
      </EmptyState>

      <Card v-else class="dq-board">
        <PageBusy overlay :busy="busy" />

        <!-- 手机：卡片列表 -->
        <template v-if="isMobile">
          <ul v-if="tableRows.length" class="dq-cards" aria-label="全市场列表">
            <li
              v-for="row in tableRows"
              :key="String(row.code)"
              class="dq-card"
              tabindex="0"
              role="button"
              :aria-label="`查看 ${row.name} 档案`"
              @click="onRowClick(row)"
              @keydown.enter.prevent="onRowClick(row)"
            >
              <div class="dq-card__main">
                <div class="dq-card__name">
                  <strong>{{ row.name }}</strong>
                  <span class="dq-code">{{ row.code }}</span>
                </div>
                <div class="dq-card__sub">
                  <span class="dq-clip">{{ row.industry || '—' }}</span>
                  <span>换手 <span class="dq-num">{{ fmtTurnover(row.turnover as number | null) }}</span></span>
                  <span>额 <span class="dq-num">{{ fmtAmount(row.amount as number | null) }}</span></span>
                </div>
              </div>
              <div class="dq-card__num">
                <span class="dq-card__big" :class="chgClass(pctOf(row))">{{ fmtPrice((row.price ?? row.local_close) as number | null) }}</span>
                <span class="dq-chip" :class="chgClass(pctOf(row))">{{ fmtPct(pctOf(row)) }}</span>
              </div>
            </li>
          </ul>
          <EmptyState
            v-else-if="!busy"
            class="dq-empty"
            :description="hasFilter ? '没有匹配的证券' : '暂无证券'"
            reason="调整关键词或重置筛选"
            :icon="Search"
          >
            <Button access="read" size="sm" variant="outline" @click="handleReset">重置筛选</Button>
          </EmptyState>
          <div v-if="boardTotal > pageSize" class="dq-pager">
            <Button access="read" variant="outline" size="sm" :disabled="page <= 1 || busy" aria-label="上一页" @click="onPageChange(page - 1)">
              <ChevronLeft aria-hidden="true" />
            </Button>
            <span class="dq-pager__text">第 {{ page }} / {{ pageCount }} 页 · 共 {{ formatCount(boardTotal) }} 只</span>
            <Button access="read"
              variant="outline"
              size="sm"
              :disabled="page >= pageCount || busy"
              aria-label="下一页"
              @click="onPageChange(page + 1)"
            >
              <ChevronRight aria-hidden="true" />
            </Button>
          </div>
        </template>

        <!-- 桌面：密度表 -->
        <BasicTable
          v-else
          v-model:columns="columns"
          class="board-table"
          :data-source="tableRows"
          :pagination="{
            currentPage: page,
            pageSize,
            total: boardTotal,
            pageSizes: [30, 50, 100],
            layout: 'total, sizes, prev, pager, next',
          }"
          :loading="busy"
          row-key="code"
          :empty-text="hasFilter ? '没有匹配的证券' : '暂无证券'"
          empty-reason="调整关键词或重置筛选"
          @row-click="onRowClick"
          @current-change="onPageChange"
          @size-change="onSizeChange"
        >
          <template #name="{ row }">
            <span class="dq-cell-inline" :title="`${row.name} ${row.code}`">
              <StockLink
                :code="String(row.code ?? '')"
                :name="String(row.name ?? '')"
                :batch="batch"
                :stop="true"
                :show-code="false"
                class="dq-name"
              />
              <span class="dq-code">{{ row.code }}</span>
            </span>
          </template>
          <template #price="{ row }">
            <span class="dq-num dq-price" :class="chgClass(pctOf(row))">
              {{ fmtPrice((row.price ?? row.local_close) as number | null) }}
            </span>
          </template>
          <template #pct="{ row }">
            <span class="dq-chip" :class="chgClass(pctOf(row))">{{ fmtPct(pctOf(row)) }}</span>
          </template>
          <template #change="{ row }">
            <span class="dq-num" :class="chgClass(pctOf(row))">
              {{ fmtChange((row.change ?? row.local_change) as number | null) }}
            </span>
          </template>
          <template #turnover="{ row }">
            <span class="dq-num">{{ fmtTurnover(row.turnover as number | null) }}</span>
          </template>
          <template #amount="{ row }">
            <span class="dq-num">{{ fmtAmount(row.amount as number | null) }}</span>
          </template>
          <template #range="{ row }">
            <span class="dq-num dq-dim">{{ rangeText(row) }}</span>
          </template>
          <template #source="{ row }">
            <span class="dq-source">
              <UiBadge v-if="row.ok" variant="ok" dot>实时</UiBadge>
              <template v-else>
                <span class="dq-dim">日线</span>
                <span class="dq-num dq-dim">{{ row.local_date || '' }}</span>
              </template>
            </span>
          </template>
          <template #empty>
            <EmptyState
              class="dq-empty"
              :description="hasFilter ? '没有匹配的证券' : '暂无证券'"
              reason="调整关键词或重置筛选"
              :icon="Search"
            >
              <Button access="read" size="sm" variant="outline" @click="handleReset">重置筛选</Button>
            </EmptyState>
          </template>
        </BasicTable>
      </Card>
    </div>
  </div>
</template>

<style scoped>
.dq-body {
  gap: var(--gap-4);
}

/* .page-scroll 是可滚的 flex 列：子项默认会被压扁而不是溢出滚动，这里全部定为不收缩 */
.dq-body > * {
  flex: 0 0 auto;
}

.dq-title {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.dq-title__badge {
  align-self: center;
  padding: 2px 10px;
  font-size: var(--fs-aux);
}

.dq-live {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-2);
  height: var(--ctl-h-sm);
  padding: 0 10px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  font-weight: 500;
  cursor: pointer;
}

.dq-filters__form {
  flex: 1 1 auto;
  min-width: 0;
}

/* 手机：关键词框 + 筛选按钮同一行 */
.dq-search {
  position: relative;
  flex: 1 1 auto;
  min-width: 0;
}

.dq-search__icon {
  position: absolute;
  top: 50%;
  left: 10px;
  width: 16px;
  height: 16px;
  color: var(--text-tertiary);
  transform: translateY(-50%);
  pointer-events: none;
}

.dq-search__input {
  height: var(--ctl-h-lg);
  padding-left: 32px;
}

.dq-more-btn {
  flex-shrink: 0;
}

.dq-more-btn__count {
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

.dq-more-sheet__form {
  padding: 0 var(--gap-4);
}

.dq-more-sheet__foot {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: var(--gap-2);
  margin-top: auto;
  padding: var(--gap-3) var(--gap-4) 0;
}

.dq-empty-market {
  min-height: 320px;
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.dq-board {
  position: relative;
  min-width: 0;
  overflow: hidden;
}

.dq-board :deep(.basic-table) {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.dq-num {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.dq-dim {
  color: var(--text-tertiary);
}

.dq-clip {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.dq-cell-inline {
  display: inline-flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
  max-width: 100%;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dq-name {
  color: var(--text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dq-name :deep(.stock-link) {
  color: inherit;
}

.dq-code {
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  color: var(--text-tertiary);
  letter-spacing: 0.02em;
}

.dq-price {
  font-weight: 600;
}

/* 涨跌 chip */
.dq-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  height: 22px;
  padding: 0 7px;
  border-radius: var(--radius-sm);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  background: var(--surface-sunken);
  color: var(--text-secondary);
}

.dq-chip.is-up {
  background: var(--up-soft);
  color: var(--up);
}

.dq-chip.is-down {
  background: var(--down-soft);
  color: var(--down);
}

.dq-source {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  font-size: var(--fs-aux);
}

.dq-empty {
  min-height: 260px;
}

/* 点行开档案：前缀限本页，裸 deep 会命中全站所有表 */
:deep(.board-table tbody tr) {
  cursor: pointer;
}

/* ─── 手机：卡片列表 ─── */
.dq-cards {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.dq-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--gap-3);
  padding: 12px var(--gap-4);
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.dq-card:last-child {
  border-bottom: 0;
}

.dq-card:active {
  background: var(--surface-hover);
}

.dq-card:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}

.dq-card__main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.dq-card__name {
  display: flex;
  align-items: baseline;
  gap: var(--gap-2);
  min-width: 0;
  color: var(--text-primary);
  font-size: var(--fs-body);
}

.dq-card__sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-2);
  min-width: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.dq-card__sub .dq-num {
  color: var(--text-secondary);
}

.dq-card__num {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.dq-card__big {
  font-family: var(--mono);
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.1;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.dq-card__big.is-up {
  color: var(--up);
}

.dq-card__big.is-down {
  color: var(--down);
}

.dq-pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-3);
  border-top: 1px solid var(--border-subtle);
}

.dq-pager__text {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 640px) {
  .dq-body {
    gap: var(--gap-3);
  }

  .dq-live {
    height: var(--ctl-h-lg);
  }
}
</style>
