<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, watch } from 'vue'

import HealthCheckList from '@/features/review/components/HealthCheckList.vue'
import HealthScanProgress from '@/features/review/components/HealthScanProgress.vue'
import HealthSealDial from '@/features/review/components/HealthSealDial.vue'
import {
  useHealthCheckup,
  type HealthCheckRow,
} from '@/features/review/composables/useHealthCheckup'
import { getOverlap } from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import { RefreshRight } from '@element-plus/icons-vue'

type InsightTab = 'health' | 'overlap'

const activeTab = ref<InsightTab>('health')
const insightTabs = [
  { name: 'health', label: '数据体检' },
  { name: 'overlap', label: '信号重叠' },
]

const {
  phase,
  error: healthError,
  report,
  progress,
  repairBusy,
  score,
  grade,
  repairPlan,
  canOneClickRepair,
  hasRepairableIssues,
  subtitle,
  issueRows,
  okRows,
  pendingRows,
  scan,
  cancelScan,
  repairAll,
  repairFinding,
} = useHealthCheckup()

const overlapPending = ref(0)
const busy = computed(() => overlapPending.value > 0)
const overlapError = ref('')
const overlap = ref<Record<string, unknown>[]>([])
const overlapDays = ref(60)
const loaded = reactive({ overlap: false })
const selectedRepairIds = ref<string[]>([])
let active = true
let overlapVersion = 0

const pageError = computed(() => healthError.value || overlapError.value)

const hasOverlapData = computed(() => loaded.overlap)

const showRepairActions = computed(
  () => phase.value === 'result' || (phase.value === 'healthy' && hasRepairableIssues.value),
)

function clearPageError(): void {
  healthError.value = ''
  overlapError.value = ''
}

function overlapRowClass({ row }: { row: Record<string, unknown>; rowIndex: number }): string {
  if (row.overlap_level === 'high') return 'row-critical'
  if (row.overlap_level === 'medium') return 'row-warning'
  return ''
}

const overlapColumns: BasicTableColumn[] = [
  { prop: 'strategy_a', label: '战法 A', minWidth: 100 },
  { prop: 'strategy_b', label: '战法 B', minWidth: 100 },
  { prop: 'avg_jaccard', label: '日均重合', align: 'right', minWidth: 100, slotName: 'jaccard' },
  { prop: 'collision_days', label: '撞车日', align: 'right', minWidth: 80 },
  { prop: 'days_compared', label: '可比日', align: 'right', minWidth: 80 },
  { prop: 'top_shared_codes', label: '常撞代码', minWidth: 180, slotName: 'codes' },
  { prop: 'overlap_level', label: '程度', align: 'right', minWidth: 80, slotName: 'level' },
]

const overlapRows = computed(() => overlap.value)

async function loadOverlap(): Promise<void> {
  const version = ++overlapVersion
  overlapPending.value += 1
  overlapError.value = ''
  try {
    const rows = await getOverlap(overlapDays.value)
    if (!active || version !== overlapVersion) return
    overlap.value = rows
    loaded.overlap = true
  } catch (e: unknown) {
    if (!active || version !== overlapVersion) return
    overlapError.value = toErrorMessage(e, '请求失败')
  } finally {
    if (active) overlapPending.value = Math.max(0, overlapPending.value - 1)
  }
}

/** 顶栏：体检页只留「取消扫描」；扫描入口只在主 CTA，避免双按钮。 */
const showHeaderAction = computed(
  () => activeTab.value === 'overlap' || phase.value === 'scanning',
)

const headerLabel = computed(() => {
  if (activeTab.value === 'overlap') return '刷新'
  return '取消扫描'
})

function onHeaderAction(): void {
  if (activeTab.value === 'health') {
    cancelScan()
    return
  }
  void loadOverlap()
}

function onRepairRow(row: HealthCheckRow): void {
  void repairFinding({
    check: row.id,
    remediation: row.remediation,
  })
}

function onRepairSelected(): void {
  const ids = selectedRepairIds.value.length
    ? selectedRepairIds.value
    : issueRows.value.filter((r) => r.remediation).map((r) => r.id)
  void repairAll(ids)
}

watch(
  activeTab,
  (tab) => {
    if (tab === 'overlap' && !loaded.overlap) void loadOverlap()
  },
  { immediate: true },
)

onUnmounted(() => {
  active = false
  overlapVersion += 1
})
</script>

<template>
  <div class="page-fill insights-page">
    <el-alert
      v-if="pageError"
      :title="pageError"
      type="error"
      show-icon
      closable
      class="mb"
      @close="clearPageError"
    />

    <div class="insights-tabs-row">
      <PageTabs v-model="activeTab" :items="insightTabs" :sticky="false" aria-label="体检分区" />
      <el-button
        v-if="showHeaderAction"
        type="primary"
        size="small"
        :icon="RefreshRight"
        :loading="activeTab === 'overlap' && busy"
        :disabled="phase === 'repairing' || busy"
        @click="onHeaderAction"
      >
        {{ headerLabel }}
      </el-button>
    </div>

    <div class="page-scroll page-scroll--busy">
      <PageBusy overlay :busy="busy && !hasOverlapData && activeTab === 'overlap'" />

      <div v-show="activeTab === 'health'" class="health-pane page-pane">
        <div class="health-hero">
          <HealthSealDial :score="score" :grade="grade" :phase="phase" :subtitle="subtitle" />

          <div class="health-cta">
            <template v-if="phase === 'idle'">
              <el-button type="primary" size="large" @click="scan">一键扫描</el-button>
              <p class="health-cta__hint">约 7 项 · 不写库 · 只读行情仓</p>
            </template>

            <template v-else-if="phase === 'scanning'">
              <el-button size="large" @click="cancelScan">取消扫描</el-button>
            </template>

            <template v-else-if="phase === 'repairing'">
              <el-button type="primary" size="large" loading disabled>正在修复…</el-button>
            </template>

            <template v-else-if="phase === 'result' || showRepairActions">
              <el-button
                v-if="canOneClickRepair || hasRepairableIssues"
                type="primary"
                size="large"
                :loading="repairBusy === '__all__'"
                :disabled="!!repairBusy || !selectedRepairIds.length"
                @click="onRepairSelected"
              >
                一键修复{{ selectedRepairIds.length ? `（${selectedRepairIds.length}）` : '' }}
              </el-button>
              <el-button size="large" :disabled="!!repairBusy" @click="scan">再次扫描</el-button>
              <p v-if="repairPlan?.labels?.length" class="health-cta__hint">
                合并动作：{{ repairPlan.labels.join(' · ') }}
              </p>
              <p v-else-if="report" class="health-cta__hint mono">
                上次 {{ report.checked_at || '—' }} · 交易日 {{ report.trade_date || '—' }}
              </p>
            </template>

            <template v-else>
              <el-button type="primary" size="large" @click="scan">再次扫描</el-button>
              <p v-if="report" class="health-cta__hint mono">
                上次 {{ report.checked_at || '—' }} · 交易日 {{ report.trade_date || '—' }}
              </p>
            </template>
          </div>
        </div>

        <HealthScanProgress
          v-if="progress"
          :progress="progress"
          :title="phase === 'scanning' ? '扫描进度' : phase === 'repairing' ? '修复进度' : undefined"
        />

        <HealthCheckList
          v-if="phase === 'scanning' || phase === 'result' || phase === 'healthy' || phase === 'repairing'"
          v-model:selected-ids="selectedRepairIds"
          :issue-rows="issueRows"
          :ok-rows="okRows"
          :pending-rows="pendingRows"
          :repair-busy="repairBusy"
          :show-actions="showRepairActions"
          @repair="onRepairRow"
        />

        <EmptyState
          v-else-if="phase === 'idle'"
          description="点「一键扫描」核对行情仓是否可安全选股"
          :image-size="56"
        />
      </div>

      <div v-show="activeTab === 'overlap'">
        <Sheet title="选股信号重叠">
          <template #actions>
            <span class="inline-label">近</span>
            <el-input-number v-model="overlapDays" :min="10" :max="250" size="small" />
            <span class="inline-label">天</span>
            <el-button size="small" :disabled="busy" @click="loadOverlap">查询</el-button>
          </template>
          <p class="form-hint overlap-intro">
            看多套选股是否天天撞同一批票（假分散）。不算持仓风险——成交账本没有战法字段。
            策略是否失效请看选股目录「近期胜率」。前视偏差由测试与生成链自动拦，不在本页。
          </p>
          <BasicTable
            v-if="overlap.length"
            :columns="overlapColumns"
            :data-source="overlapRows"
            :pagination="false"
            :row-class-name="overlapRowClass"
            :row-key="(row) => `${row.strategy_a}-${row.strategy_b}`"
          >
            <template #jaccard="{ row }">
              {{ (Number(row.avg_jaccard) * 100).toFixed(1) }}%
            </template>
            <template #codes="{ row }">
              <span
                v-if="Array.isArray(row.top_shared_codes) && row.top_shared_codes.length"
                class="mono codes"
              >
                {{ (row.top_shared_codes as string[]).slice(0, 6).join(' · ') }}
                <span v-if="Number(row.shared_code_count) > 6" class="dim">
                  +{{ Number(row.shared_code_count) - 6 }}
                </span>
              </span>
              <span v-else class="dim">—</span>
            </template>
            <template #level="{ row }">
              <span
                class="chip"
                :class="
                  row.overlap_level === 'high'
                    ? 'chip-red'
                    : row.overlap_level === 'medium'
                      ? 'chip-yellow'
                      : 'chip-green'
                "
              >
                {{
                  ({ low: '低', medium: '中', high: '高' } as Record<string, string>)[
                    String(row.overlap_level)
                  ] ?? row.overlap_level
                }}
              </span>
            </template>
          </BasicTable>
          <PageBusy v-else-if="busy" label="加载重叠度…" />
          <EmptyState
            v-else
            description="无数据：需要至少两套战法的 core 候选记录（选股并落库后可见）"
          />
          <p
            v-if="overlap.some((o) => o.overlap_level === 'high')"
            class="form-hint form-error"
          >
            高重叠 = 信号源几乎相同；建议合并战法或拉开参数/宇宙，别当成分散。
          </p>
        </Sheet>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 0.55rem;
}

.insights-tabs-row {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  margin-bottom: 0.55rem;
  padding-right: 0.85rem;
}

.insights-tabs-row :deep(.page-tabs) {
  flex: 1;
  min-width: 0;
  margin-bottom: 0;
}

.page-scroll--busy {
  position: relative;
  min-height: 12rem;
}

.health-pane {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  padding: 0.15rem 0.25rem 0.85rem;
}

.health-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.85rem;
  padding: 0.65rem 0.85rem 0.35rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.health-cta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.55rem;
  width: 100%;
}

.health-cta__hint {
  margin: 0;
  width: 100%;
  text-align: center;
  font-size: 0.78rem;
  color: var(--mist);
  line-height: 1.4;
}

.chip-red {
  background: var(--seal) !important;
  color: #fff !important;
}

.chip-green {
  background: var(--lake) !important;
  color: #fff !important;
}

.chip-yellow {
  background: #c8a400 !important;
  color: #fff !important;
}

.inline-label {
  font-size: 0.82rem;
  color: var(--mist);
}

.overlap-intro {
  margin: 0 0 0.65rem;
  line-height: 1.45;
}

.codes {
  font-size: 0.8rem;
  word-break: break-all;
}

:deep(.row-critical) {
  background: rgba(196, 30, 58, 0.05);
}

:deep(.row-warning) {
  background: rgba(200, 164, 0, 0.06);
}
</style>
