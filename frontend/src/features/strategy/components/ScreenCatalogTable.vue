<script setup lang="ts">
import { computed } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import {
  sampleBadgeLabel,
  winRateDisplayTone,
  winRateText,
} from '@/shared/lib/winrate'

import type { ScreenCatalogItem, ScreenKind } from '../composables/useScreenCatalog'

const props = defineProps<{
  rows: ScreenCatalogItem[]
  selectedId: string
  loading?: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  run: [item: ScreenCatalogItem]
}>()

const tableRows = computed(() => props.rows as unknown as Record<string, unknown>[])

const columns: BasicTableColumn[] = [
  { prop: 'kind', label: '类型', width: 88, slotName: 'kind' },
  { prop: 'name', label: '名称', minWidth: 160, slotName: 'name' },
  { prop: 'winRate', label: '胜率', minWidth: 110, align: 'right', slotName: 'winRate' },
  { prop: 'avgReturn', label: '平均收益', minWidth: 100, align: 'right', slotName: 'avgReturn' },
  { prop: 'sample', label: '样本', width: 100, align: 'right', slotName: 'sample' },
  { prop: 'recentWinRate', label: '近期胜率', minWidth: 120, align: 'right', slotName: 'recent' },
  { prop: 'actions', label: '操作', width: 88, align: 'center', fixed: 'right', slotName: 'actions' },
]

function kindLabel(kind: ScreenKind): string {
  return kind === 'engine' ? '引擎' : 'Agent'
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function decayClass(signal: string | null): string {
  if (signal === 'critical') return 'is-critical'
  if (signal === 'warning') return 'is-warning'
  return ''
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
    empty-text="暂无选股技能（战法或 Agent 技能）"
    class="screen-catalog"
    :row-class-name="({ row }) => (String(row.id) === selectedId ? 'is-selected' : '')"
    @row-click="onRowClick"
  >
    <template #kind="{ row }">
      <el-tag size="small" :type="row.kind === 'engine' ? 'danger' : 'info'" effect="plain">
        {{ kindLabel(row.kind as ScreenKind) }}
      </el-tag>
    </template>
    <template #name="{ row }">
      <strong>{{ row.name }}</strong>
    </template>
    <template #winRate="{ row }">
      <span :class="winRateDisplayTone(row.winRate as number | null, Number(row.sample))">
        {{ winRateText(row.winRate as number | null) }}
      </span>
      <span class="hint">赚钱概率</span>
    </template>
    <template #avgReturn="{ row }">
      <span
        :class="{
          'is-up': typeof row.avgReturn === 'number' && row.avgReturn > 0,
          'is-down': typeof row.avgReturn === 'number' && row.avgReturn < 0,
        }"
      >
        {{ fmtPct(row.avgReturn as number | null) }}
      </span>
    </template>
    <template #sample="{ row }">
      <span>{{ Number(row.sample) || 0 }}</span>
      <el-tag
        v-if="sampleBadgeLabel(Number(row.sample))"
        size="small"
        type="info"
        effect="plain"
        class="sample-tag"
      >
        {{ sampleBadgeLabel(Number(row.sample)) }}
      </el-tag>
    </template>
    <template #recent="{ row }">
      <div class="recent-cell">
        <span :class="decayClass(row.decaySignal as string | null)">
          {{ winRateText(row.recentWinRate as number | null) }}
        </span>
        <el-tag
          v-if="row.decaySignal === 'critical'"
          size="small"
          type="danger"
          effect="plain"
        >
          衰减
        </el-tag>
        <el-tag
          v-else-if="row.decaySignal === 'warning'"
          size="small"
          type="warning"
          effect="plain"
        >
          注意
        </el-tag>
      </div>
    </template>
    <template #actions="{ row }">
      <el-button
        size="small"
        type="primary"
        link
        :disabled="row.kind === 'skill' && row.enabled === false"
        @click.stop="emit('run', row as unknown as ScreenCatalogItem)"
      >
        跑
      </el-button>
    </template>
  </BasicTable>
</template>

<style scoped>
.hint {
  display: block;
  font-size: 0.65rem;
  color: var(--mist);
  line-height: 1.2;
}

.sample-tag {
  margin-left: 0.25rem;
}

.recent-cell {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.is-up {
  color: var(--up);
}

.is-down {
  color: var(--down);
}

.is-critical {
  color: var(--seal);
  font-weight: 650;
}

.is-warning {
  color: var(--seal-ink);
}

.screen-catalog :deep(.is-selected) {
  background: color-mix(in srgb, var(--seal-soft) 45%, var(--sheet)) !important;
}

.wr-muted {
  color: var(--mist);
}

.wr-mid {
  color: var(--muted);
}

.wr-high {
  color: var(--up);
}

.wr-low {
  color: var(--down);
}
</style>
