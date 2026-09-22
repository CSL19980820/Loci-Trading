<script setup lang="ts">
import { Label } from '@/shared/components/ui/label'
/**
 * 当前任务的最近执行历史：**时间线**（Linear activity 一路），不再是四列表格。
 *
 * 每条 = 左侧状态点（成功 / 失败 / 跳过 / 运行中）挂在一根 1px 竖线上，右侧一行
 * 「结果 · 触发 · 耗时」+ 时间；失败条把错误首行摆出来，点开 `JobRunErrorDialog`
 * 看全文并整段复制。此前全文只挂在原生 `title` 上，读不完也复制不走。
 */
import { computed, ref, watch } from 'vue'
import { ListFilter, RefreshCw } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import { Checkbox } from '@/shared/components/ui/checkbox'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Skeleton } from '@/shared/components/ui/skeleton'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
import type { JobRun } from '@/shared/types/quant'

import JobRunErrorDialog from './JobRunErrorDialog.vue'
import {
  firstLine,
  formatRunDuration,
  statusLabel,
  triggerLabel,
} from '../composables/opsLabels'
import { useJobRunsQuery } from '../composables/useJobRunsQuery'

const props = defineProps<{
  jobId: string
}>()

const { runs, isPending, refetch } = useJobRunsQuery(() => ({
  job_id: props.jobId,
  limit: 200,
}))

/** 「只看失败」：一屏几十条成功记录里找那一条红的，靠肉眼扫是最慢的一步。 */
const failedOnly = ref(false)
const errorOpen = ref(false)
const activeRun = ref<JobRun | null>(null)

const visibleRuns = computed(() =>
  failedOnly.value ? runs.value.filter((run) => run.status === 'failed') : runs.value,
)
const runCount = computed(() => visibleRuns.value.length)
const failedCount = computed(() => runs.value.filter((run) => run.status === 'failed').length)

function formatStartedAt(raw: string): string {
  const text = raw.trim()
  if (!text) return '—'
  return text.replace('T', ' ').slice(0, 19)
}

function statusVariant(status: string): 'ok' | 'stamp' | 'warn' | 'info' | 'secondary' {
  if (status === 'failed') return 'stamp'
  if (status === 'success' || status === 'ok') return 'ok'
  if (status === 'running') return 'info'
  if (status === 'skipped') return 'warn'
  return 'secondary'
}

async function reload(): Promise<void> {
  await refetch()
}

function openError(run: JobRun): void {
  activeRun.value = run
  errorOpen.value = true
}

/**
 * 直接把最近一条失败摊开。回执上的「上次失败 N」点进来就落在这里——
 * 少掉「猜是哪条任务 → 逐条点开 → 悬停读半句」三步。
 */
async function focusLatestFailure(): Promise<void> {
  await reload()
  const hit = runs.value.find((run) => run.status === 'failed')
  if (!hit) return
  failedOnly.value = true
  activeRun.value = hit
  errorOpen.value = true
}

watch(
  () => props.jobId,
  () => {
    failedOnly.value = false
    errorOpen.value = false
    activeRun.value = null
    void reload()
  },
  { immediate: true },
)

defineExpose({ reload, focusLatestFailure })
</script>

<template>
  <section class="job-runs" aria-label="最近执行历史">
    <header class="job-runs__head">
      <div class="job-runs__title">
        <strong>最近执行</strong>
        <UiBadge variant="secondary">{{ runCount }} 条</UiBadge>
      </div>
      <div class="job-runs__tools">
        <Label class="job-runs__only-failed" :class="{ 'is-disabled': !failedCount }">
          <Checkbox v-model="failedOnly" :disabled="!failedCount" aria-label="只看失败" />
          <ListFilter aria-hidden="true" />
          <span>只看失败{{ failedCount ? `（${failedCount}）` : '' }}</span>
        </Label>
        <Button access="read" variant="ghost" size="icon-sm" aria-label="刷新执行历史" :disabled="isPending" @click="reload">
          <RefreshCw :class="isPending ? 'animate-spin' : ''" />
        </Button>
      </div>
    </header>

    <div v-if="isPending && !runs.length" class="job-runs__skeleton" aria-busy="true">
      <Skeleton v-for="n in 3" :key="n" class="h-10 w-full" />
    </div>
    <ol v-else-if="visibleRuns.length" class="job-runs__timeline">
      <li
        v-for="run in visibleRuns"
        :key="run.id"
        class="run"
        :class="`is-${statusVariant(String(run.status ?? ''))}`"
      >
        <span class="run__dot" aria-hidden="true" />
        <div class="run__body">
          <div class="run__line">
            <UiBadge :variant="statusVariant(String(run.status ?? ''))">{{ statusLabel(String(run.status ?? '')) }}</UiBadge>
            <span class="run__meta">{{ triggerLabel(String(run.trigger ?? '')) }}</span>
            <span class="run__meta run__dur">{{ formatRunDuration(Number(run.duration_ms ?? 0)) }}</span>
            <time class="run__time">{{ formatStartedAt(String(run.started_at ?? '')) }}</time>
          </div>
          <Button access="read" variant="ghost"
            v-if="run.error_text"
            type="button"
            class="run__err"
            title="点开看失败全文并复制"
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
      :description="failedOnly ? '这条任务没有失败记录' : '还没有执行记录'"
      :reason="failedOnly ? '取消「只看失败」看全部' : '点「立即执行」跑一次'"
    />

    <JobRunErrorDialog v-model="errorOpen" :run="activeRun" />
  </section>
</template>

<style scoped>
.job-runs {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-xs);
  overflow: hidden;
}

.job-runs__head {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  padding: var(--gap-3) var(--gap-4);
  border-bottom: 1px solid var(--border-subtle);
}

.job-runs__title {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-2);
  color: var(--text-primary);
  font-size: var(--fs-title);
  font-weight: 600;
}

.job-runs__tools {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-2);
}

.job-runs__only-failed {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  cursor: pointer;
}

.job-runs__only-failed :deep(svg) {
  width: 14px;
  height: 14px;
  color: var(--text-tertiary);
}

.job-runs__only-failed.is-disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.job-runs__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  padding: var(--gap-4);
}

.job-runs__timeline {
  position: relative;
  margin: 0;
  padding: var(--gap-3) var(--gap-4) var(--gap-4) var(--gap-4);
  list-style: none;
  overflow: auto;
  max-height: 26rem;
  scrollbar-width: thin;
}

.run {
  position: relative;
  display: flex;
  gap: var(--gap-3);
  padding: var(--gap-2) 0 var(--gap-3) 0;
}

/* 竖线：从点的中心往下连到下一条 */
.run::before {
  content: '';
  position: absolute;
  top: 22px;
  bottom: -4px;
  left: 5px;
  width: 1px;
  background: var(--border-subtle);
}

.run:last-child::before {
  display: none;
}

.run__dot {
  position: relative;
  z-index: 1;
  flex: 0 0 auto;
  width: 11px;
  height: 11px;
  margin-top: 11px;
  border-radius: 50%;
  background: var(--border-strong);
  box-shadow: 0 0 0 3px var(--surface);
}

.run.is-ok .run__dot {
  background: var(--ok);
}

.run.is-stamp .run__dot {
  background: var(--stamp);
}

.run.is-warn .run__dot {
  background: var(--warn);
}

.run.is-info .run__dot {
  background: var(--info);
  animation: run-pulse 1.4s ease-in-out infinite;
}

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
  gap: var(--gap-2);
  min-height: 28px;
}

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
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.run__err {
  display: flex;
  align-items: center;
  gap: var(--gap-2);
  max-width: 100%;
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid color-mix(in oklab, var(--stamp) 25%, var(--border-subtle));
  border-radius: var(--radius);
  background: var(--stamp-soft);
  color: var(--text-secondary);
  font-size: var(--fs-aux);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur-fast) var(--ease);
}

.run__err:hover,
.run__err:focus-visible {
  border-color: var(--stamp);
  color: var(--stamp);
}

.run__err:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 1px;
}

.run__err-line {
  min-width: 0;
  overflow: hidden;
  font-family: var(--mono);
  white-space: nowrap;
  text-overflow: ellipsis;
}

.run__err-more {
  flex: 0 0 auto;
  padding: 0 6px;
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--stamp);
  font-size: var(--fs-kicker);
  font-weight: 600;
}

@keyframes run-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 3px var(--surface);
  }
  50% {
    box-shadow: 0 0 0 3px var(--surface), 0 0 0 6px var(--info-soft);
  }
}

@media (prefers-reduced-motion: reduce) {
  .run.is-info .run__dot {
    animation: none;
  }
}

@media (max-width: 640px) {
  .job-runs__head,
  .job-runs__timeline {
    padding-left: var(--gap-3);
    padding-right: var(--gap-3);
  }

  .run__time {
    flex-basis: 100%;
    margin-left: 0;
  }
}
</style>
