<script setup lang="ts">
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import RowActions, { type RowAction } from '@/shared/components/ui/RowActions.vue'

import {
  KIND_LABEL,
  type MarketKind,
  type MarketPackage,
} from '../composables/useMarketCatalog'

const props = defineProps<{
  rows: MarketPackage[]
  selectedId: string
  loading?: boolean
  /** installed 页显示卸载 */
  showRemove?: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  open: [item: MarketPackage]
  remove: [item: MarketPackage]
}>()

const tableRows = computed(() => props.rows as unknown as Record<string, unknown>[])

const columns = computed<BasicTableColumn[]>(() => {
  const cols: BasicTableColumn[] = [
    { prop: 'kind', label: '品类', width: 100, slotName: 'kind' },
    { prop: 'name', label: '名称', minWidth: 180, slotName: 'name' },
    { prop: 'trust', label: '信任', width: 88, slotName: 'trust' },
    { prop: 'badges', label: '契约', minWidth: 160, slotName: 'badges' },
    { prop: 'description', label: '说明', minWidth: 220, showOverflowTooltip: true, slotName: 'description' },
    { prop: 'actions', label: '操作', width: props.showRemove ? 128 : 92, align: 'right', fixed: 'right', slotName: 'actions' },
  ]
  return cols
})

function kindTone(kind: MarketKind): 'warning' | 'danger' | 'info' {
  if (kind === 'source') return 'warning'
  if (kind === 'strategy') return 'danger'
  return 'info'
}

function openLabel(item: MarketPackage): string {
  if (item.kind === 'source') return '数据源'
  return '工作台'
}

function rowActions(row: Record<string, unknown>): RowAction[] {
  const item = row as unknown as MarketPackage
  const actions: RowAction[] = [
    { key: 'open', label: openLabel(item), onClick: () => emit('open', item) },
  ]
  if (props.showRemove && item.removable) {
    actions.push({ key: 'remove', label: '卸载', type: 'danger', onClick: () => emit('remove', item) })
  }
  return actions
}

function onRowClick(row: Record<string, unknown>): void {
  emit('select', String(row.id))
}
</script>

<template>
  <BasicTable
    :columns="columns"
    :data-source="tableRows"
    :loading="loading"
    :pagination="false"
    row-key="id"
    stripe
    empty-text="货架为空"
    class="market-shelf"
    :row-class-name="({ row }) => (String(row.id) === selectedId ? 'is-selected' : '')"
    @row-click="onRowClick"
  >
    <template #kind="{ row }">
      <el-tag size="small" :type="kindTone(row.kind as MarketKind)" effect="plain">
        {{ KIND_LABEL[row.kind as MarketKind] }}
      </el-tag>
    </template>
    <template #name="{ row }">
      <div class="name-cell">
        <strong>{{ row.name }}</strong>
        <span v-if="row.version" class="version">版本 {{ row.version }}</span>
      </div>
    </template>
    <template #trust="{ row }">
      <el-tag size="small" effect="light" :type="row.trust === 'official' ? 'success' : 'info'">
        {{ row.trust === 'official' ? '官方' : '本机' }}
      </el-tag>
      <el-tag v-if="row.enabled === false" size="small" type="info" effect="plain" class="ml">
        停用
      </el-tag>
    </template>
    <template #badges="{ row }">
      <el-tag
        v-for="badge in (row.badges as string[]) || []"
        :key="badge"
        size="small"
        effect="plain"
        class="badge"
      >
        {{ badge }}
      </el-tag>
      <span v-if="!(row.badges as string[])?.length" class="dim">—</span>
    </template>
    <template #description="{ row }">
      <span v-if="row.description">{{ row.description }}</span>
      <span v-else class="dim">—</span>
    </template>
    <template #actions="{ row }">
      <RowActions :actions="rowActions(row)" />
    </template>
  </BasicTable>
</template>

<style scoped>
.name-cell {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
}
.version {
  font-size: 0.72rem;
  color: var(--mist);
}
.badge {
  margin: 0 0.25rem 0.2rem 0;
}
.ml {
  margin-left: 0.25rem;
}
.dim {
  color: var(--mist);
  font-size: 0.78rem;
}
:deep(.is-selected) {
  --el-table-tr-bg-color: color-mix(in srgb, var(--seal-soft, #f3e6dc) 55%, transparent);
}
</style>
