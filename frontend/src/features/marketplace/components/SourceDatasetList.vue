<script setup lang="ts">
import { computed, watch } from 'vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'

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
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="mb">
      <el-button :disabled="loading" @click="load(sourceId)">重试</el-button>
    </el-alert>
    <el-table
      v-loading="loading"
      :data="rows"
      size="small"
      height="min(36dvh, 18rem)"
      row-key="name"
      class="dataset-table"
      @row-click="onRowClick"
    >
      <el-table-column prop="name" label="接口" min-width="180">
        <template #default="{ row }">
          <el-button link class="mono" :aria-label="`查看接口 ${row.name}`" @click.stop="onRowClick(row)">{{ row.name }}</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="summary" label="作用" min-width="220">
        <template #default="{ row }">
          <el-tooltip :content="row.summary || '上游未写说明'" placement="top" :show-after="150">
            <span class="doc-clip">{{ row.summary || '上游未写说明' }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="入参" min-width="150">
        <template #default="{ row }">
          <el-tooltip :content="paramSummary(row as unknown as AkshareCatalogCapability)" placement="top" :show-after="150">
            <span class="mono dim doc-clip">
              {{ paramSummary(row as unknown as AkshareCatalogCapability) }}
            </span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column prop="returns" label="返回" min-width="140">
        <template #default="{ row }">
          <el-tooltip :content="row.returns || '—'" placement="top" :show-after="150" :disabled="!row.returns">
            <span class="doc-clip">{{ row.returns || '—' }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <template #empty><EmptyState :description="error ? '接口加载失败' : '此来源暂无接口'" /></template>
    </el-table>
  </div>
</template>

<style scoped>
.dataset-list {
  min-width: 0;
  margin-top: var(--gap-2);
}
.dataset-table :deep(.el-table__row) {
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
