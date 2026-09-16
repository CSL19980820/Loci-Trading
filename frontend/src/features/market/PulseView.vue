<script setup lang="ts">
/**
 * 盘面：开盘 5 秒内回答三件事——大盘怎么走 / 我的池子今天怎么样 / 系统有没有坏。
 *
 * 版面纪律：单行页头 + 刻度尺 + 报价带 + 主区（近选跟踪 | 样本榜）+ 底区（今日选股）。
 * 异常收成一行状态条；作业健康降级成页头一枚点；情报压成一行 tape。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Monitor, Refresh, RefreshRight } from '@element-plus/icons-vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import PulseHealthDot from './components/PulseHealthDot.vue'
import PulseIndexStrip from './components/PulseIndexStrip.vue'
import PulseMarketBoard from './components/PulseMarketBoard.vue'
import PulsePickTable from './components/PulsePickTable.vue'
import PulseStatusBar, { type PulseIssue } from './components/PulseStatusBar.vue'
import PulseTrackTable from './components/PulseTrackTable.vue'
import PulseWatchRail from './components/PulseWatchRail.vue'
import SessionRuler from './components/SessionRuler.vue'
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
import {
  todayEmptyShort,
  todayEmptyText,
  todayNoteText,
  trackEmptyShort,
  trackEmptyText,
  type PulseEmptyInput,
} from './composables/pulseEmptyState'
import { usePulseHome } from './composables/usePulseHome'
import { usePulseIntelBrief } from './composables/usePulseIntelBrief'
import { usePulseOpsHealth } from './composables/usePulseOpsHealth'

const {
  loading,
  error,
  indices,
  alertCount,
  sessionText,
  asOfText,
  tapeError,
  alertsError,
  historyError,
  session,
  trackRows,
  todayRows,
  trackNote,
  todayDate,
  screenHistoryTotal,
  boardTab,
  boardRows,
  sectorRows,
  boardNote,
  boardAsOf,
  pickPctMode,
  reload,
  persistSpot,
  spotPersistBusy,
  setBoardTab,
  effectivePct,
} = usePulseHome()

const intelTradeDate = computed(
  () => session.value?.last_trading_day || session.value?.today || '',
)
const { brief, briefError, briefLoading, loadBrief } = usePulseIntelBrief(intelTradeDate)

const {
  loading: healthLoading,
  error: healthError,
  hasEnabledScreenJob,
  nextScreenRunAt,
  lastFailedRun,
  load: loadOpsHealth,
} = usePulseOpsHealth()

const router = useRouter()

function goLive(): void {
  void router.push({ name: 'live' })
}
// 空态按真实状态说话：没跑过就别提定时任务，有任务就报后端算出的下次触发时间
const emptyInput = computed<PulseEmptyInput>(() => ({
  screenHistoryTotal: screenHistoryTotal.value,
  hasEnabledScreenJob: hasEnabledScreenJob.value,
  nextScreenRunAt: nextScreenRunAt.value,
}))

async function refreshAll(): Promise<void> {
  await Promise.all([reload(), loadBrief(), loadOpsHealth()])
}

/** 四条错误收成一行；全文进 popover。顺序＝严重度。 */
const issues = computed<PulseIssue[]>(() => {
  const list: PulseIssue[] = []
  if (error.value) list.push({ key: 'main', label: '盘面加载失败', detail: error.value })
  if (tapeError.value) {
    list.push({ key: 'tape', label: '行情更新失败', detail: tapeError.value })
  }
  if (alertsError.value) {
    list.push({
      key: 'alerts',
      label: '触价提醒不可用',
      detail: `请勿据此判断今日无止损：${alertsError.value}`,
    })
  }
  if (historyError.value) {
    list.push({ key: 'history', label: '选股数据不全', detail: historyError.value })
  }
  return list
})

const pickPctNote = computed(() => {
  if (pickPctMode.value === 'live') return '叠实时价'
  if (pickPctMode.value === 'local') return '本地日线价'
  return '价格待取'
})

const trackMeta = computed(() => (trackNote.value ? trackNote.value : '近 5 日'))
const trackHint = computed(() =>
  [`口径：${pickPctNote.value}`, trackNote.value, '同日同代码去重，当日选出的票只进「今日选股」']
    .filter(Boolean)
    .join(' · '),
)

const todayMeta = computed(() =>
  todayDate.value ? `${todayDate.value} · ${pickPctNote.value}` : '尚未落库',
)
const todayHint = computed(() =>
  todayDate.value
    ? `各战法合并 · 同代码取高分 · ${pickPctNote.value}`
    : todayNoteText(emptyInput.value),
)

const trackEmpty = computed(() => trackEmptyShort(emptyInput.value))
const trackEmptyHint = computed(() => trackEmptyText(emptyInput.value))
const todayEmpty = computed(() => todayEmptyShort(emptyInput.value))
const todayEmptyHint = computed(() => todayEmptyText(emptyInput.value))

const tradeDateText = computed(() => session.value?.today || '—')
</script>

<template>
  <div class="page-fill flex h-full min-h-0 flex-1 flex-col overflow-hidden" v-loading="loading">
    <PageToolbar>
      <span class="font-mono text-aux whitespace-nowrap tabular-nums text-mist">{{ tradeDateText }}</span>
      <UiBadge :variant="session?.live_allowed ? 'info' : 'secondary'">
        {{ sessionText }}
      </UiBadge>
      <span class="font-mono text-aux whitespace-nowrap tabular-nums text-mist" aria-label="行情快照时间">{{ asOfText || '--:--:--' }}</span>
      <template #actions>
        <PulseHealthDot
          :loading="healthLoading"
          :error="healthError"
          :last-failed-run="lastFailedRun"
          :has-enabled-screen-job="hasEnabledScreenJob"
          :next-screen-run-at="nextScreenRunAt"
        />
        <el-button :icon="Monitor" @click="goLive">实时大屏</el-button>
        <el-button :icon="Refresh" :loading="spotPersistBusy" :disabled="loading" @click="persistSpot">
          同步现价
        </el-button>
        <el-button type="primary" :icon="RefreshRight" :loading="loading" @click="refreshAll">刷新数据</el-button>
      </template>
    </PageToolbar>
    <SessionRuler :is-trading-day="session?.is_trading_day ?? null" />

    <PulseStatusBar :issues="issues" :busy="loading" @retry="refreshAll" />

    <div class="page-scroll pulse-home__body">
      <PulseIndexStrip
        :indices="indices"
        :alert-count="alertCount"
        :limit-up="brief?.emotion?.limit_up_count ?? null"
        :limit-down="brief?.emotion?.limit_down_count ?? null"
        :breadth-note="briefError ? `涨停/跌停读不到：${briefError}` : ''"
      />

      <PulseWatchRail
        :brief="brief"
        :brief-loading="briefLoading"
        :brief-error="briefError"
      />

      <div class="pulse-home__upper">
        <PulseTrackTable
          title="近选跟踪"
          :note="trackMeta"
          :hint="trackHint"
          :rows="trackRows"
          :empty="trackEmpty"
          :empty-hint="trackEmptyHint"
        />
        <PulseMarketBoard
          :tab="boardTab"
          :rows="boardRows"
          :sector-rows="sectorRows"
          :note="boardNote"
          :as-of="boardAsOf"
          :pct-of="effectivePct"
          @update:tab="setBoardTab"
          @retry="refreshAll"
        />
      </div>

      <PulsePickTable
        class="pulse-home__today"
        title="今日选股"
        :note="todayMeta"
        :hint="todayHint"
        :rows="todayRows"
        :empty="todayEmpty"
        :empty-hint="todayEmptyHint"
        show-strategy
      />
    </div>
  </div>
</template>

<style scoped src="./PulseView.css"></style>
