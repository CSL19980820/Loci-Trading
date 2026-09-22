<script setup lang="ts">
import { Button } from '@/shared/components/ui/button'
/**
 * 作业健康：页头上一枚状态点（正常青绿 / 失败琥珀），**不占宽度**。
 * 具体是「作业正常 / 哪个任务什么时候失败 / 下次自动选股」全部进 tooltip 与 aria-label。
 * 自己不发请求，数据由 `usePulseOpsHealth` 经父级注入；点击仍链到任务中心。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import { formatRunClock } from '../composables/pulseEmptyState'
import type { JobRun } from '@/shared/types/quant'

const props = defineProps<{
  loading?: boolean
  error?: string
  lastFailedRun: JobRun | null
  hasEnabledScreenJob: boolean
  nextScreenRunAt: string | null
}>()

const ERROR_CLIP = 48

const bad = computed(() => Boolean(props.lastFailedRun) || Boolean(props.error))

const failedText = computed(() => {
  const run = props.lastFailedRun
  if (!run) return ''
  const at = formatRunClock(run.started_at)
  return [`${run.job_name || run.kind || '任务'} 失败`, at].filter(Boolean).join(' ')
})

const lineText = computed(() => {
  if (props.error) return '作业状态读不到'
  if (failedText.value) return failedText.value
  if (props.loading) return '读取中'
  return '作业正常'
})

const nextText = computed(() => {
  if (!props.hasEnabledScreenJob) return '未启用定时选股'
  const next = formatRunClock(props.nextScreenRunAt)
  return next ? `下次自动选股 ${next}` : '定时选股未算出下次触发'
})

const tipText = computed(() => {
  if (props.error) return `作业健康读不到：${props.error}`
  const run = props.lastFailedRun
  if (!run) {
    return `${props.loading ? '作业状态读取中' : '近期作业无失败'} · ${nextText.value}`
  }
  const raw = (run.error_text || '').replace(/\s+/g, ' ').trim()
  const reason = raw.length > ERROR_CLIP ? `${raw.slice(0, ERROR_CLIP)}…` : raw
  return [failedText.value, reason, nextText.value].filter(Boolean).join(' · ')
})

const router = useRouter()

function openJobs(): void {
  void router.push({ path: '/quant', query: { tab: 'jobs' } })
}
</script>

<template>
  <Tooltip>
    <TooltipTrigger as-child>
      <Button access="read" variant="ghost"
        type="button"
        class="health"
        :class="{ 'is-bad': bad, 'is-loading': loading && !bad }"
        :aria-label="`作业健康：${tipText}`"
        @click="openJobs"
      >
        <span class="health__dot" aria-hidden="true" />
      </Button>
    </TooltipTrigger>
    <TooltipContent>{{ tipText }}</TooltipContent>
  </Tooltip>
</template>

<style scoped>
/*
 * 只是一枚点：文字（作业正常 / 失败原因 / 下次自动选股）全部进 tooltip 与 aria-label。
 * 页头那一行已经够挤，状态点不再占宽度。
 */
.health {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--ctl-h-sm);
  height: var(--ctl-h-sm);
  flex: 0 0 auto;
  padding: 0;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  background: var(--surface);
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease),
    background-color var(--dur-fast) var(--ease);
}

.health:hover {
  border-color: var(--border-default);
  background: var(--surface-hover);
}

.health:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
}

.health__dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 0 3px var(--ok-soft);
}

.health.is-loading .health__dot {
  background: var(--text-disabled);
  box-shadow: none;
}

.health.is-bad {
  border-color: color-mix(in oklab, var(--warn) 40%, var(--border-subtle));
  background: var(--warn-soft);
  color: var(--warn-ink);
}

.health.is-bad .health__dot {
  background: var(--warn);
  box-shadow: 0 0 0 3px color-mix(in oklab, var(--warn) 20%, transparent);
}
</style>
