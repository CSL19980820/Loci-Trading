<script setup lang="ts">
/**
 * 当前任务的最近执行历史：BasicTable + 客户端分页。
 */
import { nextTick, ref, watch } from 'vue'

import BasicTable, {
  type BasicTableColumn,
  type BasicTableRequest,
} from '@/shared/components/ui/BasicTable.vue'
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

const basicTableRef = ref<InstanceType<typeof BasicTable> | null>(null)

const columns = ref<BasicTableColumn[]>([
  {
    prop: 'started_at',
    label: '时间',
    minWidth: 160,
    formatter: (row) => String(row.started_at ?? '—'),
  },
  {
    prop: 'trigger',
    label: '触发',
    width: 72,
    formatter: (row) => triggerLabel(String(row.trigger ?? '')),
  },
  {
    prop: 'duration_ms',
    label: '耗时',
    width: 96,
    align: 'right',
    headerAlign: 'right',
    slotName: 'duration',
  },
  {
    prop: 'status',
    label: '结果',
    minWidth: 180,
    showOverflowTooltip: true,
    slotName: 'result',
  },
])

const loadDataTable: BasicTableRequest = async (params) => {
  const list = runs.value
  const start = (params.currentPage - 1) * params.pageSize
  return {
    list: list.slice(start, start + params.pageSize) as unknown as Record<string, unknown>[],
    total: list.length,
  }
}

function reloadList(resetPage = true): void {
  if (resetPage) void basicTableRef.value?.restReload()
  else void basicTableRef.value?.reloadTable()
}

async function reload(resetPage = true): Promise<void> {
  await refetch()
  await nextTick()
  reloadList(resetPage)
}

watch(
  () => props.jobId,
  () => {
    void reload(true)
  },
  { immediate: true },
)

defineExpose({ reload })
</script>

<template>
  <section class="job-runs-panel" aria-label="最近执行历史">
    <header class="job-runs-panel__head">
      <strong>最近执行</strong>
      <span class="job-runs-panel__meta">仅当前任务</span>
    </header>
    <div class="job-runs-panel__table">
      <BasicTable
        ref="basicTableRef"
        v-model:columns="columns"
        :request="loadDataTable"
        :pagination="{
          pageSize: 10,
          pageSizes: [10, 20, 50],
          layout: 'total, sizes, prev, pager, next',
          background: true,
          hideOnSinglePage: false,
        }"
        :toolbar-config="{ refresh: true }"
        :loading="isPending"
        :has-default-request="false"
        stripe
        border
        row-key="id"
        height="100%"
        empty-text="还没有执行记录"
        @refresh="reload(false)"
      >
        <template #duration="{ row }">
          <span class="job-runs-panel__duration">
            {{ formatRunDuration(Number(row.duration_ms ?? 0)) }}
          </span>
        </template>
        <template #result="{ row }">
          <el-tag
            size="small"
            effect="light"
            :type="
              row.status === 'failed' ? 'danger' : row.status === 'success' ? 'success' : 'info'
            "
          >
            {{ statusLabel(String(row.status ?? '')) }}
          </el-tag>
          <span v-if="row.error_text" class="job-runs-panel__err">
            {{ firstLine(String(row.error_text)) }}
          </span>
        </template>
      </BasicTable>
    </div>
  </section>
</template>

<style scoped>
.job-runs-panel {
  flex: 1 1 auto;
  min-height: 12rem;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  min-width: 0;
}

.job-runs-panel__head {
  display: flex;
  align-items: baseline;
  gap: 0.55rem;
  flex-shrink: 0;
}

.job-runs-panel__head strong {
  font-size: 0.95rem;
}

.job-runs-panel__meta {
  font-size: 0.78rem;
  color: var(--muted);
}

.job-runs-panel__table {
  flex: 1 1 auto;
  min-height: 10rem;
  display: flex;
  flex-direction: column;
}

.job-runs-panel__table :deep(.basic-table) {
  flex: 1 1 auto;
  min-height: 0;
}

.job-runs-panel__duration {
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.9em;
}

.job-runs-panel__err {
  margin-left: 0.35rem;
  color: var(--muted);
  font-size: 0.88em;
}
</style>
