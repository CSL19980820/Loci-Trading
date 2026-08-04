<script setup lang="ts">
import { computed, watch } from 'vue'

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
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="mb" />
    <p v-else-if="!loading && !datasets.length" class="dim">
      本机 akshare 目录里没有归到该来源的接口。
    </p>
    <el-table
      v-else
      v-loading="loading"
      :data="rows"
      size="small"
      height="18rem"
      row-key="name"
      class="dataset-table"
      @row-click="onRowClick"
    >
      <el-table-column prop="name" label="接口" min-width="180">
        <template #default="{ row }">
          <span class="mono">{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="summary" label="作用" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">{{ row.summary || '上游未写说明' }}</template>
      </el-table-column>
      <el-table-column label="入参" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="mono dim">
            {{ paramSummary(row as unknown as AkshareCatalogCapability) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="returns" label="返回" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">{{ row.returns || '—' }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.dataset-list {
  margin-top: 0.45rem;
}
.dataset-table :deep(.el-table__row) {
  cursor: pointer;
}
.mb {
  margin-bottom: 0.5rem;
}
.mono {
  font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 0.78rem;
}
.dim {
  color: var(--mist);
  font-size: 0.78rem;
}
</style>
