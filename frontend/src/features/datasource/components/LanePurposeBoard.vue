<script setup lang="ts">
import { StatusBadge } from '@/shared/components/ui/app/presentation'
import { default as RadioChoices } from '@/shared/components/ui/app/RadioChoices.vue'
import { default as RadioButton } from '@/shared/components/ui/app/RadioButton.vue'
import { default as ChoiceField } from '@/shared/components/ui/app/ChoiceField.vue'
import { default as ChoiceOption } from '@/shared/components/ui/app/ChoiceOption.vue'
import { default as ToggleSwitch } from '@/shared/components/ui/app/ToggleSwitch.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as DataGrid } from '@/shared/components/ui/app/DataGrid.vue'
import { default as DataColumn } from '@/shared/components/ui/app/DataColumn.vue'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'

import LatencyMeter from './LatencyMeter.vue'
import type { LaneRow, LaneSource } from '../composables/useDataSources'
import type { LanePolicyMode } from '@/shared/types/quant'

const props = defineProps<{
  rows: LaneRow[]
  busyKey: string
}>()

const emit = defineEmits<{
  toggleTool: [payload: { id: string; lane: string; enabled: boolean }]
  probe: [lane: string]
  download: [lane: string]
  savePolicy: [
    payload: {
      lane: string
      policy: { mode: LanePolicyMode; provider_id?: string | null; fallback: boolean }
    },
  ]
}>()

function asSource(row: Record<string, unknown>): LaneSource {
  return row as unknown as LaneSource
}

function sourceRows(row: LaneRow): Record<string, unknown>[] {
  return row.sources as unknown as Record<string, unknown>[]
}

function enabledSources(row: LaneRow): LaneSource[] {
  return row.sources.filter((item) => item.enabled)
}

function policyBusy(lane: string): boolean {
  return props.busyKey === `policy:${lane}`
}

function toggleSourceOnLane(lane: string, id: string, enabled: boolean): void {
  emit('toggleTool', { id, lane, enabled })
}

function changeMode(row: LaneRow, mode: LanePolicyMode): void {
  const provider = mode === 'manual' ? (row.providerId ?? enabledSources(row)[0]?.id ?? null) : null
  if (mode === 'manual' && !provider) return
  emit('savePolicy', {
    lane: row.lane,
    policy: { mode, provider_id: provider, fallback: row.fallback },
  })
}

function changeProvider(row: LaneRow, providerId: string | null): void {
  if (!providerId) return
  emit('savePolicy', {
    lane: row.lane,
    policy: { mode: 'manual', provider_id: providerId, fallback: row.fallback },
  })
}

function changeFallback(row: LaneRow, fallback: boolean): void {
  emit('savePolicy', {
    lane: row.lane,
    policy: {
      mode: row.mode,
      provider_id: row.mode === 'manual' ? row.providerId : null,
      fallback,
    },
  })
}
</script>

<template>
  <div class="lane-board">
    <section v-for="row in rows" :key="row.lane" class="lane-card" :aria-label="row.label">
      <header class="lane-card__head">
        <div class="lane-card__title">
          <strong>{{ row.label }}</strong>
          <StatusBadge v-if="row.required" size="small" tone="warning" effect="plain">必需</StatusBadge>
          <StatusBadge v-if="!row.sources.length" size="small" tone="info" effect="plain">
            未接内置源
          </StatusBadge>
          <StatusBadge v-else-if="!row.effectiveCount" size="small" tone="danger">无可用源</StatusBadge>
          <StatusBadge
            v-else-if="row.required && row.effectiveCount === 1"
            size="small"
            tone="warning"
          >
            仅 1 个源
          </StatusBadge>
          <span class="lane-card__meta">
            来源 <b>{{ row.sources.length }}</b> · 生效 <b>{{ row.effectiveCount }}</b>
          </span>
        </div>

        <div v-if="row.sources.length" class="lane-card__tools">
          <RadioChoices
            :model-value="row.mode"
            size="small"
            :disabled="policyBusy(row.lane)"
            :aria-label="`${row.label} 选源方式`"
            @change="(mode: string | number | boolean) => changeMode(row, mode as LanePolicyMode)"
          >
            <RadioButton value="auto">自动</RadioButton>
            <RadioButton value="manual" :disabled="!enabledSources(row).length">
              手选
            </RadioButton>
          </RadioChoices>
          <ChoiceField
            v-if="row.mode === 'manual'"
            :model-value="row.providerId"
            size="small"
            class="lane-card__pick"
            placeholder="选首选源"
            :disabled="policyBusy(row.lane)"
            :aria-label="`${row.label} 首选源`"
            @change="id => changeProvider(row, id)"
          >
            <ChoiceOption
              v-for="item in enabledSources(row)"
              :key="item.id"
              :label="item.label"
              :value="item.id"
            />
          </ChoiceField>
          <ToggleSwitch
            :model-value="row.fallback"
            size="small"
            active-text="失败回退"
            :disabled="policyBusy(row.lane)"
            :aria-label="`${row.label} 失败回退`"
            @change="(next: string | number | boolean) => changeFallback(row, Boolean(next))"
          />
          <ActionButton
            size="small"
            :busy="busyKey === `lane:${row.lane}`"
            @click="emit('probe', row.lane)"
          >
            探测
          </ActionButton>
          <ActionButton
            v-if="row.supportsDownloadTest"
            size="small"
            :busy="busyKey === `speed:${row.lane}`"
            @click="emit('download', row.lane)"
          >
            下载测速
          </ActionButton>
        </div>
      </header>

      <DataGrid
        v-if="row.sources.length"
        :data="sourceRows(row)"
        size="small"
        row-key="id"
        class="lane-card__table"
      >
        <DataColumn label="顺位" width="60" align="center" header-align="center">
          <template #default="{ row: item }">
            <span class="ord">{{ asSource(item).order ?? '—' }}</span>
          </template>
        </DataColumn>
        <DataColumn label="来源" min-width="140">
          <template #default="{ row: item }">
            <span :class="{ off: !asSource(item).enabled }">{{ asSource(item).label }}</span>
            <code>{{ asSource(item).id }}</code>
            <StatusBadge v-if="asSource(item).masterOff" size="small" tone="info" effect="plain">
              整源停用
            </StatusBadge>
          </template>
        </DataColumn>
        <DataColumn label="启用" width="62" align="center">
          <template #default="{ row: item }">
            <ToggleSwitch
              size="small"
              :model-value="asSource(item).masterEnabled"
              :busy="busyKey === `toggle:${asSource(item).id}:${row.lane}`"
              :aria-label="`在${row.label}启用 ${asSource(item).label}`"
              @change="(next: string | number | boolean) => toggleSourceOnLane(row.lane, asSource(item).id, Boolean(next))"
            />
          </template>
        </DataColumn>
        <DataColumn label="耗时" min-width="118">
          <template #default="{ row: item }">
            <LatencyMeter
              v-if="asSource(item).probe"
              :ms="asSource(item).probe?.rttMs ?? null"
              :ok="Boolean(asSource(item).probe?.ok)"
            />
            <span v-else class="dim">未测</span>
          </template>
        </DataColumn>
        <DataColumn label="结果" min-width="150" show-overflow-tooltip>
          <template #default="{ row: item }">
            <template v-if="asSource(item).probe">
              <StatusBadge size="small" :tone="asSource(item).probe?.ok ? 'success' : 'danger'" effect="plain">
                {{ asSource(item).probe?.ok ? '正常' : '失败' }}
              </StatusBadge>
              <span v-if="asSource(item).probe?.kind === 'download'" class="kind">下载</span>
              <span v-if="asSource(item).probe?.rows != null" class="rows">
                {{ asSource(item).probe?.rows }} 行
              </span>
              <span v-if="asSource(item).probe?.error" class="err">
                {{ asSource(item).probe?.error }}
              </span>
            </template>
            <span v-else class="dim">—</span>
          </template>
        </DataColumn>
      </DataGrid>
      <HintTooltip v-else content="去「按接口」自己勾一个上桌，或等内置源接进来" placement="top-start">
        <p class="lane-card__empty">这条用途还没有内置源</p>
      </HintTooltip>
    </section>
  </div>
</template>

<style scoped>
.lane-board {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  /* 高度随内容；滚动由 DataSourcePanel .ds-body 承担 */
  flex: 0 0 auto;
  min-height: min-content;
  padding-bottom: var(--gap-2);
}

.lane-card {
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface);
  min-width: 0;
  overflow: hidden;
}

.lane-card__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2) var(--gap-3);
  padding: var(--gap-2) var(--gap-3);
  border-bottom: 1px solid var(--rule);
  background: var(--surface-sunken);
}

.lane-card__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
}

.lane-card__title strong {
  font-family: var(--font);
  font-size: var(--fs-title);
}

.lane-card__meta {
  font-size: var(--fs-aux);
  color: var(--mist);
}

.lane-card__meta b {
  font: 600 var(--fs-body) var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.lane-card__tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
}

.lane-card__pick {
  width: 9rem;
}

.lane-card__table {
  width: 100%;
}

.lane-card__table code {
  margin-left: 0.35rem;
  font: 0.7rem var(--mono);
  color: var(--mist);
}

.lane-card__table .status-badge {
  margin-left: 0.35rem;
}

.lane-card__empty {
  margin: 0;
  padding: var(--gap-3);
  font-size: var(--fs-aux);
  color: var(--mist);
}

.ord {
  font: 650 0.8rem var(--mono);
  color: var(--muted);
}

.off {
  color: var(--mist);
}

.kind,
.rows {
  margin-left: 0.35rem;
  font: 0.74rem var(--mono);
  color: var(--mist);
}

.err {
  margin-left: 0.35rem;
  font-size: 0.76rem;
  color: var(--stamp);
}

.dim {
  color: var(--mist);
}
.lane-card__tools :deep(.action-button + .action-button) { margin-left: 0; }
@media (max-width: 640px) { .lane-card__tools { width: 100%; gap: var(--gap-2); } }
</style>
