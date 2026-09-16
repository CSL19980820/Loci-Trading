<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Setting, Refresh, VideoPlay, VideoPause, Compass, Document } from '@element-plus/icons-vue'
import { getGuardian, saveGuardian, scanGuardian } from '@/shared/api/guardian'
import { getProviders } from '@/shared/api/quant'
import { price, shortTime, strategyLabel } from '@/shared/lib/format'
import { GUARDIAN_ACTION_LABELS } from '@/shared/types/guardian'
import type { GuardianStatus, GuardianConfig, GuardianWatch, GuardianDecision } from '@/shared/types/guardian'
import type { LlmProvider } from '@/shared/types/quant'
import GuardianSettingsDrawer from './GuardianSettingsDrawer.vue'
import GuardianAccountPanel from './GuardianAccountPanel.vue'
import GuardianReviewPanel from './GuardianReviewPanel.vue'
import GuardianConsultPanel from './GuardianConsultPanel.vue'

const data = ref<GuardianStatus | null>(null)
const providers = ref<LlmProvider[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const settingsOpen = ref(false)
const startOnSave = ref(false)
const settings = ref<InstanceType<typeof GuardianSettingsDrawer> | null>(null)
const section = ref('account')
const filter = ref('all')
const selectedRun = ref('')
const latest = computed(() => data.value?.runs.find(r => r.slot === selectedRun.value) ?? data.value?.runs[0])
const enabled = computed(() => data.value?.config.enabled ?? false)
const configured = computed(() => Boolean(data.value?.config.model && data.value.config.provider))
const allocation = computed(() => data.value?.state.equity_cents ? data.value.state.market_value_cents / data.value.state.equity_cents * 100 : 0)
const pool = computed(() => {
  const map = new Map<string, GuardianWatch>((data.value?.watchlist ?? []).map(r => [r.code, r]))
  for (const p of data.value?.state.positions ?? []) map.set(p.code, { ...(map.get(p.code) ?? { code: p.code, name: p.name, signals: [], strategies: p.strategies ?? [] }), position: p })
  return [...map.values()].sort((a, b) => Number(Boolean(b.position)) - Number(Boolean(a.position)))
})
const watchCount = computed(() => pool.value.filter(r => !r.position).length)
const rows = computed(() => pool.value.filter(r => filter.value === 'all' || (filter.value === 'self' ? Boolean(r.watch) : filter.value === 'holding' ? Boolean(r.position) : !r.position)))
const decisions = computed(() => latest.value?.result.decisions ?? [])
const decisionByCode = computed(() => {
  const map = new Map<string, GuardianDecision>()
  for (const run of data.value?.runs ?? []) for (const item of run.result.decisions ?? []) if (!map.has(item.code)) map.set(item.code, item)
  return map
})
const stateLabel = computed(() => data.value?.notification_silence ? data.value.notification_silence === 'market_closed' ? '休市静默' : '日历待核验' : latest.value?.status === 'running' ? '正在研判' : !configured.value ? '等待配置' : enabled.value ? '运行中' : '已暂停')
const emit = defineEmits<{ summary: [value: { tail: string; state: 'ok' | 'idle' | 'bad' }] }>()
let controller: AbortController | null = null
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
function accept(value: GuardianStatus) {
  data.value = value
  emit('summary', { tail: value.config.enabled ? '运行中' : '已暂停', state: value.config.enabled ? 'ok' : 'idle' })
}
async function load() {
  controller?.abort()
  const request = new AbortController()
  controller = request
  loading.value = true
  try {
    const [status, list] = await Promise.all([getGuardian(request.signal), getProviders()])
    if (disposed || request.signal.aborted) return
    accept(status); providers.value = list.filter(p => p.is_active); error.value = ''
  } catch (e) { if (!request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (controller === request) loading.value = false }
}
function configure(start = false) { startOnSave.value = start; settingsOpen.value = true; error.value = '' }
async function save(config: GuardianConfig) {
  controller?.abort()
  busy.value = true; error.value = ''
  try { accept(await saveGuardian(config)); settingsOpen.value = false; ElMessage.success('交易员配置已保存') }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
function toggle() {
  if (!data.value) return
  if (!configured.value && !enabled.value) return configure(true)
  void save({ ...data.value.config, enabled: !enabled.value })
}
async function scan() {
  controller?.abort()
  busy.value = true; error.value = ''
  try { await scanGuardian(); ElMessage.info('已开始一轮研判，结果将自动更新'); accept(await getGuardian()) }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
async function poll() {
  if (disposed) return
  if (data.value && !busy.value && !loading.value && !settingsOpen.value && !document.hidden) {
    const request = new AbortController(); controller = request
    try { const next = await getGuardian(request.signal); if (!disposed && !request.signal.aborted) accept(next) }
    catch (e) { if (!request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
  }
  if (!disposed) timer = setTimeout(poll, 10000)
}
function actionLabel(item: GuardianDecision) { return GUARDIAN_ACTION_LABELS[item.action] }
function stockName(code: string) { return pool.value.find(p => p.code === code)?.name ?? code }
function plan(row: GuardianWatch) { return row.position?.holding_plan || row.watch?.entry_condition || row.watch?.reason || decisionByCode.value.get(row.code)?.holding_plan || row.position?.last_review?.reason || decisionByCode.value.get(row.code)?.reason || (row.position ? '持有周期由模型管理' : '等待模型研判') }
function since(row: GuardianWatch) { return row.position?.entry_context?.opened_at?.slice(0, 10) || row.signals.at(-1)?.date || '—' }
onMounted(() => { timer = setTimeout(poll, 10000) })
onUnmounted(() => { disposed = true; controller?.abort(); clearTimeout(timer) })
defineExpose({ load, isDirty: () => settings.value?.isDirty() ?? false })
</script>

<template>
  <div class="guardian-workspace" aria-label="自主交易员">
    <header class="guardian-header">
      <div class="guardian-identity"><span class="guardian-symbol"><el-icon><Compass /></el-icon></span><h2>自主交易员</h2><span class="guardian-state" :class="{ 'is-running': enabled }"><i />{{ stateLabel }}</span></div>
      <div class="guardian-actions"><el-button :icon="Refresh" circle aria-label="刷新交易员" :disabled="busy || loading" @click="load" /><el-button :icon="Setting" :disabled="!data || busy" @click="configure()">交易员设置</el-button><el-button :icon="enabled ? VideoPause : VideoPlay" :type="enabled ? 'default' : 'primary'" :loading="busy" :disabled="!data" @click="toggle">{{ enabled ? '暂停交易员' : configured ? '启动交易员' : '配置并开启' }}</el-button></div>
    </header>
    <el-alert v-if="error && !settingsOpen" :title="error" type="error" :closable="false" show-icon />
    <el-skeleton v-if="loading && !data" class="guardian-loading" :rows="10" animated />
    <template v-if="data">
      <div class="guardian-context"><span>{{ data.config.model || '尚未选择模型' }}</span><span>交易时段每 5 分钟研判</span><span>持仓 {{ data.state.positions.length }} 只 · 仓位 {{ Number(allocation.toFixed(2)) }}% · 观察 {{ watchCount }} 只</span></div>
      <el-tabs v-model="section" class="guardian-navigation" aria-label="交易员工作区"><el-tab-pane label="账户与持仓" name="account" /><el-tab-pane label="复盘与计划" name="reviews" /><el-tab-pane label="观察与研判" name="research" /><el-tab-pane label="与交易员沟通" name="consult" /></el-tabs>
      <GuardianConsultPanel v-if="section === 'consult'" :model="data.config.model" />
      <GuardianAccountPanel v-show="section === 'account'" :account="data.state" :trades="data.trades" :performance="data.performance" />
      <GuardianReviewPanel v-if="section === 'reviews'" :reports="data.reports ?? []" :enabled="enabled" @changed="load" />
      <div v-show="section === 'research'" class="guardian-materials"><span>自动提供</span><span v-for="s in data.active_strategies" :key="s.slug" class="guardian-strategy">{{ s.name }}</span><span v-if="!data.active_strategies?.length">已开启战法将在这里同步</span><span class="guardian-materials__note">股票池 · 持仓 · 历史操作</span></div>
      <div v-show="section === 'research'" class="guardian-body">
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
          <div v-if="data.runs.length" class="guardian-run-picker"><el-select v-model="selectedRun" :placeholder="shortTime(data.runs[0]?.slot ?? '')" aria-label="选择守护轮次"><el-option v-for="run in data.runs" :key="run.slot" :value="run.slot" :label="shortTime(run.slot)" /></el-select><span class="guardian-run-state" :class="{ failed: latest?.status === 'failed' }">{{ latest?.status === 'running' ? '研判中' : latest?.status === 'failed' ? '异常' : latest?.status === 'success' ? latest.result.outcome === 'no_action' ? '无动作' : '已完成' : '已中断' }}</span></div>
          <div v-if="latest" class="guardian-report-content">
            <p v-if="latest.result.analysis_only" class="guardian-analysis">本轮仅研判，未执行买卖。预案会在下一可交易轮次结合新行情重新核验。</p>
            <p v-if="latest.status === 'running'" class="guardian-analysis">正在读取材料并形成判断…</p><p v-else-if="latest.status === 'expired'" class="guardian-analysis">上轮运行中断，未写入模拟成交。</p><p v-else class="guardian-analysis" :class="{ failed: latest.status === 'failed' }">{{ latest.result.error || latest.result.analysis || latest.result.body }}</p>
            <div v-for="(item, i) in decisions" :key="`${item.code}-${i}`" class="guardian-decision"><div><span class="guardian-decision__action">{{ actionLabel(item) }}</span><b>{{ stockName(item.code) }}</b><span class="guardian-code">{{ item.code }}</span></div><p>{{ item.reason }}</p><p v-if="item.holding_plan" class="guardian-decision__plan">持股计划：{{ item.holding_plan }}</p><p v-if="item.take_profit_plan">止盈：{{ item.take_profit_plan }}</p><p v-if="item.stop_loss_plan">止损：{{ item.stop_loss_plan }}</p><p v-if="item.entry_condition">等待入场：{{ item.entry_condition }}</p><p v-if="item.exit_condition">撤出观察：{{ item.exit_condition }}</p></div>
            <div v-if="latest.result.fills?.length || latest.result.rejects?.length" class="guardian-execution"><h4>模拟执行</h4><p v-for="(fill, i) in latest.result.fills" :key="i">{{ fill.name || stockName(fill.code) }} · <template v-if="fill.quantity != null">{{ fill.quantity }} 股 · {{ fill.before_quantity }} → {{ fill.after_quantity }} 股 · {{ price((fill.price_cents ?? 0) / 100) }} 元</template><template v-else>历史层数记录 {{ fill.before_layers }} → {{ fill.after_layers }} 层 · {{ price(fill.price) }}</template></p><p v-for="(reject, i) in latest.result.rejects" :key="`reject-${i}`" class="failed">{{ reject.code }} · 未执行：{{ reject.reason }}</p></div>
          </div>
          <div v-else class="guardian-report-empty"><el-icon><Document /></el-icon><strong>等待第一轮研判</strong><p>{{ configured ? '启动交易员后，这里会汇总模型的判断' : '配置模型后开始，辅助材料自动接入' }}</p><span>可以持有，也可以调仓</span></div>
          <footer class="guardian-report-foot"><span>{{ latest?.result.notify ? latest.result.notify.success ? '本轮通知已送达' : latest.result.notify.skipped ? latest.result.notify.skipped === 'no_action' ? '无成交，已静默留存' : '本轮通知已跳过' : '本轮通知未送达' : data.config.notify ? '每轮合并推送' : '推送已关闭' }}</span><span>每轮同步账户和交易结果</span></footer>
        </aside>
      </div>
      <GuardianSettingsDrawer ref="settings" v-model="settingsOpen" :config="data.config" :default-prompt="data.default_prompt" :providers="providers" :busy="busy" :error="error" :start-on-save="startOnSave" @save="save" />
    </template>
  </div>
</template>
<style scoped src="./GuardianTab.css"></style>
