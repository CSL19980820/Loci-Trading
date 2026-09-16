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
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import BasicTable, { type BasicTableColumn } from '@/shared/components/ui/BasicTable.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { toErrorMessage } from '@/shared/lib/errors'
import { strategyShortLabel } from '@/shared/lib/format'
import { Close, RefreshRight } from '@element-plus/icons-vue'

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
  if (phase.value === 'idle') return 0
  if (phase.value === 'scanning' || phase.value === 'repairing') {
    return Math.max(0, Math.min(100, progress.value?.percent ?? 0))
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

/* idle 标题已是“尚未体检”，meta 不再重复“未扫描” */
const heroBarMeta = computed(() => {
  if (phase.value === 'idle') return ''
  if (phase.value === 'scanning') return '扫描中'
  if (phase.value === 'repairing') return '修复中'
  if (phase.value === 'healthy') return '健康'
  return '待处理'
})

/** 状态色纪律：中性态灰，通过态健康色，只有「待处理」才用告警色（D1：不用红绿） */
const heroBarMetaClass = computed(() => {
  if (phase.value === 'healthy') return 'text-ok'
  if (phase.value === 'result') return 'text-warn'
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

/* 两个 Tab 各自出错：标题带分区前缀，否则不知道去哪修 */
const pageError = computed(() => {
  if (activeTab.value === 'overlap' && overlapError.value) return `信号重叠：${overlapError.value}`
  if (activeTab.value !== 'overlap' && healthError.value) return `数据体检：${healthError.value}`
  return healthError.value || overlapError.value
})

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
  <div class="page-fill flex h-full min-h-0 flex-1 flex-col overflow-hidden">
    <el-alert
      v-if="pageError"
      :title="pageError"
      type="error"
      show-icon
      closable
      class="mb-2 shrink-0"
      @close="clearPageError"
    />

    <PageToolbar dense seamless :note="activeTab === 'overlap' ? OVERLAP_HINT : undefined">
      <PageTabs v-model="activeTab" :items="insightTabs" :sticky="false" aria-label="体检分区" class="min-w-0 flex-1" />
      <template v-if="activeTab === 'overlap'">
        <span class="text-aux text-mist">近</span>
        <el-input-number
          v-model="overlapDays"
          aria-label="信号重叠统计天数"
          :min="10"
          :max="250"
          size="small"
          class="w-30 shrink-0"
        />
        <span class="text-aux text-mist">天</span>
      </template>
      <template #actions>
        <el-button
          v-if="showHeaderAction"
          type="primary"
          size="small"
          :icon="activeTab === 'overlap' ? RefreshRight : Close"
          :loading="activeTab === 'overlap' && busy"
          :disabled="phase === 'repairing' || busy"
          @click="onHeaderAction"
        >
          {{ headerLabel }}
        </el-button>
      </template>
    </PageToolbar>

    <div class="insights-body" :class="{ 'insights-body--table': activeTab === 'overlap' }">
      <PageBusy overlay :busy="busy && !hasOverlapData && activeTab === 'overlap'" />

      <div v-show="activeTab === 'health'" class="flex min-h-0 flex-col gap-2">
        <div class="border-line bg-surface flex shrink-0 flex-col overflow-hidden rounded-md">
          <div class="health-hero">
            <HealthSealDial
              :score="score"
              :grade="grade"
              :phase="phase"
              :progress="dialProgress"
            />

            <div class="flex min-w-0 flex-col items-start gap-2">
              <h2 class="text-hero m-0 leading-snug font-bold tracking-wide">
                {{ headline }}
                <span class="text-aux ml-2 font-semibold" :class="heroBarMetaClass">{{ heroBarMeta }}</span>
              </h2>
              <p class="text-aux text-mist m-0 leading-snug">{{ subtitle }}</p>

              <div class="mt-1 flex w-full flex-wrap items-center gap-2">
                <template v-if="phase === 'idle'">
                  <el-button type="primary" @click="scan()">一键扫描</el-button>
                  <el-button plain @click="scan({ includeNetwork: true })">深度扫描</el-button>
                </template>

                <template v-else-if="phase === 'scanning'" />

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
                  <p v-if="repairPlan?.labels?.length" class="text-aux text-mist m-0 w-full leading-snug">
                    合并动作：{{ repairPlan.labels.join(' · ') }}
                  </p>
                  <p
                    v-else-if="hasRepairableIssues && !selectedRepairIds.length"
                    class="text-aux text-mist m-0 w-full leading-snug"
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

      <div v-show="activeTab === 'overlap'" class="page-pane min-w-0">
        <!-- 标题「选股信号重叠」= 当前 Tab 名，删；天数/刷新/口径全部并进上方分区行（任务 7） -->
        <Sheet fill>
          <BasicTable
            :columns="overlapColumns"
            height="100%"
            :data-source="overlapRows"
            :loading="busy"
            :pagination="false"
            :row-class-name="overlapRowClass"
            :row-key="(row) => `${row.strategy_a}-${row.strategy_b}`"
            empty-text="无重叠数据"
            empty-reason="需至少两套战法的精选候选记录"
          >
            <template #jaccard="{ row }">
              {{ (Number(row.avg_jaccard) * 100).toFixed(1) }}%
            </template>
            <template #codes="{ row }">
              <span
                v-if="Array.isArray(row.top_shared_codes) && row.top_shared_codes.length"
                class="text-aux font-mono break-all"
              >
                {{ (row.top_shared_codes as string[]).slice(0, 6).join(' · ') }}
                <span v-if="Number(row.shared_code_count) > 6" class="text-mist">
                  +{{ Number(row.shared_code_count) - 6 }}
                </span>
              </span>
              <span v-else class="text-mist">—</span>
            </template>
            <template #level="{ row }">
              <el-tag size="small" effect="plain" :type="overlapTagType(String(row.overlap_level))">
                {{ overlapLevelLabel(String(row.overlap_level)) }}
              </el-tag>
            </template>
          </BasicTable>
          <p v-if="hasHighOverlap" class="form-hint form-error">
            高重叠 = 信号源几乎相同，别当成分散
          </p>
        </Sheet>
      </div>
    </div>
  </div>
</template>

<style scoped src="./InsightsView.css" />
