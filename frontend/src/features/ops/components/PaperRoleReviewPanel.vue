<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import type {
  LeaderRoleHistoryResponse,
  LeaderRoleSummary,
  LeaderRoleTransition,
} from '@/shared/types/quant'

import PaperRoleTimelineChart from './PaperRoleTimelineChart.vue'
import SettingsPanel from './SettingsPanel.vue'
import {
  buildRoleTimeline,
  suggestTimelineCodes,
  type RoleHistoryRow,
} from './paperRoleTimeline'

const props = defineProps<{
  roleData: LeaderRoleHistoryResponse | null
  positions: Array<Record<string, unknown>>
}>()

const EXIT_ROLES = new Set(['weakened', 'failed'])

const ROLE_TYPE: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  leader: 'success',
  secondary: 'info',
  follower: 'info',
  weakened: 'warning',
  failed: 'danger',
}

const ROLE_LABEL: Record<string, string> = {
  leader: '龙头',
  secondary: '中军',
  follower: '跟风',
  weakened: '走弱',
  failed: '结构破坏',
}

const selectedCodes = ref<string[]>([])

const historyRows = computed<RoleHistoryRow[]>(() => {
  const rows = props.roleData?.history
  return Array.isArray(rows) ? (rows as RoleHistoryRow[]) : []
})

const summary = computed<LeaderRoleSummary | null>(() => props.roleData?.summary ?? null)
const transitions = computed<LeaderRoleTransition[]>(() => props.roleData?.transitions ?? [])
const recentTransitions = computed(() => transitions.value.slice(0, 8))
const survival = computed(() => summary.value?.leader_survival ?? [])
const warningLead = computed(() => summary.value?.warning_lead ?? null)

const timelineModel = computed(() =>
  buildRoleTimeline(historyRows.value, { codes: selectedCodes.value }),
)

const positionAlerts = computed(() => {
  const history = props.roleData?.history ?? []
  if (!history.length || !props.positions.length) return []

  const sorted = history
    .filter((row) => row.code)
    .sort((a, b) =>
      String(a.observed_at || '').localeCompare(String(b.observed_at || '')),
    )
  const latestByCode = new Map<string, Record<string, unknown>>()
  for (const row of sorted) {
    latestByCode.set(String(row.code), row)
  }

  const alerts: Array<Record<string, unknown>> = []
  for (const position of props.positions) {
    const code = String(position.code || '')
    const latest = latestByCode.get(code)
    if (!latest) continue
    const role = String(latest.role || '')
    if (!EXIT_ROLES.has(role)) continue
    alerts.push({
      code,
      name: position.name || latest.name || code,
      layers: position.layers,
      role,
      role_label: ROLE_LABEL[role] || role,
      role_basis: latest.role_basis || '',
      observed_at: latest.observed_at,
      theme_name: latest.theme_name || '',
    })
  }
  return alerts
})

const hasRoleData = computed(() => {
  const s = summary.value
  return Boolean(
    s?.observations ||
      historyRows.value.length ||
      transitions.value.length ||
      survival.value.length ||
      positionAlerts.value.length,
  )
})

watch(
  () => [historyRows.value, props.positions] as const,
  () => {
    const prefer = props.positions.map((p) => String(p.code || '').trim()).filter(Boolean)
    const next = suggestTimelineCodes(historyRows.value, { preferCodes: prefer, limit: 5 })
    const known = new Set(
      buildRoleTimeline(historyRows.value, { codes: [] }).codeOptions.map((o) => o.code),
    )
    const stillValid = selectedCodes.value.filter((c) => known.has(c))
    selectedCodes.value = stillValid.length ? stillValid : next
  },
  { immediate: true, deep: true },
)

function roleLabel(role?: string): string {
  return ROLE_LABEL[String(role ?? '')] ?? String(role ?? '—')
}

const receipt = computed(() => {
  if (!summary.value?.trade_days) return []
  return [
    { key: '交易日', value: String(summary.value.trade_days) },
    { key: '观测', value: String(summary.value.observations ?? 0) },
  ]
})

const survivalRows = computed(() => survival.value as unknown as Record<string, unknown>[])
const transitionRows = computed(() => recentTransitions.value as unknown as Record<string, unknown>[])

const survivalColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 90 },
  { prop: 'name', label: '名称', width: 110 },
  { prop: 'theme_name', label: '题材', minWidth: 110, showOverflowTooltip: true },
  {
    prop: 'leader_days',
    label: '当龙头',
    width: 90,
    formatter: (row) => `${row.leader_days ?? 0} 日`,
  },
  { prop: 'current_role', label: '现状', minWidth: 110, slotName: 'status' },
]

const transitionColumns: BasicTableColumn[] = [
  { prop: 'code', label: '代码', width: 90 },
  { prop: 'name', label: '名称', width: 110 },
  { prop: 'to_role', label: '演进', width: 150, slotName: 'move' },
  { prop: 'to_at', label: '发生于', width: 180 },
  { prop: 'basis', label: '依据', minWidth: 160, showOverflowTooltip: true },
]
</script>

<template>
  <SettingsPanel title="角色演进" :receipt="receipt" class="role-review">
    <EmptyState v-if="!hasRoleData" description="还没有龙头角色留痕" reason="跑一次日终总结后回来" />

    <template v-else>
      <template v-if="historyRows.length && timelineModel.codeOptions.length">
        <div class="mb-1 flex items-center justify-end gap-3">
          <el-tooltip
            placement="top-end"
            content="纵轴是角色档位（不是收益）；最多叠 6 只，缺口表示当日无观测"
          >
            <el-select
              v-model="selectedCodes"
              multiple
              collapse-tags
              collapse-tags-tooltip
              :max-collapse-tags="2"
              size="small"
              placeholder="选择代码"
              aria-label="角色演进图 · 选择代码"
              class="min-w-56 max-w-88"
            >
              <el-option
                v-for="opt in timelineModel.codeOptions"
                :key="opt.code"
                :label="`${opt.name}(${opt.code})`"
                :value="opt.code"
                :disabled="selectedCodes.length >= 6 && !selectedCodes.includes(opt.code)"
              />
            </el-select>
          </el-tooltip>
        </div>
        <PaperRoleTimelineChart :model="timelineModel" :height="260" />
      </template>

      <template v-if="positionAlerts.length">
        <p class="text-body text-mist mt-3 mb-1">
          持仓角色告警 <b class="font-mono font-medium">{{ positionAlerts.length }}</b>
        </p>
        <ul class="m-0 list-none p-0">
          <li
            v-for="alert in positionAlerts"
            :key="String(alert.code)"
            class="border-rule flex flex-wrap items-center gap-x-2 gap-y-1 border-b py-1 text-[length:var(--fs-body)] last:border-b-0"
          >
            <el-tag size="small" type="warning" effect="plain">{{ String(alert.role_label) }}</el-tag>
            <span class="font-semibold">{{ String(alert.name) }} {{ String(alert.code) }}</span>
            <span>已判{{ String(alert.role_label) }}仍在持仓</span>
            <span class="text-mist">{{ String(alert.role_basis || '角色依据缺失') }}</span>
            <span v-if="alert.observed_at" class="text-mist font-mono">观测 {{ String(alert.observed_at) }}</span>
            <span v-if="alert.layers != null" class="text-mist font-mono">持仓 {{ String(alert.layers) }} 层</span>
          </li>
        </ul>
      </template>

      <template v-if="survival.length">
        <p class="text-body text-mist mt-3 mb-1">
          龙头存活榜 <b class="font-mono font-medium">{{ survival.length }}</b>
        </p>
        <BasicTable
          :columns="survivalColumns"
          :data-source="survivalRows"
          :pagination="false"
          max-height="220"
          stripe
          row-key="code"
          empty-text="还没有存活统计"
        >
          <template #status="{ row }">
            <el-tag
              size="small"
              :type="row.still_leader ? 'success' : ROLE_TYPE[String(row.current_role)] || 'info'"
              effect="plain"
            >
              {{ row.still_leader ? '仍是龙头' : roleLabel(String(row.current_role)) }}
            </el-tag>
          </template>
        </BasicTable>
        <p v-if="warningLead?.samples" class="text-body text-mist mt-1 mb-0">
          走弱预警提前量：{{ warningLead.samples }} 例，平均
          {{ warningLead.avg_days }} 个交易日（{{ warningLead.min_days }}~{{ warningLead.max_days }}）
        </p>
      </template>

      <template v-if="recentTransitions.length">
        <p class="text-body text-mist mt-3 mb-1">
          最近角色转移 <b class="font-mono font-medium">{{ recentTransitions.length }}</b>
        </p>
        <BasicTable
          :columns="transitionColumns"
          :data-source="transitionRows"
          :pagination="false"
          max-height="240"
          stripe
          row-key="code"
          empty-text="还没有角色转移"
        >
          <template #move="{ row }">
            {{ roleLabel(String(row.from_role)) }} → {{ roleLabel(String(row.to_role)) }}
          </template>
        </BasicTable>
      </template>
    </template>
  </SettingsPanel>
</template>
