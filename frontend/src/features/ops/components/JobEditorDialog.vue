<script setup lang="ts">
/**
 * 本机定时任务新建/编辑弹窗。战法绑定任务不进此表单。
 *
 * 两条硬规矩：
 * 1. **默认要能触发**。此前调度预设默认「仅手动」，用户点「新建定时任务」、
 *    一路默认下去，得到的是一条永远不会自己跑的任务，而页面上什么都不说。
 *    现在默认落在盘后 15:30，「仅手动」降为要自己选的显式选项。
 * 2. **错误只有一处**。以前校验错误在弹窗里、后端错误在弹窗背后的页面 alert 上，
 *    提交失败时用户盯着的那半屏什么都没有。现在两类都落在这张表单顶部。
 */
import { computed, reactive, ref, watch } from 'vue'

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/shared/components/ui/accordion'
import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Input } from '@/shared/components/ui/input'
import { Label } from '@/shared/components/ui/label'
import {
  NumberField,
  NumberFieldContent,
  NumberFieldDecrement,
  NumberFieldIncrement,
  NumberFieldInput,
} from '@/shared/components/ui/number-field'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { Switch } from '@/shared/components/ui/switch'
import { Textarea } from '@/shared/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/shared/components/ui/tooltip'
import type { Job, JobKind, JobQuota, LlmProvider, Skill, StrategyInfo } from '@/shared/types/quant'

import CodeEditor from './CodeEditor.vue'
import { isReservedStrategyJobName } from '../composables/jobOwnership'
import { cnStrategyName, traderJobName } from '../composables/opsLabels'
import {
  TENANT_CRON_FLOOR_SECONDS,
  cronIntervalSeconds,
  cronTooFrequentTitle,
  describeCronRuns,
  normalizeCronWeekdays,
} from '../lib/cronPreview'

const props = defineProps<{
  modelValue: boolean
  editing: Job | null
  strategies: StrategyInfo[]
  skills: Skill[]
  providers: LlmProvider[]
  busy?: boolean
  /** 后端写口返回的 4xx 原文（403 / 422 / 429）。收在这张表单里显示。 */
  submitError?: string
  quota?: JobQuota | null
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

/**
 * 调度预设 → cron。写 `mon-fri` 而不是 `1-5`：APScheduler 的 0 是周一，
 * `1-5` 落到它手里是周二至周六（后端对历史写法有兼容改写，新写的不该依赖它）。
 */
const CRON_PRESETS: Record<string, string> = {
  manual: '',
  post1530: '30 15 * * mon-fri',
  intraday5: '*/5 9-14 * * mon-fri',
  post1535: '35 15 * * mon-fri',
  eod1600: '0 16 * * mon-fri',
}

/** 新建时的默认档：盘后 15:30，收盘后、日终同步前，和托管选股同一个点。 */
const DEFAULT_PRESET = 'post1530'

const formError = ref('')
const baseConfig = ref<Record<string, unknown>>({})
const form = reactive({
  name: '',
  kind: 'sync' as JobKind,
  cron: CRON_PRESETS[DEFAULT_PRESET],
  cronPreset: DEFAULT_PRESET,
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

/** 校验错误与后端 4xx 原文合成一处，谁后来谁说话。 */
const shownError = computed(() => formError.value || props.submitError || '')

/**
 * 下拉选项文案一律中文。后端的 `name` 有时是空的、有时干脆就是 slug 本身
 * （`sanyuan-tail-v1`），那样英文编码就直接摆到用户眼前了；value 仍然是 slug。
 */
const strategyOptions = computed(() =>
  props.strategies.map((s) => ({ slug: s.slug, label: cnStrategyName(s.name, s.slug) })),
)

const skillOptions = computed(() =>
  props.skills.map((s) => ({ slug: s.slug, label: cnStrategyName(s.name, s.slug) })),
)

/** 接下来 3 次触发。null = 这条表达式我们算不出来，就直说，不编时间。 */
const upcoming = computed(() => {
  const cron = currentCron()
  if (!cron) return null
  return describeCronRuns(cron, { count: 3 })
})

const intervalSeconds = computed(() => {
  const cron = currentCron()
  return cron ? cronIntervalSeconds(cron) : null
})

const tooFrequent = computed(
  () => intervalSeconds.value !== null && intervalSeconds.value < TENANT_CRON_FLOOR_SECONDS,
)

/** 当前生效的 cron：自定义档读输入框，其余读预设表。 */
function currentCron(): string {
  if (form.cronPreset === 'custom') return form.cron.trim()
  return CRON_PRESETS[form.cronPreset] ?? ''
}

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
    cron: CRON_PRESETS[DEFAULT_PRESET],
    cronPreset: DEFAULT_PRESET,
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
  // 归一化后再比：库里既有历史的 `1-5`，也有托管任务写的 `mon-fri`
  const cron = normalizeCronWeekdays(job.cron || '')
  const hit = Object.entries(CRON_PRESETS).find(
    ([name, expression]) => Boolean(expression) && expression === cron && name !== 'manual',
  )
  if (!job.cron) form.cronPreset = 'manual'
  else if (hit) form.cronPreset = hit[0]
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
  if (form.cronPreset === 'custom') return
  form.cron = CRON_PRESETS[form.cronPreset] ?? ''
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
    formError.value = '这个名字留给战法和技能自己建的任务。这两类由它们自己管，请到对应详情页开定时与推送'
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
  if (form.cronPreset === 'custom' && !form.cron.trim()) {
    formError.value = '选了自定义 cron 就得写一条，留空等于永不触发'
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
  <Dialog v-model:open="open">
    <DialogContent class="w-[min(40rem,96vw)] max-w-none gap-[var(--gap-3)] rounded-[var(--radius)] p-[var(--gap-3)] sm:max-w-none">
      <DialogHeader class="gap-1 border-b border-line pb-[var(--gap-3)] text-left">
        <DialogTitle>{{ title }}</DialogTitle>
      </DialogHeader>

      <div class="min-w-0 max-h-[calc(100dvh-var(--ctl-h)*5)] overflow-auto overscroll-contain">
        <!-- 唯一的错误位：校验与后端 4xx 都落这儿 -->
        <Alert v-if="shownError" variant="destructive" class="form-alert" data-testid="job-form-error">
          <AlertTitle class="line-clamp-none">{{ shownError }}</AlertTitle>
        </Alert>
        <p v-if="!isEdit && quota && !quota.unlimited" class="form-quota">
          自建额度 {{ quota.used }} / {{ quota.limit }}
          <span class="form-quota__dim">（系统托管任务 {{ quota.managed }} 条，不占额度）</span>
        </p>
        <form class="job-editor-form" @submit.prevent="onSubmit">
          <div class="job-field">
            <Label for="job-name" class="job-field__label">名称</Label>
            <Input v-if="isEdit" id="job-name" :model-value="traderJobName(form.kind, form.name)" disabled />
            <Input v-else id="job-name" v-model.trim="form.name" placeholder="例如：日终同步" />
          </div>
          <div class="job-field">
            <Label for="job-kind" class="job-field__label">类型</Label>
            <Select v-model="form.kind" :disabled="isEdit">
              <SelectTrigger id="job-kind" class="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="sync">同步行情</SelectItem>
                <SelectItem value="screen">选股</SelectItem>
                <SelectItem value="outcome">候选T+N</SelectItem>
                <SelectItem value="backtest">回测</SelectItem>
                <SelectItem value="skill">技能模式</SelectItem>
                <SelectItem value="notify">企微推送</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="job-field full-span">
            <Label for="job-cron-preset" class="job-field__label">调度预设</Label>
            <Select v-model="form.cronPreset" @update:model-value="applyCronPreset">
              <SelectTrigger id="job-cron-preset" class="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="post1530">盘后 15:30（推荐）</SelectItem>
                <SelectItem value="post1535">工作日 15:35</SelectItem>
                <SelectItem value="eod1600">工作日 16:00</SelectItem>
                <SelectItem value="intraday5">盘中每 5 分钟</SelectItem>
                <SelectItem value="custom">自定义 cron</SelectItem>
                <SelectItem value="manual">仅手动（永不自动触发）</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div v-if="form.cronPreset === 'custom'" class="job-field full-span">
            <Label for="job-cron" class="job-field__label">cron</Label>
            <Textarea
              id="job-cron"
              v-model.trim="form.cron"
              :rows="2"
              placeholder="可单行，也可多行/分号填多个时间点，例：&#10;50 14 * * mon-fri&#10;30 15 * * mon-fri"
            />
          </div>
          <div class="job-field full-span">
            <span class="job-field__label">接下来 3 次</span>
            <div class="cron-preview">
              <template v-if="form.cronPreset === 'manual'">
                <Tooltip>
                  <TooltipTrigger as-child>
                    <span class="cron-preview__muted cursor-default">仅手动</span>
                  </TooltipTrigger>
                  <TooltipContent>不会自动触发，只能在任务列表里点「立即执行」</TooltipContent>
                </Tooltip>
              </template>
              <template v-else-if="upcoming && upcoming.length">
                <span v-for="run in upcoming" :key="run" class="cron-preview__slot mono">{{ run }}</span>
              </template>
              <Tooltip v-else>
                <TooltipTrigger as-child>
                  <span class="cron-preview__bad cursor-default">无法预览这条 cron</span>
                </TooltipTrigger>
                <TooltipContent>本机只解析 5 段常规写法；保存时后端会再校验一次</TooltipContent>
              </Tooltip>
            </div>
          </div>
          <Alert v-if="tooFrequent" variant="destructive" class="full-span">
            <AlertTitle class="line-clamp-none">{{ cronTooFrequentTitle(intervalSeconds) }}</AlertTitle>
          </Alert>

          <template v-if="form.kind === 'sync'">
            <div class="job-field">
              <Label for="job-sync-mode" class="job-field__label">模式</Label>
              <Select v-model="form.syncMode">
                <SelectTrigger id="job-sync-mode" class="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="full">增量 + 当日补数</SelectItem>
                  <SelectItem value="today_refresh">仅重刷当日</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div class="job-field">
              <Label for="job-workers" class="job-field__label">并发数</Label>
              <NumberField v-model="form.workers" :min="1" :max="16">
                <NumberFieldContent>
                  <NumberFieldInput id="job-workers" />
                  <NumberFieldIncrement />
                  <NumberFieldDecrement />
                </NumberFieldContent>
              </NumberField>
            </div>
            <div class="job-field">
              <Label for="job-force" class="job-field__label">强制重拉</Label>
              <Switch id="job-force" v-model="form.force" />
            </div>
          </template>

          <template v-if="form.kind === 'screen'">
            <div class="job-field full-span">
              <Label for="job-strategy" class="job-field__label">战法</Label>
              <Select v-model="form.strategy">
                <SelectTrigger id="job-strategy" class="w-full" aria-label="选择战法">
                  <SelectValue placeholder="选择战法" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="s in strategyOptions" :key="s.slug" :value="s.slug">
                    {{ s.label }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div class="job-field">
              <Label for="job-top-n" class="job-field__label">选取数量</Label>
              <NumberField v-model="form.topN" :min="0" :max="200">
                <NumberFieldContent>
                  <NumberFieldInput id="job-top-n" />
                  <NumberFieldIncrement />
                  <NumberFieldDecrement />
                </NumberFieldContent>
              </NumberField>
            </div>
            <div class="job-field">
              <Label for="job-record-candidates" class="job-field__label">写入候选池</Label>
              <Switch id="job-record-candidates" v-model="form.recordCandidates" />
            </div>
            <div class="job-field">
              <Label for="job-use-ai-pick" class="job-field__label">AI 精选</Label>
              <Switch id="job-use-ai-pick" v-model="form.useAiPick" />
            </div>
            <div v-if="form.useAiPick" class="job-field full-span">
              <Label for="job-provider-screen" class="job-field__label">LLM 供应商</Label>
              <Select v-model="form.provider">
                <SelectTrigger id="job-provider-screen" class="w-full" aria-label="LLM 供应商">
                  <SelectValue placeholder="默认供应商可留空" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="p in providers" :key="p.id" :value="p.id">
                    {{ p.name }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </template>

          <template v-if="form.kind === 'skill'">
            <div class="job-field full-span">
              <Label for="job-skill" class="job-field__label">技能</Label>
              <Select v-model="form.skill">
                <SelectTrigger id="job-skill" class="w-full" aria-label="选择技能">
                  <SelectValue placeholder="选择技能" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="s in skillOptions" :key="s.slug" :value="s.slug">
                    {{ s.label }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div class="job-field full-span">
              <Label for="job-provider-skill" class="job-field__label">LLM 供应商</Label>
              <Select v-model="form.provider">
                <SelectTrigger id="job-provider-skill" class="w-full" aria-label="选择供应商">
                  <SelectValue placeholder="选择供应商" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="p in providers" :key="p.id" :value="p.id">
                    {{ p.name }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </template>

          <template v-if="form.kind === 'notify'">
            <div class="job-field full-span">
              <Label for="job-notify-template" class="job-field__label">推送模板</Label>
              <Select v-model="form.notifyTemplate">
                <SelectTrigger id="job-notify-template" class="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="alerts">触价提醒</SelectItem>
                  <SelectItem value="digest">日终简报</SelectItem>
                  <SelectItem value="screen_last">最近选股结果</SelectItem>
                  <SelectItem value="sync_fail">同步失败告警</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </template>

          <div v-if="form.kind !== 'notify'" class="job-field full-span">
            <Label for="job-push-wecom" class="job-field__label">完成后推企微</Label>
            <Switch id="job-push-wecom" v-model="form.pushWecom" />
          </div>

          <div class="job-field full-span">
            <span class="job-field__label">高级 · 原始 JSON</span>
            <Accordion type="single" collapsible class="w-full">
              <AccordionItem value="raw" class="border-b-0">
                <AccordionTrigger class="py-1 text-mist hover:no-underline">
                  覆盖/追加配置（可选）
                </AccordionTrigger>
                <AccordionContent class="pb-0">
                  <CodeEditor v-model="form.configText" language="json" height="10rem" />
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </div>
        </form>
      </div>

      <DialogFooter class="border-t border-line pt-[var(--gap-3)] sm:justify-end">
        <Button access="read" variant="outline" @click="open = false">取消</Button>
        <Button :disabled="busy" @click="onSubmit">
          {{ isEdit ? '保存' : '创建' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
.form-alert {
  margin-bottom: var(--gap-2);
}
.form-quota {
  margin: 0 0 var(--gap-2);
  font-size: var(--fs-aux);
  font-family: var(--mono);
  color: var(--muted);
}
.form-quota__dim {
  color: var(--mist);
}
.cron-preview {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1) var(--gap-2);
  width: 100%;
  font-size: var(--fs-aux);
}
.cron-preview__slot {
  padding: 0 var(--gap-1);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet-alt);
  color: var(--ink);
}
.cron-preview__muted {
  color: var(--mist);
}
/* 算不出来说算不出来，用告警色而不是灰字：这是要人看见的一句话 */
.cron-preview__bad {
  color: var(--warn);
}
.mono {
  font-family: var(--mono);
}
.job-editor-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); column-gap: var(--gap-3); }
.job-editor-form .full-span { grid-column: 1 / -1; }
/* 一行一项：左 6.5em 右标签槽 + 控件列，和旧 el-form label-position="right" 同尺寸 */
.job-field {
  display: grid;
  grid-template-columns: 6.5em minmax(0, 1fr);
  align-items: center;
  column-gap: var(--gap-2);
  min-width: 0;
  padding-bottom: var(--gap-2);
}
.job-field__label {
  justify-content: flex-end;
  text-align: right;
  color: var(--mist);
  font-size: var(--fs-aux);
  font-weight: 400;
}
</style>
