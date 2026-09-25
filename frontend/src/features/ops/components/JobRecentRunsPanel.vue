<script setup lang="ts">
/**
 * 当前任务的执行历史：顶部一条脉冲带（最近 60 次，高 = 耗时，色 = 结果），
 * 下面是时间线。失败条摆出错误首行，点开 `JobRunErrorDialog` 看全文并复制。
 */
import { computed, ref, watch } from 'vue'
import { RefreshCw } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import PageTabs, { type PageTabItem } from '@/shared/components/ui/PageTabs.vue'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { toErrorMessage } from '@/shared/lib/errors'
import type { JobRun } from '@/shared/types/quant'

import JobRunErrorDialog from './JobRunErrorDialog.vue'
import {
  firstLine,
  formatRunDuration,
  statusLabel,
  triggerLabel,
} from '../composables/opsLabels'
import { relativeDayTime } from '../composables/jobPresentation'
import { useJobRunsQuery } from '../composables/useJobRunsQuery'

const props = defineProps<{
  jobId: string
}>()

const { runs, isPending, error, refetch } = useJobRunsQuery(() => ({
  job_id: props.jobId,
  limit: 200,
}))

const filter = ref<'all' | 'failed'>('all')
const errorOpen = ref(false)
const activeRun = ref<JobRun | null>(null)

const failedCount = computed(() => runs.value.filter((run) => run.status === 'failed').length)
const visibleRuns = computed(() =>
  filter.value === 'failed' ? runs.value.filter((run) => run.status === 'failed') : runs.value,
)
const filterItems = computed<PageTabItem[]>(() => [
  { name: 'all', label: '全部', badge: runs.value.length || undefined },
  { name: 'failed', label: '失败', badge: failedCount.value || undefined, disabled: !failedCount.value },
])
const filterModel = computed({
  get: () => filter.value,
  set: (value: string) => {
    filter.value = value === 'failed' ? 'failed' : 'all'
  },
})

type Tone = 'ok' | 'stamp' | 'warn' | 'info' | 'secondary'

function toneOf(status: string): Tone {
  if (status === 'failed' || status === 'timed_out') return 'stamp'
  if (status === 'success' || status === 'ok') return 'ok'
  if (status === 'running') return 'info'
  if (status === 'skipped' || status === 'cancelled') return 'warn'
  return 'secondary'
}

/** 脉冲带：旧 → 新从左到右；高度按对数耗时，免得一次长跑把其余压扁 */
const pulse = computed(() => {
  const rows = runs.value.slice(0, 60).reverse()
  const logs = rows.map((run) => Math.log10(Math.max(1, Number(run.duration_ms) || 1)))
  const max = Math.max(1, ...logs)
  return rows.map((run, index) => ({
    run,
    tone: toneOf(String(run.status ?? '')),
    height: 22 + (logs[index]! / max) * 78,
  }))
})

const errorText = computed(() => (error.value ? toErrorMessage(error.value, '读取执行历史失败') : ''))

function formatStartedAt(raw: string): string {
  const text = raw.trim()
  if (!text) return '—'
  return text.replace('T', ' ').slice(0, 19)
}

async function reload(): Promise<void> {
  await refetch()
}

function openError(run: JobRun): void {
  activeRun.value = run
  errorOpen.value = true
}

/** 回执上的「上次失败 N」点进来就落在这里：直接摊开最近一条失败全文。 */
async function focusLatestFailure(): Promise<void> {
  await reload()
  const hit = runs.value.find((run) => run.status === 'failed')
  if (!hit) return
  filter.value = 'failed'
  activeRun.value = hit
  errorOpen.value = true
}

watch(
  () => props.jobId,
  () => {
    filter.value = 'all'
    errorOpen.value = false
    activeRun.value = null
    void reload()
  },
  { immediate: true },
)

defineExpose({ reload, focusLatestFailure })
</script>

<template>
  <section class="runs" aria-label="执行历史">
    <header class="runs__head">
      <strong class="runs__title">执行历史</strong>
      <PageTabs v-model="filterModel" :items="filterItems" variant="pill" dense :sticky="false" aria-label="执行结果筛选" class="runs__filter" />
      <Button access="read" variant="ghost" size="icon-sm" aria-label="刷新执行历史" :disabled="isPending" @click="reload">
        <RefreshCw :class="isPending ? 'animate-spin' : ''" />
      </Button>
    </header>

    <div v-if="pulse.length" class="runs__pulse" role="img" :aria-label="`最近 ${pulse.length} 次执行`">
      <Tooltip v-for="bar in pulse" :key="bar.run.id" :delay-duration="60">
        <TooltipTrigger as-child>
          <button
            type="button"
            class="runs__bar"
            :class="`is-${bar.tone}`"
            :style="{ height: `${bar.height}%` }"
            :aria-label="`${formatStartedAt(String(bar.run.started_at ?? ''))} ${statusLabel(String(bar.run.status ?? ''))}`"
            @click="bar.run.error_text ? openError(bar.run) : undefined"
          />
        </TooltipTrigger>
        <TooltipContent side="top">
          <span class="runs-tip">
            <b>{{ statusLabel(String(bar.run.status ?? '')) }}</b>
            <span>{{ relativeDayTime(String(bar.run.started_at ?? '')) }}</span>
            <span>{{ formatRunDuration(Number(bar.run.duration_ms ?? 0)) }}</span>
          </span>
        </TooltipContent>
      </Tooltip>
    </div>

    <p v-if="errorText && !runs.length" class="runs__error" role="alert">{{ errorText }}</p>
    <div v-else-if="isPending && !runs.length" class="runs__skeleton" aria-busy="true">
      <Skeleton v-for="n in 3" :key="n" class="h-9 w-full" />
    </div>
    <ol v-else-if="visibleRuns.length" class="runs__list">
      <li
        v-for="run in visibleRuns"
        :key="run.id"
        class="run"
        :class="`is-${toneOf(String(run.status ?? ''))}`"
      >
        <span class="run__dot" aria-hidden="true" />
        <div class="run__body">
          <div class="run__line">
            <span class="run__status">{{ statusLabel(String(run.status ?? '')) }}</span>
            <span class="run__meta">{{ triggerLabel(String(run.trigger ?? '')) }}</span>
            <span class="run__meta run__dur">{{ formatRunDuration(Number(run.duration_ms ?? 0)) }}</span>
            <time class="run__time" :title="formatStartedAt(String(run.started_at ?? ''))">{{ relativeDayTime(String(run.started_at ?? '')) || formatStartedAt(String(run.started_at ?? '')) }}</time>
          </div>
          <Button
            v-if="run.error_text"
            access="read"
            variant="ghost"
            type="button"
            class="run__err"
            @click="openError(run)"
          >
            <span class="run__err-line">{{ firstLine(String(run.error_text)) }}</span>
            <span class="run__err-more">全文</span>
          </Button>
        </div>
      </li>
    </ol>
    <EmptyState
      v-else
      compact
      :description="filter === 'failed' ? '没有失败记录' : '还没有执行记录'"
    />

    <JobRunErrorDialog v-model="errorOpen" :run="activeRun" />
  </section>
</template>

<style scoped>
.runs {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  overflow: hidden;
}

.runs__head {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 10px;
  padding: 10px 12px 8px 16px;
}

.runs__title {
  color: var(--text-primary);
  font-size: var(--fs-title);
  font-weight: 600;
}

.runs__filter {
  margin: 0 auto 0 0;
}

.runs__filter :deep(.page-tabs__item) {
  height: 24px;
  font-size: var(--fs-kicker);
}

.runs__pulse {
  display: flex;
  flex-shrink: 0;
  align-items: flex-end;
  gap: 2px;
  height: 44px;
  margin: 0 16px 6px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-subtle);
}

.runs__bar {
  flex: 1 1 0;
  max-width: 10px;
  min-width: 3px;
  padding: 0;
  border: 0;
  border-radius: 2px 2px 1px 1px;
  background: var(--border-strong);
  cursor: default;
  opacity: 0.85;
  transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}

.runs__bar:hover,
.runs__bar:focus-visible {
  opacity: 1;
  outline: none;
  transform: scaleY(1.08);
  transform-origin: bottom;
}

.runs__bar.is-ok { background: color-mix(in oklab, var(--ok) 78%, transparent); }
.runs__bar.is-stamp { background: var(--stamp); cursor: pointer; }
.runs__bar.is-warn { background: var(--warn); }
.runs__bar.is-info { background: var(--info); }

.runs-tip {
  display: inline-flex;
  gap: 8px;
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.runs__error {
  margin: 8px 16px 16px;
  color: var(--stamp);
  font-size: var(--fs-aux);
}

.runs__skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 16px 16px;
}

.runs__list {
  margin: 0;
  padding: 4px 16px 14px;
  overflow: auto;
  list-style: none;
  scrollbar-width: thin;
}

.run {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 6px 0;
}

.run::before {
  content: '';
  position: absolute;
  top: 24px;
  bottom: -8px;
  left: 4px;
  width: 1px;
  background: var(--border-subtle);
}

.run:last-child::before {
  display: none;
}

.run__dot {
  position: relative;
  z-index: 1;
  flex: none;
  width: 9px;
  height: 9px;
  margin-top: 9px;
  border-radius: 50%;
  background: var(--border-strong);
  box-shadow: 0 0 0 3px var(--surface);
}

.run.is-ok .run__dot { background: var(--ok); }
.run.is-stamp .run__dot { background: var(--stamp); }
.run.is-warn .run__dot { background: var(--warn); }
.run.is-info .run__dot { background: var(--info); animation: run-pulse 1.4s ease-in-out infinite; }

.run__body {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.run__line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
  min-height: 26px;
}

.run__status {
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 550;
}

.run.is-stamp .run__status { color: var(--stamp); }

.run__meta {
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.run__dur {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.run__time {
  margin-left: auto;
  color: var(--text-tertiary);
  font: var(--fs-aux) / 1 var(--mono);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.run__err {
  display: flex;
  justify-content: flex-start;
  gap: 8px;
  height: auto;
  max-width: 100%;
  min-width: 0;
  padding: 6px 10px;
  border-radius: var(--radius);
  background: var(--stamp-soft);
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  text-align: left;
}

.run__err:hover,
.run__err:focus-visible {
  background: color-mix(in oklab, var(--stamp) 16%, transparent);
  color: var(--stamp);
}

.run__err-line {
  min-width: 0;
  overflow: hidden;
  font-family: var(--mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run__err-more {
  flex: none;
  margin-left: auto;
  color: var(--stamp);
  font-size: var(--fs-kicker);
  font-weight: 600;
}

@keyframes run-pulse {
  0%, 100% { box-shadow: 0 0 0 3px var(--surface); }
  50% { box-shadow: 0 0 0 3px var(--surface), 0 0 0 6px var(--info-soft); }
}

@media (prefers-reduced-motion: reduce) {
  .run.is-info .run__dot { animation: none; }
}

@media (max-width: 640px) {
  .runs__head { padding-left: 12px; }
  .runs__pulse { margin-inline: 12px; }
  .runs__list { padding-inline: 12px; }
  .run__time { flex-basis: 100%; margin-left: 0; }
}
</style>
