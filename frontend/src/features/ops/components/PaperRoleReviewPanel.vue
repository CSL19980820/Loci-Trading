<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
import { computed, ref, watch } from 'vue'
import { ChevronDown } from '@lucide/vue'

import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import { Badge } from '@/shared/components/ui/badge'
import { Button } from '@/shared/components/ui/button'
import { Checkbox } from '@/shared/components/ui/checkbox'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
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

/** 图上最多叠 6 只；超出后未选中的项置灰，与原 `el-select` 的禁用规则一致 */
const MAX_SERIES = 6

const ROLE_TYPE: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  leader: 'success',
  secondary: 'info',
  follower: 'info',
  weakened: 'warning',
  failed: 'danger',
}

/**
 * 角色档位 → 标签配色。绿红留给价格，状态走 `--ok` / `--warn` / `--info`，
 * 破坏性走印章红（`--stamp`）。
 */
const ROLE_BADGE: Record<string, string> = {
  success: 'border-transparent bg-ok-soft text-ok',
  warning: 'border-transparent bg-warn-soft text-warn-ink',
  danger: 'border-stamp/40 bg-surface text-stamp',
  info: 'border-transparent bg-info-soft text-info-ink',
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

/** 触发器上一行摘要：与原 `collapse-tags` + `max-collapse-tags="2"` 同口径 */
const selectedLabel = computed(() => {
  const picked = timelineModel.value.codeOptions.filter((o) => selectedCodes.value.includes(o.code))
  if (!picked.length) return '选择代码'
  const shown = picked.slice(0, 2).map((o) => `${o.name}(${o.code})`)
  const more = picked.length - shown.length
  return more > 0 ? `${shown.join('、')} +${more}` : shown.join('、')
})

function codeDisabled(code: string): boolean {
  return selectedCodes.value.length >= MAX_SERIES && !selectedCodes.value.includes(code)
}

function toggleCode(code: string): void {
  if (selectedCodes.value.includes(code)) {
    selectedCodes.value = selectedCodes.value.filter((item) => item !== code)
    return
  }
  if (codeDisabled(code)) return
  selectedCodes.value = [...selectedCodes.value, code]
}

function roleBadgeClass(role?: string): string {
  return ROLE_BADGE[ROLE_TYPE[String(role ?? '')] ?? 'info'] ?? ROLE_BADGE.info
}

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
          <Popover>
            <Tooltip>
              <TooltipTrigger as-child>
                <PopoverTrigger as-child>
                  <Button
                    variant="outline"
                    size="sm"
                    class="min-w-56 max-w-88 justify-between"
                    aria-label="角色演进图 · 选择代码"
                  >
                    <span class="truncate">{{ selectedLabel }}</span>
                    <ChevronDown class="size-4 opacity-50" aria-hidden="true" />
                  </Button>
                </PopoverTrigger>
              </TooltipTrigger>
              <TooltipContent>纵轴是角色档位（不是收益）；最多叠 6 只，缺口表示当日无观测</TooltipContent>
            </Tooltip>
            <PopoverContent align="end" class="w-64 p-1">
              <Label
                v-for="opt in timelineModel.codeOptions"
                :key="opt.code"
                class="code-option"
                :class="{ 'is-disabled': codeDisabled(opt.code) }"
              >
                <Checkbox
                  :model-value="selectedCodes.includes(opt.code)"
                  :disabled="codeDisabled(opt.code)"
                  @update:model-value="toggleCode(opt.code)"
                />
                <span class="truncate">{{ opt.name }}({{ opt.code }})</span>
              </Label>
            </PopoverContent>
          </Popover>
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
            <Badge :class="roleBadgeClass(String(alert.role))">{{ String(alert.role_label) }}</Badge>
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
            <Badge :class="roleBadgeClass(row.still_leader ? 'leader' : String(row.current_role))">
              {{ row.still_leader ? '仍是龙头' : roleLabel(String(row.current_role)) }}
            </Badge>
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

<style scoped>
/* 多选列表项：整行可点，禁用项置灰 */
.code-option {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  min-width: 0;
  padding: var(--gap-1) var(--gap-2);
  border-radius: var(--radius);
  font-size: var(--fs-body);
  cursor: pointer;
}

.code-option:hover {
  background: var(--surface-hover);
}

.code-option.is-disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}
</style>
