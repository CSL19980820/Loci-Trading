<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, reactive, ref, watch } from 'vue'
import { ChevronDown, CircleAlert, Database, LoaderCircle, Plus, Upload, X } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'

import {
  CapabilityUnavailableError,
  getJobs,
  getMarketCoverage,
  getSkills,
  getStrategies,
  removeSkill,
  syncMarket,
} from '@/shared/api/quant'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import PageHeader from '@/shared/components/layout/PageHeader.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import type { MarketCoverage, Skill, StrategyInfo } from '@/shared/types/quant'
import ScreenSkillBundleImportDialog from './components/ScreenSkillBundleImportDialog.vue'
import QuantStrategiesPanel from './components/QuantStrategiesPanel.vue'

/**
 * 八个 Tab 里只有「战法」是落地就要看的，其余七块面板各自 onMounted 就拉数
 * （数据源目录、定时任务、货架、纸面舱…）。静态 import 会把它们全塞进 /quant
 * 这一个分片，进工坊先解析一堆本次会话根本不会点开的代码；配合下面的
 * mountedTabs 门闩，现在是「点进去才下载、才挂载」（frontend/AGENTS.md §1.2 第 3 条）。
 */
const DataSourcePanel = defineAsyncComponent(
  () => import('@/features/datasource/DataSourcePanel.vue'),
)
const MarketPanel = defineAsyncComponent(
  () => import('@/features/marketplace/components/MarketPanel.vue'),
)
const JobsTab = defineAsyncComponent(() => import('@/features/ops/components/JobsTab.vue'))
const PaperQuantPanel = defineAsyncComponent(
  () => import('@/features/ops/components/PaperQuantPanel.vue'),
)
const ResearchPanel = defineAsyncComponent(() => import('@/features/research/ResearchPanel.vue'))
const QuantBacktestPanel = defineAsyncComponent(
  () => import('./components/QuantBacktestPanel.vue'),
)
const QuantSkillsPanel = defineAsyncComponent(() => import('./components/QuantSkillsPanel.vue'))

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
/**
 * 「进过才挂、挂上就留」。工坊过去把 6 块 v-show 面板一次性挂满：首帧要建 6 份
 * DOM，它们各自的 onMounted 还同时打十来个请求，落地 /quant 明显卡一下，而用户
 * 当次通常只看一个 Tab。这里只记「哪些 Tab 进过」——进过的仍旧 v-show 常挂，
 * 保住切 Tab 不丢状态（滚动位置、填一半的表单、跑完的回测结果）。
 * 技能与研究台不在此列：它们带轮询，离开必须整块卸掉，模板里照旧 v-if。
 */
const mountedTabs = reactive(new Set<WorkshopTab>([activeTab.value]))
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
/** 工坊的粘贴入口：别人导出的克隆包（JSON）在这里落地成本地战法。 */
const bundleImportOpen = ref(false)

const needsBootstrap = computed(() =>
  /行情仓是空的|没有可同步的标的|数据体检未通过|empty_store|请先刷新证券列表/i.test(
    unavailable.value,
  ),
)
const marketEmpty = computed(() => Boolean(coverage.value && coverage.value.codes === 0))

watch(
  () => route.query.tab,
  (raw) => {
    if (route.name !== 'quant') return
    activeTab.value = parseTab(raw)
  },
)

watch(activeTab, (tab) => {
  if (route.name !== 'quant') return
  const revisit = mountedTabs.has(tab)
  mountedTabs.add(tab)
  const next = tab === 'engines' ? undefined : tab
  if (parseTab(route.query.tab) !== tab) {
    void router.replace({ query: { ...route.query, tab: next } })
  }
  // 首次进入那次是 JobsTab 自己的 onMounted 在拉，别再补第二枪
  if (tab === 'jobs' && revisit) void jobsTab.value?.load()
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

/** 新建入口从战法面板搬到页头：空白 / AI 草稿 / TDX 草稿都落到策稿台 */
function openCreate(source: 'blank' | 'description' | 'tdx'): void {
  void router.push({ path: '/strategy-converter', query: { source } })
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
    toast.success(`已卸载 ${skill.name}`)
    skills.value = skills.value.filter((row) => row.slug !== skill.slug)
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '卸载失败'))
  }
}

/**
 * 克隆包导入成功后刷新战法列表，并确保停在「战法」Tab——
 * 新建出来的东西必须当场看得见，否则用户不知道到底成没成。
 */
function onBundleImported(): void {
  activeTab.value = 'engines'
  void reload()
}

async function bootstrapMarket(): Promise<void> {
  syncBusy.value = true
  unavailable.value = ''
  toast.info('同步可能需要一两分钟，请稍候')
  try {
    const report = await syncMarket({
      refresh_instruments: true,
      limit: 200,
      workers: 6,
      interval: 0.1,
    })
    toast.success(
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
  <div class="workshop-page page-fill flex h-full min-h-0 flex-1 flex-col overflow-hidden">
    <PageBusy
      overlay
      :busy="activeTab !== 'research' && busy && !coverage && !strategies.length && !skills.length"
    />

    <PageHeader
      title="工坊"
      :tabs="workshopTabs"
      v-model:tab="activeTab"
    >
      <template #actions>
        <Button
          v-if="marketEmpty || needsBootstrap"
          variant="outline"
          size="sm"
          :disabled="syncBusy"
          @click="bootstrapMarket"
        >
          <LoaderCircle v-if="syncBusy" class="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          <Database v-else aria-hidden="true" />
          同步行情
        </Button>
        <Button variant="outline" size="sm" @click="bundleImportOpen = true">
          <Upload aria-hidden="true" />
          导入克隆包
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button size="sm">
              <Plus aria-hidden="true" />
              新建战法
              <ChevronDown aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem @select="openCreate('blank')">空白新建</DropdownMenuItem>
            <DropdownMenuItem @select="openCreate('description')">AI 草稿</DropdownMenuItem>
            <DropdownMenuItem @select="openCreate('tdx')">TDX 草稿</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </template>
    </PageHeader>

    <Alert v-if="unavailable" variant="destructive" class="workshop-alert">
      <CircleAlert />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <div class="min-w-0 flex-1">
          <AlertTitle class="line-clamp-none min-w-0">{{ unavailable }}</AlertTitle>
          <!-- alert 里只留能点的东西：那句「先同步行情」按钮自己就说完了（AGENTS.md 禁常驻说明） -->
          <Button
            v-if="needsBootstrap"
            variant="outline"
            size="sm"
            class="mt-1"
            :disabled="syncBusy"
            @click="bootstrapMarket"
          >
            <LoaderCircle v-if="syncBusy" class="size-4 animate-spin" aria-hidden="true" />
            同步行情
          </Button>
        </div>
        <Button access="read"
          variant="ghost"
          size="icon-xs"
          aria-label="关闭提示"
          class="shrink-0"
          @click="unavailable = ''"
        >
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>

    <div class="workshop-body">

      <!-- v-if 只管「进过没」，v-show 才是当前 Tab：见 mountedTabs 的注释 -->
      <div
        v-if="mountedTabs.has('engines')"
        v-show="activeTab === 'engines'"
        class="page-pane"
      >
        <QuantStrategiesPanel
          :strategies="strategies"
          :loading="busy && !strategies.length"
          @open-screen="goScreen('engine', $event)"
          @import-bundle="bundleImportOpen = true"
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

      <div
        v-if="mountedTabs.has('sources')"
        v-show="activeTab === 'sources'"
        class="page-pane sources-pane"
      >
        <DataSourcePanel
          :initial-view="sourceView"
          @count-changed="(count) => (sourceCount = count)"
        />
      </div>

      <div
        v-if="mountedTabs.has('jobs')"
        v-show="activeTab === 'jobs'"
        class="page-pane jobs-pane"
      >
        <JobsTab
          ref="jobsTab"
          @enable-recommended-sync="goRecommendedSync"
          @count-changed="(n) => (jobsEnabled = n)"
        />
      </div>

      <div
        v-if="mountedTabs.has('market')"
        v-show="activeTab === 'market'"
        class="page-pane market-pane"
      >
        <MarketPanel embedded @catalog-changed="reload" />
      </div>

      <div
        v-if="mountedTabs.has('backtest')"
        v-show="activeTab === 'backtest'"
        class="page-pane backtest-pane"
      >
        <QuantBacktestPanel :strategies="strategies" :loading="busy && !strategies.length" />
      </div>

      <!-- 研究台有 job 轮询：v-if 离开 Tab 才停；勿用 v-show 常挂 -->
      <div v-if="activeTab === 'research'" class="page-pane research-pane">
        <ResearchPanel :initial-code="researchCode" />
      </div>

      <div
        v-if="mountedTabs.has('paper')"
        v-show="activeTab === 'paper'"
        class="page-pane paper-pane"
      >
        <PaperQuantPanel />
      </div>
    </div>

    <!-- 粘贴模式：没有 bundle prop，用户自己贴克隆时复制的 JSON -->
    <ScreenSkillBundleImportDialog v-model="bundleImportOpen" paste @imported="onBundleImported" />
  </div>
</template>

<style scoped>
.workshop-page,
.workshop-body,
.workshop-body > .page-pane {
  min-width: 0;
}

.workshop-alert {
  flex-shrink: 0;
  margin: var(--gap-3) 0 0;
}

.workshop-body {
  display: flex;
  flex: 1 1 0%;
  flex-direction: column;
  gap: var(--gap-4);
  height: 0;
  min-height: 0;
  padding: var(--gap-4) 0 0;
  overflow: hidden;
}

.workshop-body > .page-pane {
  flex: 1 1 0%;
  height: 0;
  min-height: 0;
}

.research-pane,
.market-pane {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
}

.backtest-pane {
  overflow: auto;
  overscroll-behavior: contain;
  padding-bottom: var(--gap-4);
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

@media (max-width: 640px) {
  .workshop-body {
    gap: var(--gap-3);
    padding-top: var(--gap-3);
  }
}
</style>
