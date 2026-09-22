<script setup lang="ts">
import { computed } from 'vue'
import { Cable, Cpu, SlidersHorizontal } from '@lucide/vue'

import { Badge } from '@/shared/components/ui/badge'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Button } from '@/shared/components/ui/button'
import RowActions, { type RowAction } from '@/shared/components/ui/RowActions.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'

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
    { prop: 'kind', label: '品类', width: 100, align: 'center', headerAlign: 'center', slotName: 'kind' },
    { prop: 'name', label: '名称', minWidth: 180, align: 'center', headerAlign: 'center', slotName: 'name' },
    { prop: 'trust', label: '信任', width: 88, align: 'center', headerAlign: 'center', slotName: 'trust' },
    { prop: 'badges', label: '契约', minWidth: 160, align: 'center', headerAlign: 'center', slotName: 'badges' },
    { prop: 'description', label: '说明', minWidth: 220, align: 'center', headerAlign: 'center', showOverflowTooltip: true, slotName: 'description' },
    { prop: 'actions', label: '操作', width: props.showRemove ? 128 : 92, align: 'center', headerAlign: 'center', fixed: 'right', slotName: 'actions' },
  ]
  return cols
})

const kindIcons = { source: Cable, strategy: SlidersHorizontal, skill: Cpu }

function openLabel(item: MarketPackage): string {
  if (item.kind === 'source') return '数据源'
  return '工作台'
}

function rowActions(row: Record<string, unknown>): RowAction[] {
  const item = row as unknown as MarketPackage
  const actions: RowAction[] = [
    { key: 'open', access: 'read', label: openLabel(item), onClick: () => emit('open', item) },
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
      <Badge variant="secondary">
        <component :is="kindIcons[row.kind as MarketKind]" aria-hidden="true" />
        {{ KIND_LABEL[row.kind as MarketKind] }}
      </Badge>
    </template>
    <template #name="{ row }">
      <div class="name-cell">
        <Button access="read"
          variant="link"
          size="sm"
          class="package-name"
          :aria-label="`查看${row.name}详情`"
          @click.stop="onRowClick(row)"
        >
          {{ row.name }}
        </Button>
        <span v-if="row.version" class="version">版本 {{ row.version }}</span>
      </div>
    </template>
    <template #trust="{ row }">
      <Badge
        v-if="row.trust === 'official'"
        class="border-transparent bg-info-soft text-info-ink"
      >
        官方
      </Badge>
      <Badge v-else variant="secondary">本机</Badge>
      <Badge v-if="row.enabled === false" variant="outline" class="ml">停用</Badge>
    </template>
    <template #badges="{ row }">
      <Badge
        v-for="badge in (row.badges as string[]) || []"
        :key="badge"
        variant="outline"
        class="badge"
      >
        {{ badge }}
      </Badge>
      <span v-if="!(row.badges as string[])?.length" class="dim">—</span>
    </template>
    <template #description="{ row }">
      <span v-if="row.description">{{ row.description }}</span>
      <span v-else class="dim">—</span>
    </template>
    <template #actions="{ row }">
      <RowActions :actions="rowActions(row)" />
    </template>
    <template #empty><slot name="empty"><EmptyState description="货架为空" /></slot></template>
  </BasicTable>
</template>

<style scoped>
.name-cell {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  min-width: 0;
}
.version {
  font-family: var(--mono);
  font-size: var(--fs-kicker);
  color: var(--mist);
}
.badge {
  margin: 0 var(--gap-1) var(--gap-1) 0;
}
.ml {
  margin-left: var(--gap-1);
}
.dim {
  color: var(--mist);
  font-size: var(--fs-aux);
}
.package-name { justify-content: flex-start; font-weight: 600; white-space: normal; text-align: left; }
.package-name:focus-visible { outline: 2px solid var(--seal); outline-offset: 2px; }
</style>
