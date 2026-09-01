<script setup lang="ts">
/**
 * 工坊「定时」台：本机任务可 CRUD；战法/技能绑定（screen:/skill:）只读。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  createJob,
  deleteJob,
  getJobQuota,
  getProviders,
  getScheduleStatus,
  getSkills,
  getStrategies,
  runJob,
  updateJob,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import { toErrorMessage } from '@/shared/lib/errors'
import type {
  Job,
  JobKind,
  JobQuota,
  LlmProvider,
  ScheduleStatus,
  Skill,
  StrategyInfo,
} from '@/shared/types/quant'

import JobDetailPane from './JobDetailPane.vue'
import JobEditorDialog from './JobEditorDialog.vue'
import JobRunsDialog from './JobRunsDialog.vue'
import JobsRail, { type JobRailRow } from './JobsRail.vue'
import type { ReceiptPair } from './SettingsPanel.vue'
import SettingsPanel from './SettingsPanel.vue'
import {
  isBoundManagedJob,
  isSkillBoundJob,
  isStrategyBoundJob,
  jobOriginLabel,
  skillSlugFromBoundJob,
  strategySlugFromBoundJob,
} from '../composables/jobOwnership'
import {
  cnStrategyName,
  formatNext,
  jobHealth,
  jobHealthLabel,
  kindLabel,
  type JobHealth,
} from '../composables/opsLabels'
import { useJobsQuery } from '../composables/useJobsQuery'
import { useOpsFeedback } from '../composables/useOpsFeedback'

const emit = defineEmits<{
  'schedule-changed': [schedule: ScheduleStatus | null]
  'enable-recommended-sync': []
  'runs-changed': []
  changed: []
  'count-changed': [enabled: number]
}>()

const router = useRouter()
const route = useRoute()
const { busy, notice, errorText, guard } = useOpsFeedback()

const { jobs, isPending: jobsPending, error: jobsQueryError, refetch: refetchJobs } = useJobsQuery()
const schedule = ref<ScheduleStatus | null>(null)
/** 自建任务额度：写在「新建」旁边，别让人填完一整张表才吃 429。 */
const quota = ref<JobQuota | null>(null)
const loadError = ref('')
const selectedId = ref<string | null>(null)
const kindFilter = ref<'all' | JobKind>('all')
/** 只看失败：找「哪条挂了」以前只能逐条点开看，行上根本不显示 last_status。 */
const statusFilter = ref<'all' | JobHealth>('all')
const formOpen = ref(false)
/** 弹窗内的提交错误：模态窗后面的页面 alert 等于没显示 */
const formSubmitError = ref('')
const editingJob = ref<Job | null>(null)
const runsOpen = ref(false)
const detailRef = ref<InstanceType<typeof JobDetailPane> | null>(null)

watch(
  () => route.query.runs,
  (raw) => {
    if (raw === '1' || raw === 'true') runsOpen.value = true
  },
  { immediate: true },
)

watch(runsOpen, (open) => {
  if (open) return
  if (route.query.runs == null) return
  const next = { ...route.query }
  delete next.runs
  void router.replace({ query: next })
})

const strategies = ref<StrategyInfo[]>([])
const skills = ref<Skill[]>([])
const providers = ref<LlmProvider[]>([])

/** 最近一条失败的任务：回执上的「上次失败 N」点进来就落在它身上。 */
const latestFailedJob = computed(() => {
  const failed = jobs.value.filter((j) => jobHealth(j) === 'failed')
  const byRecency = (a: Job, b: Job): number =>
    String(b.last_run_at || '').localeCompare(String(a.last_run_at || ''))
  return [...failed].sort(byRecency)[0] ?? null
})

const quotaText = computed(() => {
  const q = quota.value
  if (!q) return ''
  if (q.unlimited) return `自建 ${q.used} · 不限`
  return `${q.used} / ${q.limit}`
})

/** 额度用满：新建按钮直接停用，省掉「填完表单→429」这一圈。 */
const quotaFull = computed(() => {
  const q = quota.value
  return Boolean(q && !q.unlimited && q.used >= q.limit)
})

const receipt = computed((): ReceiptPair[] => {
  const list = jobs.value
  const enabled = list.filter((j) => j.enabled).length
  const failed = list.filter((j) => jobHealth(j) === 'failed').length
  const bound = list.filter((j) => isBoundManagedJob(j)).length
  const nextHits = schedule.value?.jobs
    .map((j) => j.next_run_at)
    .filter(Boolean)
    .sort()
  const pairs: ReceiptPair[] = [
    { key: '在册', value: String(list.length) },
    { key: '启用', value: String(enabled) },
    { key: '绑定', value: String(bound) },
    {
      key: '上次失败',
      value: String(failed),
      hint: failed ? '点开最近一条失败的原因全文' : '没有失败记录',
      // 数字不是装饰：点它直接落到那条 run 的失败全文上
      onClick: failed ? jumpToLatestFailure : undefined,
    },
  ]
  if (quotaText.value) {
    pairs.push({ key: '自建额度', value: quotaText.value, hint: '系统托管任务不占额度' })
  }
  if (nextHits?.[0]) {
    pairs.push({ key: '下次', value: nextHits[0].replace('T', ' ').slice(0, 16) })
  }
  return pairs
})

const filteredJobs = computed(() => {
  let list = jobs.value
  if (kindFilter.value !== 'all') list = list.filter((j) => j.kind === kindFilter.value)
  if (statusFilter.value !== 'all') {
    list = list.filter((j) => jobHealth(j) === statusFilter.value)
  }
  return list
})

/** 名册行：名字解析与状态归类都在这儿算完，左栏只管画。 */
const railRows = computed((): JobRailRow[] =>
  filteredJobs.value.map((job) => {
    const health = jobHealth(job)
    return {
      id: job.id,
      title: displayName(job),
      kindText: kindLabel(job.kind),
      originText: jobOriginLabel(job),
      bound: isBoundManagedJob(job),
      enabled: job.enabled,
      health,
      healthText: jobHealthLabel(health),
    }
  }),
)

const selected = computed(() => {
  const id = selectedId.value
  if (!id) return null
  return jobs.value.find((j) => j.id === id) ?? null
})

const jobsError = computed(() => {
  const queryError = toErrorMessage(jobsQueryError.value, '定时任务加载失败')
  return queryError || loadError.value
})

watch(
  filteredJobs,
  (list) => {
    if (!list.length) {
      selectedId.value = null
      return
    }
    if (!selectedId.value || !list.some((j) => j.id === selectedId.value)) {
      selectedId.value = list[0].id
    }
  },
  { immediate: true },
)

watch(
  () => jobs.value.filter((j) => j.enabled).length,
  (n) => emit('count-changed', n),
  { immediate: true },
)

async function load(): Promise<void> {
  loadError.value = ''
  const [
    jobsResult,
    scheduleResult,
    strategiesResult,
    skillsResult,
    providersResult,
    quotaResult,
  ] = await Promise.allSettled([
    refetchJobs(),
    getScheduleStatus(),
    getStrategies(),
    getSkills(),
    getProviders(),
    getJobQuota(),
  ])
  const failures = [
    [jobsResult, '定时任务加载失败'],
    [scheduleResult, '调度状态加载失败'],
    [strategiesResult, '战法列表加载失败'],
    [skillsResult, '技能列表加载失败'],
    [providersResult, '模型提供方加载失败'],
  ] as const
  const failed = failures.find(([result]) => result.status === 'rejected')
  if (failed?.[0].status === 'rejected') {
    loadError.value = toErrorMessage(failed[0].reason, failed[1])
  }
  if (scheduleResult.status === 'fulfilled') schedule.value = scheduleResult.value
  if (strategiesResult.status === 'fulfilled') strategies.value = strategiesResult.value
  if (skillsResult.status === 'fulfilled') skills.value = skillsResult.value
  if (providersResult.status === 'fulfilled') providers.value = providersResult.value
  // 额度问不到只是少显示一行「自建额度」，不该把整页判成加载失败：
  // 老后端没有 /api/jobs/quota，报错会把一个能用的页面说成坏的。
  quota.value = quotaResult.status === 'fulfilled' ? quotaResult.value : null
  emit('schedule-changed', schedule.value)
  emit('changed')
}

// displayName 由 v-for 每行调用，逐行 find 会随目录长度线性劣化；预建索引。
// 存的是**已中文化**的名字：后端的 name 缺失或本身就是 slug 时，cnStrategyName
// 会退回共享词表，界面上不会再冒出 `sanyuan-tail-v1` 这种英文编码。
const strategyNames = computed(
  () => new Map(strategies.value.map((s) => [s.slug, cnStrategyName(s.name, s.slug)])),
)
const skillNames = computed(
  () => new Map(skills.value.map((s) => [s.slug, cnStrategyName(s.name, s.slug)])),
)

/**
 * 名字一律走中文：后端没回 name 时，旧代码 `|| slug` 直接把 `sanyuan-tail-v1`
 * 这种英文编码摆到界面上。现在统一过 cnStrategyName（含拼音词根兜底）。
 */
function displayName(job: Job): string {
  if (isStrategyBoundJob(job)) {
    const slug = strategySlugFromBoundJob(job)
    return slug ? (strategyNames.value.get(slug) ?? cnStrategyName('', slug)) : job.name
  }
  if (isSkillBoundJob(job)) {
    const slug = skillSlugFromBoundJob(job)
    return slug ? (skillNames.value.get(slug) ?? cnStrategyName('', slug)) : job.name
  }
  return job.name
}

/**
 * cron → 人话。托管任务写的是 `mon-fri`（APScheduler 口径），本机任务的历史
 * 预设写的是 `1-5`，两种都要认得出来，否则同一个时点显示成两种样子。
 */
function cronLabel(job: Job): string {
  if (!job.cron) return '仅手动'
  const text = job.cron.replace(/\bmon-fri\b/i, '1-5')
  if (text === '*/5 9-14 * * 1-5') return '盘中每 5 分钟'
  const once = /^(\d{1,2}) (\d{1,2}) \* \* 1-5$/.exec(text)
  if (once) {
    return `工作日 ${once[2].padStart(2, '0')}:${once[1].padStart(2, '0')}`
  }
  return job.cron
}

function nextRunOf(job: Job): string {
  if (!job.cron) return '仅手动'
  if (!job.enabled) return '已停用'
  const hit = schedule.value?.jobs.find((item) => item.id === job.id)
  const text = formatNext(hit?.next_run_at)
  if (text !== '—') return text
  // 调度器未跑时后端仍会按 cron 推算；若仍无值，展示原因
  return schedule.value?.reason ? `—（${schedule.value.reason}）` : '—'
}

function selectedStrategyText(job: Job): string {
  const slug = String(job.config?.strategy || strategySlugFromBoundJob(job) || '')
  if (!slug) return '—'
  return strategyNames.value.get(slug) ?? cnStrategyName('', slug)
}

function selectedSkillText(job: Job): string {
  const slug = String(job.config?.skill || skillSlugFromBoundJob(job) || '')
  if (!slug) return '—'
  return skillNames.value.get(slug) ?? cnStrategyName('', slug)
}

function openCreate(): void {
  if (quotaFull.value) {
    const q = quota.value
    errorText.value = `自建定时任务已达上限（${q?.used} / ${q?.limit} 条）。`
      + '先删掉不用的，或让管理员抬高 job_slots；系统托管任务不占这个额度。'
    return
  }
  formSubmitError.value = ''
  editingJob.value = null
  formOpen.value = true
}

/**
 * 「上次失败 N」→ 那条 run 的失败全文。旧路径是：回执数字不可点 → 在左栏逐条
 * 点（行上还看不出谁失败）→ 找到后在历史里悬停读半句。现在一步到位。
 */
function jumpToLatestFailure(): void {
  const target = latestFailedJob.value
  if (!target) return
  kindFilter.value = 'all'
  statusFilter.value = 'failed'
  selectedId.value = target.id
  void nextTick(() => {
    void detailRef.value?.focusLatestFailure()
  })
}

function openEdit(job: Job): void {
  if (isBoundManagedJob(job)) return
  formSubmitError.value = ''
  editingJob.value = job
  formOpen.value = true
}

/**
 * 写口三个闸门各有各的说法，别糊成一句「保存失败」：403 = 非主账号动系统级
 * 任务；422 = cron 快过 5 分钟下限；429 = 自建条数超额。detail 是后端原文，
 * 一个字不改地带出来，后面只补一句「这是什么」。
 */
function rethrowJobWriteError(caught: unknown): never {
  const error = caught as Error & { status?: number }
  const detail = error?.message?.trim() || '保存失败'
  if (error?.status === 403) {
    throw new Error(`${detail}（系统级任务只有主账号能建改：它们写的是全局共享的行情库）`)
  }
  if (error?.status === 429) {
    throw new Error(`${detail}（这是账号的 job_slots 上限，系统托管任务不占）`)
  }
  throw caught
}

async function onFormSubmit(payload: {
  id: string | null
  name: string
  kind: JobKind
  cron: string
  config: Record<string, unknown>
}): Promise<void> {
  formSubmitError.value = ''
  if (payload.id) {
    const saved = await guard(() =>
      updateJob(payload.id!, { cron: payload.cron, config: payload.config }).catch(
        rethrowJobWriteError,
      ),
    )
    if (!saved) return captureFormError()
    notice.value = `已更新任务 ${saved.name}`
    formOpen.value = false
    await load()
    return
  }
  const created = await guard(() =>
    createJob({
      name: payload.name,
      kind: payload.kind,
      cron: payload.cron,
      config: payload.config,
    }).catch(rethrowJobWriteError),
  )
  if (!created) return captureFormError()
  notice.value = `已创建任务 ${created.name}`
  formOpen.value = false
  selectedId.value = created.id
  await load()
}

/**
 * 把 guard 落在页面 alert 上的报错搬进表单：弹窗是模态的，报错显示在弹窗
 * **背后**等于没显示。错误只该有一处。
 */
function captureFormError(): void {
  formSubmitError.value = errorText.value
  errorText.value = ''
  // 429 多半意味着本地那份额度已经过期了，顺手再问一次
  void getJobQuota()
    .then((next) => {
      quota.value = next
    })
    .catch(() => undefined)
}

async function fire(job: Job): Promise<void> {
  const outcome = await guard(() => runJob(job.id))
  if (outcome) {
    notice.value =
      outcome.status === 'failed'
        ? `没跑成：${displayName(job)} · ${outcome.error?.trim() || '后台没有留下原因'}`
        : outcome.status === 'skipped'
          ? `任务 ${displayName(job)} 已跳过：${outcome.error?.trim() || '未提供原因'}`
        : `已跑完：${displayName(job)}`
  }
  await load()
  await detailRef.value?.reloadRuns()
  emit('runs-changed')
}

/**
 * 启停：绑定任务也走这条路。
 *
 * 以前这里对 `screen:` / `skill:` 直接 `return`，用户要停掉一条战法选股得跳去
 * 工坊把整档调度关成 off。同一个 `PATCH /api/jobs/{id}` 明明就能做。
 */
async function toggle(job: Job): Promise<void> {
  await guard(() => updateJob(job.id, { enabled: !job.enabled }))
  await load()
}

/** 就地改时点：cron 与 config.schedule 一起写，免得下次 ensure 又把它算回去。 */
async function saveSchedule(
  job: Job,
  payload: { cron: string; config: Record<string, unknown> },
): Promise<void> {
  const saved = await guard(() =>
    updateJob(job.id, { cron: payload.cron, config: payload.config }),
  )
  if (saved) {
    notice.value = payload.cron
      ? `已改时点：${displayName(job)} · ${payload.cron}`
      : `已改为仅手动：${displayName(job)}`
  }
  await load()
}

async function confirmDrop(job: Job): Promise<void> {
  if (isBoundManagedJob(job)) return
  if (!(await confirmDangerous(`确定删除定时任务「${job.name}」？`, '确认删除', '删除'))) return
  await guard(() => deleteJob(job.id), `已删除 ${job.name}`)
  await load()
}

function goBoundDetail(job: Job): void {
  if (isStrategyBoundJob(job)) {
    const slug = strategySlugFromBoundJob(job)
    if (!slug) return
    void router.push({ path: '/quant', query: { tab: 'engines', strategy: slug } })
    return
  }
  if (isSkillBoundJob(job)) {
    const slug = skillSlugFromBoundJob(job)
    if (!slug) return
    void router.push({ path: '/quant', query: { tab: 'skills', skill: slug } })
  }
}

onMounted(() => {
  void load()
})

defineExpose({ load, schedule })
</script>

<template>
  <SettingsPanel title="定时任务" fill :receipt="receipt">
    <template #action>
      <el-button :disabled="busy" @click="runsOpen = true">全部历史</el-button>
      <el-button
        type="primary"
        :disabled="busy || quotaFull"
        :title="quotaFull ? '自建任务额度已满' : '新建定时任务'"
        @click="openCreate"
      >
        新建{{ quotaFull ? '（额度已满）' : '' }}
      </el-button>
    </template>

    <el-alert
      v-if="notice"
      :title="notice"
      type="success"
      show-icon
      closable
      class="jobs-alert"
      @close="notice = ''"
    />
    <el-alert
      v-if="errorText"
      :title="errorText"
      type="error"
      show-icon
      closable
      class="jobs-alert"
      @close="errorText = ''"
    />

    <el-alert
      v-if="jobsError && !jobsPending"
      :title="jobsError"
      type="error"
      show-icon
      :closable="false"
      class="jobs-alert"
    >
      <el-button size="small" @click="load">重试</el-button>
    </el-alert>

    <div v-else-if="jobs.length" class="jobs-desk">
      <JobsRail
        v-model:selected-id="selectedId"
        v-model:kind-filter="kindFilter"
        v-model:status-filter="statusFilter"
        :rows="railRows"
      />

      <JobDetailPane
        v-if="selected"
        ref="detailRef"
        :job="selected"
        :busy="busy"
        :title="displayName(selected)"
        :cron-text="cronLabel(selected)"
        :next-run-text="nextRunOf(selected)"
        :strategy-text="selected.kind === 'screen' ? selectedStrategyText(selected) : undefined"
        :skill-text="selected.kind === 'skill' ? selectedSkillText(selected) : undefined"
        @fire="fire(selected)"
        @edit="openEdit(selected)"
        @toggle="toggle(selected)"
        @drop="confirmDrop(selected)"
        @go-bound="goBoundDetail(selected)"
        @save-schedule="(payload) => saveSchedule(selected!, payload)"
      />
      <EmptyState v-else description="选择左侧一条任务查看详情" />
    </div>

    <EmptyState
      v-else-if="!jobsPending"
      description="还没有定时任务"
      reason="任务负责按点自动跑选股、同步行情和推送。"
    >
      <el-button type="primary" @click="emit('enable-recommended-sync')">配置推荐同步</el-button>
      <el-button @click="openCreate">新建任务</el-button>
    </EmptyState>
  </SettingsPanel>

  <JobEditorDialog
    v-model="formOpen"
    :editing="editingJob"
    :strategies="strategies"
    :skills="skills"
    :providers="providers"
    :busy="busy"
    :submit-error="formSubmitError"
    :quota="quota"
    @submit="onFormSubmit"
  />

  <JobRunsDialog v-model="runsOpen" @changed="emit('changed')" />
</template>

<style scoped>
.jobs-alert {
  margin: 0.55rem 0.85rem 0;
  flex-shrink: 0;
}
.jobs-desk {
  display: grid;
  grid-template-columns: minmax(12rem, 16rem) minmax(0, 1fr);
  gap: 0.85rem;
  min-height: 0;
  flex: 1 1 auto;
  min-width: 0;
  padding: 0.55rem 0.85rem 0.75rem;
  overflow: hidden;
}
.jobs-desk > :deep(.job-detail) {
  min-height: 0;
  overflow: auto;
}
@media (max-width: 800px) {
  .jobs-desk {
    grid-template-columns: 1fr;
  }
}
</style>