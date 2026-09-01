<script setup lang="ts">
/**
 * 作业健康：正常时只是页头右侧一枚小圆点（说明进 tooltip），异常才展开成一行。
 * 自己不发请求，数据由 `usePulseOpsHealth` 经父级注入。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'

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

/** 异常时露在页头那一行的短句：≤14 字，全文进 tooltip。 */
const lineText = computed(() => {
  if (props.error) return '作业状态读不到'
  return failedText.value || '作业正常'
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
  <el-tooltip :content="tipText" placement="bottom-end" :show-after="120">
    <el-button
      class="pulse-dot"
      :class="{ 'is-bad': bad }"
      link
      size="small"
      :aria-label="`作业健康：${tipText}`"
      @click="openJobs"
    >
      <span class="pulse-dot__mark" aria-hidden="true" />
      <span v-if="bad" class="pulse-dot__text">{{ lineText }}</span>
    </el-button>
  </el-tooltip>
</template>

<style scoped>
.pulse-dot {
  flex: 0 0 auto;
  height: 20px;
  /* 全局 .el-button--small 的 min-height 是 --ctl-h，页头这枚点必须一起压下来 */
  min-height: 20px;
  padding: 0 2px;
  font-size: var(--fs-aux, 12px);
  color: var(--mist);
}

.pulse-dot__mark {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--seal);
  flex: 0 0 auto;
}

.pulse-dot.is-bad {
  color: var(--warn);
}

.pulse-dot.is-bad .pulse-dot__mark {
  background: var(--warn);
}

.pulse-dot__text {
  margin-left: 5px;
  max-width: 16ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
