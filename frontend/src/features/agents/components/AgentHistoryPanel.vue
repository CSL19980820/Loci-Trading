<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { ChevronRight, RefreshCw, Settings, Trash2 } from '@lucide/vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import AgentRunDetailDialog from './AgentRunDetail.vue'
import { beijingToday, diarySummary, executedTradeActions, tradeActionLabel, type AgentHistoryMode, type AgentHistoryStats } from './agentHistoryDisplay'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import DateField from '@/shared/components/ui/app/DateField.vue'
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from '@/shared/components/ui/pagination'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { getAgentHistory, getAgentRun } from '@/shared/api/stock_agents'
import type { AgentHistoryKind, AgentHistoryRow, AgentPage, AgentRunDetail } from '@/shared/types/stock_agents'
import { actionName, agentMoney, agentTime, phaseName, statusName } from '../agentFormat'
const props = withDefaults(defineProps<{ id:string; kind:AgentHistoryKind; refreshKey?:string | number;
  mode?:AgentHistoryMode; stats?:AgentHistoryStats; busy?:boolean }>(), { mode: 'today', busy: false })
const emit = defineEmits<{ configure: []; cleanup: [] }>()
const isMobile = useMobileLayout()
const page = ref(1)
const dates = ref<[string,string] | null>(null)
const today = ref(beijingToday())
const todayMode = computed(() => props.kind === 'runs' && props.mode === 'today')
const dateValue = computed<string | string[] | null>({
  get: () => todayMode.value ? dates.value?.[0] ?? today.value : dates.value,
  set: value => { dates.value = typeof value === 'string' ? [value, value] : Array.isArray(value) ? [value[0]!, value[1]!] : null },
})
const rows = shallowRef<AgentPage>({ items:[], total:0, offset:0, limit:20 })
const loading = ref(false)
const error = ref('')
const detail = shallowRef<AgentRunDetail | null>(null)
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const contentScroller = ref<HTMLDivElement | null>(null)
let controller:AbortController | undefined
let detailController:AbortController | undefined
let version = 0
let disposed = false
let dayTimer: ReturnType<typeof setInterval> | undefined
let inspectedRow: AgentHistoryRow | undefined
const TITLES: Record<AgentHistoryKind, string> = { runs: '工作日记', trades: '实际模拟成交', funding: '资金流水' }
/** 「09/24 15:10」拆成日期与时刻两行 */
function stampParts(value?: string | null): { day: string; time: string } {
  const [day = '', time = ''] = agentTime(value).split(/\s+/)
  return { day, time }
}
function statusVariant(status?: string) {
  if (status === 'running') return 'info' as const
  if (status === 'failed' || status === 'interrupted') return 'stamp' as const
  if (status === 'success' || status === 'filled') return 'ok' as const
  return 'secondary' as const
}
async function load() {
  controller?.abort(); controller = new AbortController()
  const request = controller; const current = ++version
  loading.value = true; error.value = ''
  try { const result = await getAgentHistory(props.id,props.kind,(page.value-1)*20,dates.value?.[0],dates.value?.[1],request.signal); if (!disposed && current === version) rows.value = result }
  catch(e) { if (!disposed && !request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (current === version) loading.value = false }
}
function dateChanged() {
  if (todayMode.value && !dates.value) dates.value = [today.value, today.value]
  page.value = 1; contentScroller.value?.scrollTo({ top: 0 }); void load()
}
function returnToToday() { today.value = beijingToday(); dates.value = [today.value, today.value]; dateChanged() }
function onPageChange(next:number) { page.value = next; contentScroller.value?.scrollTo({ top: 0 }); void load() }
function onDetailOpenChange(open:boolean) { detailOpen.value = open; if (!open) detailController?.abort() }
async function inspect(row:AgentHistoryRow) {
  inspectedRow = row
  detailController?.abort(); detailController = new AbortController()
  const request = detailController
  detailOpen.value = true; detailLoading.value = true; detailError.value = ''; detail.value = null
  try { const result = await getAgentRun(props.id,String(row.id),request.signal); if (!disposed && !request.signal.aborted) detail.value = result }
  catch(e) { if (!disposed && !request.signal.aborted) detailError.value = e instanceof Error ? e.message : String(e) }
  finally { if (detailController === request) detailLoading.value = false }
}
watch(() => [props.id,props.kind,props.mode],() => {
  today.value = beijingToday(); page.value = 1; dates.value = todayMode.value ? [today.value, today.value] : null
  detailOpen.value = false; detailController?.abort(); rows.value = { items:[],total:0,offset:0,limit:20 }; void load()
},{ immediate:true })
watch(() => props.refreshKey,() => {
  const follows = !dates.value || (todayMode.value && dates.value[0] === today.value && dates.value[1] === today.value)
  if (page.value === 1 && follows && !loading.value && !detailOpen.value && !document.hidden) void load()
})
onMounted(() => { dayTimer = setInterval(() => {
  const nextDay = beijingToday()
  if (nextDay === today.value) return
  const follows = todayMode.value && dates.value?.[0] === today.value && dates.value?.[1] === today.value
  today.value = nextDay
  if (follows) { dates.value = [nextDay, nextDay]; dateChanged() }
}, 60000) })
onUnmounted(() => { disposed = true; ++version; controller?.abort(); detailController?.abort(); clearInterval(dayTimer) })
</script>
<template>
  <Card class="agent-history" :aria-label="TITLES[kind]">
    <div class="history-filter">
      <dl v-if="kind === 'runs' && stats" class="history-stats" aria-label="日记累计统计">
        <div><dt>累计</dt><dd>{{ stats.total_runs.toLocaleString() }}</dd></div>
        <div><dt>保留</dt><dd>{{ stats.history_kept.toLocaleString() }}</dd></div>
        <div><dt>清理</dt><dd>{{ stats.cleaned_runs.toLocaleString() }}</dd></div>
      </dl>
      <DateField
        v-model="dateValue"
        :type="todayMode ? 'date' : 'daterange'"
        :clearable="!todayMode"
        :aria-label="kind === 'runs' ? '日记日期' : '历史日期'"
        value-format="YYYY-MM-DD"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        class="history-filter__dates"
        @change="dateChanged"
      />
      <Button v-if="todayMode && dates?.[0] !== today" access="read" variant="ghost" size="xs" @click="returnToToday">今日</Button>
      <div v-if="kind === 'runs'" class="history-management">
        <Button access="read" variant="ghost" size="icon-sm" aria-label="设置日记保留策略" title="保留策略" :disabled="busy" @click="emit('configure')"><Settings /></Button>
        <Button variant="ghost" size="icon-sm" aria-label="清理旧日记" title="清理旧日记" :disabled="busy" @click="emit('cleanup')"><Trash2 /></Button>
      </div>
      <span v-if="kind !== 'runs'" class="history-filter__count">{{ rows.total.toLocaleString() }} 条</span>
      <Button access="read" variant="ghost" size="icon-sm" :disabled="loading" aria-label="刷新当前历史页" @click="load">
        <Spinner v-if="loading" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
        <RefreshCw v-else aria-hidden="true" />
      </Button>
    </div>

    <div ref="contentScroller" class="history-content" data-agent-workspace-scroll role="region" :aria-label="`${TITLES[kind]}列表`" tabindex="0">
    <Alert v-if="error" variant="destructive" class="mx-4 mb-3"><AlertTitle class="line-clamp-none">{{ error }}</AlertTitle></Alert>

    <div v-if="loading && !rows.items.length" class="history-skeleton" aria-hidden="true">
      <Skeleton v-for="n in 6" :key="n" class="h-9 w-full" />
    </div>

    <!-- 工作日记 -->
    <ol v-else-if="kind === 'runs' && rows.items.length" class="diary-list">
      <li v-for="row in rows.items" :key="row.id">
        <button type="button" class="diary-row" @click="inspect(row)">
          <time class="diary-row__when" :datetime="row.started_at">
            <b>{{ stampParts(row.started_at).day }}</b>
            <span>{{ stampParts(row.started_at).time }}</span>
          </time>
          <span class="diary-row__main">
            <span class="diary-meta">
              <strong>{{ phaseName(row.phase) }}</strong>
              <UiBadge :variant="statusVariant(row.status)" :dot="row.status !== 'running'">
                <Spinner v-if="row.status === 'running'" class="size-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />
                {{ statusName(row.status) }}
              </UiBadge>
            </span>
            <span class="diary-summary" :class="{ 'is-empty': !row.summary }">{{ diarySummary(row.summary) || (row.status === 'running' ? '研究中…' : '本轮没有文字摘要') }}</span>
            <span v-if="executedTradeActions(row).length" class="diary-actions">
              <span v-for="(action, i) in executedTradeActions(row)" :key="i" class="diary-action" :class="{ 'is-rejected': action.status === 'rejected' }">{{ tradeActionLabel(action) }}</span>
            </span>
          </span>
          <ChevronRight class="diary-row__chevron" aria-hidden="true" />
        </button>
      </li>
    </ol>

    <!-- 成交 / 资金：手机卡片 -->
    <ul v-else-if="kind !== 'runs' && rows.items.length && isMobile" class="ledger-cards">
      <li v-for="row in rows.items" :key="row.id" class="ledger-card">
        <template v-if="kind === 'trades'">
          <div class="ledger-card__row">
            <span class="stock-cell">
              <strong>{{ row.name || '名称待核对' }}</strong>
              <small>{{ row.code }}</small>
            </span>
            <span class="ledger-card__amount">{{ agentMoney(row.gross_cents) }}<small>元</small></span>
          </div>
          <div class="ledger-card__meta">
            <UiBadge :variant="['sell','reduce','take_profit','stop_loss'].includes(String(row.action || row.side)) ? 'down' : 'up'">{{ actionName(row.action || row.side) }}</UiBadge>
            <span>{{ row.quantity }} 股 × {{ agentMoney(row.price_cents) }}</span>
            <span>费用 {{ agentMoney(row.fees_cents) }}</span>
            <time>{{ agentTime(row.at) }}</time>
          </div>
        </template>
        <template v-else>
          <div class="ledger-card__row">
            <span class="stock-cell"><strong>{{ row.kind === 'initial' ? '初始模拟资金' : '追加模拟资金' }}</strong></span>
            <span class="ledger-card__amount is-up">+{{ agentMoney(row.amount_cents) }}<small>元</small></span>
          </div>
          <div class="ledger-card__meta"><time>{{ agentTime(row.at) }}</time></div>
        </template>
      </li>
    </ul>

    <!-- 成交 / 资金：桌面表格 -->
    <Table v-else-if="kind !== 'runs' && rows.items.length" class="ledger-table">
      <TableHeader>
        <TableRow>
          <TableHead class="min-w-[120px]">时间</TableHead>
          <template v-if="kind === 'trades'">
            <TableHead class="min-w-[140px]">股票 · 编码</TableHead>
            <TableHead class="min-w-[80px]">操作</TableHead>
            <TableHead class="num">股数</TableHead>
            <TableHead class="num">价格</TableHead>
            <TableHead class="num">成交金额</TableHead>
            <TableHead class="num">费用</TableHead>
          </template>
          <template v-else>
            <TableHead class="min-w-[160px]">类型</TableHead>
            <TableHead class="num">金额</TableHead>
          </template>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow v-for="row in rows.items" :key="row.id">
          <TableCell class="mono text-ink-2">{{ agentTime(row.at) }}</TableCell>
          <template v-if="kind === 'trades'">
            <TableCell>
              <span class="stock-cell-inline" :title="`${row.name || '名称待核对'} ${row.code}`">
                <strong>{{ row.name || '名称待核对' }}</strong>
                <small>{{ row.code }}</small>
              </span>
            </TableCell>
            <TableCell>
              <UiBadge :variant="['sell','reduce','take_profit','stop_loss'].includes(String(row.action || row.side)) ? 'down' : 'up'">{{ actionName(row.action || row.side) }}</UiBadge>
            </TableCell>
            <TableCell class="num">{{ row.quantity }}</TableCell>
            <TableCell class="num">{{ agentMoney(row.price_cents) }}</TableCell>
            <TableCell class="num font-medium">{{ agentMoney(row.gross_cents) }}</TableCell>
            <TableCell class="num text-mist">{{ agentMoney(row.fees_cents) }}</TableCell>
          </template>
          <template v-else>
            <TableCell>{{ row.kind === 'initial' ? '初始模拟资金' : '追加模拟资金' }}</TableCell>
            <TableCell class="num font-medium">+{{ agentMoney(row.amount_cents) }}</TableCell>
          </template>
        </TableRow>
      </TableBody>
    </Table>

    <div v-else class="history-empty">
      <EmptyState :description="dates ? '该日期范围无记录' : '暂无记录'" compact />
    </div>
    </div>

    <div class="history-pagination">
      <Pagination :page="page" :items-per-page="20" :total="rows.total" :sibling-count="1" :disabled="loading" @update:page="onPageChange">
        <PaginationContent v-slot="{ items }">
          <span class="history-pagination__total">共 {{ rows.total.toLocaleString() }} 条</span>
          <PaginationPrevious aria-label="上一页"><span>上一页</span></PaginationPrevious>
          <template v-for="(item, index) in items" :key="index">
            <PaginationItem v-if="item.type === 'page'" :value="item.value" :is-active="item.value === page">{{ item.value }}</PaginationItem>
            <PaginationEllipsis v-else />
          </template>
          <PaginationNext aria-label="下一页"><span>下一页</span></PaginationNext>
        </PaginationContent>
      </Pagination>
    </div>

    <AgentRunDetailDialog :open="detailOpen" :detail="detail" :loading="detailLoading" :error="detailError"
      @update:open="onDetailOpenChange" @retry="inspectedRow && inspect(inspectedRow)" />
  </Card>
</template>
<style scoped>
.agent-history {
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}
.history-content {
  flex: 1 1 0%;
  min-height: 0;
  min-width: 0;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-default) transparent;
}
.history-content:focus-visible {
  outline: 2px solid var(--focus-ring, var(--seal));
  outline-offset: -2px;
}
.history-content :deep([data-slot="table-container"]) {
  overflow: visible;
}
.history-content :deep(thead) {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface);
}
.history-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
.history-filter__dates {
  flex: 1 1 180px;
  width: 220px;
  min-width: 150px;
  max-width: 100%;
}
.history-stats { display:flex; flex:none; gap:10px; margin:0; font-size:11px; }
.history-stats > div { display:flex; align-items:baseline; gap:4px; }
.history-stats dt { color:var(--text-tertiary); }
.history-stats dd { margin:0; font:600 12px var(--mono); }
.history-management { display:flex; align-items:center; flex:none; gap:2px; }
.history-management button { width:28px; height:28px; }
.history-filter__count {
  margin-left: auto;
  color: var(--text-tertiary);
  font: var(--fs-aux) / 1 var(--mono);
  font-variant-numeric: tabular-nums;
}
.history-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  padding: var(--gap-2) var(--gap-4) var(--gap-3);
}
/* 工作日记 */
.diary-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 6px;
  list-style: none;
}
.diary-row {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr) auto;
  align-items: start;
  gap: 14px;
  width: 100%;
  padding: 12px 10px 12px 12px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease);
}
.diary-row:hover {
  background: var(--surface-hover);
}
.diary-row:focus-visible {
  outline: 2px solid var(--focus-ring, var(--seal));
  outline-offset: -2px;
}
.diary-row__when {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding-top: 2px;
  font-variant-numeric: tabular-nums;
}
.diary-row__when b {
  color: var(--text-primary);
  font: 600 var(--fs-aux) / 1.1 var(--mono);
}
.diary-row__when span {
  color: var(--text-tertiary);
  font: var(--fs-kicker) / 1.1 var(--mono);
}
.diary-row__main {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.diary-row__chevron {
  align-self: center;
  flex-shrink: 0;
  width: 16px;
  height: 16px;
  color: var(--text-tertiary);
  opacity: 0.6;
}
.diary-row:hover .diary-row__chevron {
  opacity: 1;
}
.diary-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}
.diary-meta strong {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
}
.diary-summary {
  display: -webkit-box;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  line-height: 1.65;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow-wrap: anywhere;
}
.diary-summary.is-empty {
  color: var(--text-tertiary);
}
.diary-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.diary-action {
  padding: 0 7px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-size: var(--fs-micro);
  line-height: 20px;
}
.diary-action.is-more {
  color: var(--text-tertiary);
}
.diary-action.is-rejected { color:var(--warn-ink); background:var(--warn-soft,var(--surface-sunken)); }
/* 手机成交卡 */
.ledger-cards {
  margin: 0;
  padding: 0;
  list-style: none;
}
.ledger-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--gap-2) var(--gap-3) var(--gap-3);
  border-top: 1px solid var(--border-subtle);
}
.ledger-card__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
}
.ledger-card__amount {
  font-family: var(--mono);
  font-size: var(--fs-body);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.ledger-card__amount small {
  margin-left: 2px;
  color: var(--text-tertiary);
  font-family: var(--font);
  font-size: var(--fs-kicker);
  font-weight: 400;
}
.ledger-card__amount.is-up {
  color: var(--up);
}
.ledger-card__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px var(--gap-3);
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  font-variant-numeric: tabular-nums;
}
/* 桌面表格 */
.ledger-table :deep(th) {
  height: var(--head-h);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-weight: 500;
  white-space: nowrap;
  text-align: left;
}
.ledger-table :deep(td) {
  height: 44px;
  font-size: var(--fs-ui);
  text-align: left;
  white-space: nowrap;
}
.ledger-table :deep(th:first-child),
.ledger-table :deep(td:first-child) {
  padding-left: var(--gap-4);
}
.ledger-table :deep(th:last-child),
.ledger-table :deep(td:last-child) {
  padding-right: var(--gap-4);
}
.ledger-table :deep(.num),
.num {
  text-align: right;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.stock-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.stock-cell strong {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  line-height: 1.3;
}
.stock-cell small {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}
.stock-cell-inline {
  display: inline-flex;
  align-items: baseline;
  justify-content: flex-start;
  gap: 6px;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stock-cell-inline strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stock-cell-inline small {
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}
.history-empty {
  display: flex;
  min-height: 9rem;
  align-items: center;
  justify-content: center;
  border-top: 1px solid var(--border-subtle);
}
.history-pagination {
  display: flex;
  justify-content: flex-end;
  padding: var(--gap-2) var(--gap-4);
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
}
.history-pagination :deep([data-slot="pagination-content"]) {
  width: 100%;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.history-pagination__total {
  margin-right: auto;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  white-space: nowrap;
}
@media (max-width: 640px) {
  .history-filter {
    padding-inline: var(--gap-3);
  }
  .history-filter__dates {
    order: 4;
    flex-basis: 100%;
    width: 100%;
  }
  .history-management { margin-left:auto; }
  .diary-row {
    grid-template-columns: 48px minmax(0, 1fr) auto;
    gap: 10px;
  }
  .history-pagination {
    justify-content: flex-start;
    padding-inline: var(--gap-3);
  }
}
</style>
