<script setup lang="ts">
/**
 * 工坊「定时」台：本机任务可 CRUD；战法/技能绑定（screen:/skill:）只读。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  createJob,
  deleteJob,
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
  LlmProvider,
  ScheduleStatus,
  Skill,
  StrategyInfo,
} from '@/shared/types/quant'

import JobDetailPane from './JobDetailPane.vue'
import JobEditorDialog from './JobEditorDialog.vue'
import JobRunsDialog from './JobRunsDialog.vue'
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
import { formatNext, kindLabel } from '../composables/opsLabels'
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
const loadError = ref('')
const selectedId = ref<string | null>(null)
const kindFilter = ref<'all' | JobKind>('all')
const formOpen = ref(false)
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

const receipt = computed((): ReceiptPair[] => {
  const list = jobs.value
  const enabled = list.filter((j) => j.enabled).length
  const failed = list.filter((j) => j.last_status === 'failed').length
  const bound = list.filter((j) => isBoundManagedJob(j)).length
  const nextHits = schedule.value?.jobs
    .map((j) => j.next_run_at)
    .filter(Boolean)
    .sort()
  const pairs: ReceiptPair[] = [
    { key: '在册', value: String(list.length) },
    { key: '启用', value: String(enabled) },
    { key: '绑定', value: String(bound) },
    { key: '上次失败', value: String(failed) },
  ]
  if (nextHits?.[0]) {
    pairs.push({ key: '下次', value: nextHits[0].replace('T', ' ').slice(0, 16) })
  }
  return pairs
})

const filteredJobs = computed(() => {
  const list = jobs.value
  if (kindFilter.value === 'all') return list
  return list.filter((j) => j.kind === kindFilter.value)
})

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
  const [jobsResult, scheduleResult, strategiesResult, skillsResult, providersResult] = await Promise.allSettled([
    refetchJobs(),
    getScheduleStatus(),
    getStrategies(),
    getSkills(),
    getProviders(),
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
  emit('schedule-changed', schedule.value)
  emit('changed')
}

function displayName(job: Job): string {
  if (isStrategyBoundJob(job)) {
    const slug = strategySlugFromBoundJob(job)
    const hit = strategies.value.find((s) => s.slug === slug)
    return hit?.name || slug || job.name
  }
  if (isSkillBoundJob(job)) {
    const slug = skillSlugFromBoundJob(job)
    const hit = skills.value.find((s) => s.slug === slug)
    return hit?.name || slug || job.name
  }
  return job.name
}

function cronLabel(job: Job): string {
  if (!job.cron) return '仅手动'
  if (job.cron === '*/5 9-14 * * 1-5') return '盘中每 5 分钟'
  if (job.cron === '30 15 * * 1-5') return '工作日 15:30'
  if (job.cron === '35 15 * * 1-5') return '工作日 15:35'
  if (job.cron === '0 16 * * 1-5') return '工作日 16:00'
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
  return strategyLabel(String(job.config?.strategy || strategySlugFromBoundJob(job)))
}

function selectedSkillText(job: Job): string {
  return skillLabel(String(job.config?.skill || skillSlugFromBoundJob(job) || ''))
}

function strategyLabel(slug: string): string {
  return strategies.value.find((s) => s.slug === slug)?.name || slug || '—'
}

function skillLabel(slug: string): string {
  return skills.value.find((s) => s.slug === slug)?.name || slug || '—'
}

function openCreate(): void {
  editingJob.value = null
  formOpen.value = true
}

function openEdit(job: Job): void {
  if (isBoundManagedJob(job)) return
  editingJob.value = job
  formOpen.value = true
}

async function onFormSubmit(payload: {
  id: string | null
  name: string
  kind: JobKind
  cron: string
  config: Record<string, unknown>
}): Promise<void> {
  if (payload.id) {
    const saved = await guard(() =>
      updateJob(payload.id!, { cron: payload.cron, config: payload.config }),
    )
    if (saved) {
      notice.value = `已更新任务 ${saved.name}`
      formOpen.value = false
      await load()
    }
    return
  }
  const created = await guard(() =>
    createJob({
      name: payload.name,
      kind: payload.kind,
      cron: payload.cron,
      config: payload.config,
    }),
  )
  if (created) {
    notice.value = `已创建任务 ${created.name}`
    formOpen.value = false
    selectedId.value = created.id
    await load()
  }
}

async function fire(job: Job): Promise<void> {
  const outcome = await guard(() => runJob(job.id))
  if (outcome) {
    notice.value =
      outcome.status === 'failed'
        ? `任务失败：${outcome.error ?? ''}`
        : outcome.status === 'skipped'
          ? `任务 ${displayName(job)} 已跳过：${outcome.error?.trim() || '未提供原因'}`
        : `任务 ${displayName(job)} 执行成功`
  }
  await load()
  await detailRef.value?.reloadRuns()
  emit('runs-changed')
}

async function toggle(job: Job): Promise<void> {
  if (isBoundManagedJob(job)) return
  await guard(() => updateJob(job.id, { enabled: !job.enabled }))
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
      <el-button type="primary" :disabled="busy" @click="openCreate">新建</el-button>
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
      <aside class="jobs-rail">
        <el-select v-model="kindFilter" size="small" class="jobs-filter">
          <el-option label="全部类型" value="all" />
          <el-option label="同步行情" value="sync" />
          <el-option label="选股" value="screen" />
          <el-option label="技能" value="skill" />
          <el-option label="企微推送" value="notify" />
          <el-option label="其它" value="outcome" />
        </el-select>
        <el-scrollbar class="jobs-list-scroll">
          <div
            v-for="job in filteredJobs"
            :key="job.id"
            role="button"
            tabindex="0"
            class="job-row"
            :class="{ active: job.id === selectedId }"
            @click="selectedId = job.id"
            @keydown.enter.prevent="selectedId = job.id"
          >
            <div class="job-row-top">
              <strong>{{ displayName(job) }}</strong>
              <el-tag
                size="small"
                effect="light"
                :type="isBoundManagedJob(job) ? 'info' : 'danger'"
              >
                {{ jobOriginLabel(job) }}
              </el-tag>
            </div>
            <div class="job-row-meta">
              <span>{{ kindLabel(job.kind) }}</span>
              <span :class="job.enabled ? 'on' : 'off'">{{ job.enabled ? '启用' : '停用' }}</span>
            </div>
          </div>
          <EmptyState v-if="!filteredJobs.length" description="该类型下没有任务" />
        </el-scrollbar>
      </aside>

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
      />
      <EmptyState v-else description="选择左侧一条任务查看详情" />
    </div>

    <EmptyState v-else-if="!jobsPending" description="尚无任务">
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
  min-height: 18rem;
  flex: 1 1 auto;
  min-width: 0;
  padding: 0.55rem 0.85rem 0.75rem;
}
.jobs-rail {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  min-height: 0;
  border-right: 1px solid var(--rule);
  padding-right: 0.65rem;
}
.jobs-filter {
  width: 100%;
  flex-shrink: 0;
}
.jobs-list-scroll {
  flex: 1 1 auto;
  min-height: 0;
}
.job-row {
  display: block;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  color: inherit;
  border-radius: 6px;
  padding: 0.55rem 0.6rem;
  margin-bottom: 0.25rem;
  cursor: pointer;
}
.job-row:hover {
  background: color-mix(in srgb, var(--panel) 80%, var(--rule));
}
.job-row.active {
  border-color: var(--rule);
  background: color-mix(in srgb, var(--accent, #b54a32) 8%, transparent);
}
.job-row-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem;
}
.job-row-top strong {
  font-size: 0.92rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.job-row-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 0.25rem;
  font-size: 0.78rem;
  color: var(--muted);
}
.job-row-meta .on {
  color: var(--success, #3f7d4e);
}
.job-row-meta .off {
  color: var(--muted);
}
@media (max-width: 800px) {
  .jobs-desk {
    grid-template-columns: 1fr;
  }
  .jobs-rail {
    border-right: none;
    padding-right: 0;
    border-bottom: 1px solid var(--rule);
    padding-bottom: 0.65rem;
    max-height: 14rem;
  }
}
</style>
