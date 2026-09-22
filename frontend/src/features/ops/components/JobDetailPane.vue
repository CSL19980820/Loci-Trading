<script setup lang="ts">
/**
 * 定时任务右侧详情：标题头 + 四格读数 + 就地改时点 + 最近执行时间线。
 *
 * 绑定任务（`screen:` / `skill:`）在这里**不再只读**：改时点与启停走的是和本机
 * 任务同一个 `PATCH /api/jobs/{id}`。要跳去工坊的只剩战法专属配置（股票池、
 * top_n、AI 精选等）——那些确实长在战法那边。
 */
import { computed, ref } from 'vue'
import { Ellipsis, ExternalLink, Pencil, Play, Power, Trash2 } from '@lucide/vue'

import { Button } from '@/shared/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import UiBadge from '@/shared/components/ui/UiBadge.vue'
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

const healthVariant = computed((): 'ok' | 'stamp' | 'warn' | 'info' | 'secondary' => {
  if (health.value === 'ok') return 'ok'
  if (health.value === 'failed') return 'stamp'
  if (health.value === 'skipped') return 'warn'
  if (health.value === 'running') return 'info'
  return 'secondary'
})

const lastLabel = computed(() =>
  props.job.last_status ? statusLabel(props.job.last_status) : jobHealthLabel(health.value),
)

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
    <header class="job-detail__head">
      <div class="job-detail__lead">
        <div class="job-detail__title-row">
          <h3 class="job-detail__title">{{ title }}</h3>
          <UiBadge variant="outline">{{ kindLabel(job.kind) }}</UiBadge>
          <UiBadge :variant="bound ? 'info' : 'secondary'">{{ jobOriginLabel(job) }}</UiBadge>
          <UiBadge v-if="!job.enabled" variant="secondary" dot>已停用</UiBadge>
        </div>
        <p class="job-detail__sub">
          <code class="job-detail__cron">{{ job.cron || '仅手动' }}</code>
          <span v-if="strategyText" class="job-detail__bind">战法 · {{ strategyText }}</span>
          <span v-if="skillText" class="job-detail__bind">技能 · {{ skillText }}</span>
        </p>
      </div>
      <div class="job-detail__actions">
        <Button size="sm" :disabled="busy" @click="emit('fire')">
          <Play />
          立即执行
        </Button>
        <Button variant="outline" size="sm" :disabled="busy" @click="emit('toggle')">
          <Power />
          {{ job.enabled ? '停用' : '启用' }}
        </Button>
        <Tooltip v-if="bound">
          <TooltipTrigger as-child>
            <Button variant="outline" size="sm" :disabled="busy" @click="emit('goBound')">
              <ExternalLink />
              {{ isSkillBoundJob(job) ? '去技能改配置' : '去工坊改配置' }}
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            {{ isSkillBoundJob(job) ? '时点与启停在这里改；其余配置在技能详情' : '时点与启停在这里改；其余配置在工坊' }}
          </TooltipContent>
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

    <dl class="job-detail__facts">
      <div class="job-detail__fact">
        <dt>调度</dt>
        <dd>{{ cronText }}</dd>
      </div>
      <div class="job-detail__fact">
        <dt>下次触发</dt>
        <dd class="mono">
          <Tooltip v-if="bound">
            <TooltipTrigger as-child>
              <span>{{ nextRunText }}</span>
            </TooltipTrigger>
            <TooltipContent>
              托管任务默认时点按账号错峰（选股 15:30~15:44、情报 15:40~15:54、候选跟踪 15:45~15:59），不同账号分钟不同属正常
            </TooltipContent>
          </Tooltip>
          <template v-else>{{ nextRunText }}</template>
        </dd>
      </div>
      <div class="job-detail__fact">
        <dt>上次结果</dt>
        <dd class="job-detail__last">
          <UiBadge :variant="healthVariant" dot>{{ lastLabel }}</UiBadge>
          <span class="mono dim">{{ job.last_run_at || '—' }}</span>
        </dd>
      </div>
      <div class="job-detail__fact">
        <dt>{{ bound ? '推送企微' : '任务 id' }}</dt>
        <dd v-if="bound">{{ job.config?.push_wecom === false ? '关' : '开' }}</dd>
        <dd v-else class="mono dim" :title="job.id">{{ job.id }}</dd>
      </div>
    </dl>

    <JobScheduleInline
      :key="job.id"
      :job="job"
      :busy="busy"
      @save="(payload) => emit('saveSchedule', payload)"
    />

    <JobRecentRunsPanel :key="job.id" ref="runsRef" :job-id="job.id" />
  </section>
</template>

<style scoped>
.job-detail {
  display: flex;
  flex: 1 1 auto;
  flex-direction: column;
  gap: var(--gap-4);
  width: 100%;
  min-width: 0;
  min-height: 0;
  overscroll-behavior: contain;
}

.job-detail__head {
  display: flex;
  flex-shrink: 0;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-3);
}

.job-detail__lead {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.job-detail__title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.job-detail__title {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--fs-hero);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.job-detail__sub {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-3);
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.job-detail__cron {
  padding: 1px 6px;
  border-radius: var(--radius-xs);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-kicker);
}

.job-detail__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.job-detail__facts {
  display: grid;
  flex-shrink: 0;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--gap-2);
  margin: 0;
}

.job-detail__fact {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: var(--gap-3) var(--gap-4);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.job-detail__fact dt {
  color: var(--text-tertiary);
  font-size: var(--fs-kicker);
  font-weight: 500;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.job-detail__fact dd {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--fs-ui);
  font-weight: 500;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.job-detail__last {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}

.dim {
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-weight: 400;
}

@media (max-width: 720px) {
  .job-detail__facts {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .job-detail__actions > :deep(button) {
    min-height: 36px;
  }
}
</style>
