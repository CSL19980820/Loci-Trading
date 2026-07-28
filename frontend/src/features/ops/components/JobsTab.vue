<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import {
  createJob,
  deleteJob,
  getScheduleStatus,
  runJob,
  updateJob,
} from '@/shared/api/quant'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import Sheet from '@/shared/components/layout/Sheet.vue'
import { confirmDangerous } from '@/shared/lib/confirm'
import type { Job, JobKind, ScheduleStatus } from '@/shared/types/quant'
import { kindLabel, statusLabel } from '../composables/opsLabels'
import { useJobsQuery } from '../composables/useJobsQuery'
import { useOpsFeedback } from '../composables/useOpsFeedback'
import CodeEditor from './CodeEditor.vue'

const emit = defineEmits<{
  'schedule-changed': [schedule: ScheduleStatus | null]
  'enable-recommended-sync': []
  'runs-changed': []
}>()

const { busy, notice, errorText, guard } = useOpsFeedback()

const { jobs, refetch: refetchJobs } = useJobsQuery()
const schedule = ref<ScheduleStatus | null>(null)

const jobFormOpen = ref(false)
const jobEditingId = ref<string | null>(null)
const jobForm = reactive({
  name: '',
  kind: 'sync' as JobKind,
  cron: '',
  cronPreset: 'manual',
  configText: '',
  syncMode: 'full',
  workers: 4,
  force: false,
  strategy: '',
  topN: 3,
  recordCandidates: true,
  useAiPick: false,
  provider: '',
  skill: '',
  notifyTemplate: 'alerts',
  pushWecom: false,
})

const configPlaceholder = computed(() => {
  const samples: Partial<Record<JobKind, string>> = {
    sync: '{"workers": 6}',
    screen: '{"strategy": "qianlong-auction"}',
    backtest: '{"strategy": "qianlong-auction", "start": "2025-01-01", "hold_days": 1}',
    skill: '{"skill": "my-skill", "provider": "openrouter", "context": ["screen"]}',
    notify: '{"template": "alerts"}',
  }
  return samples[jobForm.kind] ?? '{}'
})

async function load(): Promise<void> {
  const [, sc] = await Promise.all([refetchJobs(), getScheduleStatus()])
  schedule.value = sc
  emit('schedule-changed', sc)
}

function applyCronPreset(): void {
  const map: Record<string, string> = {
    manual: '',
    intraday5: '*/5 9-14 * * 1-5',
    post1535: '35 15 * * 1-5',
    eod1600: '0 16 * * 1-5',
  }
  if (jobForm.cronPreset !== 'custom') {
    jobForm.cron = map[jobForm.cronPreset] ?? ''
  }
}

function resetJobForm(): void {
  jobEditingId.value = null
  Object.assign(jobForm, {
    name: '',
    kind: 'sync',
    cron: '',
    cronPreset: 'manual',
    configText: '',
    syncMode: 'full',
    workers: 4,
    force: false,
    strategy: '',
    topN: 3,
    recordCandidates: true,
    useAiPick: false,
    provider: '',
    skill: '',
    notifyTemplate: 'alerts',
    pushWecom: false,
  })
}

function openCreateJob(): void {
  resetJobForm()
  jobFormOpen.value = true
}

function openEditJob(job: Job): void {
  resetJobForm()
  jobEditingId.value = job.id
  jobForm.name = job.name
  jobForm.kind = job.kind
  jobForm.cron = job.cron || ''
  const cron = job.cron || ''
  if (!cron) jobForm.cronPreset = 'manual'
  else if (cron === '*/5 9-14 * * 1-5') jobForm.cronPreset = 'intraday5'
  else if (cron === '35 15 * * 1-5') jobForm.cronPreset = 'post1535'
  else if (cron === '0 16 * * 1-5') jobForm.cronPreset = 'eod1600'
  else jobForm.cronPreset = 'custom'
  const cfg = job.config || {}
  jobForm.syncMode = String(cfg.mode || 'full')
  jobForm.workers = Number(cfg.workers || 4)
  jobForm.force = Boolean(cfg.force)
  jobForm.strategy = String(cfg.strategy || '')
  jobForm.topN = Number(cfg.top_n ?? 3)
  jobForm.recordCandidates = Boolean(cfg.record_candidates)
  jobForm.useAiPick = Boolean(cfg.use_ai_pick)
  jobForm.provider = String(cfg.provider || '')
  jobForm.skill = String(cfg.skill || '')
  jobForm.notifyTemplate = String(cfg.template || 'alerts')
  jobForm.pushWecom = Boolean(cfg.push_wecom)
  jobFormOpen.value = true
}

function buildJobConfig(): Record<string, unknown> {
  let extra: Record<string, unknown> = {}
  if (jobForm.configText.trim()) {
    extra = JSON.parse(jobForm.configText) as Record<string, unknown>
  }
  const base: Record<string, unknown> = { ...extra }
  if (jobForm.kind === 'sync') {
    Object.assign(base, {
      mode: jobForm.syncMode,
      workers: jobForm.workers,
      force: jobForm.force,
      push_wecom: jobForm.pushWecom,
    })
  } else if (jobForm.kind === 'screen') {
    Object.assign(base, {
      strategy: jobForm.strategy,
      top_n: jobForm.topN,
      record_candidates: jobForm.recordCandidates,
      use_ai_pick: jobForm.useAiPick,
      push_wecom: jobForm.pushWecom,
    })
    if (jobForm.provider) base.provider = jobForm.provider
  } else if (jobForm.kind === 'skill') {
    Object.assign(base, {
      skill: jobForm.skill,
      provider: jobForm.provider,
      push_wecom: jobForm.pushWecom,
    })
  } else if (jobForm.kind === 'notify') {
    Object.assign(base, { template: jobForm.notifyTemplate })
  } else if (jobForm.pushWecom) {
    base.push_wecom = true
  }
  return base
}

function nextRunOf(id: string): string {
  const hit = schedule.value?.jobs.find((item) => item.id === id)
  return hit?.next_run_at?.replace('T', ' ').slice(0, 16) ?? '—'
}

async function submitJob(): Promise<void> {
  applyCronPreset()
  let config: Record<string, unknown>
  try {
    config = buildJobConfig()
  } catch {
    errorText.value = '配置不是合法 JSON'
    return
  }
  if (jobEditingId.value) {
    const saved = await guard(() =>
      updateJob(jobEditingId.value!, {
        cron: jobForm.cron,
        config,
      }),
    )
    if (saved) {
      notice.value = `已更新任务 ${saved.name}`
      jobFormOpen.value = false
      resetJobForm()
      await load()
    }
    return
  }
  const created = await guard(() =>
    createJob({ name: jobForm.name, kind: jobForm.kind, cron: jobForm.cron, config }),
  )
  if (created) {
    notice.value = `已创建任务 ${created.name}`
    jobFormOpen.value = false
    resetJobForm()
    await load()
  }
}

async function fire(job: Job): Promise<void> {
  const outcome = await guard(() => runJob(job.id))
  if (outcome) {
    notice.value =
      outcome.status === 'failed' ? `任务失败：${outcome.error ?? ''}` : `任务 ${job.name} 执行成功`
  }
  await load()
  emit('runs-changed')
}

async function toggle(job: Job): Promise<void> {
  await guard(() => updateJob(job.id, { enabled: !job.enabled }))
  await load()
}

async function confirmDropJob(job: Job): Promise<void> {
  if (!(await confirmDangerous(`确定删除定时任务「${job.name}」？`, '确认删除', '删除'))) return
  await guard(() => deleteJob(job.id), `已删除 ${job.name}`)
  await load()
}

defineExpose({ load, schedule })
</script>

<template>
  <Sheet title="定时任务" :chip="jobs.length">
    <template #actions>
      <el-button type="primary" link @click="openCreateJob">新建</el-button>
    </template>

    <div v-if="jobs.length" class="table-wrap">
      <table class="dense">
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>cron</th>
            <th>上次</th>
            <th>下次触发</th>
            <th class="r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.id">
            <td>
              <strong>{{ job.name }}</strong>
              <span v-if="!job.enabled" class="chip muted-chip">停用</span>
            </td>
            <td><span class="tag">{{ kindLabel(job.kind) }}</span></td>
            <td class="mono">{{ job.cron || '手动' }}</td>
            <td>
              <span :class="job.last_status === 'failed' ? 'tone-down' : ''">
                {{ statusLabel(job.last_status) }}
              </span>
              <span class="dim mono"> {{ job.last_run_at }}</span>
            </td>
            <td class="mono dim">{{ nextRunOf(job.id) }}</td>
            <td class="r">
              <el-button size="small" text :disabled="busy" @click="openEditJob(job)">编辑</el-button>
              <el-button size="small" text :disabled="busy" @click="fire(job)">执行</el-button>
              <el-button size="small" text :disabled="busy" @click="toggle(job)">
                {{ job.enabled ? '停用' : '启用' }}
              </el-button>
              <el-button size="small" text :disabled="busy" @click="confirmDropJob(job)">
                删除
              </el-button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      description="尚无任务"
      reason="还没有手动或定时任务"
      eta="可一键启用推荐行情同步，或新建选股/推送任务"
    >
      <el-button type="primary" @click="emit('enable-recommended-sync')">启用推荐同步</el-button>
      <el-button @click="openCreateJob">新建任务</el-button>
    </EmptyState>
    <p v-if="schedule && !schedule.running" class="form-hint">
      调度器未启用（{{ schedule.reason }}）。任务仍可手动执行；线上需在容器设置
      PALACE_ENABLE_SCHEDULER=1。
    </p>
  </Sheet>

  <el-dialog
    v-model="jobFormOpen"
    :title="jobEditingId ? '编辑定时任务' : '新建定时任务'"
    width="40rem"
    destroy-on-close
  >
    <el-form label-position="top" @submit.prevent="submitJob">
      <div class="form-grid">
        <el-form-item label="名称" required>
          <el-input v-model.trim="jobForm.name" :disabled="Boolean(jobEditingId)" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="jobForm.kind" class="full" :disabled="Boolean(jobEditingId)">
            <el-option label="同步行情" value="sync" />
            <el-option label="选股" value="screen" />
            <el-option label="回测" value="backtest" />
            <el-option label="技能模式" value="skill" />
            <el-option label="企微推送" value="notify" />
          </el-select>
        </el-form-item>
        <el-form-item label="调度预设" class="full-span">
          <el-select v-model="jobForm.cronPreset" class="full" @change="applyCronPreset">
            <el-option label="仅手动" value="manual" />
            <el-option label="盘中每 5 分钟" value="intraday5" />
            <el-option label="工作日 15:35" value="post1535" />
            <el-option label="工作日 16:00" value="eod1600" />
            <el-option label="自定义 cron" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="jobForm.cronPreset === 'custom'" label="cron" class="full-span">
          <el-input v-model.trim="jobForm.cron" placeholder="35 15 * * 1-5" />
        </el-form-item>

        <template v-if="jobForm.kind === 'sync'">
          <el-form-item label="模式">
            <el-select v-model="jobForm.syncMode" class="full">
              <el-option label="增量 + 当日补数" value="full" />
              <el-option label="仅重刷当日" value="today_refresh" />
            </el-select>
          </el-form-item>
          <el-form-item label="workers">
            <el-input-number v-model="jobForm.workers" :min="1" :max="16" />
          </el-form-item>
          <el-form-item label="force 重拉">
            <el-switch v-model="jobForm.force" />
          </el-form-item>
        </template>

        <template v-if="jobForm.kind === 'screen'">
          <el-form-item label="战法 slug" class="full-span">
            <el-input v-model.trim="jobForm.strategy" placeholder="qianlong-auction" />
          </el-form-item>
          <el-form-item label="top_n">
            <el-input-number v-model="jobForm.topN" :min="0" :max="200" />
          </el-form-item>
          <el-form-item label="写入候选池">
            <el-switch v-model="jobForm.recordCandidates" />
          </el-form-item>
          <el-form-item label="AI 精选">
            <el-switch v-model="jobForm.useAiPick" />
          </el-form-item>
          <el-form-item v-if="jobForm.useAiPick" label="LLM 供应商" class="full-span">
            <el-input v-model.trim="jobForm.provider" placeholder="默认供应商可留空" />
          </el-form-item>
        </template>

        <template v-if="jobForm.kind === 'skill'">
          <el-form-item label="技能 slug" class="full-span">
            <el-input v-model.trim="jobForm.skill" />
          </el-form-item>
          <el-form-item label="LLM 供应商" class="full-span">
            <el-input v-model.trim="jobForm.provider" />
          </el-form-item>
        </template>

        <template v-if="jobForm.kind === 'notify'">
          <el-form-item label="推送模板" class="full-span">
            <el-select v-model="jobForm.notifyTemplate" class="full">
              <el-option label="触价提醒" value="alerts" />
              <el-option label="日终简报" value="digest" />
              <el-option label="最近选股结果" value="screen_last" />
              <el-option label="同步失败告警" value="sync_fail" />
            </el-select>
          </el-form-item>
        </template>

        <el-form-item v-if="jobForm.kind !== 'notify'" label="完成后推企微" class="full-span">
          <el-switch v-model="jobForm.pushWecom" />
        </el-form-item>

        <el-form-item label="高级 · 原始 JSON" class="full-span">
          <el-collapse>
            <el-collapse-item title="覆盖/追加配置（可选）" name="raw">
              <CodeEditor v-model="jobForm.configText" language="json" height="10rem" />
              <p class="form-hint">{{ configPlaceholder }}</p>
            </el-collapse-item>
          </el-collapse>
        </el-form-item>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="jobFormOpen = false">取消</el-button>
      <el-button type="primary" :disabled="busy" @click="submitJob">
        {{ jobEditingId ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>
