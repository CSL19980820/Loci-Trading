<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getGuardianReview, runGuardianReview } from '@/shared/api/guardian'
import GuardianReportDocument from './GuardianReportDocument.vue'
import type { GuardianReviewSummary, GuardianReviewPeriod, GuardianReviewDetail } from '@/shared/types/guardian'

const props = defineProps<{ reports: GuardianReviewSummary[]; enabled: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const labels = { premarket: '盘前计划', daily: '日复盘', weekly: '周复盘' }
const selected = ref('')
const pending = ref('')
const detail = ref<GuardianReviewDetail | null>(null)
const error = ref('')
const busy = ref(false)
const loading = ref(false)
let controller: AbortController | undefined
const active = computed(() => props.reports.find(r => r.report_key === selected.value))
watch(() => props.reports, rows => {
  if (pending.value) {
    if (!rows.some(r => r.report_key === pending.value)) return
    selected.value = pending.value; pending.value = ''
  }
  if (!rows.some(r => r.report_key === selected.value)) selected.value = rows[0]?.report_key ?? ''
}, { immediate: true })
watch([() => selected.value, () => active.value?.status, () => active.value?.created_at, () => active.value?.notify?.success, () => active.value?.notify?.skipped], async () => {
  controller?.abort()
  if (!active.value) { detail.value = null; return }
  const request = new AbortController(); controller = request
  loading.value = true
  try {
    const value = await getGuardianReview(active.value.period, active.value.trade_date, request.signal)
    if (!request.signal.aborted) { detail.value = value; error.value = '' }
  } catch (e) { if (!request.signal.aborted) error.value = e instanceof Error ? e.message : String(e) }
  finally { if (controller === request) loading.value = false }
}, { immediate: true })
onUnmounted(() => controller?.abort())
async function generate(period: GuardianReviewPeriod) {
  busy.value = true; error.value = ''
  try { const result = await runGuardianReview(period); pending.value = result.report_key; selected.value = result.report_key; ElMessage.info('报告已提交后台生成，完成后自动更新'); emit('changed') }
  catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>

<template>
  <section class="review-panel" aria-label="复盘与计划">
    <header><div><h3>复盘与计划</h3><p>08:50 盘前计划 · 15:45 日复盘 · 每周最后交易日 15:55 周复盘</p></div><el-select v-if="reports.length" v-model="selected" aria-label="选择交易员报告" class="review-select"><el-option v-for="r in reports" :key="r.report_key" :value="r.report_key" :label="`${r.trade_date} ${labels[r.period]} · ${r.status === 'success' ? '已完成' : r.status === 'running' ? '生成中' : '未完成'}`" /></el-select></header>
    <div class="review-actions"><el-button :disabled="!enabled" :loading="busy" @click="generate('premarket')">生成盘前计划</el-button><el-button :disabled="!enabled" :loading="busy" @click="generate('daily')">生成今日日复盘</el-button><el-button :disabled="!enabled" :loading="busy" @click="generate('weekly')">生成本周复盘</el-button><span>收盘行情未就绪会等待补跑；已完成报告不会重复生成和推送</span></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-skeleton v-if="loading" :rows="3" animated />
    <template v-else-if="detail">
      <el-alert v-if="detail.status === 'failed'" :title="detail.result.error || '本次报告未完成，后续自动补跑或手动重试'" type="warning" :closable="false" show-icon />
      <p v-else-if="detail.status === 'running'" class="review-note">正在核对账本、行情和交易计划，结果将自动更新…</p>
      <GuardianReportDocument v-if="detail.result.sections?.length" :sections="detail.result.sections" :period="detail.period" />
      <pre v-else-if="detail.result.body" class="review-body">{{ detail.result.body }}</pre>
      <footer v-if="detail.status === 'success'">{{ detail.result.notify?.success ? '通知已送达' : detail.result.notify?.skipped ? '通知按策略跳过' : '报告已保存，通知状态待确认' }} · 经验以证据为依据，尚待验证，不自动改写交易约束</footer>
    </template>
    <p v-else-if="pending" class="review-note">报告任务已提交，正在等待生成记录…</p>
    <p v-else class="review-note">尚无报告。盘前准备条件化计划，盘后核对逐股收益与费用；交易员会在后续研判中读取这些计划和待验证经验。</p>
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
.review-body { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 440px; overflow: auto; padding: var(--gap-3); background: var(--surface-canvas); font-family: inherit; font-size: var(--fs-body); line-height: 1.9; font-variant-numeric: tabular-nums; }
footer { border-top: 1px solid var(--rule-soft); padding-top: var(--gap-2); }
</style>
