<script setup lang="ts">
import { onUnmounted, ref, shallowRef, watch } from 'vue'
import { Refresh, Document } from '@element-plus/icons-vue'
import { getAgentHistory, getAgentRun } from '@/shared/api/stock_agents'
import type { AgentHistoryKind, AgentHistoryRow, AgentPage, AgentRunDetail } from '@/shared/types/stock_agents'
import { actionName, agentMoney, agentTime, phaseName, statusName } from '../agentFormat'
const props = defineProps<{ id:string; kind:AgentHistoryKind; refreshKey?:string | number }>()
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
async function load() {
  controller?.abort(); controller = new AbortController()
  const request = controller; const current = ++version
  loading.value = true; error.value = ''
  try { const result = await getAgentHistory(props.id,props.kind,(page.value-1)*20,dates.value?.[0],dates.value?.[1],request.signal); if (!disposed && current === version) rows.value = result }
  catch(e) { if (!disposed && !request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (current === version) loading.value = false }
}
function dateChanged() { page.value = 1; void load() }
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
  <section class="agent-history" :aria-label="kind === 'runs' ? '工作日记' : kind === 'trades' ? '成交记录' : '资金流水'">
    <header><div><h3>{{ kind === 'runs' ? '工作日记' : kind === 'trades' ? '实际模拟成交' : '资金流水' }}<span>{{ rows.total.toLocaleString() }} 条</span></h3><p>{{ kind === 'runs' ? '列表仅加载摘要，完整决策按需打开。翻阅历史时不会被实时刷新跳回第一页。' : kind === 'trades' ? '只包含已经记入账本的模拟成交，不包含观察及被拒绝的意图。' : '初始资金与追加资金独立记账，不混入交易盈亏。' }}</p></div><el-button :icon="Refresh" circle :loading="loading" aria-label="刷新当前历史页" @click="load" /></header>
    <div class="date-filter"><el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" unlink-panels @change="dateChanged" /><span>北京时间 · 每页 20 条</span></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-skeleton v-if="loading && !rows.items.length" :rows="7" animated />
    <div v-else-if="kind === 'runs' && rows.items.length" class="diary-list">
      <article v-for="row in rows.items" :key="row.id" class="diary-row"><div class="diary-mark"><el-icon><Document /></el-icon></div><div class="diary-content"><div class="diary-meta"><strong>{{ phaseName(row.phase) }}</strong><span>{{ statusName(row.status) }}</span><time>{{ agentTime(row.started_at) }}</time></div><p>{{ row.summary || (row.status === 'running' ? '正在研究市场与账户，完成后显示结果。' : '本轮没有文字摘要') }}</p><div class="diary-actions"><span v-for="(action,i) in row.actions?.slice(0,5)" :key="i">{{ actionName(action.action) }} {{ action.name || action.code }}<small>{{ statusName(action.status) }}</small></span></div></div><el-button link type="primary" @click="inspect(row)">查看详情</el-button></article>
    </div>
    <el-table v-else-if="kind !== 'runs' && rows.items.length" :data="rows.items" class="financial-history" empty-text="暂无记录">
      <el-table-column label="时间" min-width="135"><template #default="{ row }">{{ agentTime(row.at) }}</template></el-table-column>
      <template v-if="kind === 'trades'"><el-table-column label="股票" min-width="140"><template #default="{ row }"><b>{{ row.name || '名称待核对' }}</b><small class="code">{{ row.code }}</small></template></el-table-column><el-table-column label="操作" min-width="90"><template #default="{ row }">{{ actionName(row.action || row.side) }}</template></el-table-column><el-table-column prop="quantity" label="股数" width="90" align="right" /><el-table-column label="价格（元）" min-width="110" align="right"><template #default="{ row }">{{ agentMoney(row.price_cents) }}</template></el-table-column><el-table-column label="成交金额（元）" min-width="140" align="right"><template #default="{ row }">{{ agentMoney(row.gross_cents) }}</template></el-table-column><el-table-column label="费用（元）" min-width="100" align="right"><template #default="{ row }">{{ agentMoney(row.fees_cents) }}</template></el-table-column></template>
      <template v-else><el-table-column label="类型" min-width="160"><template #default="{ row }">{{ row.kind === 'initial' ? '初始模拟资金' : '追加模拟资金' }}</template></el-table-column><el-table-column label="金额（元）" min-width="160" align="right"><template #default="{ row }">+{{ agentMoney(row.amount_cents) }}</template></el-table-column></template>
    </el-table>
    <el-empty v-else :description="dates ? '这个日期范围内没有记录' : '尚无记录'" :image-size="70" />
    <div class="history-pagination"><el-pagination v-model:current-page="page" :total="rows.total" :page-size="20" layout="total, prev, pager, next" :pager-count="5" :disabled="loading" @current-change="load" /></div>
    <el-drawer v-model="detailOpen" title="工作日记详情" size="min(720px, 100vw)" destroy-on-close @closed="detailController?.abort()">
      <el-skeleton v-if="detailLoading" :rows="10" animated /><el-alert v-else-if="detailError" :title="detailError" type="error" :closable="false" />
      <article v-else-if="detail" class="diary-detail"><div class="detail-meta"><el-tag>{{ phaseName(detail.phase) }}</el-tag><span>{{ statusName(detail.status) }}</span><time>{{ agentTime(detail.started_at) }}</time></div><p class="summary">{{ detail.detail.summary || detail.summary }}</p><el-alert v-if="detail.detail.analysis_only" title="本轮只形成判断和计划，不执行模拟成交" type="info" :closable="false" />
        <h4 v-if="detail.detail.decisions?.length">本轮决策</h4><section v-for="(decision,i) in detail.detail.decisions" :key="i" class="decision"><header><b>{{ actionName(decision.action) }} · {{ decision.name || decision.code }}</b><span v-if="decision.quantity">{{ decision.quantity }} 股</span></header><p>{{ decision.reason }}</p></section>
        <h4 v-if="detail.detail.rejects?.length">未执行及原因</h4><section v-for="(reject,i) in detail.detail.rejects" :key="i" class="decision reject"><b>{{ reject.code }} {{ actionName(reject.action) }}</b><p>{{ reject.reason }}</p></section>
        <div v-if="detail.detail.usage" class="usage"><span v-if="detail.detail.usage.model">模型 {{ detail.detail.usage.model }}</span><span v-if="detail.detail.usage.elapsed_ms != null">耗时 {{ (detail.detail.usage.elapsed_ms/1000).toFixed(1) }} 秒</span><span v-if="detail.detail.usage.input_tokens != null">输入 {{ detail.detail.usage.input_tokens.toLocaleString() }} tokens</span><span v-if="detail.detail.usage.output_tokens != null">输出 {{ detail.detail.usage.output_tokens.toLocaleString() }} tokens</span></div>
      </article>
    </el-drawer>
  </section>
</template>
<style scoped>
.agent-history { border:1px solid var(--line); border-radius:12px; padding:26px; background:var(--el-bg-color); min-width:0; }header { display:flex; justify-content:space-between; gap:20px; align-items:flex-start; }h3 { font-size:16px; font-weight:600; margin:0 0 9px; }h3 span { font-size:12px; color:var(--muted); margin-left:12px; font-weight:400; }header p { color:var(--muted); font-size:12px; line-height:1.8; margin:0; }.date-filter { display:flex; align-items:center; flex-wrap:wrap; gap:18px; margin:25px 0; }.date-filter :deep(.el-date-editor) { max-width:340px; flex-grow:0; }.date-filter>span { font-size:11px; color:var(--muted); }.diary-row { display:flex; gap:17px; padding:24px 0; border-top:1px solid var(--line); align-items:flex-start; }.diary-mark { width:32px; height:32px; border-radius:8px; background:var(--el-fill-color-light); display:grid; place-items:center; color:var(--muted); flex-shrink:0; }.diary-content { min-width:0; flex:1; }.diary-meta { display:flex; flex-wrap:wrap; align-items:center; gap:12px; font-size:11px; color:var(--muted); }.diary-meta strong { font-size:13px; color:var(--ink); }.diary-content>p { font-size:13px; line-height:1.9; margin:10px 0 12px; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; overflow-wrap:anywhere; }.diary-actions { display:flex; flex-wrap:wrap; gap:8px; }.diary-actions>span { background:var(--el-fill-color-lighter); padding:5px 9px; border-radius:5px; font-size:11px; }.diary-actions small { color:var(--muted); margin-left:7px; }.history-pagination { display:flex; justify-content:flex-end; margin-top:24px; overflow:auto; }.code { display:block; font-size:11px; color:var(--muted); }.detail-meta { display:flex; align-items:center; flex-wrap:wrap; gap:12px; font-size:12px; color:var(--muted); }.summary { white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.95; font-size:14px; margin:25px 0; }.diary-detail h4 { margin:30px 0 15px; }.decision { padding:18px 0; border-bottom:1px solid var(--line); }.decision header,.decision b { font-size:13px; }.decision p { margin:10px 0 0; line-height:1.9; font-size:13px; white-space:pre-wrap; overflow-wrap:anywhere; }.reject { color:var(--el-color-warning); }.usage { display:flex; flex-wrap:wrap; gap:12px; font-size:11px; color:var(--muted); margin:25px 0; }
@media(max-width:600px) { .agent-history { padding:19px 14px; }.diary-mark { display:none; }.diary-row { gap:10px; }.diary-row>.el-button { font-size:11px; }.date-filter :deep(.el-date-editor) { width:100%; }.history-pagination { justify-content:flex-start; } }
</style>
