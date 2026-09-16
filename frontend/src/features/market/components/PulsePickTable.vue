<script setup lang="ts">
/** 今日选股：密度表，随窗口高度伸缩（至少 6 行可见）。 */
import { computed } from 'vue'
import { Tickets } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '@/shared/components/ui/EmptyState.vue'
import StockLink from '@/shared/components/ui/StockLink.vue'
import { toBatchItems } from '@/shared/lib/batchBrowse'
import { signedPct } from '@/shared/lib/format'

import { strategyDisplayName } from '../composables/pulseHomeLogic'
import type { PulsePickRow } from '../composables/usePulseHome'

import './pulseSkin.css'

const props = defineProps<{
  title: string
  note?: string
  hint?: string
  rows: PulsePickRow[]
  empty: string
  emptyHint?: string
  showStrategy?: boolean
}>()

const route = useRoute()
const router = useRouter()

const batch = computed(() => ({
  source: props.title,
  sourcePath: route.fullPath || '/',
  items: toBatchItems(props.rows),
}))

function fmtScore(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  const n = Number(value)
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return 'pulse-flat'
  if (Number(value) > 0) return 'pulse-up'
  if (Number(value) < 0) return 'pulse-down'
  return 'pulse-flat'
}

/** 战法列是窄列：短名 + 中文兜底（数据层已收口，这里再挡一次裸 slug）。 */
function strategyText(row: PulsePickRow): string {
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
        <el-icon class="pulse-panel__icon" aria-hidden="true"><Tickets /></el-icon>
        <h2 class="pulse-panel__title">{{ title }}</h2>
        <span v-if="rows.length" class="pulse-panel__meta">{{ rows.length }}只</span>
      </div>
      <el-tooltip v-if="hint" :content="hint" placement="bottom-end" :show-after="200">
        <span class="pulse-panel__meta">{{ note }}</span>
      </el-tooltip>
      <span v-else class="pulse-panel__meta">{{ note }}</span>
    </header>
    <el-table :data="rows" size="small" stripe height="100%" class="pulse-table">
      <el-table-column prop="rank" label="#" width="48" align="center" header-align="center">
        <template #default="{ row }">
          <span class="pulse-num pulse-dim">{{ row.rank }}</span>
        </template>
      </el-table-column>
      <el-table-column label="名称" min-width="160" align="left" header-align="left">
        <template #default="{ row }">
          <span class="pulse-name">
            <StockLink :code="row.code" :name="row.name" :batch="batch" :show-code="false" />
          </span>
          <span class="pulse-code"> {{ row.code }}</span>
        </template>
      </el-table-column>
      <el-table-column
        v-if="showStrategy"
        label="战法"
        min-width="150"
        align="left"
        header-align="left"
      >
        <template #default="{ row }">
          <el-tooltip :content="strategyText(row as PulsePickRow)" placement="top" :show-after="200">
            <span class="pulse-dim pulse-clip">{{ strategyText(row as PulsePickRow) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="今涨" width="90" align="right" header-align="right">
        <template #default="{ row }">
          <span class="pulse-num" :class="tone(row.pct)">{{ signedPct(row.pct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="评分" width="80" align="right" header-align="right">
        <template #default="{ row }">
          <span class="pulse-num pulse-dim">{{ fmtScore(row.score) }}</span>
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
