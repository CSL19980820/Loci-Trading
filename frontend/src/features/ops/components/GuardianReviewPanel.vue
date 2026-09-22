<script setup lang="ts">
import { toast } from 'vue-sonner'
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from '@/shared/components/ui/dropdown-menu'
import { Button } from '@/shared/components/ui/button'
import { Badge } from '@/shared/components/ui/badge'
import { Sparkles, LoaderCircle, ChevronDown } from '@lucide/vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { default as Pager } from '@/shared/components/ui/app/Pager.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { Notice, SkeletonBlock, EmptyBlock } from '@/shared/components/ui/app/presentation'

import { computed, nextTick, onUnmounted, ref, shallowRef, watch } from 'vue'

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
const documentScroll = ref<HTMLElement | null>(null)
watch(selected, async () => { await nextTick(); if (documentScroll.value) documentScroll.value.scrollTop = 0 })
const pending = ref('')
const pendingPeriod = ref<GuardianReviewPeriod | ''>('')
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
  if (busy.value || !props.enabled) return
  busy.value = true; pendingPeriod.value = period; error.value = ''
  try {
    const result = await runGuardianReview(period)
    if (disposed) return
    pending.value = result.report_key; selected.value = result.report_key
    todayOnly()
    toast.info('报告已提交后台生成，完成后自动更新'); emit('changed')
  } catch (e) { if (!disposed) error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false; pendingPeriod.value = '' }
}
</script>

<template>
  <section class="review-panel" aria-label="复盘与计划">
    <div class="review-toolbar">
      <GuardianHistoryFilter :value="range" :loading="listLoading" @apply="apply" />
      <div v-if="reports.length" class="report-selector-inline">
        <span class="report-label">报告</span>
        <ChoiceField v-model="selected" aria-label="选择交易员报告" class="report-choice">
          <ChoiceOption v-for="r in reports" :key="r.report_key" :value="r.report_key" :label="`${r.trade_date} ${labels[r.period]}`" />
        </ChoiceField>
        <Badge
          variant="outline"
          class="h-7 text-[11px] font-normal gap-1.5 px-2 shrink-0"
          :class="{
            'border-gain/40 text-gain': active?.status === 'success',
            'border-loss/40 text-loss': active?.status === 'failed',
            'border-seal/40 text-seal': active?.status === 'running',
          }"
        >
          <span
            class="size-1.5 rounded-full"
            :class="{
              'bg-gain': active?.status === 'success',
              'bg-loss': active?.status === 'failed',
              'bg-seal animate-pulse': active?.status === 'running',
            }"
          />
          {{ active?.status === 'success' ? '已完成' : active?.status === 'running' ? '生成中' : '未完成' }}
        </Badge>
      </div>
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <Button variant="outline" size="sm" class="review-generate" :disabled="!props.enabled || busy">
            <LoaderCircle v-if="busy" class="animate-spin" aria-hidden="true" />
            <Sparkles v-else aria-hidden="true" />
            {{ busy && pendingPeriod ? `生成${labels[pendingPeriod]}中` : '生成报告' }}
            <ChevronDown aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem v-for="(label, period) in labels" :key="period" @select="generate(period)">生成{{ label }}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
    <div v-if="total > range.limit" class="review-pagination">
      <Pager v-if="total > range.limit" :current-page="page" :page-size="range.limit" :total="total" layout="prev, pager, next" :disabled="listLoading" @current-change="changePage" />
    </div>

    <div ref="documentScroll" class="review-document-scroll" tabindex="0" aria-label="报告内容">
    <Notice v-if="listError" :title="listError" tone="error" :closable="false" show-icon><ActionButton access="read" variant="link" @click="load()">重试列表</ActionButton></Notice>
    <Notice v-if="error" :title="error" tone="error" :closable="false" show-icon><ActionButton v-if="active" variant="link" @click="loadDetail">重试详情</ActionButton></Notice>
    <SkeletonBlock v-if="loading || (listLoading && !reports.length)" :rows="3" animated />
    <template v-else-if="detail">
      <Notice v-if="detail.status === 'failed'" :title="detail.result.error || '本次报告未完成，后续自动补跑或手动重试'" tone="warning" :closable="false" show-icon />
      <p v-else-if="detail.status === 'running'" class="review-note">正在核对账本、行情和交易计划，结果将自动更新…</p>
      <GuardianReportDocument v-if="detail.result.sections?.length" :sections="detail.result.sections" :period="detail.period" :title="labels[detail.period]" :metadata="`${detail.trade_date} · 自主交易员 · 第${detail.result.revision ?? 1}版`" />
      <pre v-else-if="detail.result.body" class="review-body">{{ detail.result.body }}</pre>
      <footer v-if="detail.status === 'success'">{{ detail.result.notify?.success ? '通知已送达' : detail.result.notify?.skipped ? '通知按策略跳过' : '报告已保存，通知状态待确认' }}</footer>
    </template>
    <p v-else-if="pending" class="review-note">报告任务已提交，正在等待生成记录…</p>
    <EmptyBlock v-else-if="!error && !listError" description="所选日期暂无报告，可调整日期查询历史" :image-size="64" />
    </div>
  </section>
</template>

<style scoped>
.review-panel {
  display: flex;
  flex-direction: column;
  gap: var(--workspace-gap,5px);
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  min-width: 0;
  color: var(--ink);
}

.review-toolbar, .review-control-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 12px;
  min-width: 0;
  flex: none;
}
.review-toolbar { container-type: inline-size; }
.review-generate { margin-left:auto; flex:none; }
.review-pagination { display:flex; justify-content:flex-end; flex:none; }
.review-control-bar { padding-bottom: 8px; border-bottom: 1px solid var(--rule-soft); }
.review-document-scroll { min-width:0; display:flex; flex-direction:column; gap:12px; background:var(--surface); border:1px solid var(--border-subtle); border-radius:10px; padding:12px; }
.review-document-scroll:has(> .empty-block) { justify-content:center; }
@media (min-width: 1024px) and (min-height: 600px) {
  .review-panel { flex: 1 1 0%; min-height: 0; overflow: hidden; }
  .review-document-scroll { flex: 1 1 0%; min-height: 0; overflow: auto; overscroll-behavior: contain; scrollbar-width: thin; }
  .review-document-scroll > * { flex-shrink: 0; }
}
.report-selector-inline {
  flex:1 1 290px;
  display: flex;
  align-items: center;
  flex-wrap:nowrap;
  min-width:0;
  max-width:100%;
  gap:6px;
}

.report-selector-inline :deep(.choice-field) {
  flex:1 1 200px;
  width:200px;
  min-width: 0;
  max-width: 100%;
}

.report-label {
  font-size: 11px;
  color: var(--muted);
  white-space: nowrap;
}

.review-note, footer {
  font-size: var(--fs-aux);
  color: var(--muted);
  line-height: 1.8;
}

.review-body {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  padding: var(--gap-3);
  background: var(--surface-canvas);
  border: 1px solid var(--rule-soft);
  border-radius: var(--radius-sm);
  font-family: inherit;
  font-size: var(--fs-body);
  line-height: 1.9;
  font-variant-numeric: tabular-nums;
}

footer {
  border-top: 1px solid var(--rule-soft);
  padding-top: var(--gap-2);
}
.review-document-scroll :deep(.trading-report) { width:100%; border:0; border-radius:0; }
@media(min-width:1250px) { .review-toolbar { flex-wrap:nowrap; } }
@media(max-width:767px) {
 .review-toolbar { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:7px; }
 .review-toolbar > :deep(.mobile-history-filter) { grid-column:1; grid-row:1; }
 .review-generate { grid-column:2; grid-row:1; min-height:36px; margin:0; font-size:12px; padding-inline:10px; }
 .report-selector-inline { grid-column:1/-1; grid-row:2; width:100%; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:7px; }
 .report-label { display:none; }
 .report-selector-inline :deep(.choice-field) { width:100%; max-width:none; min-width:0; }
 .report-selector-inline :deep(button[role=combobox]) { width:100%; min-height:36px; font-size:12px; }
 .report-selector-inline > :deep([data-slot=badge]) { height:30px; }
 .review-panel { flex:1 1 0%; min-height:0; overflow:hidden; gap:8px; }
 .review-document-scroll { flex:1 1 0%; min-height:0; padding:0; overflow-y:auto; overflow-x:hidden; gap:7px; overscroll-behavior:contain; }
 .review-document-scroll > * { flex-shrink:0; }
 .review-document-scroll :deep(.trading-report) { max-width:none; margin:0; padding:14px 12px 8px; font-size:14px; line-height:1.75; }
 .review-document-scroll :deep(.report-header h3) { font-size:19px; }
 .review-document-scroll :deep(.report-section) { padding-block:12px; }
 .review-document-scroll :deep(.kind-overview .report-paragraph) { font-size:14px; font-weight:550; }
 .review-document-scroll :deep(table td), .review-document-scroll :deep(table th) { text-align:left; }
 .review-document-scroll :deep(.report-plan-meta) { text-align:left; }
 .review-document-scroll > footer { padding:8px 12px; font-size:11px; }
}
</style>
