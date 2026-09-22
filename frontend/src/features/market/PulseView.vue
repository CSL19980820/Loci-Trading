<script setup lang="ts">
/**
 * 盘面：开盘 5 秒内回答三件事——大盘怎么走 / 我的池子今天怎么样 / 系统有没有坏。
 *
 * 版面（Vercel Dashboard 一路）：
 *   页头（标题 + 盘面状态 + 时段倒计时 + 库内快照时间 + 作业健康 + 动作）
 *   指数卡带（上证 / 深成 / 创业 / 科创50）
 *   情报 chip 行
 *   近选跟踪 + 智能体研判：两张表平分剩余高度，各在面板内滚，页面本身不滚
 * 手机：全部纵向堆叠，表格换成卡片列表，卡带横滑。
 */
import { computed, ref } from 'vue'
import MobilePageFrame from '@/shared/components/layout/MobilePageFrame.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import { useMobileLayout } from '@/shared/composables/useMobileLayout'
import { useRouter } from 'vue-router'
import { LoaderCircle, RotateCw } from '@lucide/vue'

import PageBusy from '@/shared/components/ui/PageBusy.vue'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import { Button } from '@/shared/components/ui/button'
import { toast } from 'vue-sonner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import PulseAgentFeed from './components/PulseAgentFeed.vue'
import PulseHealthDot from './components/PulseHealthDot.vue'
import PulseIndexStrip from './components/PulseIndexStrip.vue'
import PulseStatusBar, { type PulseIssue } from './components/PulseStatusBar.vue'
import PulseTrackTable from './components/PulseTrackTable.vue'
import PulseWatchRail from './components/PulseWatchRail.vue'
import {
  trackEmptyShort,
  trackEmptyText,
  type PulseEmptyInput,
} from './composables/pulseEmptyState'
import { usePulseAgentFeed } from './composables/usePulseAgentFeed'
import { usePulseHome } from './composables/usePulseHome'
import { usePulseIntelBrief } from './composables/usePulseIntelBrief'
import { usePulseOpsHealth } from './composables/usePulseOpsHealth'
import { useSessionClock } from './composables/useSessionClock'

const {
  loading,
  error,
  indices,
  tapeError,
  historyError,
  session,
  trackRows,
  trackNote,
  screenHistoryTotal,
  boardAsOf,
  pickPctMode,
  reload,
  persistSpot,
  spotPersistBusy,
} = usePulseHome()

const {
  rows: agentRows,
  loading: agentLoading,
  error: agentError,
  partialError: agentPartialError,
  load: loadAgentFeed,
} = usePulseAgentFeed()

const intelTradeDate = computed(() => session.value?.last_trading_day || session.value?.today || '')
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
const {
  phaseLabel: sessionPhase,
  remainText: sessionRemain,
  statusText: sessionStatus,
} = useSessionClock(() => session.value?.is_trading_day ?? null)

const emptyInput = computed<PulseEmptyInput>(() => ({
  screenHistoryTotal: screenHistoryTotal.value,
  hasEnabledScreenJob: hasEnabledScreenJob.value,
  nextScreenRunAt: nextScreenRunAt.value,
}))

/**
 * 刷新＝「同步现价 + 重读本页」两步。用户看到的是一件事：让盘面上的数字是最新的。
 * 写盘失败只提示不中断——读的部分照常刷新。
 */
async function refreshAll(): Promise<void> {
  const written = await persistSpot()
  if (written) toast.success(`现价已落盘 ${written} 只`)
  await Promise.all([reload(), loadBrief(), loadOpsHealth(), loadAgentFeed()])
}

/** 三条错误收成一行；全文进 popover。顺序＝严重度。 */
const issues = computed<PulseIssue[]>(() => {
  const list: PulseIssue[] = []
  if (error.value) list.push({ key: 'main', label: '盘面加载失败', detail: error.value })
  if (tapeError.value) list.push({ key: 'tape', label: '行情更新失败', detail: tapeError.value })
  if (historyError.value) list.push({ key: 'history', label: '选股数据不全', detail: historyError.value })
  return list
})

const pickPctNote = computed(() => {
  if (pickPctMode.value === 'live') return '叠实时价'
  if (pickPctMode.value === 'local') return '本地日线价'
  return '价格待取'
})

const trackMeta = computed(() => (trackNote.value ? trackNote.value : '近 5 日'))
const trackHint = computed(() =>
  [`口径：${pickPctNote.value}`, trackNote.value, '同日同代码去重，当日选出的票不再进这里'].filter(Boolean).join(' · '),
)

const trackEmpty = computed(() => trackEmptyShort(emptyInput.value))
const trackEmptyHint = computed(() => trackEmptyText(emptyInput.value))

const isLive = computed(() => Boolean(session.value?.live_allowed))
const boardClock = computed(() => {
  const raw = (boardAsOf.value || '').trim()
  if (!raw) return ''
  return raw.match(/(\d{2}:\d{2}:\d{2})/)?.[1] ?? raw.slice(-8)
})
const busy = computed(() => loading.value || spotPersistBusy.value)
const mobile = useMobileLayout()
const mobileSection = ref('tracking')
</script>

<template>
  <MobilePageFrame v-if="mobile" title="盘面" class="pulse-mobile">
    <template #actions><UiBadge :variant="isLive ? 'ok' : 'secondary'" dot>{{ sessionPhase }}</UiBadge><Button access="read" variant="ghost" size="icon" :disabled="busy" aria-label="同步现价并刷新本页" @click="refreshAll"><RotateCw :class="{'animate-spin':busy}" /></Button></template>
    <div class="pulse-mobile__status"><span>{{ sessionRemain }}</span><time v-if="boardClock">{{ boardClock }} 更新</time><PulseHealthDot :loading="healthLoading" :error="healthError" :last-failed-run="lastFailedRun" :has-enabled-screen-job="hasEnabledScreenJob" :next-screen-run-at="nextScreenRunAt" /></div>
    <PulseStatusBar :issues="issues" :busy="loading" @retry="refreshAll" />
    <PulseIndexStrip :indices="indices" />
    <PageTabs v-model="mobileSection" :items="[{name:'tracking',label:'近选跟踪',badge:trackRows.length},{name:'analysis',label:'智能体研判'},{name:'intel',label:'情报'}]" variant="pill" :sticky="false" class="pulse-mobile__tabs" aria-label="盘面内容" />
    <PulseTrackTable v-if="mobileSection === 'tracking'" compact title="近选跟踪" :note="trackMeta" :hint="trackHint" :rows="trackRows" :empty="trackEmpty" :empty-hint="trackEmptyHint" />
    <template v-else-if="mobileSection === 'analysis'"><p v-if="agentPartialError" class="pulse-mobile__partial">{{ agentPartialError }}</p><PulseAgentFeed compact :rows="agentRows" :loading="agentLoading" :error="agentError" :partial-error="agentPartialError" @retry="refreshAll" /></template>
    <PulseWatchRail v-else :brief="brief" :brief-loading="briefLoading" :brief-error="briefError" />
  </MobilePageFrame>
  <div v-else class="page-fill pulse-home relative flex h-full min-h-0 flex-1 flex-col overflow-hidden">
    <PageBusy overlay :busy="loading" label="加载盘面…" />

    <PageHeader title="盘面" seamless>
      <template #title>
        <span class="pulse-home__title">
          <UiBadge :variant="isLive ? 'ok' : 'secondary'" dot class="pulse-home__session">{{ sessionPhase }}</UiBadge>
          <span class="pulse-home__session-time" :title="sessionStatus">{{ sessionRemain }}</span>
        </span>
      </template>
      <template #actions>
        <span v-if="boardClock" class="pulse-home__clock" :title="`本地库快照 ${boardAsOf}`">库内 {{ boardClock }}</span>
        <PulseHealthDot
          :loading="healthLoading"
          :error="healthError"
          :last-failed-run="lastFailedRun"
          :has-enabled-screen-job="hasEnabledScreenJob"
          :next-screen-run-at="nextScreenRunAt"
        />
        <Tooltip>
          <TooltipTrigger as-child>
            <Button access="read" size="sm" :disabled="busy" aria-label="同步现价并刷新本页" @click="refreshAll">
              <LoaderCircle v-if="busy" class="animate-spin" aria-hidden="true" />
              <RotateCw v-else aria-hidden="true" />
              刷新
            </Button>
          </TooltipTrigger>
          <TooltipContent>把当前实时价落到本地日线，并重读本页数据</TooltipContent>
        </Tooltip>
      </template>
    </PageHeader>

    <div class="page-scroll pulse-home__body">
      <PulseStatusBar :issues="issues" :busy="loading" @retry="refreshAll" />

      <PulseIndexStrip :indices="indices" />

      <PulseWatchRail :brief="brief" :brief-loading="briefLoading" :brief-error="briefError" />

      <PulseTrackTable
        class="pulse-home__track"
        title="近选跟踪"
        :note="trackMeta"
        :hint="trackHint"
        :rows="trackRows"
        :empty="trackEmpty"
        :empty-hint="trackEmptyHint"
      />

      <PulseAgentFeed
        class="pulse-home__agents"
        :rows="agentRows"
        :loading="agentLoading"
        :error="agentError"
        :partial-error="agentPartialError"
        @retry="refreshAll"
      />
    </div>
  </div>
</template>

<style scoped src="./PulseView.css"></style>
<style scoped>
.pulse-mobile__status { display:flex; align-items:center; gap:8px; padding:0 0 10px; color:var(--text-tertiary); font-size:11px; }
.pulse-mobile__status time { margin-left:auto; }
.pulse-mobile__tabs { margin:12px 0 8px; }
.pulse-mobile__tabs :deep(.page-tabs__list) { width:100%; }.pulse-mobile__tabs :deep(.page-tabs__item) { flex:1; justify-content:center; height:36px; font-size:12px; padding-inline:7px; }
.pulse-mobile :deep(.pulse-panel) { width:100%; min-height:0; height:auto; flex:none; overflow:visible; box-shadow:none; }
.pulse-mobile :deep(.pulse-cards),.pulse-mobile :deep(.agent-feed-list) { overflow:visible; }
.pulse-mobile :deep(.pulse-card) { padding:13px 12px; min-height:82px; }
.pulse-mobile :deep(.agent-feed-item) { padding:8px 13px 14px; }.pulse-mobile :deep(.agent-feed-item__head button) { min-height:36px; font-size:14px; }.pulse-mobile :deep(.agent-feed-item__summary) { font-size:13px; line-height:1.8; }
.pulse-mobile__partial { color:var(--warn); font-size:12px; line-height:1.6; padding:8px 0; }
</style>
