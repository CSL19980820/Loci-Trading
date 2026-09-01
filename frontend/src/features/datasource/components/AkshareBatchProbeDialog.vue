<script setup lang="ts">
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import type { AkshareBatchProbeItem } from '@/shared/types/quant'

const open = defineModel<boolean>({ required: true })

const props = defineProps<{
  busy: boolean
  progress: { done: number; total: number; ok: number; failed: number; skipped: number }
  results: AkshareBatchProbeItem[]
}>()

const emit = defineEmits<{
  stop: []
}>()

const percent = computed(() => {
  if (!props.progress.total) return 0
  return Math.min(100, Math.round((props.progress.done / props.progress.total) * 100))
})

const tableRows = computed(() =>
  [...props.results].reverse().map((item) => ({ ...item }) as Record<string, unknown>),
)

const columns: BasicTableColumn[] = [
  { prop: 'name', label: '接口', minWidth: 200, align: 'center', headerAlign: 'center', showOverflowTooltip: true },
  { prop: 'ok', label: '结果', width: 88, align: 'center', headerAlign: 'center', slotName: 'status' },
  { prop: 'elapsed_ms', label: '响应', width: 100, align: 'center', headerAlign: 'center', slotName: 'rtt' },
  { prop: 'rows', label: '行数', width: 72, align: 'center', headerAlign: 'center', formatter: (row) => (row.rows == null ? '—' : String(row.rows)) },
  { prop: 'error', label: '说明', minWidth: 220, align: 'left', headerAlign: 'left', showOverflowTooltip: true, slotName: 'error' },
]

function statusLabel(row: Record<string, unknown>): { type: 'success' | 'danger' | 'info'; text: string } {
  if (row.skipped) return { type: 'info', text: '跳过' }
  if (row.ok) return { type: 'success', text: '通过' }
  return { type: 'danger', text: '失败' }
}
</script>

<template>
  <el-dialog
    v-model="open"
    title="一键全测"
    width="min(920px, 96vw)"
    destroy-on-close
    :close-on-click-modal="!busy"
  >
    <div class="batch-head">
      <el-progress :percentage="percent" :status="busy ? undefined : percent >= 100 ? 'success' : undefined" />
      <p class="batch-readout">
        进度 <b>{{ progress.done }}</b> / {{ progress.total || '—' }}
        <span class="sep">·</span>通 <b class="ok">{{ progress.ok }}</b>
        <span class="sep">·</span>败 <b class="bad">{{ progress.failed }}</b>
        <span class="sep">·</span>跳过 <b>{{ progress.skipped }}</b>
      </p>
    </div>

    <BasicTable
      :columns="columns"
      :data-source="tableRows"
      :pagination="false"
      :loading="busy && !results.length"
      row-key="name"
      stripe
      max-height="360"
      empty-text="等待首批探测结果"
      class="batch-table"
    >
      <template #status="{ row }">
        <el-tag size="small" :type="statusLabel(row).type">{{ statusLabel(row).text }}</el-tag>
      </template>
      <template #rtt="{ row }">
        <span class="mono">{{ row.elapsed_ms == null ? '—' : `${Math.round(Number(row.elapsed_ms))} ms` }}</span>
      </template>
      <template #error="{ row }">
        <span :class="{ 'is-fail': !row.ok && !row.skipped }">{{ row.error || (row.ok ? '—' : '') }}</span>
      </template>
    </BasicTable>

    <template #footer>
      <el-button v-if="busy" type="danger" plain @click="emit('stop')">停止</el-button>
      <el-button type="primary" @click="open = false">{{ busy ? '后台继续' : '关闭' }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.batch-head { display: flex; flex-direction: column; gap: var(--gap-2); margin-bottom: var(--gap-2); }
.batch-readout { margin: 0; font-size: var(--fs-aux); color: var(--mist); }
.batch-readout b { font-family: var(--mono); font-variant-numeric: tabular-nums; color: var(--ink); }
/* 通/败是探测结果，不是涨跌：走状态色，不借 --up / --down（D1） */
.batch-readout .ok { color: var(--info); }
.batch-readout .bad { color: var(--warn); }
.sep { margin: 0 var(--gap-1); color: var(--rule); }
.mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.is-fail { color: var(--warn); }
/* 高度内容驱动：结果少时表就矮，不再用 min-height 撑出 360px 空表 */
.batch-table { min-height: 0; }
</style>
