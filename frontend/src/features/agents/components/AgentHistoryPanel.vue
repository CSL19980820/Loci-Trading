<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { onUnmounted, ref, shallowRef, watch } from 'vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { ChevronRight, RefreshCw } from '@lucide/vue'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import { Card } from '@/shared/components/ui/card'
import TradingReportDocument from '@/shared/components/TradingReportDocument.vue'
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
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/shared/components/ui/sheet'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/components/ui/table'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { getAgentHistory, getAgentRun } from '@/shared/api/stock_agents'
import type { AgentHistoryKind, AgentHistoryRow, AgentPage, AgentRunDetail } from '@/shared/types/stock_agents'
import { actionName, agentMoney, agentTime, phaseName, statusName } from '../agentFormat'
const props = defineProps<{ id:string; kind:AgentHistoryKind; refreshKey?:string | number }>()
const isMobile = useMobileLayout()
const page = ref(1)
const dates = ref<[string,string] | null>(null)
const rows = shallowRef<AgentPage>({ items:[], total:0, offset:0, limit:20 })
const loading = ref(false)
const error = ref('')
const detail = shallowRef<AgentRunDetail | null>(null)
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
let controller:AbortController | undefined
let detailController:AbortController | undefined
let version = 0
let disposed = false
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
function dateChanged() { page.value = 1; void load() }
function onPageChange(next:number) { page.value = next; void load() }
function onDetailOpenChange(open:boolean) { detailOpen.value = open; if (!open) detailController?.abort() }
async function inspect(row:AgentHistoryRow) {
  detailController?.abort(); detailController = new AbortController()
  const request = detailController
  detailOpen.value = true; detailLoading.value = true; detailError.value = ''; detail.value = null
  try { const result = await getAgentRun(props.id,String(row.id),request.signal); if (!disposed && !request.signal.aborted) detail.value = result }
  catch(e) { if (!disposed && !request.signal.aborted) detailError.value = e instanceof Error ? e.message : String(e) }
  finally { if (detailController === request) detailLoading.value = false }
}
watch(() => [props.id,props.kind],() => { page.value = 1; dates.value = null; detailOpen.value = false; detailController?.abort(); rows.value = { items:[],total:0,offset:0,limit:20 }; void load() },{ immediate:true })
watch(() => props.refreshKey,() => { if (page.value === 1 && !dates.value && !loading.value && !detailOpen.value && !document.hidden) void load() })
onUnmounted(() => { disposed = true; ++version; controller?.abort(); detailController?.abort() })
</script>
<template>
  <Card class="agent-history" :aria-label="TITLES[kind]">
    <div class="history-filter">
      <DateField
        v-model="dates"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        class="history-filter__dates"
        @change="dateChanged"
      />
      <span class="history-filter__count">{{ rows.total.toLocaleString() }} 条</span>
      <Button access="read" variant="ghost" size="icon-sm" :disabled="loading" aria-label="刷新当前历史页" @click="load">
        <Spinner v-if="loading" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
        <RefreshCw v-else aria-hidden="true" />
      </Button>
    </div>

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
            <span class="diary-summary" :class="{ 'is-empty': !row.summary }">{{ row.summary || (row.status === 'running' ? '研究中…' : '—') }}</span>
            <span v-if="row.actions?.length" class="diary-actions">
              <span v-for="(action, i) in row.actions.slice(0, 4)" :key="i" class="diary-action">{{ actionName(action.action) }} {{ action.name || action.code }}</span>
              <span v-if="row.actions.length > 4" class="diary-action is-more">+{{ row.actions.length - 4 }}</span>
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

    <div class="history-pagination">
      <Pagination :page="page" :items-per-page="20" :total="rows.total" :sibling-count="1" :disabled="loading" @update:page="onPageChange">
        <PaginationContent v-slot="{ items }">
          <span class="history-pagination__total">共 {{ rows.total.toLocaleString() }} 条</span>
          <PaginationPrevious><span>上一页</span></PaginationPrevious>
          <template v-for="(item, index) in items" :key="index">
            <PaginationItem v-if="item.type === 'page'" :value="item.value" :is-active="item.value === page">{{ item.value }}</PaginationItem>
            <PaginationEllipsis v-else />
          </template>
          <PaginationNext><span>下一页</span></PaginationNext>
        </PaginationContent>
      </Pagination>
    </div>

    <Sheet :open="detailOpen" @update:open="onDetailOpenChange">
      <SheetContent side="right" class="gap-0 p-0 sm:w-[720px] sm:max-w-[calc(100vw-2rem)]">
        <SheetHeader class="border-b border-line px-4 py-3 text-left"><SheetTitle class="text-title">工作日记详情</SheetTitle></SheetHeader>
        <div class="history-sheet__body">
          <div v-if="detailLoading" class="history-skeleton" aria-hidden="true"><Skeleton v-for="n in 10" :key="n" class="h-9 w-full" /></div>
          <Alert v-else-if="detailError" variant="destructive"><AlertTitle class="line-clamp-none">{{ detailError }}</AlertTitle></Alert>
          <TradingReportDocument v-else-if="detail?.sections" :sections="detail.sections" :title="phaseName(detail.phase)" :metadata="`${agentTime(detail.started_at)} · ${statusName(detail.status)} · 模拟账户`" />
          <article v-else-if="detail" class="diary-detail">
            <div class="detail-meta"><Badge>{{ phaseName(detail.phase) }}</Badge><span>{{ statusName(detail.status) }}</span><time>{{ agentTime(detail.started_at) }}</time></div>
            <p class="summary">{{ detail.detail.summary || detail.summary }}</p>
            <Alert v-if="detail.detail.analysis_only"><AlertTitle class="line-clamp-none">仅研判，未交易</AlertTitle></Alert>
            <h4 v-if="detail.detail.decisions?.length">本轮决策</h4>
            <section v-for="(decision,i) in detail.detail.decisions" :key="i" class="decision">
              <header><b>{{ actionName(decision.action) }} · {{ decision.name || decision.code }}</b><span v-if="decision.quantity">{{ decision.quantity }} 股</span></header>
              <p>{{ decision.reason }}</p>
            </section>
            <h4 v-if="detail.detail.rejects?.length">未执行及原因</h4>
            <section v-for="(reject,i) in detail.detail.rejects" :key="i" class="decision reject">
              <b>{{ reject.code }} {{ actionName(reject.action) }}</b>
              <p>{{ reject.reason }}</p>
            </section>
            <div v-if="detail.detail.usage" class="usage">
              <span v-if="detail.detail.usage.model">模型 {{ detail.detail.usage.model }}</span>
              <span v-if="detail.detail.usage.elapsed_ms != null">耗时 {{ (detail.detail.usage.elapsed_ms/1000).toFixed(1) }} 秒</span>
              <span v-if="detail.detail.usage.input_tokens != null">输入 {{ detail.detail.usage.input_tokens.toLocaleString() }} tokens</span>
              <span v-if="detail.detail.usage.output_tokens != null">输出 {{ detail.detail.usage.output_tokens.toLocaleString() }} tokens</span>
            </div>
          </article>
        </div>
      </SheetContent>
    </Sheet>
  </Card>
</template>
<style scoped>
.agent-history {
  min-width: 0;
}
.history-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2) var(--gap-3);
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
}
.history-filter__dates {
  width: 260px;
  max-width: 100%;
}
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
}
.history-pagination__total {
  margin-right: auto;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  white-space: nowrap;
}
/* 详情抽屉 */
.history-sheet__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 0 var(--gap-4) var(--gap-4);
}
.detail-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-3);
  padding-top: var(--gap-3);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}
.summary {
  margin: var(--gap-3) 0;
  font-size: var(--fs-ui);
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.diary-detail h4 {
  margin: var(--gap-4) 0 var(--gap-2);
  font-size: var(--fs-ui);
  font-weight: 600;
}
.decision {
  padding: var(--gap-3) 0;
  border-bottom: 1px solid var(--border-subtle);
}
.decision header,
.decision b {
  font-size: var(--fs-aux);
  font-weight: 600;
}
.decision header {
  display: flex;
  justify-content: space-between;
  gap: var(--gap-2);
}
.decision p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.reject {
  color: var(--warn-ink);
}
.usage {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-3);
  margin: var(--gap-3) 0;
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}
@media (max-width: 640px) {
  .history-filter {
    padding-inline: var(--gap-3);
  }
  .history-filter__dates {
    width: 100%;
  }
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
