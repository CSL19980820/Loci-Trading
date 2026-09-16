<script setup lang="ts">
/** 近选跟踪（T～T+4）：密度表，数字列等宽右对齐，涨跌带符号。 */
import { computed } from 'vue'
import { TrendCharts } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { price as fmtPrice, signedPct } from '@/shared/lib/format'

import { strategyDisplayName } from '../composables/pulseHomeLogic'
import type { PulseTrackRow } from '../composables/usePulseHome'

import './pulseSkin.css'

const props = defineProps<{
  title: string
  /** 单行元信息（12px 次要色）；长解释请走 `hint` */
  note?: string
  /** 进 tooltip 的口径说明 */
  hint?: string
  rows: PulseTrackRow[]
  /** 空态一行短句（≤14 字） */
  empty: string
  /** 空态长解释，进 tooltip */
  emptyHint?: string
}>()

const route = useRoute()
const router = useRouter()

const batch = computed(() => ({
  source: props.title,
  sourcePath: route.fullPath || '/',
  items: toBatchItems(props.rows),
}))

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return 'pulse-flat'
  if (Number(value) > 0) return 'pulse-up'
  if (Number(value) < 0) return 'pulse-down'
  return 'pulse-flat'
}

function shortDate(value: string): string {
  if (!value || value.length < 10) return value || '—'
  return value.slice(5)
}

/** 战法列窄：短名 + 中文兜底（数据层已收口，这里再挡一次裸 slug）。 */
function strategyText(row: PulseTrackRow): string {
  return strategyDisplayName(row.strategyName || row.strategy)
}

function openScreen(): void {
  void router.push('/screen-history')
}
</script>

<template>
  <section class="pulse-panel">
    <header class="pulse-panel__head">
      <div class="pulse-panel__lead">
        <el-icon class="pulse-panel__icon" aria-hidden="true"><TrendCharts /></el-icon>
        <h2 class="pulse-panel__title">{{ title }}</h2>
        <span class="pulse-panel__meta">T～T+4</span>
      </div>
      <el-tooltip v-if="hint" :content="hint" placement="bottom-end" :show-after="200">
        <span class="pulse-panel__meta">{{ note }}</span>
      </el-tooltip>
      <span v-else class="pulse-panel__meta">{{ note }}</span>
    </header>
    <el-table :data="rows" size="small" stripe height="100%" class="pulse-table">
      <el-table-column label="名称" min-width="160" align="left" header-align="left">
        <template #default="{ row }">
          <span class="pulse-name">
            <StockLink :code="row.code" :name="row.name" :batch="batch" :show-code="false" />
          </span>
          <span class="pulse-code"> {{ row.code }}</span>
        </template>
      </el-table-column>
      <el-table-column label="选股日" width="64" align="right" header-align="right">
        <template #default="{ row }">
          <span class="pulse-num pulse-dim">{{ shortDate(row.date) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="选入" min-width="66" align="right" header-align="right">
        <template #default="{ row }">
          <span class="pulse-num">{{ fmtPrice(row.entryPrice) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="最新" min-width="66" align="right" header-align="right">
        <template #default="{ row }">
          <span class="pulse-num">{{ fmtPrice(row.latestPrice) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="涨跌幅" min-width="78" align="right" header-align="right">
        <template #default="{ row }">
          <span class="pulse-num" :class="tone(row.changePct)">{{ signedPct(row.changePct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="低→高" min-width="78" align="right" header-align="right">
        <template #default="{ row }">
          <span class="pulse-num" :class="tone(row.swingPct)">{{ signedPct(row.swingPct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="T+1" min-width="70" align="right" header-align="right">
        <template #default="{ row }">
          <span class="pulse-num" :class="tone(row.t1)">{{ signedPct(row.t1) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="T+3" min-width="66" align="right" header-align="right">
        <template #default="{ row }">
          <span class="pulse-num" :class="tone(row.t3)">{{ signedPct(row.t3) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="战法" min-width="110" align="left" header-align="left">
        <template #default="{ row }">
          <el-tooltip :content="strategyText(row as PulseTrackRow)" placement="top" :show-after="200">
            <span class="pulse-dim pulse-clip">{{ strategyText(row as PulseTrackRow) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <template #empty>
        <el-tooltip v-if="emptyHint" :content="emptyHint" placement="top" :show-after="200">
          <EmptyState class="pulse-panel__empty" :description="empty">
            <el-button link type="primary" size="small" @click="openScreen">去选股</el-button>
          </EmptyState>
        </el-tooltip>
        <EmptyState v-else class="pulse-panel__empty" :description="empty">
          <el-button link type="primary" size="small" @click="openScreen">去选股</el-button>
        </EmptyState>
      </template>
    </el-table>
  </section>
</template>

<style scoped>
.pulse-panel__title {
  margin: 0;
}
</style>
