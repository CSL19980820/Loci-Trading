<script setup lang="ts">
/**
 * 当前任务的最近执行历史：BasicTable（常规表，条数少不必虚拟化）。
 */
import { computed, ref, watch } from 'vue'
import { CircleCheck, CircleClose, WarningFilled } from '@element-plus/icons-vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
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

const tableRows = computed(() => runs.value as unknown as Record<string, unknown>[])
const runCount = computed(() => runs.value.length)

const columns = ref<BasicTableColumn[]>([
  {
    prop: 'started_at',
    label: '时间',
    minWidth: 168,
    align: 'left',
    headerAlign: 'left',
    showOverflowTooltip: true,
    formatter: (row) => formatStartedAt(String(row.started_at ?? '')),
  },
  {
    prop: 'trigger',
    label: '触发',
    width: 88,
    slotName: 'trigger',
  },
  {
    prop: 'duration_ms',
    label: '耗时',
    width: 104,
    align: 'right',
    headerAlign: 'right',
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

watch(
  () => props.jobId,
  () => {
    void reload()
  },
  { immediate: true },
)

defineExpose({ reload })
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
          <span v-if="row.error_text" class="job-runs-panel__err" :title="String(row.error_text)">
            {{ firstLine(String(row.error_text)) }}
          </span>
        </div>
      </template>
    </BasicTable>
  </section>
</template>

<style scoped>
.job-runs-panel {
  flex: 1 1 auto;
  min-height: 14rem;
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
  padding: 0.45rem 0.75rem;
  background: color-mix(in srgb, var(--panel-2) 70%, var(--sheet));
}

.job-runs-panel__title {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
}

.job-runs-panel__title strong {
  font-size: 0.92rem;
}

.job-runs-panel__meta {
  font-size: 0.76rem;
  color: var(--muted);
}

.job-runs-panel__duration {
  font-variant-numeric: tabular-nums;
  font-family: var(--mono);
  font-size: 0.9em;
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

.job-runs-panel__err {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: 0.84em;
}
</style>
