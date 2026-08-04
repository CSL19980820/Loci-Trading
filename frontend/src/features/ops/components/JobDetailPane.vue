<script setup lang="ts">
/**
 * 定时任务右侧详情：元信息 + 当前任务最近执行。
 */
import { computed, ref } from 'vue'

import type { Job } from '@/shared/types/quant'

import JobRecentRunsPanel from './JobRecentRunsPanel.vue'
import {
  isBoundManagedJob,
  isSkillBoundJob,
  jobOriginLabel,
} from '../composables/jobOwnership'
import { kindLabel, statusLabel } from '../composables/opsLabels'

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
}>()

const runsRef = ref<InstanceType<typeof JobRecentRunsPanel> | null>(null)
const bound = computed(() => isBoundManagedJob(props.job))

async function reloadRuns(): Promise<void> {
  await runsRef.value?.reload(true)
}

defineExpose({ reloadRuns })
</script>

<template>
  <section class="job-detail">
    <header class="job-detail__head">
      <div>
        <h3>{{ title }}</h3>
        <p class="job-detail__sub">
          <el-tag size="small" effect="plain">{{ kindLabel(job.kind) }}</el-tag>
          <el-tag
            size="small"
            effect="light"
            :type="bound ? 'info' : 'danger'"
            class="ml"
          >
            {{ jobOriginLabel(job) }}
          </el-tag>
          <el-tag
            v-if="!job.enabled"
            size="small"
            type="info"
            effect="light"
            class="ml"
          >
            停用
          </el-tag>
        </p>
      </div>
      <div class="job-detail__actions">
        <el-button :disabled="busy" @click="emit('fire')">立即执行</el-button>
        <template v-if="bound">
          <el-button type="primary" plain @click="emit('goBound')">
            {{ isSkillBoundJob(job) ? '去技能改' : '去战法改' }}
          </el-button>
        </template>
        <template v-else>
          <el-button :disabled="busy" @click="emit('edit')">编辑</el-button>
          <el-button :disabled="busy" @click="emit('toggle')">
            {{ job.enabled ? '停用' : '启用' }}
          </el-button>
          <el-button type="danger" plain :disabled="busy" @click="emit('drop')">
            删除
          </el-button>
        </template>
      </div>
    </header>

    <el-alert
      v-if="bound"
      type="info"
      :closable="false"
      show-icon
      :title="
        isSkillBoundJob(job)
          ? '技能绑定：在此只读。改定时 / 推送请到技能详情。'
          : '战法绑定：在此只读。改定时 / 推送请到战法配置弹窗。'
      "
      class="job-detail__hint"
    />

    <el-descriptions :column="2" border class="job-detail__desc">
      <el-descriptions-item label="调度">{{ cronText }}</el-descriptions-item>
      <el-descriptions-item label="cron">
        <span class="mono">{{ job.cron || '—' }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="下次触发">
        <span class="mono">{{ nextRunText }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="上次">
        <el-tag
          size="small"
          effect="light"
          :type="
            job.last_status === 'failed'
              ? 'danger'
              : job.last_status === 'success'
                ? 'success'
                : 'info'
          "
        >
          {{ statusLabel(job.last_status) }}
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
  gap: 0.85rem;
  min-height: 0;
  flex: 1 1 auto;
}
.job-detail__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.job-detail__head h3 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}
.job-detail__sub {
  margin: 0.35rem 0 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.25rem;
}
.job-detail__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}
.job-detail__hint {
  margin: 0;
  flex-shrink: 0;
}
.job-detail__desc {
  width: 100%;
  font-size: 0.95rem;
  flex-shrink: 0;
}
.job-detail__desc :deep(.el-descriptions__label) {
  width: 7.5rem;
  font-size: 0.9rem;
}
.job-detail__desc :deep(.el-descriptions__content) {
  font-size: 0.95rem;
}
.ml {
  margin-left: 0.25rem;
}
.mono {
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: 0.95em;
}
.dim {
  color: var(--muted);
}
</style>
