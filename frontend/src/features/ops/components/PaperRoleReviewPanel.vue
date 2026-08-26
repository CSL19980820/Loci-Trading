<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type {
  LeaderRoleHistoryResponse,
  LeaderRoleSummary,
  LeaderRoleTransition,
} from '@/shared/types/quant'

import PaperRoleTimelineChart from './PaperRoleTimelineChart.vue'
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
    // 首次或全部失效时重选；否则只丢掉已不存在的代码
    selectedCodes.value = stillValid.length ? stillValid : next
  },
  { immediate: true, deep: true },
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

function roleLabel(role?: string): string {
  return ROLE_LABEL[String(role ?? '')] ?? String(role ?? '—')
}
</script>

<template>
  <el-card shadow="never" class="role-review">
    <template #header>
      角色演进
      <span v-if="summary?.trade_days" class="muted">
        · 累计 {{ summary.trade_days }} 个交易日 / {{ summary.observations ?? 0 }} 次观测
      </span>
    </template>

    <el-empty v-if="!hasRoleData" description="还没有龙头角色留痕，日终总结或盯盘跑过后会逐步累积" />

    <template v-else>
      <template v-if="historyRows.length && timelineModel.codeOptions.length">
        <div class="chart-head">
          <p class="section dim chart-title">角色演进图</p>
          <el-select
            v-model="selectedCodes"
            multiple
            collapse-tags
            collapse-tags-tooltip
            :max-collapse-tags="2"
            size="small"
            placeholder="选择代码"
            class="code-select"
          >
            <el-option
              v-for="opt in timelineModel.codeOptions"
              :key="opt.code"
              :label="`${opt.name}(${opt.code})`"
              :value="opt.code"
              :disabled="
                selectedCodes.length >= 6 && !selectedCodes.includes(opt.code)
              "
            />
          </el-select>
        </div>
        <p class="dim footnote chart-hint">
          纵轴是角色档位（不是收益）；最多叠 6 只，缺口表示当日无观测。
        </p>
        <PaperRoleTimelineChart :model="timelineModel" :height="260" />
      </template>

      <template v-if="positionAlerts.length">
        <p class="section dim">持仓角色告警</p>
        <el-alert
          v-for="alert in positionAlerts"
          :key="String(alert.code)"
          class="alert-row"
          type="warning"
          show-icon
          :closable="false"
          :title="`${String(alert.name)} ${String(alert.code)} 已判${String(alert.role_label)}仍在持仓`"
          :description="`${alert.observed_at ? `观测 ${alert.observed_at} · ` : ''}${String(alert.role_basis || '角色依据缺失')}${alert.layers != null ? ` · 持仓 ${alert.layers} 层` : ''}`"
        />
      </template>

      <template v-if="survival.length">
        <p class="section dim">龙头存活榜</p>
        <el-table :data="survival" size="small" max-height="220" empty-text="还没有存活统计">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" width="110" />
          <el-table-column prop="theme_name" label="题材" min-width="110" show-overflow-tooltip />
          <el-table-column label="当龙头" width="90">
            <template #default="{ row }">{{ row.leader_days ?? 0 }} 日</template>
          </el-table-column>
          <el-table-column label="现状" min-width="110">
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="row.still_leader ? 'success' : ROLE_TYPE[String(row.current_role)] || 'info'"
                effect="plain"
              >
                {{
                  row.still_leader
                    ? '仍是龙头'
                    : roleLabel(String(row.current_role))
                }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <p v-if="warningLead?.samples" class="dim footnote">
          走弱预警提前量：{{ warningLead.samples }} 例，平均
          {{ warningLead.avg_days }} 个交易日（{{ warningLead.min_days }}~{{
            warningLead.max_days
          }}）
        </p>
      </template>

      <template v-if="recentTransitions.length">
        <p class="section dim">最近角色转移</p>
        <el-table :data="recentTransitions" size="small" max-height="240" empty-text="还没有角色转移">
          <el-table-column prop="code" label="代码" width="90" />
          <el-table-column prop="name" label="名称" width="110" />
          <el-table-column label="演进" width="150">
            <template #default="{ row }">
              {{ roleLabel(row.from_role) }} → {{ roleLabel(row.to_role) }}
            </template>
          </el-table-column>
          <el-table-column prop="to_at" label="发生于" width="180" />
          <el-table-column prop="basis" label="依据" min-width="160" show-overflow-tooltip />
        </el-table>
      </template>
    </template>
  </el-card>
</template>

<style scoped>
.role-review {
  flex: 0 0 auto;
}
.section {
  margin: 0.75rem 0 0.35rem;
  font-size: 0.85rem;
}
.section:first-child {
  margin-top: 0;
}
.dim {
  color: var(--el-text-color-secondary);
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 0.85rem;
  font-weight: normal;
}
.alert-row {
  margin-bottom: 0.5rem;
}
.footnote {
  margin: 0.35rem 0 0;
  font-size: 0.85rem;
}
.chart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
}
.chart-title {
  margin: 0;
}
.code-select {
  min-width: 14rem;
  max-width: 22rem;
}
.chart-hint {
  margin: 0.25rem 0 0.5rem;
}
</style>
