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
import { strategyShortLabel } from '@/shared/lib/format'
import { InfoFilled, RefreshRight } from '@element-plus/icons-vue'

type InsightTab = 'health' | 'overlap'

const activeTab = ref<InsightTab>('health')
const insightTabs = [
  { name: 'health', label: '数据体检' },
  { name: 'overlap', label: '信号重叠' },
]

const {
  phase,
  error: healthError,
  progress,
  repairBusy,
  score,
  grade,
  repairPlan,
  canOneClickRepair,
  hasRepairableIssues,
  headline,
  subtitle,
  idleSkeletonRows,
  issueRows,
  okRows,
  pendingRows,
  scan,
  cancelScan,
  cancelRepair,
  repairAll,
  repairFinding,
} = useHealthCheckup()

const dialProgress = computed(() => {
  if (phase.value === 'idle') return 8
  if (phase.value === 'scanning' || phase.value === 'repairing') {
    return Math.max(8, Math.min(100, progress.value?.percent ?? 12))
  }
  if (score.value != null) return Math.min(100, Math.max(0, score.value))
  return 0
})

const listPendingRows = computed(() =>
  phase.value === 'idle' ? idleSkeletonRows.value : pendingRows.value,
)

const showCheckList = computed(
  () =>
    phase.value === 'idle' ||
    phase.value === 'scanning' ||
    phase.value === 'result' ||
    phase.value === 'healthy' ||
    phase.value === 'repairing',
)

const heroBarMeta = computed(() => {
  if (phase.value === 'idle') return '未扫描'
  if (phase.value === 'scanning') return '扫描中'
  if (phase.value === 'repairing') return '修复中'
  if (phase.value === 'healthy') return '健康'
  return '待处理'
})

/** 状态色纪律：中性态灰，通过态湖绿，只有「待处理」才用告警红 */
const heroBarMetaClass = computed(() => {
  if (phase.value === 'healthy') return 'health-hero__meta--ok'
  if (phase.value === 'result') return 'health-hero__meta--loss'
  return ''
})

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

/** 重叠口径长句只写一份，放 tooltip，不常驻页面（连同原来占一行的导语一起） */
const OVERLAP_HINT =
  '看多套选股是否天天撞同一批票。只看选股信号是否互相重合，不算持仓风险（成交账本没有战法字段）。' +
  '策略是否失效看选股目录「近期胜率」；前视偏差由测试与生成链自动拦，不在本页。'

const OVERLAP_LEVEL_LABELS: Record<string, string> = { low: '低', medium: '中', high: '高' }

function overlapLevelLabel(level: string): string {
  return OVERLAP_LEVEL_LABELS[level] ?? level
}

/*
 * 程度徽章走 EP 语义档，不再自绘 .chip-red/.chip-yellow/.chip-green。
 * 旧写法把「高重叠」染成 --seal（品牌色）、「低」染成 --lake（跌绿）——
 * 既占了品牌色，又把绿色借给了非价格语义，两条都违反 D1。
 */
function overlapTagType(level: string): 'danger' | 'warning' | 'info' {
  if (level === 'high') return 'danger'
  if (level === 'medium') return 'warning'
  return 'info'
}

const overlapColumns: BasicTableColumn[] = [
  /* 战法列展示中文短名；slug 只留在 row-key 里，界面不露英文（任务 8） */
  {
    prop: 'strategy_a',
    label: '战法 A',
    minWidth: 100,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => strategyShortLabel(String(row.strategy_a ?? '')),
  },
  {
    prop: 'strategy_b',
    label: '战法 B',
    minWidth: 100,
    align: 'center',
    headerAlign: 'center',
    formatter: (row) => strategyShortLabel(String(row.strategy_b ?? '')),
  },
  { prop: 'avg_jaccard', label: '日均重合', align: 'center', headerAlign: 'center', minWidth: 100, slotName: 'jaccard' },
  { prop: 'collision_days', label: '撞车日', align: 'center', headerAlign: 'center', minWidth: 80 },
  { prop: 'days_compared', label: '可比日', align: 'center', headerAlign: 'center', minWidth: 80 },
  { prop: 'top_shared_codes', label: '常撞代码', minWidth: 180, align: 'center', headerAlign: 'center', slotName: 'codes' },
  { prop: 'overlap_level', label: '程度', align: 'center', headerAlign: 'center', minWidth: 80, slotName: 'level' },
]

const overlapRows = computed(() => overlap.value)

const hasHighOverlap = computed(() =>
  overlap.value.some((row) => row.overlap_level === 'high'),
)

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
    autoFixable: row.autoFixable,
  })
}

function onRepairSelected(): void {
  const ids = selectedRepairIds.value.length
    ? selectedRepairIds.value
    : issueRows.value.filter((r) => r.autoFixable).map((r) => r.id)
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
      <!-- 重叠查询的天数与口径也并进这一行：Sheet 头与正文说明各省一行 -->
      <template v-if="activeTab === 'overlap'">
        <span class="inline-label">近</span>
        <el-input-number
          v-model="overlapDays"
          :min="10"
          :max="250"
          size="small"
          class="days-input"
        />
        <span class="inline-label">天</span>
      </template>
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
      <el-tooltip
        v-if="activeTab === 'overlap'"
        :content="OVERLAP_HINT"
        placement="bottom-end"
        :show-after="200"
      >
        <el-icon class="tabs-note" tabindex="0" :aria-label="OVERLAP_HINT"><InfoFilled /></el-icon>
      </el-tooltip>
    </div>

    <div class="page-scroll page-scroll--busy">
      <PageBusy overlay :busy="busy && !hasOverlapData && activeTab === 'overlap'" />

      <div v-show="activeTab === 'health'" class="health-pane page-pane">
        <div class="health-hero">
          <div class="health-hero__body">
            <HealthSealDial
              :score="score"
              :grade="grade"
              :phase="phase"
              :progress="dialProgress"
            />

            <div class="health-hero__copy">
              <h2 class="health-hero__headline">
                {{ headline }}
                <span class="health-hero__meta" :class="heroBarMetaClass">{{ heroBarMeta }}</span>
              </h2>
              <p class="health-hero__sub">{{ subtitle }}</p>

              <div class="health-cta">
                <template v-if="phase === 'idle'">
                  <el-button type="primary" @click="scan()">一键扫描</el-button>
                  <el-button plain @click="scan({ includeNetwork: true })">深度扫描</el-button>
                </template>

                <template v-else-if="phase === 'scanning'">
                  <el-button @click="cancelScan">取消扫描</el-button>
                </template>

                <template v-else-if="phase === 'repairing'">
                  <el-button type="primary" loading disabled>正在修复…</el-button>
                  <el-button @click="cancelRepair">停止等待</el-button>
                </template>

                <template v-else-if="phase === 'result' || showRepairActions">
                  <el-button
                    v-if="canOneClickRepair || hasRepairableIssues"
                    type="primary"
                    :loading="repairBusy === '__all__'"
                    :disabled="!!repairBusy || !selectedRepairIds.length"
                    @click="onRepairSelected"
                  >
                    一键修复{{ selectedRepairIds.length ? `（${selectedRepairIds.length}）` : '' }}
                  </el-button>
                  <el-button :disabled="!!repairBusy" @click="scan()">再次扫描</el-button>
                  <el-button :disabled="!!repairBusy" @click="scan({ includeNetwork: true })">
                    深度扫描
                  </el-button>
                  <p v-if="repairPlan?.labels?.length" class="health-cta__hint">
                    合并动作：{{ repairPlan.labels.join(' · ') }}
                  </p>
                  <p
                    v-else-if="hasRepairableIssues && !selectedRepairIds.length"
                    class="health-cta__hint"
                  >
                    勾选可修项后一键修复；人工项点「去处理」
                  </p>
                </template>

                <template v-else>
                  <el-button type="primary" @click="scan()">再次扫描</el-button>
                  <el-button @click="scan({ includeNetwork: true })">深度扫描</el-button>
                </template>
              </div>
            </div>
          </div>
        </div>

        <HealthScanProgress
          v-if="progress"
          :progress="progress"
          :title="phase === 'scanning' ? '扫描进度' : phase === 'repairing' ? '修复进度' : undefined"
        />

        <HealthCheckList
          v-if="showCheckList"
          v-model:selected-ids="selectedRepairIds"
          :issue-rows="phase === 'idle' ? [] : issueRows"
          :ok-rows="phase === 'idle' ? [] : okRows"
          :pending-rows="listPendingRows"
          :repair-busy="repairBusy"
          :show-actions="showRepairActions"
          :pending-title="phase === 'idle' ? '待检' : undefined"
          @repair="onRepairRow"
        />
      </div>

      <div v-show="activeTab === 'overlap'">
        <!-- 标题「选股信号重叠」= 当前 Tab 名，删；天数/刷新/口径全部并进上方分区行（任务 7） -->
        <Sheet>
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
              <el-tag size="small" effect="plain" :type="overlapTagType(String(row.overlap_level))">
                {{ overlapLevelLabel(String(row.overlap_level)) }}
              </el-tag>
            </template>
          </BasicTable>
          <PageBusy v-else-if="busy" label="加载重叠度…" />
          <EmptyState
            v-else
            description="无重叠数据"
            reason="需至少两套战法的 core 候选记录"
          />
          <p v-if="hasHighOverlap" class="form-hint form-error">
            高重叠 = 信号源几乎相同，别当成分散
          </p>
        </Sheet>
      </div>
    </div>
  </div>
</template>

<style scoped>
.insights-tabs-row {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  margin-bottom: var(--gap-1);
  padding-right: var(--gap-3);
}
.insights-tabs-row :deep(.page-tabs) {
  flex: 1;
  min-width: 0;
  margin-bottom: 0;
}
/* 只做 PageBusy 蒙版的定位锚点：不再写 min-height:12rem —— 空数据时那是 12rem 死白 */
.page-scroll--busy {
  position: relative;
}
.health-pane {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  min-height: 0;
}
.health-hero {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  overflow: hidden;
}
/* 状态字并进标题行：原来它独占一条 hero 头栏，标题还与 Tab 名重复 */
.health-hero__meta {
  margin-left: var(--gap-2);
  font-size: var(--fs-aux);
  font-weight: 600;
  color: var(--mist);
}
/* 通过态走 --success（令牌层已把它挂在跌绿上），待处理是告警不是亏损 */
.health-hero__meta--ok {
  color: var(--success);
}
.health-hero__meta--loss {
  color: var(--warn);
}
.health-hero__body {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--gap-3) var(--gap-4);
  align-items: center;
  padding: var(--gap-3);
}
.health-hero__copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--gap-1);
}
/* 中文标题上限 --fs-hero(17px)：旧版 1.35rem 大标题违反 D2 */
.health-hero__headline {
  margin: 0;
  font-size: var(--fs-hero);
  font-weight: 700;
  letter-spacing: 0.03em;
  line-height: 1.3;
  color: var(--ink);
}
.health-hero__sub {
  margin: 0;
  font-size: var(--fs-aux);
  line-height: 1.45;
  color: var(--mist);
}
.health-cta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
  width: 100%;
  margin-top: var(--gap-1);
}
.health-cta__hint {
  margin: 0;
  width: 100%;
  font-size: var(--fs-aux);
  color: var(--mist);
  line-height: 1.4;
}
@media (max-width: 720px) {
  .health-hero__body {
    grid-template-columns: minmax(0, 1fr);
    justify-items: center;
    text-align: center;
  }
  .health-hero__copy {
    align-items: center;
  }
  .health-cta {
    justify-content: center;
  }
}
.inline-label {
  font-size: var(--fs-aux);
  color: var(--mist);
}
.days-input {
  width: 7.5rem;
  flex-shrink: 0;
}
/* 口径提示：一枚 ⓘ，不占文本宽度 */
.tabs-note {
  flex-shrink: 0;
  font-size: var(--fs-aux);
  color: var(--mist);
  cursor: help;
}
.tabs-note:focus-visible {
  outline: 2px solid var(--seal);
  outline-offset: 2px;
  border-radius: var(--radius);
}
.codes {
  font-size: var(--fs-aux);
  word-break: break-all;
}
/* 行底纹用状态色而不是价格红：高重叠是「配置问题」，不是跌 */
:deep(.row-critical) {
  background: color-mix(in srgb, var(--stamp) 7%, transparent);
}
:deep(.row-warning) {
  background: color-mix(in srgb, var(--warn) 8%, transparent);
}
</style>
