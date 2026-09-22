<script setup lang="ts">
import { default as SidePanel } from '@/shared/components/ui/app/SidePanel.vue'
import { default as HintTooltip } from '@/shared/components/ui/app/HintTooltip.vue'
import { StatusBadge, Notice } from '@/shared/components/ui/app/presentation'
import { default as ToggleSwitch } from '@/shared/components/ui/app/ToggleSwitch.vue'
import { default as ActionButton } from '@/shared/components/ui/app/ActionButton.vue'
import { default as DataGrid } from '@/shared/components/ui/app/DataGrid.vue'
import { default as DataColumn } from '@/shared/components/ui/app/DataColumn.vue'

import { computed } from 'vue'

import LatencyMeter from './LatencyMeter.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type { SourceRow, SourceTool } from '../composables/useDataSources'

const props = defineProps<{
  modelValue: boolean
  row: SourceRow | null
  busyKey: string
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
  probe: [id: string]
  toggleSource: [payload: { id: string; enabled: boolean }]
  toggleTool: [payload: { id: string; lane: string; enabled: boolean }]
  /** 去「按接口」看这家源的 AkShare 接口 */
  interfaces: [id: string]
}>()

const open = computed({
  get: () => props.modelValue,
  set: (next: boolean) => emit('update:modelValue', next),
})

const probing = computed(() => props.busyKey === `source:${props.row?.id ?? ''}`)

/** 两段常驻说明收进读数行的 tooltip：抽屉正文里不再留介绍文字。 */
const scopeHint = computed(() =>
  props.row?.interfaceOnly
    ? '这家只出现在 AkShare 接口目录里，没有内置取数线路：点接口数去「按接口」勾选，勾上的会进内置 MCP 工具清单。'
    : '源总开关关掉时，这家所有工具都不参与选源；单个工具停用只影响那一条线路。',
)

function toolRows(): Record<string, unknown>[] {
  return (props.row?.tools ?? []) as unknown as Record<string, unknown>[]
}

function asTool(row: Record<string, unknown>): SourceTool {
  return row as unknown as SourceTool
}

function statusOf(tool: SourceTool): { label: string; type: 'success' | 'danger' | 'info' } {
  if (!tool.probe) return { label: '未测', type: 'info' }
  if (tool.probe.unsupported) return { label: '不支持', type: 'info' }
  return tool.probe.ok ? { label: '正常', type: 'success' } : { label: '失败', type: 'danger' }
}
</script>

<template>
  <SidePanel v-model="open" class="source-detail-drawer" size="min(540px, 100vw)" direction="rtl" append-to-body>
    <template #header="{ titleId, titleClass }">
      <div class="ds-detail__head">
        <div class="ds-detail__name">
          <h4 :id="titleId" :class="titleClass">{{ row?.label ?? '数据源' }}</h4>
          <HintTooltip v-if="row" :content="scopeHint" placement="bottom-start">
            <code>{{ row.id }}</code>
          </HintTooltip>
          <p v-if="row?.baseUrl" class="ds-detail__url">{{ row.baseUrl }}</p>
        </div>
        <StatusBadge v-if="row?.interfaceOnly" size="small" tone="info" effect="plain">接口源</StatusBadge>
        <ToggleSwitch
          v-else-if="row"
          :model-value="row.masterEnabled"
          :busy="busyKey === `toggle:${row.id}`"
          active-text="启用"
          inactive-text="停用"
          :aria-label="`启用 ${row.label}`"
          @change="(next: string | number | boolean) => emit('toggleSource', { id: row!.id, enabled: Boolean(next) })"
        />
      </div>
    </template>

    <template v-if="row">
      <div class="ds-detail__bar">
        <p class="ds-detail__counts">
          <template v-if="row.tools.length">
            线路 <b>{{ row.tools.length }}</b> · 启用 <b>{{ row.enabledCount }}</b> · 停用
            <b>{{ row.disabledCount }}</b>
          </template>
          <template v-if="row.interfaceCount != null">
            <template v-if="row.tools.length"> · </template>
            <!-- 接口明细不在本抽屉，给一条能点过去的路，别让这个数字成为死数 -->
            <ActionButton access="read" variant="link" tone="primary" class="ds-detail__jump" @click="emit('interfaces', row!.id)">
              接口 {{ row.interfaceCount }} →
            </ActionButton>
          </template>
        </p>
        <ActionButton
          v-if="row.tools.length"
          tone="primary"
          size="small"
          :busy="probing"
          @click="emit('probe', row.id)"
        >
          探测连接
        </ActionButton>
      </div>

      <Notice
        v-if="row.probedCount && row.failedCount"
        :title="`${row.failedCount} 个工具本次探测失败`"
        tone="warning"
        show-icon
        :closable="false"
        class="ds-detail__alert"
      />

      <DataGrid
        v-if="row.tools.length"
        :data="toolRows()"
        size="small"
        row-key="lane"
        class="ds-detail__table"
      >
        <DataColumn label="工具" min-width="118">
          <template #default="{ row: item }">
            <span class="tool-name">{{ asTool(item).label }}</span>
            <StatusBadge v-if="asTool(item).required" size="small" tone="warning" effect="plain">
              必需
            </StatusBadge>
          </template>
        </DataColumn>
        <DataColumn label="顺位" width="62" align="center" header-align="center">
          <template #default="{ row: item }">
            <span class="ord">{{ asTool(item).order ?? '—' }}</span>
          </template>
        </DataColumn>
        <DataColumn label="启用" width="62" align="center">
          <template #default="{ row: item }">
            <ToggleSwitch
              size="small"
              :model-value="asTool(item).enabled"
              :disabled="!row!.enabled"
              :busy="busyKey === `toggle:${row!.id}:${asTool(item).lane}`"
              :aria-label="`启用 ${asTool(item).label}`"
              @change="(next: string | number | boolean) => emit('toggleTool', { id: row!.id, lane: asTool(item).lane, enabled: Boolean(next) })"
            />
          </template>
        </DataColumn>
        <DataColumn label="耗时" min-width="120">
          <template #default="{ row: item }">
            <LatencyMeter
              v-if="asTool(item).probe"
              :ms="asTool(item).probe?.rttMs ?? null"
              :ok="Boolean(asTool(item).probe?.ok)"
            />
            <span v-else class="dim">—</span>
          </template>
        </DataColumn>
        <DataColumn label="结果" min-width="140" show-overflow-tooltip>
          <template #default="{ row: item }">
            <StatusBadge size="small" :tone="statusOf(asTool(item)).type" effect="plain">
              {{ statusOf(asTool(item)).label }}
            </StatusBadge>
            <span v-if="asTool(item).probe?.rows != null" class="rows">
              {{ asTool(item).probe?.rows }} 行
            </span>
            <span v-if="asTool(item).probe?.error" class="err">
              {{ asTool(item).probe?.error }}
            </span>
          </template>
        </DataColumn>
      </DataGrid>
    </template>
    <EmptyState v-else description="未选中数据源" reason="在列表里点一行查看" />
  </SidePanel>
</template>

<style scoped>
.ds-detail__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-3);
  flex-wrap: wrap;
  width: 100%;
  /* 右上角是抽屉自带的关闭按钮，给它留出位置 */
  padding-right: 1.6rem;
}

.ds-detail__name h4 {
  margin: 0;
  font: 600 var(--fs-title)/1.3 var(--font);
  color: var(--ink);
}

.ds-detail__name code {
  font: 0.76rem var(--mono);
  color: var(--mist);
  cursor: help;
}

.ds-detail__url {
  margin: 0.15rem 0 0;
  font: 0.74rem var(--mono);
  color: var(--mist);
  word-break: break-all;
}

.ds-detail__bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  margin: 0 0 var(--gap-3);
  padding: var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface-sunken);
}

.ds-detail__counts {
  margin: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
}

.ds-detail__counts b {
  font: 600 var(--fs-body) var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}

.ds-detail__jump {
  font-size: var(--fs-aux);
  vertical-align: baseline;
}

.ds-detail__alert {
  margin-bottom: 0.55rem;
}

.ds-detail__table {
  width: 100%;
}

.tool-name {
  margin-right: 0.35rem;
}

.ord {
  font: 650 0.8rem var(--mono);
  color: var(--muted);
}

.rows {
  margin-left: 0.35rem;
  font: 0.76rem var(--mono);
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
.ds-detail__name { min-width: 0; }
.source-detail-drawer :deep(.side-panel__header) { border-bottom: 1px solid var(--rule); padding-bottom: var(--gap-3); }
.source-detail-drawer :deep(.side-panel__body) { overscroll-behavior: contain; }
</style>
