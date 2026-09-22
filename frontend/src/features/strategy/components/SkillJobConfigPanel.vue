<script setup lang="ts">
/**
 * 技能详情「定时」配置：定点/间隔 + 推送企微 + LLM 供应商。
 */
import { computed, onScopeDispose, ref, watch } from 'vue'
import { toast } from 'vue-sonner'

import { getProviders } from '@/shared/api/quant'
import { getSkillJob, upsertSkillJob } from '@/shared/api/quant_ops'
import PageBusy from '@/shared/components/ui/PageBusy.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Switch } from '@/shared/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
import { toErrorMessage } from '@/shared/lib/errors'
import type { LlmProvider, SkillJob } from '@/shared/types/quant'

import StrategyField from './StrategyField.vue'

type ScheduleMode = 'off' | 'once' | 'interval'

const props = defineProps<{
  slug: string
}>()

const emit = defineEmits<{
  saved: [job: SkillJob]
}>()

const HOUR_OPTS = Array.from({ length: 24 }, (_, i) => i)
const MINUTE_OPTS = Array.from({ length: 12 }, (_, i) => i * 5)
const INTERVAL_OPTS = [5, 10, 15, 30, 60]

const loading = ref(false)
const saving = ref(false)
const providers = ref<LlmProvider[]>([])
const scheduleEnabled = ref(false)
const scheduleMode = ref<'once' | 'interval'>('once')
const pushWecom = ref(true)
const provider = ref('')
const runHour = ref(15)
const runMinute = ref(30)
const intervalMinutes = ref(10)
const windowStartHour = ref(9)
const windowStartMinute = ref(30)
const windowEndHour = ref(14)
const windowEndMinute = ref(50)
const nextRuns = ref<string[]>([])
let loadToken = 0

onScopeDispose(() => {
  loadToken += 1
})

const previewRuns = computed(() => {
  if (!scheduleEnabled.value) return [] as string[]
  return buildPreview(
    scheduleMode.value,
    runHour.value,
    runMinute.value,
    intervalMinutes.value,
    windowStartHour.value,
    windowStartMinute.value,
    windowEndHour.value,
    windowEndMinute.value,
  )
})


const providerOptions = computed(() =>
  providers.value.map((item) => ({
    value: item.name,
    label: item.is_default ? `${item.name}（默认）` : item.name,
  })),
)

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function buildPreview(
  mode: 'once' | 'interval',
  hour: number,
  minute: number,
  every: number,
  startH: number,
  startM: number,
  endH: number,
  endM: number,
): string[] {
  const now = new Date()
  const day = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
  if (mode === 'once') return [`${day} ${pad(hour)}:${pad(minute)}`]
  const start = startH * 60 + startM
  const end = endH * 60 + endM
  const out: string[] = []
  for (let t = start; t <= end && out.length < 5; t += every) {
    out.push(`${day} ${pad(Math.floor(t / 60))}:${pad(t % 60)}`)
  }
  return out
}

function hydrate(job: SkillJob): void {
  if (!job.bound) {
    scheduleEnabled.value = false
    pushWecom.value = true
    provider.value = ''
    nextRuns.value = []
    return
  }
  const cfg = job.config ?? {}
  const schedule = cfg.schedule
  if (schedule?.mode === 'once' || schedule?.mode === 'interval') {
    scheduleEnabled.value = true
    scheduleMode.value = schedule.mode
    runHour.value = Number(schedule.run_hour ?? 15)
    runMinute.value = Number(schedule.run_minute ?? 30)
    intervalMinutes.value = Number(schedule.interval_minutes ?? 10)
    windowStartHour.value = Number(schedule.window_start_hour ?? 9)
    windowStartMinute.value = Number(schedule.window_start_minute ?? 30)
    windowEndHour.value = Number(schedule.window_end_hour ?? 14)
    windowEndMinute.value = Number(schedule.window_end_minute ?? 50)
  } else if (job.enabled && job.cron) {
    scheduleEnabled.value = true
  }
  pushWecom.value = cfg.push_wecom !== false
  provider.value = String(cfg.provider || '')
  nextRuns.value = job.next_runs ?? []
}

async function load(): Promise<void> {
  const token = ++loadToken
  loading.value = true
  try {
    const [job, list] = await Promise.all([getSkillJob(props.slug), getProviders()])
    if (token !== loadToken) return
    providers.value = list
    if (!provider.value) {
      provider.value = list.find((p) => p.is_default)?.name || list[0]?.name || ''
    }
    hydrate(job)
  } catch (caught: unknown) {
    if (token !== loadToken) return
    toast.error(toErrorMessage(caught, '读取定时失败'))
  } finally {
    if (token === loadToken) loading.value = false
  }
}

async function save(): Promise<void> {
  const mode: ScheduleMode = scheduleEnabled.value ? scheduleMode.value : 'off'
  if (mode !== 'off' && !provider.value.trim()) {
    toast.warning('开启定时必须选择 LLM 供应商')
    return
  }
  saving.value = true
  try {
    const job = await upsertSkillJob(props.slug, {
      schedule_mode: mode,
      run_hour: runHour.value,
      run_minute: runMinute.value,
      interval_minutes: intervalMinutes.value,
      window_start_hour: windowStartHour.value,
      window_start_minute: windowStartMinute.value,
      window_end_hour: windowEndHour.value,
      window_end_minute: windowEndMinute.value,
      provider: provider.value.trim(),
      push_wecom: pushWecom.value,
      enabled: mode !== 'off',
    })
    nextRuns.value = job.next_runs?.length ? job.next_runs : previewRuns.value
    toast.success(mode === 'off' ? '已关闭定时并移除任务' : '已保存')
    emit('saved', job)
  } catch (caught: unknown) {
    toast.error(toErrorMessage(caught, '保存失败'))
  } finally {
    saving.value = false
  }
}

watch(
  () => props.slug,
  () => {
    void load()
  },
  { immediate: true },
)

defineExpose({ save, saving, load })
</script>

<template>
  <div class="skill-job-config relative">
    <PageBusy :busy="loading" overlay />
    <div class="cfg-form">
      <StrategyField label="定时运行" inline>
        <Switch v-model="scheduleEnabled" aria-label="定时运行" />
      </StrategyField>

      <template v-if="scheduleEnabled">
        <StrategyField label="推送企微" inline>
          <div class="field-row">
            <Switch v-model="pushWecom" aria-label="推送企微" />
            <span class="dim hint">开启后定时任务结束自动推送（有选股结果用选股模板）</span>
          </div>
        </StrategyField>

        <StrategyField label="LLM" inline>
          <Select v-model="provider">
            <SelectTrigger class="w-full" aria-label="选择供应商">
              <SelectValue placeholder="选择供应商" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="item in providerOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </SelectItem>
            </SelectContent>
          </Select>
        </StrategyField>

        <StrategyField label="方式" inline>
          <ToggleGroup
            type="single"
            variant="outline"
            :model-value="scheduleMode"
            aria-label="定时方式"
            @update:model-value="(value) => (scheduleMode = value as 'once' | 'interval')"
          >
            <ToggleGroupItem value="once">定点</ToggleGroupItem>
            <ToggleGroupItem value="interval">间隔</ToggleGroupItem>
          </ToggleGroup>
        </StrategyField>

        <StrategyField v-if="scheduleMode === 'once'" label="交易日" inline>
          <div class="time-row">
            <Select v-model="runHour">
              <SelectTrigger size="sm" class="time-select" aria-label="小时">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="h in HOUR_OPTS" :key="h" :value="h">{{ pad(h) }}</SelectItem>
              </SelectContent>
            </Select>
            <span class="time-sep">:</span>
            <Select v-model="runMinute">
              <SelectTrigger size="sm" class="time-select" aria-label="分钟">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="m in MINUTE_OPTS" :key="m" :value="m">{{ pad(m) }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </StrategyField>

        <template v-else>
          <StrategyField label="时段" inline>
            <div class="time-row">
              <Select v-model="windowStartHour">
                <SelectTrigger size="sm" class="time-select" aria-label="起始小时">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="h in HOUR_OPTS" :key="`s${h}`" :value="h">{{ pad(h) }}</SelectItem>
                </SelectContent>
              </Select>
              <span class="time-sep">:</span>
              <Select v-model="windowStartMinute">
                <SelectTrigger size="sm" class="time-select" aria-label="起始分钟">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="m in MINUTE_OPTS" :key="`sm${m}`" :value="m">{{ pad(m) }}</SelectItem>
                </SelectContent>
              </Select>
              <span class="time-sep">–</span>
              <Select v-model="windowEndHour">
                <SelectTrigger size="sm" class="time-select" aria-label="结束小时">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="h in HOUR_OPTS" :key="`e${h}`" :value="h">{{ pad(h) }}</SelectItem>
                </SelectContent>
              </Select>
              <span class="time-sep">:</span>
              <Select v-model="windowEndMinute">
                <SelectTrigger size="sm" class="time-select" aria-label="结束分钟">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="m in MINUTE_OPTS" :key="`em${m}`" :value="m">{{ pad(m) }}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </StrategyField>
          <StrategyField label="间隔" inline>
            <Select v-model="intervalMinutes">
              <SelectTrigger size="sm" class="time-select wide" aria-label="间隔分钟">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="m in INTERVAL_OPTS" :key="m" :value="m">{{ m }} 分钟</SelectItem>
              </SelectContent>
            </Select>
          </StrategyField>
        </template>

        <StrategyField label="预览" inline>
          <div class="preview">
            <span v-for="slot in nextRuns.length ? nextRuns : previewRuns" :key="slot" class="mono">
              {{ slot }}
            </span>
            <span v-if="!(nextRuns.length || previewRuns.length)" class="dim">—</span>
          </div>
        </StrategyField>
      </template>
    </div>
  </div>
</template>

<style scoped>
.cfg-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.dim {
  color: var(--mist);
  font-size: 0.76rem;
}
.field-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}
.hint {
  margin-left: 0.5rem;
}
.time-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
}
.time-select {
  width: 4.5rem;
}
.time-select.wide {
  width: 7rem;
}
.time-sep {
  color: var(--mist);
}
.preview {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.75rem;
}
.mono {
  font-family: var(--mono);
  font-size: var(--fs-aux);
}
</style>
