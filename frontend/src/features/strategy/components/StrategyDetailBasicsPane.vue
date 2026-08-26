<script setup lang="ts">
import { computed } from 'vue'
import type { StrategyInfo, StrategyVersion } from '@/shared/types/quant'
import {
  formatBacktestConfig,
  formatPercent,
  formatProfitFactor,
  isActiveVersion,
  strategyEntryLabel,
  strategyFieldRows,
  strategyRevisionLabel,
  strategySourceLabel,
} from './strategyDetailFormat'

const props = defineProps<{
  strategy: StrategyInfo | null
  loadingVersions: boolean
  versionRows: StrategyVersion[]
  canManageVersions: boolean
  versionActing: string
}>()

const emit = defineEmits<{
  rollback: [version: string]
  'remove-version': [version: string]
}>()

const sourceLabel = computed(() => strategySourceLabel(props.strategy))
const entryLabel = computed(() => strategyEntryLabel(props.strategy))
const revisionLabel = computed(() => strategyRevisionLabel(props.strategy))
const fieldRows = computed(() => strategyFieldRows(props.strategy))
const backtestMetrics = computed(() => props.strategy?.backtest_metrics ?? null)
const backtestConfigLabel = computed(() => formatBacktestConfig(props.strategy?.backtest_config))

function versionKey(version: string): string {
  return version
}

function activeVersion(row: StrategyVersion): boolean {
  return isActiveVersion(row, props.strategy?.version)
}
</script>

<template>
  <el-descriptions :column="2" border size="small" class="detail-desc">
    <el-descriptions-item label="来源">{{ sourceLabel }}</el-descriptions-item>
    <el-descriptions-item label="入场">{{ entryLabel }}</el-descriptions-item>
    <el-descriptions-item label="最少 K 线">{{ strategy?.min_bars }}</el-descriptions-item>
    <el-descriptions-item label="修订">{{ revisionLabel }}</el-descriptions-item>
    <el-descriptions-item label="当前版本">{{ strategy?.version || '—' }}</el-descriptions-item>
    <el-descriptions-item label="回测交易数">{{ backtestMetrics?.trades ?? '—' }}</el-descriptions-item>
    <el-descriptions-item label="回测胜率">{{ formatPercent(backtestMetrics?.win_rate) }}</el-descriptions-item>
    <el-descriptions-item label="平均净收益">{{ formatPercent(backtestMetrics?.avg_net_return) }}</el-descriptions-item>
    <el-descriptions-item label="PF">{{ formatProfitFactor(backtestMetrics?.profit_factor) }}</el-descriptions-item>
    <el-descriptions-item label="回测口径" :span="2">{{ backtestConfigLabel }}</el-descriptions-item>
    <el-descriptions-item v-if="strategy?.entry_instructions" label="买入说明" :span="2">
      {{ strategy.entry_instructions }}
    </el-descriptions-item>
    <el-descriptions-item label="说明" :span="2">
      {{ strategy?.description || '—' }}
    </el-descriptions-item>
    <el-descriptions-item label="所需字段" :span="2">
      <div v-if="fieldRows.length" class="field-tags">
        <el-tag
          v-for="row in fieldRows"
          :key="row.key"
          size="small"
          effect="plain"
          type="info"
        >
          {{ row.label }}
          <span class="field-key">{{ row.key }}</span>
        </el-tag>
      </div>
      <span v-else class="dim">—</span>
    </el-descriptions-item>
  </el-descriptions>
  <div class="version-history" v-loading="loadingVersions">
    <div class="version-history__title">历史版本</div>
    <div v-if="versionRows.length" class="version-list">
      <div v-for="row in versionRows" :key="row.id || row.version" class="version-row">
        <div class="version-row__meta">
          <strong class="mono">{{ row.version }}</strong>
          <el-tag v-if="activeVersion(row)" size="small" type="success">当前</el-tag>
          <el-tag v-else-if="row.status" size="small" effect="plain">{{ row.status }}</el-tag>
          <span class="dim">{{ row.created_at || '—' }}</span>
        </div>
        <div v-if="canManageVersions && !activeVersion(row)" class="version-row__actions">
          <el-button
            link
            type="primary"
            :loading="versionActing === versionKey(row.version)"
            @click="emit('rollback', row.version)"
          >
            回滚
          </el-button>
          <el-button
            link
            type="danger"
            :disabled="Boolean(versionActing)"
            @click="emit('remove-version', row.version)"
          >
            删除
          </el-button>
        </div>
      </div>
    </div>
    <span v-else class="dim">暂无历史版本</span>
  </div>
</template>

<style scoped>
.detail-desc { width: 100%; }
.detail-desc :deep(.el-descriptions__label) { color: var(--mist); width: 5.5rem; }
.field-tags, .version-row__meta, .version-row__actions { display: flex; flex-wrap: wrap; align-items: center; }
.field-tags { gap: 0.35rem; }
.field-key { margin-left: 0.35rem; color: var(--mist); font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace); font-size: 0.72rem; }
.version-list { display: flex; flex-direction: column; gap: 0.15rem; }
.mono { font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace); font-variant-numeric: tabular-nums; }
.version-history { margin-top: 1rem; }
.version-history__title { margin-bottom: 0.35rem; font-size: 0.86rem; font-weight: 600; }
.version-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.35rem 0; border-bottom: 1px solid var(--line, var(--el-border-color-lighter)); }
.version-row__meta { gap: 0.35rem; min-width: 0; }
.version-row__actions { gap: 0.15rem; flex-shrink: 0; }
.dim { color: var(--mist); font-size: 0.82rem; }
</style>
