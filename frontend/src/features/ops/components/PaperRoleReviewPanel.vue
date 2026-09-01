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
        <!--
          「角色演进图」这行标题删了：卡片头已经写着「角色演进」，图自己有坐标轴与
          图例，标题只是把选码控件挤到第二行。读法说明（纵轴是档位、最多 6 只、
          缺口＝当日无观测）挪进选码控件的 tooltip，页面上不留常驻说明段。
        -->
        <div class="chart-head">
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
          </el-tooltip>
        </div>
        <PaperRoleTimelineChart :model="timelineModel" :height="260" />
      </template>

      <template v-if="positionAlerts.length">
        <p class="section dim">持仓角色告警 <b class="count">{{ positionAlerts.length }}</b></p>
        <!--
          这一块原来是一摞 el-alert，靠 description 摊开「观测日 · 角色依据 · 持仓层数」。
          description 禁用，但那三样是**证据数据**、不是介绍段，藏进 tooltip 等于丢证据。
          改成每条一行：状态 chip + 标的 + 判定 + 依据 + 观测日 + 层数，全部留在页面上。
        -->
        <ul class="role-alert-list">
          <li v-for="alert in positionAlerts" :key="String(alert.code)" class="alert-row">
            <el-tag size="small" type="warning" effect="plain">{{ String(alert.role_label) }}</el-tag>
            <span class="alert-row__who">{{ String(alert.name) }} {{ String(alert.code) }}</span>
            <span>已判{{ String(alert.role_label) }}仍在持仓</span>
            <span class="dim">{{ String(alert.role_basis || '角色依据缺失') }}</span>
            <span v-if="alert.observed_at" class="dim mono">观测 {{ String(alert.observed_at) }}</span>
            <span v-if="alert.layers != null" class="dim mono">持仓 {{ String(alert.layers) }} 层</span>
          </li>
        </ul>
      </template>

      <template v-if="survival.length">
        <p class="section dim">龙头存活榜 <b class="count">{{ survival.length }}</b></p>
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
        <p class="section dim">最近角色转移 <b class="count">{{ recentTransitions.length }}</b></p>
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
/* 每条告警一行：chip + 标的 + 判定 + 证据，横排到底，不换行成第二段 */
.role-alert-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.alert-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.55rem;
  padding: 0.25rem 0;
  font-size: 0.85rem;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.alert-row:last-child {
  border-bottom: 0;
}
.alert-row__who {
  font-weight: 600;
}
.mono {
  font-family: var(--mono);
}
.footnote {
  margin: 0.35rem 0 0;
  font-size: 0.85rem;
}
/* 图上方只剩选码控件，靠右贴齐图的右边缘 */
.chart-head {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 0.35rem;
}
.code-select {
  min-width: 14rem;
  max-width: 22rem;
}
.count {
  font-family: var(--mono);
  font-weight: 500;
  color: var(--el-text-color-secondary);
}
</style>
