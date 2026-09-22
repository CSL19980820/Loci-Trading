<script setup lang="ts">
import { vBusy } from '@/shared/directives/busy'
import { DetailList, DetailItem, StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'

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

  <DetailList :column="2" border size="small" class="detail-desc">
    <DetailItem label="来源">{{ sourceLabel }}</DetailItem>
    <DetailItem label="入场">{{ entryLabel }}</DetailItem>
    <DetailItem label="最少 K 线">{{ strategy?.min_bars }}</DetailItem>
    <DetailItem label="修订">{{ revisionLabel }}</DetailItem>
    <DetailItem label="当前版本">{{ strategy?.version || '—' }}</DetailItem>
    <DetailItem label="回测交易数">{{ backtestMetrics?.trades ?? '—' }}</DetailItem>
    <DetailItem label="回测胜率">{{ formatPercent(backtestMetrics?.win_rate) }}</DetailItem>
    <DetailItem label="平均净收益">{{ formatPercent(backtestMetrics?.avg_net_return) }}</DetailItem>
    <DetailItem label="PF">{{ formatProfitFactor(backtestMetrics?.profit_factor) }}</DetailItem>
  </DetailList>

  <!-- margin-top:-1px：两张表的边框各 1px，叠在一起才是一条线，不是两条 -->
  <DetailList :column="1" border size="small" class="detail-desc detail-desc--prose">
    <DetailItem label="回测口径">
      <div class="desc-text mono-text">{{ backtestConfigLabel }}</div>
    </DetailItem>
    <DetailItem v-if="strategy?.entry_instructions" label="买入说明">
      <div class="desc-text">{{ strategy.entry_instructions }}</div>
    </DetailItem>
    <DetailItem label="说明">
      <div class="desc-text">{{ strategy?.description || '—' }}</div>
    </DetailItem>
    <DetailItem label="所需字段">
      <div v-if="fieldRows.length" class="field-tags">
        <StatusBadge
          v-for="row in fieldRows"
          :key="row.key"
          size="small"
          effect="plain"
          tone="info"
        >
          {{ row.label }}
          <span class="field-key">{{ row.key }}</span>
        </StatusBadge>
      </div>
      <span v-else class="dim">—</span>
    </DetailItem>
  </DetailList>
  <div class="version-history" v-busy="loadingVersions">
    <div class="version-history__title">历史版本</div>
    <div v-if="versionRows.length" class="version-list">
      <div v-for="row in versionRows" :key="row.id || row.version" class="version-row">
        <div class="version-row__meta">
          <strong class="mono">{{ row.version }}</strong>
          <StatusBadge v-if="activeVersion(row)" size="small" tone="success">当前</StatusBadge>
          <StatusBadge v-else-if="row.status" size="small" effect="plain">{{ row.status }}</StatusBadge>
          <span class="dim">{{ row.created_at || '—' }}</span>
        </div>
        <div v-if="canManageVersions && !activeVersion(row)" class="version-row__actions">
          <ActionButton
            variant="link"
            tone="primary"
            :busy="versionActing === versionKey(row.version)"
            @click="emit('rollback', row.version)"
          >
            回滚
          </ActionButton>
          <ActionButton
            variant="link"
            tone="danger"
            :disabled="Boolean(versionActing)"
            @click="emit('remove-version', row.version)"
          >
            删除
          </ActionButton>
        </div>
      </div>
    </div>
    <span v-else class="dim">暂无历史版本</span>
  </div>
</template>

<style scoped>
.detail-desc { width: 100%; }
.detail-desc :deep(.detail-list) { table-layout: fixed; }
.detail-desc :deep(.detail-item__label) { color: var(--mist); width: 6.5rem; text-align: right; }
/* 断行只在「一个词真的放不下」时发生：不再逐字断，中文与百分数才不会竖排 */
.detail-desc :deep(.detail-item__content) { min-width: 0; word-break: normal; overflow-wrap: break-word; }
/* 长文本块紧贴上一张表：两张表各带 1px 边框，-1px 才收成一条线 */
.detail-desc--prose { margin-top: -1px; }
.desc-text { line-height: 1.5; font-size: var(--fs-aux); white-space: pre-wrap; overflow-wrap: break-word; }
.mono-text { font-family: var(--mono); font-size: 0.76rem; color: var(--ink); }
.field-tags, .version-row__meta, .version-row__actions { display: flex; flex-wrap: wrap; align-items: center; }
.field-tags { gap: 0.35rem; }
.field-key { margin-left: 0.35rem; color: var(--mist); font-family: var(--mono); font-size: var(--fs-kicker); }
.version-list { display: flex; flex-direction: column; gap: 0.15rem; }
.mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.version-history { margin-top: 1rem; }
.version-history__title { margin-bottom: 0.35rem; font-size: 0.86rem; font-weight: 600; }
.version-row { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.35rem 0; border-bottom: 1px solid var(--rule); }
.version-row__meta { gap: 0.35rem; min-width: 0; }
.version-row__actions { gap: 0.15rem; flex-shrink: 0; }
.dim { color: var(--mist); font-size: var(--fs-aux); }
</style>
