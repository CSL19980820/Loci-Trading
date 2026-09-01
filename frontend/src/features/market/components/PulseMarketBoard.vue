<script setup lang="ts">
/** 库内样本榜：涨幅 / 换手 / 板块。口径解释一律进 tooltip，不占版面。 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { signedPct } from '@/shared/lib/format'
import type { BoardRow } from '@/shared/types/quant'

import type { PulseBoardTab, SectorBoardRow } from '../composables/usePulseHome'

import './pulseSkin.css'

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
  return raw.match(/(\d{2}:\d{2}:\d{2})/)?.[1] ?? ''
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

/** 口径 + 降级原因都进 tooltip：榜是「库内样本」不是全市场领涨。 */
const scopeTip = computed(() =>
  ['库内样本排序，非全市场领涨', props.note].filter(Boolean).join(' · '),
)

function fmtTurnover(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return 'pulse-flat'
  if (Number(value) > 0) return 'pulse-up'
  if (Number(value) < 0) return 'pulse-down'
  return 'pulse-flat'
}
</script>

<template>
  <section class="pulse-panel">
    <header class="pulse-panel__head">
      <div class="pulse-panel__lead">
        <h2 class="pulse-panel__title">样本榜</h2>
        <el-tooltip :content="scopeTip" placement="bottom-start" :show-after="200">
          <span class="pulse-panel__meta">库内 · {{ clockText || '—' }}</span>
        </el-tooltip>
      </div>
      <div class="pulse-tabs">
        <el-button
          v-for="t in tabs"
          :key="t.id"
          link
          size="small"
          :type="tab === t.id ? 'primary' : 'default'"
          :class="{ 'pulse-tab--on': tab === t.id }"
          :aria-pressed="tab === t.id"
          @click="emit('update:tab', t.id)"
        >
          {{ t.label }}
        </el-button>
      </div>
    </header>

    <el-table
      v-if="hasRows && isSector"
      :data="sectorList"
      size="small"
      stripe
      height="100%"
      class="pulse-table"
    >
      <el-table-column label="板块" min-width="96" align="center" header-align="center">
        <template #default="{ row }">
          <span class="pulse-name">{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column label="涨幅" width="76" align="center" header-align="center">
        <template #default="{ row }">
          <span class="pulse-num" :class="tone(row.pct)">{{ signedPct(row.pct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="成分" width="56" align="center" header-align="center">
        <template #default="{ row }">
          <span class="pulse-num pulse-dim">{{ row.count }}</span>
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
      <el-table-column label="名称" width="96" align="center" header-align="center">
        <template #default="{ row }">
          <span class="pulse-name">
            <StockLink :code="row.code" :name="row.name" :batch="batch" :show-code="false" />
          </span>
        </template>
      </el-table-column>
      <el-table-column
        :label="tab === 'turnover' ? '换手' : '涨幅'"
        width="76"
        align="center"
        header-align="center"
      >
        <template #default="{ row }">
          <span v-if="tab === 'turnover'" class="pulse-num">{{ fmtTurnover(row.turnover) }}</span>
          <span v-else class="pulse-num" :class="tone(pctOf(row))">
            {{ signedPct(pctOf(row)) }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="板块" min-width="76" align="center" header-align="center" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="pulse-dim pulse-clip">{{ row.industry || '—' }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div v-else class="pulse-panel__empty">
      <span>{{ isSector ? '暂无行业样本' : '暂无榜单' }}</span>
      <el-button link type="primary" size="small" @click="emit('update:tab', tab)">重新取数</el-button>
    </div>
  </section>
</template>

<style scoped>
.pulse-panel__title {
  margin: 0;
}
</style>
