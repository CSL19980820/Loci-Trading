<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHeader from '@/shared/components/layout/PageHeader.vue'
import type { LanesSummary, LlmProvider, ScheduleStatus } from '@/shared/types/quant'
import DataDirTab from './components/DataDirTab.vue'
import JobsTab from './components/JobsTab.vue'
import LanesTab from './components/LanesTab.vue'
import LlmTab from './components/LlmTab.vue'
import MarketSyncTab from './components/MarketSyncTab.vue'
import McpTab from './components/McpTab.vue'
import NotifyTab from './components/NotifyTab.vue'
import RunsTab from './components/RunsTab.vue'
import SkillsTab from './components/SkillsTab.vue'
import { provideOpsFeedback } from './composables/useOpsFeedback'

type TabLoadable = { load: () => Promise<void> }

const { busy, notice, errorText, guard } = provideOpsFeedback()

const activeTab = ref('skills')
const providers = ref<LlmProvider[]>([])
const schedule = ref<ScheduleStatus | null>(null)
const lanesSummary = ref<LanesSummary | null>(null)

const skillsTab = ref<TabLoadable | null>(null)
const mcpTab = ref<TabLoadable | null>(null)
const llmTab = ref<TabLoadable | null>(null)
const dataDirTab = ref<TabLoadable | null>(null)
const marketSyncTab = ref<(TabLoadable & { enableRecommendedSync: () => Promise<void> }) | null>(
  null,
)
const lanesTab = ref<TabLoadable | null>(null)
const notifyTab = ref<TabLoadable | null>(null)
const jobsTab = ref<TabLoadable | null>(null)
const runsTab = ref<TabLoadable | null>(null)

const headerSubtitle = computed(() => {
  if (activeTab.value === 'lanes' && lanesSummary.value) {
    const s = lanesSummary.value
    const total = s.ok + s.degraded + s.down
    if (total > 0) return `线路 · 通 ${s.ok} / 降级 ${s.degraded} / 断 ${s.down}`
  }
  if (!schedule.value) return undefined
  return schedule.value.running
    ? `调度运行中 · ${schedule.value.jobs.length} 个任务`
    : '调度未启用'
})

function onProvidersLoaded(list: LlmProvider[]): void {
  providers.value = list
}

function onScheduleChanged(value: ScheduleStatus | null): void {
  schedule.value = value
}

function onLanesSummaryChanged(value: LanesSummary | null): void {
  lanesSummary.value = value
}

async function reload(): Promise<void> {
  await guard(async () => {
    await Promise.all([
      skillsTab.value?.load(),
      mcpTab.value?.load(),
      llmTab.value?.load(),
      dataDirTab.value?.load(),
      marketSyncTab.value?.load(),
      lanesTab.value?.load(),
      notifyTab.value?.load(),
      jobsTab.value?.load(),
      runsTab.value?.load(),
    ])
  })
}

async function enableRecommendedSync(): Promise<void> {
  activeTab.value = 'market-sync'
  await marketSyncTab.value?.enableRecommendedSync()
  await jobsTab.value?.load()
}

async function onJobsChanged(): Promise<void> {
  await jobsTab.value?.load()
}

async function onRunsChanged(): Promise<void> {
  await runsTab.value?.load()
}

onMounted(reload)
</script>

<template>
  <div class="page-fill">
    <PageHeader title="设置" :subtitle="headerSubtitle">
      <el-button :disabled="busy" @click="reload">刷新</el-button>
    </PageHeader>

    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      show-icon
      closable
      class="mb"
      @close="notice = ''"
    />
    <el-alert
      v-if="errorText"
      :title="errorText"
      type="error"
      show-icon
      closable
      class="mb"
      @close="errorText = ''"
    />

    <div class="page-scroll">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="技能包" name="skills">
          <SkillsTab ref="skillsTab" :providers="providers" />
        </el-tab-pane>
        <el-tab-pane label="MCP" name="mcp">
          <McpTab ref="mcpTab" />
        </el-tab-pane>
        <el-tab-pane label="LLM" name="llm">
          <LlmTab ref="llmTab" @providers-loaded="onProvidersLoaded" />
        </el-tab-pane>
        <el-tab-pane label="数据目录" name="data-dir">
          <DataDirTab ref="dataDirTab" />
        </el-tab-pane>
        <el-tab-pane label="行情同步" name="market-sync">
          <MarketSyncTab ref="marketSyncTab" @jobs-changed="onJobsChanged" />
        </el-tab-pane>
        <el-tab-pane label="线路" name="lanes">
          <LanesTab ref="lanesTab" @summary-changed="onLanesSummaryChanged" />
        </el-tab-pane>
        <el-tab-pane label="推送" name="notify">
          <NotifyTab ref="notifyTab" />
        </el-tab-pane>
        <el-tab-pane label="定时任务" name="jobs">
          <JobsTab
            ref="jobsTab"
            @schedule-changed="onScheduleChanged"
            @enable-recommended-sync="enableRecommendedSync"
            @runs-changed="onRunsChanged"
          />
        </el-tab-pane>
        <el-tab-pane label="执行历史" name="runs">
          <RunsTab ref="runsTab" @go-jobs="activeTab = 'jobs'" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>
