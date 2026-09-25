<script setup lang="ts">
/**
 * 工坊「定时」台：本机任务可 CRUD；战法/技能绑定（screen:/skill:）只读。
 *
 * 这个文件留下的是「这屏的交互」：筛选与选中、六个写动作（新建 / 改 / 跑 / 启停 /
 * 改时点 / 删）、回执与错误落点。目录读取与中文名解析在 useJobsCatalog，cron、
 * 下次触发、名册行的展示换算在 jobPresentation——那两块既不认这里的 emit，
 * 也不该跟着这屏的 UI 状态一起翻。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { useRoute, useRouter } from 'vue-router'
import { CircleAlert, CircleCheck, History, Plus, TriangleAlert, X } from '@lucide/vue'

import { createJob, deleteJob, getJobQuota, runJob, updateJob } from '@/shared/api/quant'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/shared/components/ui/sheet'
import { confirmDangerous } from '@/shared/lib/confirm'
import type { Job, JobKind, ScheduleStatus } from '@/shared/types/quant'

import JobDetailPane from './JobDetailPane.vue'
import JobEditorDialog from './JobEditorDialog.vue'
import JobRunsDialog from './JobRunsDialog.vue'
import JobsRail from './JobsRail.vue'
import type { ReceiptPair } from './SettingsPanel.vue'
import SettingsPanel from './SettingsPanel.vue'
import {
  isBoundManagedJob,
  isSkillBoundJob,
  isStrategyBoundJob,
  skillSlugFromBoundJob,
  strategySlugFromBoundJob,
} from '../composables/jobOwnership'
import { jobHealth, type JobHealth } from '../composables/opsLabels'
import { cronLabel, nextRunAt, nextRunText, railRowsOf, relativeDayTime } from '../composables/jobPresentation'
import { useJobsCatalog } from '../composables/useJobsCatalog'
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

const catalog = useJobsCatalog()
const {
  jobs,
  jobsPending,
  jobsError,
  schedule,
  quota,
  strategies,
  skills,
  providers,
  displayName,
  selectedStrategyText,
  selectedSkillText,
} = catalog

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
/** ≤800px 时左栏铺满，详情改在贴底 Sheet 里打开（点卡才开，自动选中不开） */
const isNarrow = useMediaQuery('(max-width: 800px)')
const detailOpen = ref(false)

function onPickJob(): void {
  if (isNarrow.value) detailOpen.value = true
}

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
      // 数字不是装饰：点它直接落到那条 run 的失败全文上
      onClick: failed ? jumpToLatestFailure : undefined,
    },
  ]
  if (quotaText.value) {
    pairs.push({ key: '自建额度', value: quotaText.value })
  }
  if (nextHits?.[0]) {
    pairs.push({ key: '下次', value: relativeDayTime(nextHits[0]) || nextHits[0].replace('T', ' ').slice(0, 16) })
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

/** 名册行：名字解析与状态归类都在渲染前算完，左栏只管画。 */
const railRows = computed(() => railRowsOf(filteredJobs.value, displayName, schedule.value))

const selected = computed(() => {
  const id = selectedId.value
  if (!id) return null
  return jobs.value.find((j) => j.id === id) ?? null
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

/** 目录读完顺手把回执往外抛：schedule 归工坊头，changed 归历史弹窗。 */
async function load(): Promise<void> {
  await catalog.load()
  emit('schedule-changed', schedule.value)
  emit('changed')
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
    notice.value = `已更新任务 ${displayName(saved)}`
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
  if (!(await confirmDangerous(`确定删除定时任务「${displayName(job)}」？`, '确认删除', '删除'))) return
  await guard(() => deleteJob(job.id), `已删除 ${displayName(job)}`)
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
  <SettingsPanel
    title="定时任务"
    fill
    :receipt="receipt"
  >
    <template #action>
      <Button variant="outline" size="sm" :disabled="busy" @click="runsOpen = true">
        <History />
        全部历史
      </Button>
      <Button
        size="sm"
        :disabled="busy || quotaFull"
        :title="quotaFull ? '自建任务额度已满' : '新建定时任务'"
        @click="openCreate"
      >
        <Plus />
        新建{{ quotaFull ? '（额度已满）' : '' }}
      </Button>
    </template>

    <Alert v-if="notice" class="jobs-alert">
      <CircleCheck />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ notice }}</AlertTitle>
        <Button variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="notice = ''">
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>
    <Alert v-if="errorText" variant="destructive" class="jobs-alert">
      <CircleAlert />
      <div class="flex w-full min-w-0 items-start justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ errorText }}</AlertTitle>
        <Button access="read" variant="ghost" size="icon-xs" aria-label="关闭提示" class="shrink-0" @click="errorText = ''">
          <X class="size-3.5" />
        </Button>
      </div>
    </Alert>

    <Alert v-if="jobsError && !jobsPending" variant="destructive" class="jobs-alert">
      <TriangleAlert />
      <div class="flex w-full min-w-0 flex-wrap items-center justify-between gap-2">
        <AlertTitle class="line-clamp-none min-w-0">{{ jobsError }}</AlertTitle>
        <Button access="read" variant="outline" size="sm" @click="load">重试</Button>
      </div>
    </Alert>

    <div v-else-if="jobs.length" class="jobs-layout" :class="{ 'is-narrow': isNarrow }">
      <JobsRail
        v-model:selected-id="selectedId"
        v-model:kind-filter="kindFilter"
        v-model:status-filter="statusFilter"
        :rows="railRows"
        class="jobs-layout__rail"
        @pick="onPickJob"
      />

      <div v-if="!isNarrow" class="jobs-layout__detail">
        <JobDetailPane
          v-if="selected"
          ref="detailRef"
          :job="selected"
          :busy="busy"
          :title="displayName(selected)"
          :cron-text="cronLabel(selected)"
          :next-run-text="nextRunText(selected, schedule)"
          :next-run-at="nextRunAt(selected, schedule)"
          :strategy-text="selected.kind === 'screen' ? selectedStrategyText(selected) : undefined"
          :skill-text="selected.kind === 'skill' ? selectedSkillText(selected) : undefined"
          @fire="fire(selected)"
          @edit="openEdit(selected)"
          @toggle="toggle(selected)"
          @drop="confirmDrop(selected)"
          @go-bound="goBoundDetail(selected)"
          @save-schedule="(payload) => saveSchedule(selected!, payload)"
        />
        <EmptyState v-else description="未选择任务" />
      </div>

      <Sheet v-else :open="detailOpen && Boolean(selected)" @update:open="detailOpen = $event">
        <SheetContent side="right" class="jobs-sheet">
          <SheetHeader class="jobs-sheet__head">
            <SheetTitle>{{ selected ? displayName(selected) : '任务详情' }}</SheetTitle>
          </SheetHeader>
          <JobDetailPane
            v-if="selected"
            ref="detailRef"
            :job="selected"
            :busy="busy"
            :title="displayName(selected)"
            :cron-text="cronLabel(selected)"
            :next-run-text="nextRunText(selected, schedule)"
            :next-run-at="nextRunAt(selected, schedule)"
            :strategy-text="selected.kind === 'screen' ? selectedStrategyText(selected) : undefined"
            :skill-text="selected.kind === 'skill' ? selectedSkillText(selected) : undefined"
            @fire="fire(selected)"
            @edit="openEdit(selected)"
            @toggle="toggle(selected)"
            @drop="confirmDrop(selected)"
            @go-bound="goBoundDetail(selected)"
            @save-schedule="(payload) => saveSchedule(selected!, payload)"
          />
        </SheetContent>
      </Sheet>
    </div>

    <EmptyState
      v-else-if="!jobsPending"
      description="还没有定时任务"
      class="jobs-empty"
    >
      <Button @click="emit('enable-recommended-sync')">配置推荐同步</Button>
      <Button variant="outline" @click="openCreate">新建任务</Button>
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
  flex-shrink: 0;
  margin-bottom: var(--gap-3);
}

.jobs-layout {
  display: grid;
  flex: 1 1 auto;
  grid-template-columns: minmax(268px, 340px) minmax(0, 1fr);
  gap: var(--gap-4);
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.jobs-layout.is-narrow {
  grid-template-columns: minmax(0, 1fr);
}

.jobs-layout__rail {
  min-height: 0;
}

.jobs-layout__detail {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  padding: 0 2px 2px;
}

.jobs-empty {
  min-height: 320px;
  border: 1px dashed var(--border-default);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.jobs-sheet {
  display: flex;
  flex-direction: column;
  gap: var(--gap-3);
  padding: var(--gap-4);
}

.jobs-sheet__head {
  padding: 0;
  padding-right: var(--gap-6);
}
</style>
