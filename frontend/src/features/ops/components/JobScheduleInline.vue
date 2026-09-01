<script setup lang="ts">
/**
 * 任务详情里的就地改时点。
 *
 * 为什么必须就地：战法/技能绑定的任务在这里原本**只读**，改一个 15:30 → 15:40
 * 要跳 `/quant?tab=engines&strategy=slug`、开战法弹窗、找到「调度」那一栏、
 * 保存、再回来确认——多 4~6 步，而且换了一套长得完全不一样的表单。
 *
 * 为什么改的是**结构化档位**而不是裸 cron：`screen:{slug}` 的 cron 在每次启动时
 * 由 `ensure_managed_screen_jobs` 从 `config.schedule` 重新算出来覆盖。只 PATCH
 * `cron` 的话，用户改完当场看着是对的，重启一次就被打回去——比不让改更糟。
 * 所以这里同时写回 `cron` 与 `config.schedule`，与战法弹窗保存的是同一份东西。
 */
import { computed, reactive, ref, watch } from 'vue'

import type { Job } from '@/shared/types/quant'

import {
  TENANT_CRON_FLOOR_SECONDS,
  TRADING_INTERVALS,
  composeTradingCron,
  cronIntervalSeconds,
  cronTooFrequentTitle,
  defaultTradingSchedule,
  describeCronRuns,
  nearestTradingInterval,
  type TradingSchedule,
  type TradingScheduleMode,
} from '../lib/cronPreview'

const props = defineProps<{
  job: Job
  busy: boolean
}>()

const emit = defineEmits<{
  /** 交给 JobsTab 去打同一个 `PATCH /api/jobs/{id}`（本机任务与绑定任务同一条路） */
  save: [payload: { cron: string; config: Record<string, unknown> }]
}>()

const HOURS = Array.from({ length: 24 }, (_, i) => i)
const MINUTES = Array.from({ length: 60 }, (_, i) => i)

const open = ref(false)
const draft = reactive<TradingSchedule>(defaultTradingSchedule())

const composed = computed(() => composeTradingCron(draft))
const nextRuns = computed(() => (composed.value ? describeCronRuns(composed.value, { count: 3 }) : []))
const intervalSeconds = computed(() =>
  composed.value ? cronIntervalSeconds(composed.value) : null,
)
const tooFrequent = computed(
  () => intervalSeconds.value !== null && intervalSeconds.value < TENANT_CRON_FLOOR_SECONDS,
)
const dirty = computed(() => composed.value !== (props.job.cron || ''))

watch(
  () => [props.job.id, props.job.cron] as const,
  () => {
    hydrate()
  },
  { immediate: true },
)

/** 优先读 `config.schedule`（权威），读不到再从 cron 反推一个够用的档位。 */
function hydrate(): void {
  Object.assign(draft, defaultTradingSchedule())
  const saved = props.job.config?.schedule
  if (saved && typeof saved === 'object') {
    const row = saved as Record<string, unknown>
    Object.assign(draft, {
      mode: normalizeMode(row.mode),
      run_hour: pick(row.run_hour, draft.run_hour),
      run_minute: pick(row.run_minute, draft.run_minute),
      interval_minutes: nearestTradingInterval(pick(row.interval_minutes, draft.interval_minutes)),
      window_start_hour: pick(row.window_start_hour, draft.window_start_hour),
      window_start_minute: pick(row.window_start_minute, draft.window_start_minute),
      window_end_hour: pick(row.window_end_hour, draft.window_end_hour),
      window_end_minute: pick(row.window_end_minute, draft.window_end_minute),
    })
    if (composeTradingCron(draft) === (props.job.cron || '')) return
  }
  fromCron(props.job.cron || '')
}

function normalizeMode(raw: unknown): TradingScheduleMode {
  const text = String(raw || '')
  if (text === 'once' || text === 'interval' || text === 'off') return text
  return 'once'
}

function pick(raw: unknown, fallback: number): number {
  const value = Number(raw)
  return Number.isFinite(value) ? value : fallback
}

/**
 * cron → 档位。只认本仓真会出现的两种形状；认不出来就停在「仅手动」并让
 * 上层显示原始 cron——猜一个像模像样的档位再存回去，等于替用户改了调度。
 */
function fromCron(cron: string): void {
  const text = cron.trim().toLowerCase().replace('mon-fri', '1-5')
  if (!text) {
    draft.mode = 'off'
    return
  }
  const once = /^(\d{1,2}) (\d{1,2}) \* \* (1-5|\*)$/.exec(text)
  if (once) {
    draft.mode = 'once'
    draft.run_minute = Number(once[1])
    draft.run_hour = Number(once[2])
    return
  }
  const interval = /^\*\/(\d{1,2}) (\d{1,2})-(\d{1,2}) \* \* (1-5|\*)$/.exec(text)
  if (interval) {
    draft.mode = 'interval'
    draft.interval_minutes = nearestTradingInterval(Number(interval[1]))
    draft.window_start_hour = Number(interval[2])
    draft.window_end_hour = Number(interval[3])
    return
  }
  draft.mode = 'off'
}

function cancel(): void {
  hydrate()
  open.value = false
}

function submit(): void {
  const config = { ...(props.job.config || {}) }
  // schedule 与 cron 一起写：只写 cron 会在下次 ensure 时被 config.schedule 覆盖回去
  config.schedule = { ...draft }
  emit('save', { cron: composed.value, config })
  open.value = false
}

defineExpose({ open })
</script>

<template>
  <section class="job-sched" aria-label="就地改时点">
    <header class="job-sched__bar">
      <span class="job-sched__now">
        <span class="job-sched__label">调度</span>
        <span class="mono">{{ job.cron || '仅手动' }}</span>
      </span>
      <el-button v-if="!open" size="small" :disabled="busy" @click="open = true">
        改时点
      </el-button>
    </header>

    <div v-if="open" class="job-sched__form">
      <el-radio-group v-model="draft.mode" size="small">
        <el-radio-button value="off">仅手动</el-radio-button>
        <el-radio-button value="once">每交易日定点</el-radio-button>
        <el-radio-button value="interval">盘中间隔</el-radio-button>
      </el-radio-group>

      <div v-if="draft.mode === 'once'" class="job-sched__row">
        <span class="job-sched__label">时点</span>
        <el-select v-model="draft.run_hour" size="small" class="job-sched__pick">
          <el-option v-for="h in HOURS" :key="`h${h}`" :label="String(h).padStart(2, '0')" :value="h" />
        </el-select>
        <span class="job-sched__sep">:</span>
        <el-select v-model="draft.run_minute" size="small" class="job-sched__pick">
          <el-option v-for="m in MINUTES" :key="`m${m}`" :label="String(m).padStart(2, '0')" :value="m" />
        </el-select>
        <span class="job-sched__hint">只在交易日（周一至周五）触发</span>
      </div>

      <div v-else-if="draft.mode === 'interval'" class="job-sched__row">
        <span class="job-sched__label">每</span>
        <el-select v-model="draft.interval_minutes" size="small" class="job-sched__pick">
          <el-option v-for="n in TRADING_INTERVALS" :key="`i${n}`" :label="`${n} 分钟`" :value="n" />
        </el-select>
        <span class="job-sched__label">时段</span>
        <el-select v-model="draft.window_start_hour" size="small" class="job-sched__pick">
          <el-option v-for="h in HOURS" :key="`ws${h}`" :label="String(h).padStart(2, '0')" :value="h" />
        </el-select>
        <span class="job-sched__sep">—</span>
        <el-select v-model="draft.window_end_hour" size="small" class="job-sched__pick">
          <el-option v-for="h in HOURS" :key="`we${h}`" :label="String(h).padStart(2, '0')" :value="h" />
        </el-select>
        <span class="job-sched__hint">点</span>
      </div>

      <p class="job-sched__preview">
        <span class="job-sched__label">cron</span>
        <span class="mono">{{ composed || '（不定时，只能手动跑）' }}</span>
      </p>
      <p v-if="composed" class="job-sched__preview">
        <span class="job-sched__label">接下来</span>
        <span v-if="nextRuns && nextRuns.length" class="mono">{{ nextRuns.join(' · ') }}</span>
        <span v-else class="job-sched__warn">无法预览这个表达式</span>
      </p>

      <el-alert
        v-if="tooFrequent"
        type="warning"
        show-icon
        :closable="false"
        :title="cronTooFrequentTitle(intervalSeconds)"
      />

      <div class="job-sched__actions">
        <el-button size="small" @click="cancel">取消</el-button>
      <el-button
        size="small"
        type="primary"
        :disabled="busy || !dirty"
        @click="submit"
      >
        保存时点
      </el-button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.job-sched {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  padding: var(--gap-2);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet-alt);
  flex-shrink: 0;
}

.job-sched__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-2);
  min-width: 0;
}

.job-sched__now {
  display: flex;
  align-items: baseline;
  gap: var(--gap-1);
  min-width: 0;
  overflow: hidden;
}

.job-sched__form {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
}

.job-sched__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-1);
}

.job-sched__pick {
  width: 6rem;
}

.job-sched__label {
  font-size: var(--fs-aux);
  color: var(--mist);
}

.job-sched__sep {
  color: var(--mist);
}

.job-sched__hint {
  font-size: var(--fs-aux);
  color: var(--mist);
}

.job-sched__preview {
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: var(--gap-1);
  flex-wrap: wrap;
  font-size: var(--fs-aux);
}

.job-sched__warn {
  color: var(--warn);
  font-size: var(--fs-aux);
}

.job-sched__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--gap-1);
}

.mono {
  font-family: var(--mono);
  font-size: var(--fs-body);
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
