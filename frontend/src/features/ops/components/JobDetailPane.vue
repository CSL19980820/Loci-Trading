<script setup lang="ts">
/**
 * 定时任务右侧详情：元信息 + 就地改时点 + 当前任务最近执行。
 *
 * 绑定任务（`screen:` / `skill:`）在这里**不再只读**：改时点与启停走的是和本机
 * 任务同一个 `PATCH /api/jobs/{id}`。要跳去工坊的只剩战法专属配置（股票池、
 * top_n、AI 精选等）——那些确实长在战法那边。
 */
import { computed, ref } from 'vue'

import type { Job } from '@/shared/types/quant'

import JobRecentRunsPanel from './JobRecentRunsPanel.vue'
import JobScheduleInline from './JobScheduleInline.vue'
import {
  isBoundManagedJob,
  isSkillBoundJob,
  jobOriginLabel,
} from '../composables/jobOwnership'
import { jobHealth, jobHealthLabel, kindLabel, statusLabel } from '../composables/opsLabels'

const props = defineProps<{
  job: Job
  busy: boolean
  nextRunText: string
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
const bound = computed(() => isBoundManagedJob(props.job))
const health = computed(() => jobHealth(props.job))

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
  <section class="job-detail">
    <!--
      标题与那排标签原来是上下两行。合成一行：标题 + 类型/来源/停用 chip + 操作按钮。
      原先跟在下面的常驻 info 提示条也删了——它讲的是「其余配置去哪改」，
      已经挂到那颗「去工坊/去技能改配置」按钮的 tooltip 上。
    -->
    <header class="job-detail__head">
      <h3 class="job-detail__title">{{ title }}</h3>
      <el-tag size="small" effect="plain">{{ kindLabel(job.kind) }}</el-tag>
      <el-tag size="small" effect="light" :type="bound ? 'info' : 'primary'">
        {{ jobOriginLabel(job) }}
      </el-tag>
      <el-tag v-if="!job.enabled" size="small" type="info" effect="light">停用</el-tag>
      <div class="job-detail__actions">
        <el-button :disabled="busy" @click="emit('fire')">立即执行</el-button>
        <!-- 启停对绑定任务同样开放：它和改时点是同一件事的两半 -->
        <el-button :disabled="busy" @click="emit('toggle')">
          {{ job.enabled ? '停用' : '启用' }}
        </el-button>
        <template v-if="bound">
          <el-tooltip
            placement="top-end"
            :content="
              isSkillBoundJob(job)
                ? '时点与启停在这里改；其余配置在技能详情'
                : '时点与启停在这里改；其余配置在工坊'
            "
          >
            <el-button plain :disabled="busy" @click="emit('goBound')">
              {{ isSkillBoundJob(job) ? '去技能改配置' : '去工坊改配置' }}
            </el-button>
          </el-tooltip>
        </template>
        <template v-else>
          <el-button :disabled="busy" @click="emit('edit')">编辑</el-button>
          <el-button type="danger" plain :disabled="busy" @click="emit('drop')">
            删除
          </el-button>
        </template>
      </div>
    </header>

    <JobScheduleInline
      :key="job.id"
      :job="job"
      :busy="busy"
      @save="(payload) => emit('saveSchedule', payload)"
    />

    <el-descriptions :column="2" border class="job-detail__desc">
      <el-descriptions-item label="调度">{{ cronText }}</el-descriptions-item>
      <el-descriptions-item label="cron">
        <span class="mono">{{ job.cron || '—' }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="下次触发">
        <el-tooltip
          v-if="bound"
          placement="top-start"
          content="托管任务默认时点按账号错峰（选股 15:30~15:44、情报 15:40~15:54、候选跟踪 15:45~15:59），不同账号分钟不同属正常"
        >
          <span class="mono">{{ nextRunText }}</span>
        </el-tooltip>
        <span v-else class="mono">{{ nextRunText }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="上次">
        <span class="job-detail__dot" :class="`job-detail__dot--${health}`" aria-hidden="true" />
        <el-tag
          size="small"
          effect="light"
          :type="
            health === 'failed' ? 'danger' : health === 'ok' ? 'success' : 'info'
          "
        >
          {{ job.last_status ? statusLabel(job.last_status) : jobHealthLabel(health) }}
        </el-tag>
        <span class="mono dim"> {{ job.last_run_at || '—' }}</span>
      </el-descriptions-item>
      <el-descriptions-item v-if="job.kind === 'screen'" label="战法" :span="2">
        {{ strategyText || '—' }}
      </el-descriptions-item>
      <el-descriptions-item v-if="job.kind === 'skill'" label="技能" :span="2">
        {{ skillText || '—' }}
      </el-descriptions-item>
      <el-descriptions-item v-if="bound" label="推送企微" :span="2">
        {{ job.config?.push_wecom === false ? '关' : '开' }}
      </el-descriptions-item>
      <el-descriptions-item label="任务 id" :span="2">
        <span class="mono dim">{{ job.id }}</span>
      </el-descriptions-item>
    </el-descriptions>

    <JobRecentRunsPanel :key="job.id" ref="runsRef" :job-id="job.id" />
  </section>
</template>

<style scoped>
.job-detail {
  min-width: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--gap-3);
  overscroll-behavior: contain;
  min-height: 0;
  flex: 1 1 auto;
}
/* 一行到底：标题 + chip + 按钮；按钮靠右 */
.job-detail__head {
  display: flex;
  padding: var(--gap-2) var(--gap-3);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--surface-sunken);
  align-items: center;
  gap: 0.35rem 0.5rem;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.job-detail__title {
  margin: 0;
  margin-right: 0.15rem;
  font-size: var(--fs-title);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.job-detail__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-left: auto;
}
.job-detail__desc {
  width: 100%;
  overflow: auto;
  font-size: var(--fs-body);
  flex-shrink: 0;
}
.job-detail__desc :deep(.el-descriptions__label) {
  width: 7.5rem;
  font-size: 0.9rem;
}
.job-detail__desc :deep(.el-descriptions__content) {
  font-size: var(--fs-body);
}
/* 状态点与左栏同一套语义色，别在两处各挑一个红 */
.job-detail__dot {
  display: inline-block;
  width: 0.5rem;
  height: 0.5rem;
  margin-right: 0.35rem;
  border-radius: 50%;
  background: var(--rule);
  vertical-align: middle;
}
.job-detail__dot--ok {
  background: var(--el-color-success);
}
.job-detail__dot--failed {
  background: var(--el-color-danger);
}
.job-detail__dot--skipped {
  background: var(--el-color-warning);
}
.job-detail__dot--running {
  background: var(--info);
}
.job-detail__dot--never {
  background: transparent;
  border: 1px solid var(--line-2);
}
.mono {
  font-family: var(--mono);
  font-size: 0.95em;
}
.dim {
  color: var(--muted);
}
.job-detail__actions :deep(.el-button + .el-button) { margin-left: 0; }
.job-detail > :deep(.job-runs-panel) { flex-shrink: 0; }
</style>
