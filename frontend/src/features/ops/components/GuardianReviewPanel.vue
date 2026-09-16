<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getGuardianReports, getGuardianReview, runGuardianReview } from '@/shared/api/guardian'
import GuardianReportDocument from './GuardianReportDocument.vue'
import GuardianHistoryFilter from './GuardianHistoryFilter.vue'
import { useGuardianHistory } from '../composables/useGuardianHistory'
import type { GuardianReviewPeriod, GuardianReviewDetail } from '@/shared/types/guardian'

const props = defineProps<{ enabled: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const labels = { premarket: '盘前计划', daily: '日复盘', weekly: '周复盘' }
const { range, page, items: reports, total, loading: listLoading, error: listError, load, apply, changePage, todayOnly } = useGuardianHistory(getGuardianReports)
const selected = ref('')
const pending = ref('')
const detail = shallowRef<GuardianReviewDetail | null>(null)
const error = ref('')
const busy = ref(false)
const loading = ref(false)
let controller: AbortController | undefined
let disposed = false
const active = computed(() => reports.value.find(r => r.report_key === selected.value))
watch(reports, rows => {
  if (pending.value && rows.some(r => r.report_key === pending.value)) {
    selected.value = pending.value; pending.value = ''
  }
  if (!rows.some(r => r.report_key === selected.value)) selected.value = rows[0]?.report_key ?? ''
})
async function loadDetail(): Promise<void> {
  controller?.abort()
  detail.value = null; error.value = ''; loading.value = false
  const report = active.value
  if (!report) return
  const request = new AbortController(); controller = request
  loading.value = true
  try {
    const value = await getGuardianReview(report.period, report.trade_date, request.signal)
    if (!disposed && !request.signal.aborted) detail.value = value
  } catch (e) { if (!disposed && !request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (controller === request) loading.value = false }
}
watch(() => JSON.stringify([selected.value, active.value?.status, active.value?.started, active.value?.created_at, active.value?.notify]), () => { void loadDetail() })
onUnmounted(() => { disposed = true; controller?.abort() })
async function generate(period: GuardianReviewPeriod): Promise<void> {
  busy.value = true; error.value = ''
  try {
    const result = await runGuardianReview(period)
    if (disposed) return
    pending.value = result.report_key; selected.value = result.report_key
    todayOnly()
    ElMessage.info('报告已提交后台生成，完成后自动更新'); emit('changed')
  } catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>

<template>
  <section class="review-panel" aria-label="复盘与计划">
    <header><div><h3>复盘与计划</h3><p>默认今天 · 历史报告按日期查询</p></div><el-select v-if="reports.length" v-model="selected" aria-label="选择交易员报告" class="review-select"><el-option v-for="r in reports" :key="r.report_key" :value="r.report_key" :label="`${r.trade_date} ${labels[r.period]} · ${r.status === 'success' ? '已完成' : r.status === 'running' ? '生成中' : '未完成'}`" /></el-select></header>
    <GuardianHistoryFilter :value="range" :loading="listLoading" @apply="apply" />
    <el-pagination :current-page="page" :page-size="range.limit" :total="total" layout="total, prev, pager, next" :disabled="listLoading" @current-change="changePage" />
    <div class="review-actions"><el-button :disabled="!props.enabled" :loading="busy" @click="generate('premarket')">生成盘前计划</el-button><el-button :disabled="!props.enabled" :loading="busy" @click="generate('daily')">生成今日日复盘</el-button><el-button :disabled="!props.enabled" :loading="busy" @click="generate('weekly')">生成本周复盘</el-button><span>仅生成当前报告；历史查询不会触发模型或推送</span></div>
    <el-alert v-if="listError" :title="listError" type="error" :closable="false" show-icon><el-button link @click="load()">重试列表</el-button></el-alert>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon><el-button v-if="active" link @click="loadDetail">重试详情</el-button></el-alert>
    <el-skeleton v-if="loading || (listLoading && !reports.length)" :rows="3" animated />
    <template v-else-if="detail">
      <el-alert v-if="detail.status === 'failed'" :title="detail.result.error || '本次报告未完成，后续自动补跑或手动重试'" type="warning" :closable="false" show-icon />
      <p v-else-if="detail.status === 'running'" class="review-note">正在核对账本、行情和交易计划，结果将自动更新…</p>
      <GuardianReportDocument v-if="detail.result.sections?.length" :sections="detail.result.sections" :period="detail.period" />
      <pre v-else-if="detail.result.body" class="review-body">{{ detail.result.body }}</pre>
      <footer v-if="detail.status === 'success'">{{ detail.result.notify?.success ? '通知已送达' : detail.result.notify?.skipped ? '通知按策略跳过' : '报告已保存，通知状态待确认' }} · 经验以证据为依据，尚待验证，不自动改写交易约束</footer>
    </template>
    <p v-else-if="pending" class="review-note">报告任务已提交，正在等待生成记录…</p>
    <el-empty v-else-if="!error && !listError" description="所选日期暂无报告，可调整日期查询历史" :image-size="64" />
  </section>
</template>

<style scoped>
.review-panel { padding: var(--gap-3); border: 1px solid var(--rule); border-radius: var(--radius); background: var(--surface); flex: 1 1 auto; min-width: 0; min-height: 0; overflow: auto; overscroll-behavior: contain; }
header { display: flex; justify-content: space-between; align-items: center; gap: var(--gap-3); flex-wrap: wrap; }
h3 { margin: 0; font-size: var(--fs-body); }
header p, .review-note, footer, .review-actions > span { font-size: var(--fs-aux); color: var(--muted); line-height: 1.8; }
header p { margin: var(--gap-1) 0 0; }
.review-select { width: 290px; max-width: 100%; }
.review-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--gap-2); margin-block: var(--gap-3); }
.review-actions .el-button { margin-left: 0; }
.review-body { white-space: pre-wrap; overflow-wrap: anywhere; padding: var(--gap-3); background: var(--surface-canvas); font-family: inherit; font-size: var(--fs-body); line-height: 1.9; font-variant-numeric: tabular-nums; }
footer { border-top: 1px solid var(--rule-soft); padding-top: var(--gap-2); }
</style>
