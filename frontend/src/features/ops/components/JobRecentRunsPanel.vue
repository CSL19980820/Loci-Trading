<script setup lang="ts">
/**
 * 当前任务的最近执行历史：BasicTable（常规表，条数少不必虚拟化）。
 *
 * 失败原因**必须点得开**：`error_text` 在单元格里只放得下第一行，全文经
 * `JobRunErrorDialog` 展开并可整段复制。此前全文只挂在原生 `title` 上，
 * 读不完也复制不走。
 */
import { computed, ref, watch } from 'vue'
import { CircleCheck, CircleClose, WarningFilled } from '@element-plus/icons-vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import type { JobRun } from '@/shared/types/quant'

import JobRunErrorDialog from './JobRunErrorDialog.vue'
import {
  firstLine,
  formatRunDuration,
  statusLabel,
  triggerLabel,
} from '../composables/opsLabels'
import { useJobRunsQuery } from '../composables/useJobRunsQuery'

const props = defineProps<{
  jobId: string
}>()

const { runs, isPending, refetch } = useJobRunsQuery(() => ({
  job_id: props.jobId,
  limit: 200,
}))

/** 「只看失败」：一屏几十条成功记录里找那一条红的，靠肉眼扫是最慢的一步。 */
const failedOnly = ref(false)
const errorOpen = ref(false)
const activeRun = ref<JobRun | null>(null)

const visibleRuns = computed(() =>
  failedOnly.value ? runs.value.filter((run) => run.status === 'failed') : runs.value,
)
const tableRows = computed(() => visibleRuns.value as unknown as Record<string, unknown>[])
const runCount = computed(() => visibleRuns.value.length)
const failedCount = computed(() => runs.value.filter((run) => run.status === 'failed').length)

const columns = ref<BasicTableColumn[]>([
  {
    prop: 'started_at',
    label: '时间',
    minWidth: 168,
    align: 'center',
    headerAlign: 'center',
    showOverflowTooltip: true,
    formatter: (row) => formatStartedAt(String(row.started_at ?? '')),
  },
  {
    prop: 'trigger',
    label: '触发',
    width: 88,
    align: 'center',
    headerAlign: 'center',
    slotName: 'trigger',
  },
  {
    prop: 'duration_ms',
    label: '耗时',
    width: 104,
    align: 'center',
    headerAlign: 'center',
    slotName: 'duration',
  },
  {
    prop: 'status',
    label: '结果',
    minWidth: 220,
    align: 'left',
    headerAlign: 'left',
    showOverflowTooltip: true,
    slotName: 'result',
  },
])

function formatStartedAt(raw: string): string {
  const text = raw.trim()
  if (!text) return '—'
  return text.replace('T', ' ').slice(0, 19)
}

function statusType(status: string): 'success' | 'danger' | 'info' | 'warning' {
  if (status === 'failed') return 'danger'
  if (status === 'success') return 'success'
  if (status === 'running') return 'warning'
  return 'info'
}

function statusIcon(status: string) {
  if (status === 'failed') return CircleClose
  if (status === 'success') return CircleCheck
  return WarningFilled
}

async function reload(): Promise<void> {
  await refetch()
}

function openError(row: Record<string, unknown>): void {
  const id = String(row.id ?? '')
  activeRun.value = runs.value.find((run) => run.id === id) ?? null
  if (!activeRun.value) return
  errorOpen.value = true
}

/**
 * 直接把最近一条失败摊开。回执上的「上次失败 N」点进来就落在这里——
 * 少掉「猜是哪条任务 → 逐条点开 → 悬停读半句」三步。
 */
async function focusLatestFailure(): Promise<void> {
  await reload()
  const hit = runs.value.find((run) => run.status === 'failed')
  if (!hit) return
  failedOnly.value = true
  activeRun.value = hit
  errorOpen.value = true
}

watch(
  () => props.jobId,
  () => {
    failedOnly.value = false
    errorOpen.value = false
    activeRun.value = null
    void reload()
  },
  { immediate: true },
)

defineExpose({ reload, focusLatestFailure })
</script>

<template>
  <section class="job-runs-panel" aria-label="最近执行历史">
    <BasicTable
      v-model:columns="columns"
      class="job-runs-panel__table"
      :data-source="tableRows"
      :pagination="false"
      :toolbar-config="{ refresh: true }"
      :loading="isPending"
      stripe
      border
      size="small"
      row-key="id"
      max-height="22rem"
      empty-text="还没有执行记录"
      @refresh="reload"
    >
      <template #toolbarButtons>
        <div class="job-runs-panel__title">
          <strong>最近执行</strong>
          <span class="job-runs-panel__meta">仅当前任务</span>
          <el-tag size="small" effect="plain" type="info">{{ runCount }} 条</el-tag>
          <el-checkbox
            v-model="failedOnly"
            size="small"
            class="job-runs-panel__only-failed"
            :disabled="!failedCount"
          >
            只看失败{{ failedCount ? `（${failedCount}）` : '' }}
          </el-checkbox>
        </div>
      </template>

      <template #trigger="{ row }">
        <el-tag size="small" effect="plain" type="info">
          {{ triggerLabel(String(row.trigger ?? '')) }}
        </el-tag>
      </template>

      <template #duration="{ row }">
        <span class="job-runs-panel__duration">
          {{ formatRunDuration(Number(row.duration_ms ?? 0)) }}
        </span>
      </template>

      <template #result="{ row }">
        <div class="job-runs-panel__result">
          <el-tag
            size="small"
            effect="light"
            :type="statusType(String(row.status ?? ''))"
            class="job-runs-panel__status"
          >
            <el-icon class="job-runs-panel__status-icon">
              <component :is="statusIcon(String(row.status ?? ''))" />
            </el-icon>
            {{ statusLabel(String(row.status ?? '')) }}
          </el-tag>
          <el-button
            v-if="row.error_text"
            link
            size="small"
            class="job-runs-panel__err"
            title="点开看失败全文并复制"
            @click="openError(row)"
          >
            <span class="job-runs-panel__err-body">
              <span class="job-runs-panel__err-line">{{ firstLine(String(row.error_text)) }}</span>
              <span class="job-runs-panel__err-more">全文</span>
            </span>
          </el-button>
        </div>
      </template>
    </BasicTable>

    <JobRunErrorDialog v-model="errorOpen" :run="activeRun" />
  </section>
</template>

<style scoped>
.job-runs-panel {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  min-width: 0;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  overflow: hidden;
}

.job-runs-panel__table {
  flex: 1 1 auto;
  min-height: 0;
  height: auto;
}

.job-runs-panel__table :deep(.basic-table__toolbar) {
  padding: var(--gap-1) var(--gap-2);
  background: var(--surface-sunken);
}

.job-runs-panel__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
}

.job-runs-panel__title strong {
  font-size: var(--fs-title);
}

.job-runs-panel__meta {
  font-size: var(--fs-aux);
  color: var(--muted);
}

.job-runs-panel__duration {
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
  font-size: var(--fs-body);
  color: var(--ink);
}

.job-runs-panel__result {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
  width: 100%;
}

.job-runs-panel__status {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
}

.job-runs-panel__status-icon {
  margin-right: 0.1rem;
  vertical-align: middle;
}

.job-runs-panel__only-failed {
  margin-left: auto;
}

/* 失败原因是个 el-button link：一眼看得出「这半句还能点开」，不是一段哑掉的灰字。 */
.job-runs-panel__err.el-button {
  height: auto;
  min-width: 0;
  padding: 0;
  overflow: hidden;
  font-size: var(--fs-aux);
  font-weight: 400;
  text-align: left;
  --el-button-text-color: var(--muted);
  --el-button-hover-text-color: var(--el-color-danger);
  --el-button-active-text-color: var(--el-color-danger);
}

/* EP 把默认插槽再包一层 span，省略号要靠 min-width:0 一路传下去才生效 */
.job-runs-panel__err :deep(span) {
  min-width: 0;
}

.job-runs-panel__err-body {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-1);
  min-width: 0;
}

.job-runs-panel__err:hover .job-runs-panel__err-line,
.job-runs-panel__err:focus-visible .job-runs-panel__err-line {
  /* 失败用全站危险色（EP 语义 token），不借涨跌色 */
  color: var(--el-color-danger);
  text-decoration: underline;
}

.job-runs-panel__err-line {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-runs-panel__err-more {
  flex: 0 0 auto;
  padding: 0 var(--gap-1);
  border: 1px solid color-mix(in oklab, var(--el-color-danger) 35%, var(--rule));
  border-radius: var(--radius);
  font-size: var(--fs-kicker);
  color: var(--el-color-danger);
}
</style>
