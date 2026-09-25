<script setup lang="ts">
import { Spinner } from '@/shared/components/ui/spinner'
import { toast } from 'vue-sonner'
import { FileText as Document, History, Play, RefreshCw } from '@lucide/vue'
import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/shared/components/ui/dialog'
import { Notice, SkeletonBlock, IconBox } from '@/shared/components/ui/app/presentation'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as RadioChoices } from '@/shared/components/ui/app/RadioChoices.vue'
import { default as RadioButton } from '@/shared/components/ui/app/RadioButton.vue'
import { default as DataGrid } from '@/shared/components/ui/app/DataGrid.vue'
import { default as DataColumn } from '@/shared/components/ui/app/DataColumn.vue'
import { default as Pager } from '@/shared/components/ui/app/Pager.vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'

import { computed, onActivated, onUnmounted, ref, shallowRef, useId, watch } from 'vue'


import { getGuardianResearch, getGuardianRuns, getGuardianRun, scanGuardian } from '@/shared/api/guardian'
import { price, shortTime, strategyLabel } from '@/shared/lib/format'
import { formatDateTime } from '@/shared/lib/dateTime'
import { GUARDIAN_ACTION_LABELS } from '@/shared/types/guardian'
import type { GuardianAccount, GuardianResearch, GuardianWatch, GuardianDecision, GuardianRun } from '@/shared/types/guardian'
import GuardianHistoryFilter from './GuardianHistoryFilter.vue'
import TradingReportDocument from '@/shared/components/TradingReportDocument.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { guardianDaysAgo, guardianToday, useGuardianHistory } from '../composables/useGuardianHistory'
const props = defineProps<{ account: GuardianAccount; enabled: boolean; notify: boolean; historyMode?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const data = shallowRef<GuardianResearch>({})
const historyOpen = ref(false)
const mobile = useMobileLayout()
const mobilePane = ref('pool')
const { range, page, items: runs, total, loading: listLoading, error: listError, load, apply, changePage, todayOnly } = useGuardianHistory(getGuardianRuns, !props.historyMode, { start: props.historyMode ? guardianDaysAgo(29) : guardianToday(), limit: props.historyMode ? 20 : 200, followToday: !props.historyMode })
const selectedRun = ref('')
const latest = shallowRef<GuardianRun | null>(null)
const detailLoading = ref(false)
const error = ref('')
const busy = ref(false)
const researchLoading = ref(false)
const filter = ref('watching')
const selectedStock = shallowRef<GuardianWatch | null>(null)
function openStock(row: unknown) { selectedStock.value = row as GuardianWatch }
let controller: AbortController | undefined
let researchController: AbortController | undefined
let disposed = false
const active = computed(() => runs.value.find(r => r.slot === selectedRun.value))
watch(runs, rows => { if (!rows.some(r => r.slot === selectedRun.value)) selectedRun.value = rows[0]?.slot ?? '' })
async function loadDetail(): Promise<void> {
  controller?.abort(); latest.value = null; detailLoading.value = false
  const row = active.value
  if (!row) return
  const request = new AbortController(); controller = request
  detailLoading.value = true; error.value = ''
  try { const result = await getGuardianRun(row.slot, request.signal); if (!disposed && !request.signal.aborted) latest.value = result }
  catch (e) { if (!disposed && !request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (controller === request) detailLoading.value = false }
}
watch(() => JSON.stringify([selectedRun.value, active.value?.status, active.value?.started, active.value?.result]), () => { void loadDetail() })
async function loadResearch(): Promise<void> {
  researchController?.abort()
  const request = new AbortController(); researchController = request
  researchLoading.value = true; error.value = ''
  try { const result = await getGuardianResearch(request.signal); if (!disposed && !request.signal.aborted) data.value = result }
  catch (e) { if (!disposed && !request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (researchController === request) researchLoading.value = false }
}
async function scan(): Promise<void> {
  busy.value = true; error.value = ''
  try { await scanGuardian(); if (!disposed) { toast.info('已开始一轮研判，结果将自动更新'); todayOnly(); emit('changed') } }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
const pool = computed(() => {
  const map = new Map<string, GuardianWatch>((data.value?.watchlist ?? []).map(r => [r.code, { ...r, position: undefined }]))
  for (const p of props.account.positions ?? []) map.set(p.code, { ...(map.get(p.code) ?? { code: p.code, name: p.name, signals: [], strategies: p.strategies ?? [] }), position: p })
  return [...map.values()].sort((a, b) => Number(Boolean(b.position)) - Number(Boolean(a.position)))
})
const watchRows = computed(() => pool.value.filter(r => r.watch || r.signals.length > 0))
const holdingRows = computed(() => pool.value.filter(r => Boolean(r.position)))
const rows = computed(() => filter.value === 'holding' ? holdingRows.value : watchRows.value)
const decisions = computed(() => latest.value?.result.decisions ?? [])
const decisionByCode = computed(() => {
  const map = new Map<string, GuardianDecision>()
  for (const run of (latest.value ? [latest.value] : [])) for (const item of run.result.decisions ?? []) if (!map.has(item.code)) map.set(item.code, item)
  return map
})
function actionLabel(item: GuardianDecision) { return GUARDIAN_ACTION_LABELS[item.action] }
function stockName(code: string) { return pool.value.find(p => p.code === code)?.name ?? code }
function plan(raw: unknown) { const row = raw as GuardianWatch; return row.position?.holding_plan || row.watch?.entry_condition || row.watch?.reason || decisionByCode.value.get(row.code)?.holding_plan || row.position?.last_review?.reason || decisionByCode.value.get(row.code)?.reason || (row.position ? '持有周期由模型管理' : '等待模型研判') }
function since(raw: unknown) {
  const row = raw as GuardianWatch
  if (row.watch?.added_at && filter.value !== 'holding') return formatDateTime(row.watch.added_at).slice(0, 16)
  const recordedAt = filter.value === 'holding' ? row.position?.entry_context?.opened_at : row.signals.at(-1)?.created_at
  if (recordedAt) {
    const formatted = formatDateTime(recordedAt)
    if (formatted !== '—') return formatted.slice(0, 16)
  }
  return row.position?.entry_context?.opened_at?.slice(0, 10) || row.signals.at(-1)?.date || '—'
}
function sinceLabel(raw: unknown) {
  const row = raw as GuardianWatch
  return row.watch && filter.value !== 'holding' ? '加入观察时间' : filter.value === 'holding' ? '建仓时间' : '候选记录时间'
}
onActivated(() => { if (!props.historyMode) void loadResearch() })
watch(() => props.account, () => { if (!props.historyMode) void loadResearch() })
onUnmounted(() => { disposed = true; controller?.abort(); researchController?.abort() })
const panelId = `guardian-research-panel-${useId()}`
</script>
<template>
  <section class="research-workspace" :class="{ 'research-workspace--history': historyMode }" aria-label="观察">
    <PageTabs v-if="mobile && !historyMode" :panel-id="panelId" v-model="mobilePane" :items="[{name:'analysis',label:'今日研判'},{name:'pool',label:'股票池'}]" variant="pill" :sticky="false" class="research-mobile-tabs" aria-label="研判视图" />
    <Notice v-if="listError || error" :title="listError || error" tone="error" :closable="false"><ActionButton access="read" variant="link" @click="load(); loadResearch(); loadDetail()">重试</ActionButton></Notice>
    <div :id="panelId" class="guardian-body" :role="mobile && !historyMode ? 'tabpanel' : undefined" :tabindex="mobile && !historyMode ? 0 : undefined" :aria-labelledby="mobile && !historyMode ? `${panelId}-tab-${mobilePane}` : undefined">
      <!-- 左栏：股票池 -->
      <section v-if="!historyMode" v-show="!mobile || mobilePane === 'pool'" class="guardian-pool" aria-label="股票池">
        <div class="guardian-section-head">
          <div class="pool-title-and-scope">
            <h3 v-if="!mobile">股票池</h3>
            <RadioChoices v-model="filter" aria-label="股票池范围">
              <RadioButton value="watching">自选股 · {{ watchRows.length }}</RadioButton><RadioButton value="holding">持仓股 · {{ holdingRows.length }}</RadioButton>
            </RadioChoices>
          </div>
          <div class="flex items-center gap-2"><span class="guardian-count">{{ rows.length }} 只</span><Button access="read" variant="ghost" size="xs" :disabled="researchLoading" @click="loadResearch"><RefreshCw class="size-3" />刷新</Button></div>
        </div>

        <div v-if="mobile && rows.length" class="research-mobile-stocks">
          <article v-for="row in rows" :key="row.code" class="research-mobile-stock">
            <div><span role="button" tabindex="0" class="stock-detail-link" :aria-label="`查看 ${row.name} 交易参考`" @click="openStock(row)" @keydown.enter.prevent="openStock(row)" @keydown.space.prevent="openStock(row)">{{ row.name }} <small>{{ row.code }}</small></span><span class="research-mobile-state">{{ row.position ? '持仓中' : '观察中' }}</span></div>
            <p>{{ plan(row) }}</p>
            <footer><time>{{ sinceLabel(row) }} {{ since(row) }}</time><span v-if="row.position">{{ row.position.quantity.toLocaleString() }} 股 · 成本 {{ price(row.position.average_cost) }}元</span><span v-else>{{ row.strategies.map(tag => strategyLabel(tag)).join(' / ') }}</span></footer>
          </article>
        </div>
        <DataGrid v-else-if="rows.length" :data="rows" row-key="code" class="guardian-stock-table" @row-click="openStock">
          <DataColumn label="股票" min-width="190">
            <template #default="{ row }">
              <div class="guardian-stock-name">
                <span role="button" tabindex="0" class="stock-detail-link" :aria-label="`查看 ${row.name} 交易参考`" @click.stop="openStock(row)" @keydown.enter.stop.prevent="openStock(row)" @keydown.space.stop.prevent="openStock(row)">{{ row.name }}（{{ row.code }}）</span>
              </div>
            </template>
          </DataColumn>
          <DataColumn label="记录时间" width="180"><template #default="{ row }"><span class="font-mono" :title="sinceLabel(row)">{{ since(row) }}</span></template></DataColumn>
          <DataColumn label="状态" width="90">
            <template #default="{ row }">
              <span class="guardian-stock-state" :class="{ held: row.position }">
                {{ row.position ? '持仓中' : '观察中' }}
              </span>
            </template>
          </DataColumn>
          <DataColumn label="持仓股数" width="90" align="right">
            <template #default="{ row }">{{ row.position ? `${row.position.quantity} 股` : '—' }}</template>
          </DataColumn>
          <DataColumn label="参考成本" width="86" align="right">
            <template #default="{ row }">{{ price(row.position?.average_cost) }}</template>
          </DataColumn>
          <DataColumn label="模型管理计划" min-width="160">
            <template #default="{ row }">
              <span class="guardian-plan" :title="plan(row)">{{ plan(row) }}</span>
            </template>
          </DataColumn>
        </DataGrid>

        <div v-else class="guardian-pool-empty">
          <div class="guardian-empty-mark"><span /><span /><span /></div>
          <strong>{{ filter === 'holding' ? '暂无持仓股' : '暂无自选股' }}</strong>
        </div>

      </section>

      <!-- 右栏：交易研判 -->
      <aside v-show="!mobile || historyMode || mobilePane === 'analysis'" class="guardian-report" aria-label="交易研判">
        <div class="guardian-section-head">
          <div class="section-title-group">
            <h3>{{ historyMode ? '历史研判' : '模型研判' }}</h3>
            <span v-if="!historyMode" class="run-label" :title="range.start">{{ total }} 次</span>
          </div>
          <div v-if="!historyMode" class="research-actions">
          <Button v-if="!historyMode" access="read" variant="ghost" size="sm" @click="historyOpen = true"><History class="size-3" />历史</Button>
          <Button v-if="!historyMode"
            variant="outline"
            size="sm"
            class="h-7 text-xs px-2.5 gap-1 font-medium border-rule"
            :disabled="busy || !enabled"
            @click="scan"
          >
            <Spinner v-if="busy" class="size-3 animate-spin" aria-hidden="true" />
            <Play v-else class="size-3 text-seal" aria-hidden="true" />
            <span>立即研判</span>
          </Button>
          </div>
        </div>

        <!-- 历史查询 + 轮次选择 合并为统一紧凑工具栏 -->
        <div class="research-control-bar">
          <GuardianHistoryFilter v-if="historyMode" :value="range" :loading="listLoading" @apply="apply" />
          <div v-if="runs.length" class="run-selector-inline">
            <span class="run-label">轮次</span>
            <ChoiceField v-model="selectedRun" :placeholder="shortTime(runs[0]?.slot ?? '')" aria-label="选择守护轮次" class="run-choice">
              <ChoiceOption v-for="run in runs" :key="run.slot" :value="run.slot" :label="shortTime(run.slot)" />
            </ChoiceField>
            <Badge
              variant="outline"
              class="h-7 text-[11px] font-normal gap-1.5 px-2 shrink-0"
              :class="{
                'border-loss/40 text-loss': latest?.status === 'failed',
                'border-gain/40 text-gain': latest?.status === 'success' && latest.result.outcome !== 'no_action',
                'border-seal/40 text-seal': latest?.status === 'running',
              }"
            >
              <span
                class="size-1.5 rounded-full"
                :class="{
                  'bg-seal animate-pulse': latest?.status === 'running',
                  'bg-loss': latest?.status === 'failed',
                  'bg-gain': latest?.status === 'success' && latest.result.outcome !== 'no_action',
                  'bg-mist': latest?.status === 'success' && latest.result.outcome === 'no_action',
                }"
              />
              {{ detailLoading ? '加载中' : latest?.status === 'running' ? '研判中' : latest?.status === 'failed' ? '异常' : latest?.status === 'success' ? latest.result.outcome === 'no_action' ? '无动作' : latest.result.outcome === 'observation_changed' ? '观察已变更' : '已完成' : '已中断' }}
            </Badge>
          </div>
          <Pager v-if="historyMode" :current-page="page" :page-size="range.limit" :total="total" layout="total, prev, pager, next" :disabled="listLoading" @current-change="changePage" />
          <span v-else-if="total > range.limit" class="run-label">最近 {{ range.limit }} / {{ total }}</span>
        </div>

        <SkeletonBlock v-if="detailLoading" :rows="4" animated />
        <TradingReportDocument v-else-if="latest?.result.sections?.length" :sections="latest.result.sections" title="研判记录" :metadata="`${formatDateTime(latest.result.as_of || latest.slot)} · 模拟账户`" />
        <div v-else-if="latest" class="guardian-report-content">
          <div v-if="latest.result.analysis_only || latest.status === 'running' || latest.status === 'expired' || latest.result.error || latest.result.analysis || latest.result.body" class="guardian-analysis guardian-analysis-box">
            <p v-if="latest.result.analysis_only" class="guardian-analysis-text">本轮仅研判，未执行买卖。预案会在下一可交易轮次结合新行情重新核验。</p>
            <p v-else-if="latest.status === 'running'" class="guardian-analysis-text">正在读取材料并形成判断…</p>
            <p v-else-if="latest.status === 'expired'" class="guardian-analysis-text">上轮运行中断，未写入模拟成交。</p>
            <p v-else class="guardian-analysis-text" :class="{ failed: latest.status === 'failed' }">{{ latest.result.error || latest.result.analysis || latest.result.body }}</p>
          </div>

          <!-- 双列研判决策卡片网格 (支持容器查询双列) -->
          <div class="guardian-decisions-grid">
            <article v-for="(item, i) in decisions" :key="`${item.code}-${i}`" class="guardian-decision-card">
              <div class="decision-head">
                <Badge
                  :variant="item.action === 'sell' ? 'destructive' : item.action === 'buy' ? 'default' : item.action === 'hold' ? 'outline' : 'secondary'"
                  class="h-5 px-1.5 text-[10px] font-semibold shrink-0"
                  :class="{ 'border-seal/40 bg-seal/10 text-seal': item.action === 'hold' }"
                >
                  {{ actionLabel(item) }}
                </Badge>
                <b class="stock-name truncate">{{ stockName(item.code) }}</b>
                <span class="guardian-code font-mono">{{ item.code }}</span>
              </div>

              <p class="decision-reason line-clamp-2 hover:line-clamp-none transition-all cursor-pointer" :title="item.reason">{{ item.reason }}</p>

              <div class="decision-plans">
                <div v-if="item.holding_plan" class="plan-holding-strip">
                  <span class="plan-tag">持股</span>
                  <span class="plan-desc" :title="item.holding_plan">{{ item.holding_plan }}</span>
                </div>

                <!-- 止盈 / 止损 双列展示 -->
                <div v-if="item.take_profit_plan || item.stop_loss_plan" class="plan-targets-grid">
                  <div v-if="item.take_profit_plan" class="target-col target-tp">
                    <span class="target-title text-gain">🎯 止盈</span>
                    <span class="target-text" :title="item.take_profit_plan">{{ item.take_profit_plan }}</span>
                  </div>
                  <div v-if="item.stop_loss_plan" class="target-col target-sl">
                    <span class="target-title text-loss">🛡️ 止损</span>
                    <span class="target-text" :title="item.stop_loss_plan">{{ item.stop_loss_plan }}</span>
                  </div>
                </div>

                <!-- 等待入场 / 撤出观察 双列展示 -->
                <div v-if="item.entry_condition || item.exit_condition" class="plan-targets-grid">
                  <div v-if="item.entry_condition" class="target-col target-entry">
                    <span class="target-title text-seal">等待入场：</span>
                    <span class="target-text" :title="item.entry_condition">{{ item.entry_condition }}</span>
                  </div>
                  <div v-if="item.exit_condition" class="target-col target-exit">
                    <span class="target-title text-mist">撤出观察：</span>
                    <span class="target-text" :title="item.exit_condition">{{ item.exit_condition }}</span>
                  </div>
                </div>
              </div>
            </article>
          </div>

          <!-- 模拟执行记录 -->
          <div v-if="latest.result.fills?.length || latest.result.rejects?.length" class="guardian-execution-box">
            <h4>模拟执行记录</h4>
            <div class="execution-list">
              <div v-for="(fill, i) in latest.result.fills" :key="i" class="execution-item">
                <Badge variant="outline" class="h-5 text-[10px]">{{ fill.action || '成交' }}</Badge>
                <b class="execution-name">{{ fill.name || stockName(fill.code) }}</b>
                <span v-if="fill.quantity != null" class="execution-detail font-mono">
                  {{ fill.quantity }} 股 · {{ fill.before_quantity }} → {{ fill.after_quantity }} 股 · {{ price((fill.price_cents ?? 0) / 100) }} 元
                </span>
                <span v-else class="execution-detail font-mono">
                  {{ fill.before_layers }} → {{ fill.after_layers }} 层 · {{ price(fill.price) }}
                </span>
              </div>
              <div v-for="(reject, i) in latest.result.rejects" :key="`reject-${i}`" class="execution-item failed text-loss text-xs">
                <span>{{ reject.code }} · 未执行：{{ reject.reason }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="guardian-report-empty">
          <IconBox><Document /></IconBox>
          <strong>暂无研判</strong>

        </div>

        <footer class="guardian-report-foot">
          <span>{{ latest?.result.notify ? latest.result.notify.success ? '本轮通知已送达' : latest.result.notify.skipped ? latest.result.notify.skipped === 'no_action' ? '无成交，已静默留存' : '本轮通知已跳过' : '本轮通知未送达' : notify ? '每轮合并推送' : '推送已关闭' }}</span>

        </footer>
      </aside>
    </div>
    <Dialog :open="Boolean(selectedStock)" @update:open="value => { if (!value) selectedStock = null }">
      <DialogContent class="sm:max-w-3xl max-h-[85dvh] overflow-y-auto stock-detail-dialog">
        <DialogHeader v-if="selectedStock" class="text-left">
          <DialogTitle class="flex items-center gap-3">{{ selectedStock.name }} <span class="font-mono text-base text-muted-foreground">{{ selectedStock.code }}</span><Badge variant="secondary">{{ selectedStock.position ? '持仓股' : '自选股' }}</Badge></DialogTitle>
          <DialogDescription>{{ sinceLabel(selectedStock) }} {{ since(selectedStock) }} · 交易参考详情</DialogDescription>
        </DialogHeader>
        <div v-if="selectedStock">
          <div v-if="selectedStock.position" class="stock-detail-metrics"><div><span>持仓股数</span><b>{{ selectedStock.position.quantity }} 股</b></div><div><span>参考成本</span><b>{{ price(selectedStock.position.average_cost) }} 元</b></div><div><span>可卖股数</span><b>{{ selectedStock.position.available_quantity }} 股</b></div></div>
              <div class="guardian-stock-detail">
                <span>持有计划</span>
                <p>{{ plan(selectedStock) }}</p>
                <template v-if="selectedStock.position?.take_profit_plan">
                  <span>止盈计划</span>
                  <p>{{ selectedStock.position.take_profit_plan }}</p>
                </template>
                <template v-if="selectedStock.position?.stop_loss_plan">
                  <span>止损计划</span>
                  <p>{{ selectedStock.position.stop_loss_plan }}</p>
                </template>
                <template v-if="selectedStock.watch">
                  <span>加入观察时间</span>
                  <p>{{ formatDateTime(selectedStock.watch.added_at) }}</p>
                  <span>观察依据</span>
                  <p>{{ selectedStock.watch.reason }}</p>
                  <span>入场 / 撤出观察条件</span>
                  <p>{{ selectedStock.watch.entry_condition || '模型持续研判' }} / {{ selectedStock.watch.exit_condition || '模型持续研判' }}</p>
                </template>
                <span>辅助材料</span>
                <p>{{ selectedStock.strategies.map((s: string) => strategyLabel(s)).join(' / ') || '已有模拟持仓' }}</p>
                <p v-for="(signal, i) in selectedStock.signals" :key="i">{{ signal.date }} · {{ signal.reason || '精选入池' }}</p>
              </div>
        </div>
      </DialogContent>
    </Dialog>
    <Dialog v-if="!historyMode" v-model:open="historyOpen">
      <DialogContent class="guardian-history-dialog sm:max-w-6xl">
        <DialogHeader><DialogTitle>研判历史</DialogTitle><DialogDescription class="sr-only">按日期与轮次查询研判记录</DialogDescription></DialogHeader>
        <GuardianResearchPanel v-if="historyOpen" :account="account" :enabled="false" :notify="false" history-mode />
      </DialogContent>
    </Dialog>
  </section>
</template>
<style scoped src="./GuardianTab.css"></style>
<style scoped>
.research-workspace { display:flex; flex-direction:column; flex:1; min-width:0; min-height:0; gap:var(--gap-2); }
.guardian-body,.guardian-pool,.guardian-report { width:100%; min-width:0; }
.guardian-body { align-items:stretch; }
.guardian-report { align-self:stretch; }
.guardian-report > .trading-report { width:100%; max-width:none; margin:0; border:0; border-radius:0; padding:18px 18px 10px; }
.guardian-report :deep(.report-plans td),.guardian-report :deep(.report-plans th) { text-align:left; }
.section-title-group { min-width:0; align-items:center; gap:8px; }
.section-title-group h3,.research-actions button { white-space:nowrap; }
.section-title-group h3 { flex:none; margin:0; }
.research-actions { display:flex; flex:none; align-items:center; gap:6px; margin-left:auto; }
.run-selector-inline { flex:1 1 260px; flex-wrap:nowrap; }
.run-selector-inline :deep(.choice-field) { width:auto; min-width:0; flex:1 1 180px; }
.run-selector-inline :deep(button[role=combobox]) { width:100%; }
.research-history { padding:var(--gap-2) var(--gap-3); flex-shrink:0; }
.pool-tip { font-size: var(--fs-micro); color: var(--mist); }
</style>

<style scoped>
.stock-detail-link { cursor:pointer; font-weight:600; text-align:left; color:var(--ink); border:0; background:transparent; box-shadow:none; text-decoration:none; }
.stock-detail-link:hover, .stock-detail-link:focus, .stock-detail-link:focus-visible { color:var(--seal); text-decoration:none; outline:none; border:0; box-shadow:none; }
.pool-title-and-scope { display:flex; align-items:center; flex-wrap:wrap; gap:8px; min-width:0; }
.pool-title-and-scope h3 { flex:none; }
.guardian-history-dialog { height:90dvh; display:flex; flex-direction:column; overflow:hidden; }
.research-workspace--history { flex:1 1 0%; overflow:hidden; }
.research-workspace--history .guardian-body { display:flex; flex:1 1 0%; min-height:0; }
.research-workspace--history .guardian-report { flex:1 1 0%; min-height:0; overflow:auto; }
.research-workspace--history .guardian-report > .guardian-section-head { display:none; }
.stock-detail-dialog .guardian-stock-detail { text-align:left; background:transparent; padding:16px 0 0; }
.stock-detail-dialog .guardian-stock-detail > span { display:block; font-weight:600; color:var(--text-secondary); margin-top:16px; }
.stock-detail-dialog .guardian-stock-detail > p { margin:6px 0 0; line-height:1.8; white-space:pre-wrap; overflow-wrap:anywhere; }
.stock-detail-metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; border-radius:10px; padding:16px; background:var(--surface-sunken); }
.stock-detail-metrics > div { display:grid; gap:6px; }
.stock-detail-metrics span { color:var(--muted); font-size:12px; }
.stock-detail-metrics b { font-variant-numeric:tabular-nums; }
@media(min-width:1024px) and (min-height:600px) {
  .guardian-body { flex:1 1 0%; min-height:0; align-items:stretch; overflow:hidden; }
  .guardian-pool,.guardian-report { min-height:0; overflow-y:auto; overscroll-behavior:contain; scrollbar-width:thin; }
  .guardian-section-head { flex-shrink:0; position:sticky; top:0; z-index:2; }
  .guardian-pool { overflow:hidden; }
  .guardian-stock-table { flex:1 1 0%; min-height:0; }
  .guardian-stock-table :deep([data-slot="table-container"]) { height:100%; }
  .guardian-stock-table :deep(table) { height:100%; }
  .guardian-stock-table :deep(thead) { height:44px; }
  .guardian-stock-table :deep(td) { height:48px; font-size:15px; padding:10px 12px; }
  .guardian-stock-table :deep(th) { font-size:14px; }
  .guardian-stock-name > .stock-detail-link { font:600 15px/1.5 var(--font-sans, sans-serif); color:var(--ink); }
  .guardian-stock-state,.guardian-plan { font-size:15px; }
  .guardian-pool-empty { flex:1; }
}
</style>

<style scoped src="./GuardianResearchPanel.mobile.css"></style>
