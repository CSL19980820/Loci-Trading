<script setup lang="ts">
import { computed, watch } from 'vue'
import { CircleAlert } from '@lucide/vue'

import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'

import type { AkshareCatalogCapability } from '@/shared/types/quant'

import { useSourceDatasets } from '../composables/useSourceDatasets'

const props = defineProps<{
  sourceId: string
}>()

const emit = defineEmits<{
  select: [dataset: AkshareCatalogCapability]
}>()

const { datasets, loading, error, load, reset } = useSourceDatasets()

const rows = computed(() => datasets.value as unknown as Record<string, unknown>[])

const columns: BasicTableColumn[] = [
  { prop: 'name', label: '接口', minWidth: 180, align: 'center', headerAlign: 'center', slotName: 'name' },
  { prop: 'summary', label: '作用', minWidth: 220, align: 'center', headerAlign: 'center', slotName: 'summary' },
  { prop: 'params', label: '入参', minWidth: 150, align: 'center', headerAlign: 'center', slotName: 'params' },
  { prop: 'returns', label: '返回', minWidth: 140, align: 'center', headerAlign: 'center', slotName: 'returns' },
]

function onRowClick(row: Record<string, unknown>): void {
  emit('select', row as unknown as AkshareCatalogCapability)
}

function paramSummary(row: AkshareCatalogCapability): string {
  const names = (row.parameters || []).map((p) => p.name)
  if (!names.length) return '无'
  return names.join(' · ')
}

watch(
  () => props.sourceId,
  (id) => {
    if (id) void load(id)
    else reset()
  },
  { immediate: true },
)
</script>

<template>
  <div class="dataset-list">
    <Alert v-if="error" variant="destructive" class="mb">
      <CircleAlert aria-hidden="true" />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ error }}</AlertTitle>
        <Button access="read" variant="outline" size="sm" class="shrink-0" :disabled="loading" @click="load(sourceId)">
          重试
        </Button>
      </div>
    </Alert>
    <BasicTable
      :columns="columns"
      :data-source="rows"
      :loading="loading"
      :pagination="false"
      height="min(36dvh, 18rem)"
      row-key="name"
      class="dataset-table"
      @row-click="onRowClick"
    >
      <template #name="{ row }">
        <Button access="read"
          variant="link"
          size="sm"
          class="mono"
          :aria-label="`查看接口 ${row.name}`"
          @click.stop="onRowClick(row)"
        >
          {{ row.name }}
        </Button>
      </template>
      <template #summary="{ row }">
        <Tooltip :delay-duration="150">
          <TooltipTrigger as-child>
            <span class="doc-clip">{{ String(row.summary || '上游未写说明') }}</span>
          </TooltipTrigger>
          <TooltipContent>{{ String(row.summary || '上游未写说明') }}</TooltipContent>
        </Tooltip>
      </template>
      <template #params="{ row }">
        <Tooltip :delay-duration="150">
          <TooltipTrigger as-child>
            <span class="mono dim doc-clip">
              {{ paramSummary(row as unknown as AkshareCatalogCapability) }}
            </span>
          </TooltipTrigger>
          <TooltipContent>{{ paramSummary(row as unknown as AkshareCatalogCapability) }}</TooltipContent>
        </Tooltip>
      </template>
      <template #returns="{ row }">
        <Tooltip :delay-duration="150" :disabled="!row.returns">
          <TooltipTrigger as-child>
            <span class="doc-clip">{{ String(row.returns || '—') }}</span>
          </TooltipTrigger>
          <TooltipContent>{{ String(row.returns || '—') }}</TooltipContent>
        </Tooltip>
      </template>
      <template #empty><EmptyState :description="error ? '接口加载失败' : '此来源暂无接口'" /></template>
    </BasicTable>
  </div>
</template>

<style scoped>
.dataset-list {
  min-width: 0;
  margin-top: var(--gap-2);
}
.dataset-table :deep([data-slot='table-row']) {
  cursor: pointer;
}
.mb {
  margin-bottom: var(--gap-2);
}
.mono {
  font-family: var(--mono);
  font-size: var(--fs-aux);
}

.doc-clip {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.dim {
  color: var(--mist);
  font-size: var(--fs-aux);
}
</style>
