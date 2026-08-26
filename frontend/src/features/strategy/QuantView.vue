<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import {
  CapabilityUnavailableError,
  getJobs,
  getMarketCoverage,
  getSkills,
  getStrategies,
  removeSkill,
  syncMarket,
} from '@/shared/api/quant'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageTabs from '@/shared/components/ui/PageTabs.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import type { MarketCoverage, Skill, StrategyInfo } from '@/shared/types/quant'
import DataSourcePanel from '@/features/datasource/DataSourcePanel.vue'
import MarketPanel from '@/features/marketplace/components/MarketPanel.vue'
import JobsTab from '@/features/ops/components/JobsTab.vue'

import QuantBacktestPanel from './components/QuantBacktestPanel.vue'
import QuantSkillsPanel from './components/QuantSkillsPanel.vue'
import QuantStrategiesPanel from './components/QuantStrategiesPanel.vue'
import ResearchPanel from '@/features/research/ResearchPanel.vue'
import PaperQuantPanel from '@/features/ops/components/PaperQuantPanel.vue'

type WorkshopTab =
  | 'engines'
  | 'skills'
  | 'sources'
  | 'jobs'
  | 'market'
  | 'backtest'
  | 'research'
  | 'paper'

const route = useRoute()
const router = useRouter()

function parseTab(raw: unknown): WorkshopTab {
  const value = String(raw || 'engines')
  if (
    value === 'skills'
    || value === 'sources'
    || value === 'jobs'
    || value === 'market'
    || value === 'backtest'
    || value === 'research'
    || value === 'paper'
  ) {
    return value
  }
  return 'engines'
}

const activeTab = ref<WorkshopTab>(parseTab(route.query.tab))
/** 运维旧链接会带 view=interfaces 直落「按接口」 */
const sourceView = computed(() => String(route.query.view || ''))
/** 选股/行情等入口可通过 query 直接打开对应研究标的 */
const researchCode = computed(() => String(route.query.code || '').trim())
/** 数据源角标只数源家数，工具条数不参与统计 */
const sourceCount = ref(0)
const jobsEnabled = ref(0)
const workshopTabs = computed(() => [
  { name: 'engines', label: '战法', badge: strategies.value.length || undefined },
  { name: 'skills', label: '技能', badge: skills.value.length || undefined },
  { name: 'sources', label: '数据源', badge: sourceCount.value || undefined },
  { name: 'jobs', label: '定时', badge: jobsEnabled.value || undefined },
  { name: 'market', label: '市场' },
  { name: 'backtest', label: '回测' },
  { name: 'research', label: '研究' },
  { name: 'paper', label: '纸面量化' },
])

const strategies = ref<StrategyInfo[]>([])
const skills = ref<Skill[]>([])
const coverage = ref<MarketCoverage | null>(null)
const busy = ref(false)
const syncBusy = ref(false)
const unavailable = ref('')
const jobsTab = ref<{ load: () => Promise<void> } | null>(null)

const needsBootstrap = computed(() =>
  /行情仓是空的|没有可同步的标的|数据体检未通过|empty_store|请先刷新证券列表/i.test(unavailable.value),
)

watch(
  () => route.query.tab,
  (raw) => {
    activeTab.value = parseTab(raw)
  },
)

watch(activeTab, (tab) => {
  const next = tab === 'engines' ? undefined : tab
  if (parseTab(route.query.tab) === tab) return
  void router.replace({ query: { ...route.query, tab: next } })
  if (tab === 'jobs') void jobsTab.value?.load()
})

async function guard<T>(task: () => Promise<T>): Promise<T | null> {
  busy.value = true
  unavailable.value = ''
  try {
    return await task()
  } catch (caught: unknown) {
    unavailable.value =
      caught instanceof CapabilityUnavailableError
        ? caught.message
        : caught instanceof Error
          ? caught.message
          : '请求失败'
    return null
  } finally {
    busy.value = false
  }
}

async function reload(): Promise<void> {
  await guard(async () => {
    const [list, skillList, cov, jobList] = await Promise.all([
      getStrategies(),
      getSkills(),
      getMarketCoverage(),
      getJobs().catch(() => []),
    ])
    strategies.value = list
    skills.value = skillList
    coverage.value = cov
    jobsEnabled.value = jobList.filter((j) => j.enabled).length
  })
}

function goScreen(kind: 'engine' | 'skill', slug: string): void {
  void router.push({
    path: '/screen-history',
    query: { select: `${kind}:${slug}` },
  })
}

function goRecommendedSync(): void {
  void router.push({ path: '/ops', query: { tab: 'system' }, hash: '#sys-sync' })
}

async function uninstallSkill(skill: Skill): Promise<void> {
  if (
    !(await confirmDangerous(
      `确定卸载技能「${skill.name}」？选股台将不再列出它。`,
      '卸载技能',
      '卸载',
    ))
  ) {
    return
  }
  try {
    await removeSkill(skill.slug)
    ElMessage.success(`已卸载 ${skill.name}`)
    skills.value = skills.value.filter((row) => row.slug !== skill.slug)
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '卸载失败'))
  }
}

async function bootstrapMarket(): Promise<void> {
  syncBusy.value = true
  unavailable.value = ''
  ElMessage.info('同步可能需要一两分钟，请稍候')
  try {
    const report = await syncMarket({
      refresh_instruments: true,
      limit: 200,
      workers: 6,
      interval: 0.1,
    })
    ElMessage.success(
      `同步完成：成功 ${String(report.succeeded ?? 0)} / 跳过 ${String(report.skipped ?? 0)}`
        + (report.spot_rows ? ` · 当日实时 ${String(report.spot_rows)} 行` : ''),
    )
    coverage.value = await getMarketCoverage()
  } catch (caught: unknown) {
    unavailable.value = caught instanceof Error ? caught.message : '同步失败'
  } finally {
    syncBusy.value = false
  }
}

onMounted(() => {
  void reload()
})
</script>

<template>
  <div class="page-fill">
    <PageBusy overlay :busy="activeTab !== 'research' && busy && !coverage && !strategies.length && !skills.length" />
    <el-alert
      v-if="unavailable"
      :title="unavailable"
      type="error"
      show-icon
      closable
      class="mb"
      @close="unavailable = ''"
    >
      <template v-if="needsBootstrap" #default>
        <p class="hint">行情仓为空或过期时选股会被拒绝。先同步行情。</p>
        <el-button size="small" type="primary" :loading="syncBusy" @click="bootstrapMarket">同步行情</el-button>
      </template>
    </el-alert>

    <el-alert
      v-if="coverage && coverage.codes === 0"
      type="warning"
      show-icon
      :closable="false"
      class="mb"
      title="行情仓为空：选股会失败"
    >
      <el-button size="small" type="primary" :loading="syncBusy" @click="bootstrapMarket">同步行情</el-button>
    </el-alert>

    <PageTabs v-model="activeTab" :items="workshopTabs" aria-label="工坊分区" />

    <div class="page-scroll workshop-scroll">
      <div v-show="activeTab === 'engines'" class="page-pane">
        <QuantStrategiesPanel
          :strategies="strategies"
          :loading="busy && !strategies.length"
          @open-screen="goScreen('engine', $event)"
        />
      </div>

      <!-- 技能面板可能带刷新/轮询：v-if 离开 Tab 才卸载 -->
      <div v-if="activeTab === 'skills'" class="page-pane">
        <QuantSkillsPanel
          :skills="skills"
          :loading="busy && !skills.length"
          @open-screen="goScreen('skill', $event)"
          @remove="uninstallSkill"
          @refresh="reload"
        />
      </div>

      <div v-show="activeTab === 'sources'" class="page-pane sources-pane">
        <DataSourcePanel
          :initial-view="sourceView"
          @count-changed="(count) => (sourceCount = count)"
        />
      </div>

      <div v-show="activeTab === 'jobs'" class="page-pane jobs-pane">
        <JobsTab
          ref="jobsTab"
          @enable-recommended-sync="goRecommendedSync"
          @count-changed="(n) => (jobsEnabled = n)"
        />
      </div>

      <div v-show="activeTab === 'market'" class="page-pane market-pane">
        <MarketPanel embedded @catalog-changed="reload" />
      </div>

      <div v-show="activeTab === 'backtest'" class="page-pane backtest-pane">
        <QuantBacktestPanel
          :strategies="strategies"
          :loading="busy && !strategies.length"
        />
      </div>

      <!-- 研究台有 job 轮询：v-if 离开 Tab 才停；勿用 v-show 常挂 -->
      <div v-if="activeTab === 'research'" class="page-pane research-pane">
        <ResearchPanel :initial-code="researchCode" />
      </div>

      <div v-show="activeTab === 'paper'" class="page-pane paper-pane">
        <PaperQuantPanel />
      </div>
    </div>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 0.65rem;
}
.hint {
  margin: 0.35rem 0 0.65rem;
  color: var(--muted);
  font-size: 0.88rem;
}
.workshop-scroll {
  padding-bottom: 0;
  position: relative;
  min-height: 0;
}
.market-pane,
.sources-pane,
.jobs-pane,
.backtest-pane,
.paper-pane {
  padding: 0 0.35rem 0;
}
.sources-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}
.jobs-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.jobs-pane :deep(.settings-panel) {
  flex: 1 1 auto;
  min-height: 0;
}
</style>
