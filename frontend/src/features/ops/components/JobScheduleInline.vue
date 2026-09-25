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
import { computed, reactive, watch } from 'vue'
import { TriangleAlert } from '@lucide/vue'

import { Alert, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'
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

const open = defineModel<boolean>('open', { default: false })
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

/*
 * 原生 select 原语只吃字符串值，而档位里的小时/分钟/间隔都是数字。
 * 五个计算代理把「数字模型 ↔ 字符串选项」这一层收在一个地方，
 * 免得每个 `<Select>` 上各写一遍 `Number($event)`。
 */
function numberProxy(key: 'run_hour' | 'run_minute' | 'interval_minutes' | 'window_start_hour' | 'window_end_hour') {
  return computed({
    get: () => String(draft[key]),
    set: (value: string) => {
      draft[key] = Number(value)
    },
  })
}

const runHour = numberProxy('run_hour')
const runMinute = numberProxy('run_minute')
const intervalMinutes = numberProxy('interval_minutes')
const windowStartHour = numberProxy('window_start_hour')
const windowEndHour = numberProxy('window_end_hour')

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

</script>

<template>
  <section v-if="open" class="sched" aria-label="改时点">
    <div class="sched__row">
      <ToggleGroup v-model="draft.mode" type="single" variant="outline" size="sm" class="sched__modes" aria-label="任务调度方式">
        <ToggleGroupItem value="off">仅手动</ToggleGroupItem>
        <ToggleGroupItem value="once">交易日定点</ToggleGroupItem>
        <ToggleGroupItem value="interval">盘中间隔</ToggleGroupItem>
      </ToggleGroup>

      <div v-if="draft.mode === 'once'" class="sched__picks">
        <Select v-model="runHour">
          <SelectTrigger size="sm" class="sched__pick" aria-label="执行小时">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="h in HOURS" :key="`h${h}`" :value="String(h)">
              {{ String(h).padStart(2, '0') }}
            </SelectItem>
          </SelectContent>
        </Select>
        <span class="sched__sep">:</span>
        <Select v-model="runMinute">
          <SelectTrigger size="sm" class="sched__pick" aria-label="执行分钟">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="m in MINUTES" :key="`m${m}`" :value="String(m)">
              {{ String(m).padStart(2, '0') }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div v-else-if="draft.mode === 'interval'" class="sched__picks">
        <Select v-model="intervalMinutes">
          <SelectTrigger size="sm" class="sched__pick sched__pick--wide" aria-label="执行间隔">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="n in TRADING_INTERVALS" :key="`i${n}`" :value="String(n)">
              每 {{ n }} 分钟
            </SelectItem>
          </SelectContent>
        </Select>
        <Select v-model="windowStartHour">
          <SelectTrigger size="sm" class="sched__pick" aria-label="时段开始小时">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="h in HOURS" :key="`ws${h}`" :value="String(h)">
              {{ String(h).padStart(2, '0') }} 时
            </SelectItem>
          </SelectContent>
        </Select>
        <span class="sched__sep">—</span>
        <Select v-model="windowEndHour">
          <SelectTrigger size="sm" class="sched__pick" aria-label="时段结束小时">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="h in HOURS" :key="`we${h}`" :value="String(h)">
              {{ String(h).padStart(2, '0') }} 时
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>

    <dl class="sched__preview">
      <div>
        <dt>cron</dt>
        <dd>{{ composed || '仅手动' }}</dd>
      </div>
      <div v-if="composed">
        <dt>接下来</dt>
        <dd v-if="nextRuns && nextRuns.length">{{ nextRuns.join('  ·  ') }}</dd>
        <dd v-else class="is-warn">无法预览</dd>
      </div>
    </dl>

    <Alert v-if="tooFrequent">
      <TriangleAlert />
      <AlertTitle class="line-clamp-none">{{ cronTooFrequentTitle(intervalSeconds) }}</AlertTitle>
    </Alert>

    <div class="sched__actions">
      <Button variant="ghost" size="sm" @click="cancel">取消</Button>
      <Button size="sm" :disabled="busy || !dirty" @click="submit">保存时点</Button>
    </div>
  </section>
</template>

<style scoped>
.sched {
  display: flex;
  flex-shrink: 0;
  flex-direction: column;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--seal-border);
  border-radius: var(--radius-lg);
  background: color-mix(in oklab, var(--seal) 4%, var(--surface));
  animation: sched-in var(--dur) var(--ease);
}

.sched__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
}

.sched__modes {
  max-width: 100%;
  flex-wrap: nowrap;
  overflow-x: auto;
}

.sched__picks {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.sched__pick {
  width: 5.5rem;
}

.sched__pick--wide {
  width: 8rem;
}

.sched__sep {
  color: var(--text-tertiary);
}

.sched__preview {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 4px 14px;
  margin: 0;
  font-size: var(--fs-aux);
}

.sched__preview > div {
  display: contents;
}

.sched__preview dt {
  color: var(--text-tertiary);
}

.sched__preview dd {
  margin: 0;
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sched__preview dd.is-warn {
  color: var(--warn-ink);
  font-family: var(--font);
}

.sched__actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

@keyframes sched-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: none; }
}

@media (prefers-reduced-motion: reduce) {
  .sched { animation: none; }
}
</style>
