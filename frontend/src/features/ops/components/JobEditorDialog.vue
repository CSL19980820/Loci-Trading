<script setup lang="ts">
/**
 * 本机定时任务新建/编辑弹窗。战法绑定任务不进此表单。
 */
import { computed, reactive, ref, watch } from 'vue'

import CodeEditor from './CodeEditor.vue'
import type { Job, JobKind, LlmProvider, Skill, StrategyInfo } from '@/shared/types/quant'
import { isReservedStrategyJobName } from '../composables/jobOwnership'

const props = defineProps<{
  modelValue: boolean
  editing: Job | null
  strategies: StrategyInfo[]
  skills: Skill[]
  providers: LlmProvider[]
  busy?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [open: boolean]
  submit: [
    payload: {
      id: string | null
      name: string
      kind: JobKind
      cron: string
      config: Record<string, unknown>
    },
  ]
}>()

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const formError = ref('')
const baseConfig = ref<Record<string, unknown>>({})
const form = reactive({
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

const title = computed(() => (props.editing ? '编辑定时任务' : '新建定时任务'))
const isEdit = computed(() => Boolean(props.editing))

watch(
  () => [props.modelValue, props.editing] as const,
  ([opened, job]) => {
    if (!opened) return
    formError.value = ''
    if (job) hydrate(job)
    else reset()
  },
)

function reset(): void {
  baseConfig.value = {}
  Object.assign(form, {
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

function hydrate(job: Job): void {
  reset()
  form.name = job.name
  form.kind = job.kind
  form.cron = job.cron || ''
  const cron = job.cron || ''
  if (!cron) form.cronPreset = 'manual'
  else if (cron === '*/5 9-14 * * 1-5') form.cronPreset = 'intraday5'
  else if (cron === '35 15 * * 1-5') form.cronPreset = 'post1535'
  else if (cron === '0 16 * * 1-5') form.cronPreset = 'eod1600'
  else form.cronPreset = 'custom'
  const cfg = job.config || {}
  baseConfig.value = { ...cfg }
  form.syncMode = String(cfg.mode || 'full')
  form.workers = Number(cfg.workers || 4)
  form.force = Boolean(cfg.force)
  form.strategy = String(cfg.strategy || '')
  form.topN = Number(cfg.top_n ?? 3)
  form.recordCandidates = Boolean(cfg.record_candidates)
  form.useAiPick = Boolean(cfg.use_ai_pick)
  form.provider = String(cfg.provider || '')
  form.skill = String(cfg.skill || '')
  form.notifyTemplate = String(cfg.template || 'alerts')
  form.pushWecom = Boolean(cfg.push_wecom)
}

function applyCronPreset(): void {
  const map: Record<string, string> = {
    manual: '',
    intraday5: '*/5 9-14 * * 1-5',
    post1535: '35 15 * * 1-5',
    eod1600: '0 16 * * 1-5',
  }
  if (form.cronPreset !== 'custom') {
    form.cron = map[form.cronPreset] ?? ''
  }
}

function buildConfig(): Record<string, unknown> {
  let extra: Record<string, unknown> = {}
  if (form.configText.trim()) {
    extra = JSON.parse(form.configText) as Record<string, unknown>
  }
  const base: Record<string, unknown> = { ...baseConfig.value, ...extra }
  if (form.kind === 'sync') {
    Object.assign(base, {
      mode: form.syncMode,
      workers: form.workers,
      force: form.force,
      push_wecom: form.pushWecom,
    })
  } else if (form.kind === 'screen') {
    Object.assign(base, {
      strategy: form.strategy,
      top_n: form.topN,
      record_candidates: form.recordCandidates,
      use_ai_pick: form.useAiPick,
      push_wecom: form.pushWecom,
    })
    if (form.provider) base.provider = form.provider
    else delete base.provider
  } else if (form.kind === 'skill') {
    Object.assign(base, {
      skill: form.skill,
      provider: form.provider,
      push_wecom: form.pushWecom,
    })
  } else if (form.kind === 'notify') {
    Object.assign(base, { template: form.notifyTemplate })
    delete base.push_wecom
  } else if (form.pushWecom) {
    base.push_wecom = true
  } else {
    delete base.push_wecom
  }
  return base
}

function onSubmit(): void {
  formError.value = ''
  applyCronPreset()
  const name = form.name.trim()
  if (!name) {
    formError.value = '请填写名称'
    return
  }
  if (isReservedStrategyJobName(name)) {
    formError.value = 'screen:/skill: 前缀留给战法/技能绑定，请到对应详情开定时与推送'
    return
  }
  if (form.kind === 'screen' && !form.strategy) {
    formError.value = '请选择战法'
    return
  }
  if (form.kind === 'skill' && !form.skill) {
    formError.value = '请选择技能'
    return
  }
  let config: Record<string, unknown>
  try {
    config = buildConfig()
  } catch {
    formError.value = '配置不是合法 JSON'
    return
  }
  emit('submit', {
    id: props.editing?.id ?? null,
    name,
    kind: form.kind,
    cron: form.cron,
    config,
  })
}
</script>

<template>
  <el-dialog v-model="open" :title="title" width="40rem" destroy-on-close>
    <el-alert
      v-if="formError"
      :title="formError"
      type="error"
      show-icon
      closable
      class="form-alert"
      @close="formError = ''"
    />
    <el-form label-position="top" @submit.prevent="onSubmit">
      <div class="form-grid">
        <el-form-item label="名称" required>
          <el-input v-model.trim="form.name" :disabled="isEdit" placeholder="例如：日终同步" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.kind" class="full" :disabled="isEdit">
            <el-option label="同步行情" value="sync" />
            <el-option label="选股" value="screen" />
            <el-option label="候选T+N" value="outcome" />
            <el-option label="回测" value="backtest" />
            <el-option label="技能模式" value="skill" />
            <el-option label="企微推送" value="notify" />
          </el-select>
        </el-form-item>
        <el-form-item label="调度预设" class="full-span">
          <el-select v-model="form.cronPreset" class="full" @change="applyCronPreset">
            <el-option label="仅手动" value="manual" />
            <el-option label="盘中每 5 分钟" value="intraday5" />
            <el-option label="工作日 15:35" value="post1535" />
            <el-option label="工作日 16:00" value="eod1600" />
            <el-option label="自定义 cron" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="form.cronPreset === 'custom'" label="cron" class="full-span">
          <el-input v-model.trim="form.cron" placeholder="35 15 * * 1-5" />
        </el-form-item>

        <template v-if="form.kind === 'sync'">
          <el-form-item label="模式">
            <el-select v-model="form.syncMode" class="full">
              <el-option label="增量 + 当日补数" value="full" />
              <el-option label="仅重刷当日" value="today_refresh" />
            </el-select>
          </el-form-item>
          <el-form-item label="workers">
            <el-input-number v-model="form.workers" :min="1" :max="16" />
          </el-form-item>
          <el-form-item label="force 重拉">
            <el-switch v-model="form.force" />
          </el-form-item>
        </template>

        <template v-if="form.kind === 'screen'">
          <el-form-item label="战法" class="full-span" required>
            <el-select
              v-model="form.strategy"
              class="full"
              filterable
              clearable
              placeholder="选择战法"
            >
              <el-option
                v-for="s in strategies"
                :key="s.slug"
                :label="s.name"
                :value="s.slug"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="top_n">
            <el-input-number v-model="form.topN" :min="0" :max="200" />
          </el-form-item>
          <el-form-item label="写入候选池">
            <el-switch v-model="form.recordCandidates" />
          </el-form-item>
          <el-form-item label="AI 精选">
            <el-switch v-model="form.useAiPick" />
          </el-form-item>
          <el-form-item v-if="form.useAiPick" label="LLM 供应商" class="full-span">
            <el-select
              v-model="form.provider"
              class="full"
              filterable
              clearable
              placeholder="默认供应商可留空"
            >
              <el-option
                v-for="p in providers"
                :key="p.id"
                :label="p.name"
                :value="p.id"
              />
            </el-select>
          </el-form-item>
        </template>

        <template v-if="form.kind === 'skill'">
          <el-form-item label="技能" class="full-span" required>
            <el-select
              v-model="form.skill"
              class="full"
              filterable
              clearable
              placeholder="选择技能"
            >
              <el-option
                v-for="s in skills"
                :key="s.slug"
                :label="s.name"
                :value="s.slug"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="LLM 供应商" class="full-span">
            <el-select
              v-model="form.provider"
              class="full"
              filterable
              clearable
              placeholder="选择供应商"
            >
              <el-option
                v-for="p in providers"
                :key="p.id"
                :label="p.name"
                :value="p.id"
              />
            </el-select>
          </el-form-item>
        </template>

        <template v-if="form.kind === 'notify'">
          <el-form-item label="推送模板" class="full-span">
            <el-select v-model="form.notifyTemplate" class="full">
              <el-option label="触价提醒" value="alerts" />
              <el-option label="日终简报" value="digest" />
              <el-option label="最近选股结果" value="screen_last" />
              <el-option label="同步失败告警" value="sync_fail" />
            </el-select>
          </el-form-item>
        </template>

        <el-form-item v-if="form.kind !== 'notify'" label="完成后推企微" class="full-span">
          <el-switch v-model="form.pushWecom" />
        </el-form-item>

        <el-form-item label="高级 · 原始 JSON" class="full-span">
          <el-collapse>
            <el-collapse-item title="覆盖/追加配置（可选）" name="raw">
              <CodeEditor v-model="form.configText" language="json" height="10rem" />
            </el-collapse-item>
          </el-collapse>
        </el-form-item>
      </div>
    </el-form>
    <template #footer>
      <el-button @click="open = false">取消</el-button>
      <el-button type="primary" :disabled="busy" @click="onSubmit">
        {{ isEdit ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.form-alert {
  margin-bottom: 0.75rem;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.35rem 0.85rem;
}
.full-span {
  grid-column: 1 / -1;
}
.full {
  width: 100%;
}
@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
