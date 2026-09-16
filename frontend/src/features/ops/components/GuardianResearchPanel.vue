<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Document } from '@element-plus/icons-vue'
import { getGuardianResearch, getGuardianRuns, getGuardianRun, scanGuardian } from '@/shared/api/guardian'
import { price, shortTime, strategyLabel } from '@/shared/lib/format'
import { GUARDIAN_ACTION_LABELS } from '@/shared/types/guardian'
import type { GuardianAccount, GuardianResearch, GuardianWatch, GuardianDecision, GuardianRun } from '@/shared/types/guardian'
import GuardianHistoryFilter from './GuardianHistoryFilter.vue'
import { useGuardianHistory } from '../composables/useGuardianHistory'
const props = defineProps<{ account: GuardianAccount; enabled: boolean; notify: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const data = shallowRef<GuardianResearch>({})
const { range, page, items: runs, total, loading: listLoading, error: listError, load, apply, changePage, todayOnly } = useGuardianHistory(getGuardianRuns)
const selectedRun = ref('')
const latest = shallowRef<GuardianRun | null>(null)
const detailLoading = ref(false)
const error = ref('')
const busy = ref(false)
const researchLoading = ref(false)
const filter = ref('all')
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
  try { await scanGuardian(); if (!disposed) { ElMessage.info('已开始一轮研判，结果将自动更新'); todayOnly(); emit('changed') } }
  catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
const pool = computed(() => {
  const map = new Map<string, GuardianWatch>((data.value?.watchlist ?? []).map(r => [r.code, r]))
  for (const p of props.account.positions ?? []) map.set(p.code, { ...(map.get(p.code) ?? { code: p.code, name: p.name, signals: [], strategies: p.strategies ?? [] }), position: p })
  return [...map.values()].sort((a, b) => Number(Boolean(b.position)) - Number(Boolean(a.position)))
})
const rows = computed(() => pool.value.filter(r => filter.value === 'all' || (filter.value === 'self' ? Boolean(r.watch) : filter.value === 'holding' ? Boolean(r.position) : !r.position)))
const decisions = computed(() => latest.value?.result.decisions ?? [])
const decisionByCode = computed(() => {
  const map = new Map<string, GuardianDecision>()
  for (const run of (latest.value ? [latest.value] : [])) for (const item of run.result.decisions ?? []) if (!map.has(item.code)) map.set(item.code, item)
  return map
})
function actionLabel(item: GuardianDecision) { return GUARDIAN_ACTION_LABELS[item.action] }
function stockName(code: string) { return pool.value.find(p => p.code === code)?.name ?? code }
function plan(row: GuardianWatch) { return row.position?.holding_plan || row.watch?.entry_condition || row.watch?.reason || decisionByCode.value.get(row.code)?.holding_plan || row.position?.last_review?.reason || decisionByCode.value.get(row.code)?.reason || (row.position ? '持有周期由模型管理' : '等待模型研判') }
function since(row: GuardianWatch) { return row.position?.entry_context?.opened_at?.slice(0, 10) || row.signals.at(-1)?.date || '—' }
onMounted(() => { void loadResearch() })
onUnmounted(() => { disposed = true; controller?.abort(); researchController?.abort() })
</script>
<template>
  <section class="research-workspace" aria-label="观察与研判">
    <el-alert v-if="listError || error" :title="listError || error" type="error" :closable="false"><el-button link @click="load(); loadResearch(); loadDetail()">重试</el-button></el-alert>
    <el-button class="research-refresh" link :loading="researchLoading" @click="loadResearch">刷新观察池</el-button>
      <div class="guardian-materials"><span>自动提供</span><span v-for="s in data.active_strategies" :key="s.slug" class="guardian-strategy">{{ s.name }}</span><span v-if="!data.active_strategies?.length">已开启战法将在这里同步</span><span class="guardian-materials__note">股票池 · 持仓 · 历史操作</span></div>
      <div class="guardian-body">
        <section class="guardian-pool" aria-label="交易参考池">
          <div class="guardian-section-head"><div><h3>交易参考池</h3><span>{{ data.watchlist_note || '策略仅提供参考 · 模型可自主选择池外股票' }}</span></div><span class="guardian-count">{{ pool.length }} 只</span></div>
          <div class="guardian-pool-toolbar"><el-radio-group v-model="filter" aria-label="股票池范围"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="holding">持有</el-radio-button><el-radio-button value="watching">未持仓</el-radio-button><el-radio-button value="self">自主观察</el-radio-button></el-radio-group><span>全市场自主交易 · 清仓后可再次买入</span></div>
          <el-table v-if="rows.length" :data="rows" row-key="code" class="guardian-stock-table" height="100%">
            <el-table-column type="expand" width="32"><template #default="{ row }"><div class="guardian-stock-detail"><span>持有计划</span><p>{{ plan(row) }}</p><template v-if="row.position?.take_profit_plan"><span>止盈计划</span><p>{{ row.position.take_profit_plan }}</p></template><template v-if="row.position?.stop_loss_plan"><span>止损计划</span><p>{{ row.position.stop_loss_plan }}</p></template><template v-if="row.watch"><span>自主观察依据</span><p>{{ row.watch.reason }}</p><span>入场 / 撤出观察条件</span><p>{{ row.watch.entry_condition || '模型持续研判' }} / {{ row.watch.exit_condition || '模型持续研判' }}</p></template><span>辅助材料</span><p>{{ row.strategies.map((s: string) => strategyLabel(s)).join(' / ') || '已有模拟持仓' }}</p><p v-for="(signal, i) in row.signals" :key="i">{{ signal.date }} · {{ signal.reason || '精选入池' }}</p></div></template></el-table-column>
            <el-table-column label="股票" min-width="135"><template #default="{ row }"><div class="guardian-stock-name"><b>{{ row.name }}（{{ row.code }}）</b><span>{{ since(row) }}</span></div></template></el-table-column>
            <el-table-column label="状态" width="82"><template #default="{ row }"><span class="guardian-stock-state" :class="{ held: row.position }">{{ row.position ? '持股' : row.watch ? '自主观察' : '策略参考' }}</span></template></el-table-column>
            <el-table-column label="持仓股数" width="90" align="right"><template #default="{ row }">{{ row.position ? `${row.position.quantity} 股` : '—' }}</template></el-table-column>
            <el-table-column label="参考成本" width="86" align="right"><template #default="{ row }">{{ price(row.position?.average_cost) }}</template></el-table-column>
            <el-table-column label="模型管理计划" min-width="160"><template #default="{ row }"><span class="guardian-plan" :title="plan(row)">{{ plan(row) }}</span></template></el-table-column>
          </el-table>
          <div v-else class="guardian-pool-empty"><div class="guardian-empty-mark"><span /><span /><span /></div><strong>{{ filter === 'holding' ? '尚未建立持仓' : filter === 'watching' ? '暂无观察中的股票' : '等待精选股入池' }}</strong><p>{{ filter === 'holding' ? '是否买入、持有多久，由模型判断' : '近五个交易日的精选股会自动出现在这里' }}</p></div>
          <footer class="guardian-pool-foot"><span>持有周期由模型自主决定</span><span>本金 20 万元 · 精确股数记账</span></footer>
        </section>
        <aside class="guardian-report" aria-label="交易研判">
          <div class="guardian-section-head"><div><h3>模型研判</h3><span>本轮判断与持仓管理</span></div><el-button link :disabled="busy || !enabled" @click="scan">立即研判</el-button></div>
          <div class="research-history"><GuardianHistoryFilter :value="range" :loading="listLoading" @apply="apply" /><el-pagination :current-page="page" :page-size="range.limit" :total="total" layout="total, prev, pager, next" :disabled="listLoading" @current-change="changePage" /></div>
          <div v-if="runs.length" class="guardian-run-picker"><el-select v-model="selectedRun" :placeholder="shortTime(runs[0]?.slot ?? '')" aria-label="选择守护轮次"><el-option v-for="run in runs" :key="run.slot" :value="run.slot" :label="shortTime(run.slot)" /></el-select><span class="guardian-run-state" :class="{ failed: latest?.status === 'failed' }">{{ latest?.status === 'running' ? '研判中' : latest?.status === 'failed' ? '异常' : latest?.status === 'success' ? latest.result.outcome === 'no_action' ? '无动作' : '已完成' : '已中断' }}</span></div>
          <el-skeleton v-if="detailLoading" :rows="4" animated /><div v-else-if="latest" class="guardian-report-content">
            <p v-if="latest.result.analysis_only" class="guardian-analysis">本轮仅研判，未执行买卖。预案会在下一可交易轮次结合新行情重新核验。</p>
            <p v-if="latest.status === 'running'" class="guardian-analysis">正在读取材料并形成判断…</p><p v-else-if="latest.status === 'expired'" class="guardian-analysis">上轮运行中断，未写入模拟成交。</p><p v-else class="guardian-analysis" :class="{ failed: latest.status === 'failed' }">{{ latest.result.error || latest.result.analysis || latest.result.body }}</p>
            <div v-for="(item, i) in decisions" :key="`${item.code}-${i}`" class="guardian-decision"><div><span class="guardian-decision__action">{{ actionLabel(item) }}</span><b>{{ stockName(item.code) }}</b><span class="guardian-code">{{ item.code }}</span></div><p>{{ item.reason }}</p><p v-if="item.holding_plan" class="guardian-decision__plan">持股计划：{{ item.holding_plan }}</p><p v-if="item.take_profit_plan">止盈：{{ item.take_profit_plan }}</p><p v-if="item.stop_loss_plan">止损：{{ item.stop_loss_plan }}</p><p v-if="item.entry_condition">等待入场：{{ item.entry_condition }}</p><p v-if="item.exit_condition">撤出观察：{{ item.exit_condition }}</p></div>
            <div v-if="latest.result.fills?.length || latest.result.rejects?.length" class="guardian-execution"><h4>模拟执行</h4><p v-for="(fill, i) in latest.result.fills" :key="i">{{ fill.name || stockName(fill.code) }} · <template v-if="fill.quantity != null">{{ fill.quantity }} 股 · {{ fill.before_quantity }} → {{ fill.after_quantity }} 股 · {{ price((fill.price_cents ?? 0) / 100) }} 元</template><template v-else>历史层数记录 {{ fill.before_layers }} → {{ fill.after_layers }} 层 · {{ price(fill.price) }}</template></p><p v-for="(reject, i) in latest.result.rejects" :key="`reject-${i}`" class="failed">{{ reject.code }} · 未执行：{{ reject.reason }}</p></div>
          </div>
          <div v-else class="guardian-report-empty"><el-icon><Document /></el-icon><strong>所选日期暂无研判</strong><p>可调整日期范围查询历史研判</p><span>可以持有，也可以调仓</span></div>
          <footer class="guardian-report-foot"><span>{{ latest?.result.notify ? latest.result.notify.success ? '本轮通知已送达' : latest.result.notify.skipped ? latest.result.notify.skipped === 'no_action' ? '无成交，已静默留存' : '本轮通知已跳过' : '本轮通知未送达' : notify ? '每轮合并推送' : '推送已关闭' }}</span><span>每轮同步账户和交易结果</span></footer>
        </aside>
      </div>
  </section>
</template>
<style scoped src="./GuardianTab.css"></style>
<style scoped>
.research-workspace { display:flex; flex-direction:column; flex:1; min-width:0; min-height:0; gap:var(--gap-2); }
.research-history { padding:var(--gap-2) var(--gap-3); flex-shrink:0; }
.research-refresh { align-self:flex-end; }
</style>
