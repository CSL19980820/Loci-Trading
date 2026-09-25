<script setup lang="ts">
/**
 * 定时任务详情：标题与动作 → 下次触发 / 调度 → 读数 → 就地改时点 → 执行历史。
 *
 * 绑定任务（`screen:` / `skill:`）的时点与启停与本机任务走同一个
 * `PATCH /api/jobs/{id}`；只有战法专属配置（股票池、top_n 等）跳去工坊。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Ellipsis, ExternalLink, Pencil, Play, Trash2 } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { Switch } from '@/shared/components/ui/switch'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import type { Job } from '@/shared/types/quant'

import JobRecentRunsPanel from './JobRecentRunsPanel.vue'
import JobScheduleInline from './JobScheduleInline.vue'
import {
  isBoundManagedJob,
  isSkillBoundJob,
  jobOriginLabel,
} from '../composables/jobOwnership'
import { countdownText, relativeDayTime } from '../composables/jobPresentation'
import { formatRunDuration, jobHealth, jobHealthLabel, kindLabel } from '../composables/opsLabels'
import { useJobRunsQuery } from '../composables/useJobRunsQuery'

const props = defineProps<{
  job: Job
  busy: boolean
  nextRunText: string
  /** 调度器给出的下次触发原文（ISO）；没有就是空串 */
  nextRunAt?: string
  cronText: string
  title: string
  strategyText?: string
  skillText?: string
}>()

const emit = defineEmits<{
  fire: []
  edit: []
  toggle: []
  drop: []
  goBound: []
  saveSchedule: [payload: { cron: string; config: Record<string, unknown> }]
}>()

const runsRef = ref<InstanceType<typeof JobRecentRunsPanel> | null>(null)
const scheduleOpen = ref(false)
const bound = computed(() => isBoundManagedJob(props.job))
const health = computed(() => jobHealth(props.job))

watch(() => props.job.id, () => {
  scheduleOpen.value = false
})

/* 倒计时每 30 秒刷新一次；离开详情即停 */
const now = ref(new Date())
let clock: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  clock = setInterval(() => {
    now.value = new Date()
  }, 30_000)
})
onBeforeUnmount(() => {
  if (clock) clearInterval(clock)
})

const nextStamp = computed(() => (props.job.enabled ? String(props.nextRunAt || '') : ''))
const nextParts = computed(() => {
  const text = relativeDayTime(nextStamp.value, now.value)
  if (!text) return null
  const [day, time] = text.includes(' ') ? text.split(' ') : ['', text]
  return { day: day ?? '', time: time ?? text }
})
const countdown = computed(() => countdownText(nextStamp.value, now.value))
const nextFallback = computed(() => {
  if (!props.job.enabled) return '已停用'
  if (!props.job.cron) return '仅手动'
  return props.nextRunText
})

/* 读数与历史面板用同一个查询键：共享缓存，不多打一次请求 */
const { runs } = useJobRunsQuery(() => ({ job_id: props.job.id, limit: 200 }))
const settled = computed(() =>
  runs.value.filter((run) => run.status !== 'running' && run.status !== 'skipped'),
)
const successRate = computed(() => {
  const rows = settled.value
  if (!rows.length) return null
  return (rows.filter((run) => run.status === 'success').length / rows.length) * 100
})
const avgDuration = computed(() => {
  const rows = runs.value.filter((run) => run.status === 'success' && Number(run.duration_ms) > 0)
  if (!rows.length) return ''
  const total = rows.reduce((sum, run) => sum + Number(run.duration_ms), 0)
  return formatRunDuration(total / rows.length)
})

const LAST_STATUS_TEXT: Record<string, string> = {
  success: '成功',
  failed: '失败',
  timed_out: '超时',
  skipped: '跳过',
  cancelled: '已取消',
  running: '运行中',
}
const lastLabel = computed(() => {
  const status = String(props.job.last_status || '').trim().toLowerCase()
  return LAST_STATUS_TEXT[status] ?? jobHealthLabel(health.value).replace('上次', '')
})
const lastWhen = computed(() => relativeDayTime(String(props.job.last_run_at || ''), now.value))

async function reloadRuns(): Promise<void> {
  await runsRef.value?.reload()
}

/** 回执上的「上次失败 N」一路点到这里：直接摊开最近一条失败的全文。 */
async function focusLatestFailure(): Promise<void> {
  await runsRef.value?.focusLatestFailure()
}

defineExpose({ reloadRuns, focusLatestFailure })
</script>

<template>
  <section class="jd">
    <header class="jd__head">
      <div class="jd__lead">
        <div class="jd__crumbs">
          <span class="jd__kind">{{ kindLabel(job.kind) }}</span>
          <span class="jd__origin" :class="{ 'is-bound': bound }">{{ jobOriginLabel(job) }}</span>
          <span v-if="strategyText" class="jd__bind">{{ strategyText }}</span>
          <span v-if="skillText" class="jd__bind">{{ skillText }}</span>
        </div>
        <h3 class="jd__title">{{ title }}</h3>
      </div>
      <div class="jd__actions">
        <label class="jd__switch" :class="{ 'is-on': job.enabled }">
          <Switch :model-value="job.enabled" :disabled="busy" aria-label="启用任务" @update:model-value="emit('toggle')" />
          <span>{{ job.enabled ? '启用中' : '已停用' }}</span>
        </label>
        <Button size="sm" :disabled="busy" @click="emit('fire')">
          <Play />
          立即执行
        </Button>
        <Tooltip v-if="bound">
          <TooltipTrigger as-child>
            <Button variant="outline" size="icon-sm" :disabled="busy" :aria-label="isSkillBoundJob(job) ? '打开技能' : '打开战法'" @click="emit('goBound')">
              <ExternalLink />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{{ isSkillBoundJob(job) ? '打开技能' : '打开战法' }}</TooltipContent>
        </Tooltip>
        <DropdownMenu v-else>
          <DropdownMenuTrigger as-child>
            <Button variant="outline" size="icon-sm" :disabled="busy" aria-label="更多操作">
              <Ellipsis />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem @select="emit('edit')"><Pencil />编辑任务</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" @select="emit('drop')"><Trash2 />删除任务</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>

    <section class="jd__hero" :class="{ 'is-off': !job.enabled }">
      <div class="jd__clock">
        <span class="jd__label">下次触发</span>
        <template v-if="nextParts">
          <strong class="jd__time">{{ nextParts.time }}</strong>
          <span class="jd__when">
            <span>{{ nextParts.day }}</span>
            <span v-if="countdown" class="jd__countdown">{{ countdown }}{{ countdown === '即将' ? '' : '后' }}</span>
          </span>
        </template>
        <strong v-else class="jd__time is-muted">{{ nextFallback }}</strong>
      </div>
      <div class="jd__sched">
        <span class="jd__label">调度</span>
        <strong class="jd__sched-text">{{ cronText }}</strong>
        <span class="jd__sched-row">
          <code class="jd__cron" :title="job.cron">{{ job.cron || '—' }}</code>
          <Button
            variant="ghost"
            size="xs"
            class="jd__edit"
            :class="{ 'is-on': scheduleOpen }"
            :disabled="busy"
            :aria-expanded="scheduleOpen"
            @click="scheduleOpen = !scheduleOpen"
          >
            改时点
          </Button>
        </span>
      </div>
    </section>

    <JobScheduleInline
      :key="job.id"
      v-model:open="scheduleOpen"
      :job="job"
      :busy="busy"
      @save="(payload) => emit('saveSchedule', payload)"
    />

    <dl class="jd__stats">
      <div class="jd__stat" :class="`is-${health}`">
        <dt>上次结果</dt>
        <dd>
          <span class="jd__health"><i aria-hidden="true" />{{ lastLabel }}</span>
          <span v-if="lastWhen" class="jd__sub">{{ lastWhen }}</span>
        </dd>
      </div>
      <div class="jd__stat">
        <dt>成功率</dt>
        <dd>
          <span class="jd__num">{{ successRate == null ? '—' : `${successRate.toFixed(successRate >= 99.95 ? 0 : 1)}%` }}</span>
          <span v-if="settled.length" class="jd__sub">{{ settled.length }} 次</span>
        </dd>
        <span v-if="successRate != null" class="jd__meter" aria-hidden="true"><i :style="{ width: `${successRate}%` }" /></span>
      </div>
      <div class="jd__stat">
        <dt>平均耗时</dt>
        <dd><span class="jd__num">{{ avgDuration || '—' }}</span></dd>
      </div>
      <div class="jd__stat">
        <dt>{{ bound ? '推送企微' : '任务 id' }}</dt>
        <dd v-if="bound"><span class="jd__num">{{ job.config?.push_wecom === false ? '关' : '开' }}</span></dd>
        <dd v-else><span class="jd__id" :title="job.id">{{ job.id }}</span></dd>
      </div>
    </dl>

    <JobRecentRunsPanel :key="job.id" ref="runsRef" :job-id="job.id" />
  </section>
</template>

<style scoped>
.jd {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 14px;
  width: 100%;
  min-width: 0;
  min-height: 0;
}

/* ─── 头 ─── */
.jd__head {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px 16px;
  padding: 2px 2px 0;
}

.jd__lead {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.jd__crumbs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.jd__kind {
  color: var(--text-secondary);
}

.jd__origin {
  padding: 0 6px;
  border-radius: var(--radius-xs);
  background: var(--surface-sunken);
  font-size: var(--fs-kicker);
  font-weight: 600;
  line-height: 18px;
}

.jd__origin.is-bound {
  background: var(--seal-soft);
  color: var(--seal-ink);
}

.jd__bind::before {
  content: '·';
  margin-right: 6px;
  color: var(--text-disabled);
}

.jd__title {
  margin: 0;
  color: var(--text-primary);
  font-size: 22px;
  font-weight: 650;
  letter-spacing: -0.02em;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.jd__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.jd__switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: var(--ctl-h-sm);
  padding: 0 10px 0 6px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken);
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-weight: 500;
  cursor: pointer;
}

.jd__switch.is-on {
  color: var(--text-primary);
}

/* ─── 下次触发 / 调度 ─── */
.jd__hero {
  display: grid;
  flex-shrink: 0;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background:
    radial-gradient(90% 160% at 0% 0%, color-mix(in oklab, var(--seal) 9%, transparent), transparent 70%),
    var(--surface);
}

.jd__hero.is-off {
  background: var(--surface);
}

.jd__clock,
.jd__sched {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: 16px 20px;
}

.jd__sched {
  margin: 8px;
  border-radius: var(--radius);
  background: color-mix(in oklab, var(--surface-sunken) 75%, transparent);
}

.jd__label {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  font-weight: 500;
  letter-spacing: 0.04em;
}

.jd__time {
  color: var(--text-primary);
  font: 650 34px / 1 var(--mono);
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
}

.jd__time.is-muted {
  color: var(--text-tertiary);
  font-family: var(--font);
  font-size: 20px;
  letter-spacing: -0.01em;
}

.jd__when {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
}

.jd__countdown {
  padding: 0 7px;
  border-radius: var(--radius-pill);
  background: var(--seal-soft);
  color: var(--seal-ink);
  font: 600 var(--fs-kicker) / 18px var(--mono);
}

.jd__sched-text {
  color: var(--text-primary);
  font-size: var(--fs-title);
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.jd__sched-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin-top: auto;
}

.jd__cron {
  min-width: 0;
  overflow: hidden;
  padding: 2px 7px;
  border-radius: var(--radius-xs);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font: var(--fs-kicker) / 1.5 var(--mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jd__edit {
  flex: none;
  color: var(--seal-ink);
}

.jd__edit.is-on {
  background: var(--seal-soft);
}

/* ─── 读数 ─── */
.jd__stats {
  display: grid;
  flex-shrink: 0;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.jd__stat {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  padding: 12px 16px;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.jd__stat dt {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
}

.jd__stat dd {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  margin: 0;
}

.jd__num {
  color: var(--text-primary);
  font: 600 var(--fs-title) / 1.2 var(--mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.jd__sub {
  overflow: hidden;
  color: var(--text-tertiary);
  font: var(--fs-kicker) / 1.2 var(--mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jd__health {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 600;
  white-space: nowrap;
}

.jd__health i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border-strong);
}

.jd__stat.is-ok .jd__health i { background: var(--ok); box-shadow: 0 0 0 3px var(--ok-soft); }
.jd__stat.is-failed .jd__health { color: var(--stamp); }
.jd__stat.is-failed .jd__health i { background: var(--stamp); box-shadow: 0 0 0 3px var(--stamp-soft); }
.jd__stat.is-skipped .jd__health i { background: var(--warn); }
.jd__stat.is-running .jd__health i { background: var(--info); }

.jd__meter {
  position: absolute;
  right: 16px;
  bottom: 0;
  left: 16px;
  height: 2px;
  overflow: hidden;
  border-radius: 2px;
  background: var(--surface-sunken);
}

.jd__meter i {
  display: block;
  height: 100%;
  background: var(--ok);
}

.jd__id {
  min-width: 0;
  overflow: hidden;
  color: var(--text-secondary);
  font: var(--fs-aux) / 1.4 var(--mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 900px) {
  .jd__hero {
    grid-template-columns: minmax(0, 1fr);
  }

  .jd__sched {
    margin-top: 0;
  }

  .jd__stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

}

@media (max-width: 640px) {
  .jd__title {
    font-size: 19px;
  }

  .jd__time {
    font-size: 28px;
  }

  .jd__actions > :deep(button) {
    min-height: 36px;
  }
}
</style>
