<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { pct as fmtPct } from '@/shared/lib/format'
import type { BoardRow } from '@/shared/types/quant'

import type { PulseBoardTab, SectorBoardRow } from '../composables/usePulseHome'

const props = defineProps<{
  tab: PulseBoardTab
  rows: BoardRow[]
  sectorRows?: SectorBoardRow[]
  note?: string
  asOf?: string
  pctOf: (row: BoardRow) => number | null
}>()

const emit = defineEmits<{
  'update:tab': [tab: PulseBoardTab]
}>()

const route = useRoute()

const batch = computed(() => ({
  source: '库内样本榜',
  sourcePath: route.fullPath || '/',
  items: toBatchItems(
    props.rows.map((r) => ({
      code: r.code,
      name: r.name,
      changePct: props.pctOf(r),
    })),
  ),
}))

/** 标题旁只露时分秒。 */
const clockText = computed(() => {
  const raw = (props.asOf || '').trim()
  if (!raw) return ''
  const match = raw.match(/(\d{2}:\d{2}:\d{2})/)
  return match?.[1] ?? ''
})

const tabs: { id: PulseBoardTab; label: string }[] = [
  { id: 'gain', label: '涨幅' },
  { id: 'turnover', label: '换手' },
  { id: 'sector', label: '板块' },
]

const isSector = computed(() => props.tab === 'sector')
const sectorList = computed(() => props.sectorRows ?? [])
const hasRows = computed(() =>
  isSector.value ? sectorList.value.length > 0 : props.rows.length > 0,
)


function fmtTurnover(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function tone(value: number | null): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}
</script>

<template>
  <section class="pulse-panel">
    <header class="pulse-panel__head">
      <div class="pulse-board__title">
        <strong>库内样本榜</strong>
        <span class="pulse-board__scope">非全市场领涨</span>
        <span v-if="clockText" class="pulse-board__clock">{{ clockText }}</span>
      </div>
      <div class="pulse-tabs">
        <el-button
          v-for="t in tabs"
          :key="t.id"
          size="small"
          :type="tab === t.id ? 'primary' : 'default'"
          plain
          @click="emit('update:tab', t.id)"
        >
          {{ t.label }}
        </el-button>
      </div>
    </header>
    <p v-if="note" class="pulse-panel__note">{{ note }}</p>
    <el-table
      v-if="hasRows && isSector"
      :data="sectorList"
      size="small"
      stripe
      height="100%"
      class="pulse-table"
    >
      <el-table-column
        type="index"
        label="序号"
        width="60"
        align="center"
        header-align="center"
      />
      <el-table-column label="板块" min-width="120" align="center" header-align="center">
        <template #default="{ row }">
          <span>{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="涨幅" min-width="120" align="center" header-align="center">
        <template #default="{ row }">
          <span class="num" :class="tone(row.pct)">{{ fmtPct(row.pct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="成分" min-width="80" align="center" header-align="center">
        <template #default="{ row }">
          <span class="num pulse-muted">{{ row.count }}</span>
        </template>
      </el-table-column>
    </el-table>
    <el-table
      v-else-if="hasRows"
      :data="rows"
      size="small"
      stripe
      height="100%"
      class="pulse-table"
    >
      <el-table-column
        type="index"
        label="序号"
        width="60"
        align="center"
        header-align="center"
      />
      <el-table-column label="名称" min-width="120" align="center" header-align="center">
        <template #default="{ row }">
          <StockLink :code="row.code" :name="row.name" :batch="batch" :show-code="false" />
        </template>
      </el-table-column>
      <el-table-column
        :label="tab === 'turnover' ? '换手' : '涨幅'"
        min-width="120"
        align="center"
        header-align="center"
      >
        <template #default="{ row }">
          <span
            v-if="tab === 'turnover'"
            class="num"
          >{{ fmtTurnover(row.turnover) }}</span>
          <span v-else class="num" :class="tone(pctOf(row))">{{ fmtPct(pctOf(row)) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="板块" min-width="120" align="center" header-align="center">
        <template #default="{ row }">
          <span class="pulse-muted">{{ row.industry || '—' }}</span>
        </template>
      </el-table-column>
    </el-table>
    <el-empty
      v-else
      :description="isSector ? '暂无行业样本，请先同步行情并补全行业' : '暂无榜单，请先同步行情'"
      :image-size="56"
    />
  </section>
</template>

<style scoped>
.pulse-panel {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pulse-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.4rem 0.55rem;
  border-bottom: 1px solid var(--rule);
}

.pulse-board__title {
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  min-width: 0;
}

.pulse-panel__head strong {
  font-size: 0.88rem;
}

.pulse-board__scope {
  font-size: 0.68rem;
  color: var(--mist);
  font-weight: normal;
}

.pulse-board__clock {
  font-size: 0.7rem;
  color: var(--mist);
  font-variant-numeric: tabular-nums;
  font-family: var(--mono, ui-monospace, monospace);
}

.pulse-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.08rem;
}

.pulse-tabs :deep(.el-button + .el-button) {
  margin-left: 0;
}

.pulse-panel__note {
  margin: 0;
  padding: 0.25rem 0.65rem 0;
  font-size: 0.7rem;
  color: var(--mist);
}

.pulse-table {
  flex: 1;
  min-height: 140px;
}

.pulse-table :deep(.el-table__cell) {
  padding: 4px 0;
}

.num {
  font-variant-numeric: tabular-nums;
  font-family: var(--mono, ui-monospace, monospace);
  font-size: 0.8rem;
}

.pulse-muted {
  color: var(--mist);
  font-size: 0.78rem;
}

.is-up {
  color: var(--up, #c41e3a);
}

.is-down {
  color: var(--down, #0f6b5c);
}
</style>
