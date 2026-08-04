<script setup lang="ts">
/**
 * 技能详情「定时」配置：定点/间隔 + 推送企微 + LLM 供应商。
 */
import { computed, onScopeDispose, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { getProviders } from '@/shared/api/quant'
import { getSkillJob, upsertSkillJob } from '@/shared/api/quant_ops'
import { toErrorMessage } from '@/shared/lib/errors'
import type { LlmProvider, SkillJob } from '@/shared/types/quant'

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
    ElMessage.error(toErrorMessage(caught, '读取定时失败'))
  } finally {
    if (token === loadToken) loading.value = false
  }
}

async function save(): Promise<void> {
  const mode: ScheduleMode = scheduleEnabled.value ? scheduleMode.value : 'off'
  if (mode !== 'off' && !provider.value.trim()) {
    ElMessage.warning('开启定时必须选择 LLM 供应商')
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
    ElMessage.success(mode === 'off' ? '已关闭定时并移除任务' : '已保存')
    emit('saved', job)
  } catch (caught: unknown) {
    ElMessage.error(toErrorMessage(caught, '保存失败'))
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
  <div v-loading="loading" class="skill-job-config">
    <el-form label-position="left" label-width="5.5rem" size="small">
      <el-form-item label="定时运行">
        <el-switch v-model="scheduleEnabled" />
      </el-form-item>

      <template v-if="scheduleEnabled">
        <el-form-item label="推送企微">
          <el-switch v-model="pushWecom" />
          <span class="dim hint">开启后定时任务结束自动推送（有选股结果用选股模板）</span>
        </el-form-item>

        <el-form-item label="LLM">
          <el-select v-model="provider" filterable placeholder="选择供应商" class="full">
            <el-option
              v-for="item in providers"
              :key="item.name"
              :label="item.is_default ? `${item.name}（默认）` : item.name"
              :value="item.name"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="方式">
          <el-radio-group v-model="scheduleMode">
            <el-radio-button value="once">定点</el-radio-button>
            <el-radio-button value="interval">间隔</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="scheduleMode === 'once'" label="交易日">
          <div class="time-row">
            <el-select v-model="runHour" class="time-select">
              <el-option v-for="h in HOUR_OPTS" :key="h" :label="pad(h)" :value="h" />
            </el-select>
            <span class="time-sep">:</span>
            <el-select v-model="runMinute" class="time-select">
              <el-option v-for="m in MINUTE_OPTS" :key="m" :label="pad(m)" :value="m" />
            </el-select>
          </div>
        </el-form-item>

        <template v-else>
          <el-form-item label="时段">
            <div class="time-row">
              <el-select v-model="windowStartHour" class="time-select">
                <el-option v-for="h in HOUR_OPTS" :key="`s${h}`" :label="pad(h)" :value="h" />
              </el-select>
              <span class="time-sep">:</span>
              <el-select v-model="windowStartMinute" class="time-select">
                <el-option v-for="m in MINUTE_OPTS" :key="`sm${m}`" :label="pad(m)" :value="m" />
              </el-select>
              <span class="time-sep">–</span>
              <el-select v-model="windowEndHour" class="time-select">
                <el-option v-for="h in HOUR_OPTS" :key="`e${h}`" :label="pad(h)" :value="h" />
              </el-select>
              <span class="time-sep">:</span>
              <el-select v-model="windowEndMinute" class="time-select">
                <el-option v-for="m in MINUTE_OPTS" :key="`em${m}`" :label="pad(m)" :value="m" />
              </el-select>
            </div>
          </el-form-item>
          <el-form-item label="间隔">
            <el-select v-model="intervalMinutes" class="time-select wide">
              <el-option
                v-for="m in INTERVAL_OPTS"
                :key="m"
                :label="`${m} 分钟`"
                :value="m"
              />
            </el-select>
          </el-form-item>
        </template>

        <el-form-item label="预览">
          <div class="preview">
            <span v-for="slot in nextRuns.length ? nextRuns : previewRuns" :key="slot" class="mono">
              {{ slot }}
            </span>
            <span v-if="!(nextRuns.length || previewRuns.length)" class="dim">—</span>
          </div>
        </el-form-item>
      </template>
    </el-form>
  </div>
</template>

<style scoped>
.full {
  width: 100%;
  max-width: 18rem;
}
.dim {
  color: var(--mist);
  font-size: 0.76rem;
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
  font-family: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 0.8rem;
}
</style>
