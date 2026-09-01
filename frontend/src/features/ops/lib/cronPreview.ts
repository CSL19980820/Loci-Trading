/**
 * 极简 cron 预览：只为「新建 / 改定时」表单回答一句「接下来什么时候跑」。
 *
 * 为什么在前端算
 * --------------
 * 后端 `GET /api/jobs/schedule`（`preview_upcoming_jobs`）只能算**已经存在**的
 * 任务：它遍历 jobs 表、按 id 匹配调度器实况。表单里那条还没保存的 cron 在库里
 * 没有行，问不出下一次触发——而「不动就得到一个永不触发的任务」正是要治的病。
 * 所以这里做一个**够用就好**的解析器，只覆盖仓内真会出现的写法。
 *
 * 支持范围（其余一律返回 null，界面显示「无法预览」）
 * ------------------------------------------------
 * - 必须是 5 段：`分 时 日 月 周`
 * - 每段支持 `*`、数字、`a-b`、步长（斜杠 n）、以及它们的逗号列表
 * - 月份 / 星期额外接受英文缩写（`jan`…`dec`、`mon`…`sun`）——仓内托管任务的
 *   cron 就写成 `30 15 * * mon-fri`（见 `compose_trading_cron`）
 *
 * **算不出来就说算不出来**：宁可显示「无法预览」，也不能编一个错时间——用户会
 * 拿它当承诺，然后在错误的时刻等一个不会来的结果。
 *
 * 两个必须与后端对齐的口径
 * ------------------------
 * 1. **星期编号 0 = 周一**。APScheduler 的 `from_crontab` 就是这么数的，
 *    和 Unix 的 0 = 周日不同（`src/ops/infrastructure/scheduler.py` 有同款注释）。
 * 2. 后端 `normalize_cron_weekdays` 会把历史写法 `1-5` / `1,2,3,4,5` 改写成
 *    `mon-fri` 再交给 APScheduler。这里照做，否则同一条「盘中每 5 分钟」的
 *    cron（周字段写 `1-5`），前端会预览成「周二到周六」、后端实际跑「周一到周五」。
 *
 * 时区：按浏览器本地时区推算。后端调度按 Asia/Shanghai；两者不一致时预览会偏，
 * 这是刻意的取舍——不为一行提示塞一个时区库进来。
 */

/** APScheduler 的星期缩写，下标即编号（0 = 周一）。 */
const DOW_NAMES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

const MONTH_NAMES = [
  'jan', 'feb', 'mar', 'apr', 'may', 'jun',
  'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
] as const

type FieldSpec = {
  min: number
  max: number
  /** 名称表，下标 0 对应 `min` */
  names?: readonly string[]
}

/** 顺序即 cron 的字段顺序：分 时 日 月 周。 */
const FIELDS: readonly FieldSpec[] = [
  { min: 0, max: 59 },
  { min: 0, max: 23 },
  { min: 1, max: 31 },
  { min: 1, max: 12, names: MONTH_NAMES },
  { min: 0, max: 6, names: DOW_NAMES },
]

/** 后端 `normalize_cron_weekdays` 只改写这两种历史写法，这里一字不差地照抄。 */
const UNIX_MON_FRI: Record<string, true> = {
  '1-5': true,
  '1,2,3,4,5': true,
}

/** 往前扫多少天找触发点。跨过 `0 0 30 2 *` 这类永不成立的组合后仍然收敛。 */
const MAX_SCAN_DAYS = 400

export interface CronPreview {
  /** 与后端一致的归一化表达式（`1-5` → `mon-fri`） */
  normalized: string
  /** 接下来的触发时刻，严格晚于 `from` */
  runs: Date[]
  /** 相邻两次触发的间隔秒数；只找得到一次触发时为 null */
  intervalSeconds: number | null
}

/** 拆分多行或分号分隔的多个 cron 表达式。 */
export function splitCronExpressions(expression: string): string[] {
  const text = (expression || '').trim()
  if (!text) return []
  return text
    .replace(/;/g, '\n')
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0 && !l.startsWith('#'))
}

/** 把 Unix 习惯的工作日字段改成 APScheduler 认的 `mon-fri`，与后端同款。 */
export function normalizeCronWeekdays(expression: string): string {
  const lines = splitCronExpressions(expression)
  if (!lines.length) return (expression || '').trim()
  const normalizedLines: string[] = []
  for (let line of lines) {
    const fields = line.split(/\s+/)
    if (fields.length === 5 && UNIX_MON_FRI[fields[4].toLowerCase()]) {
      fields[4] = 'mon-fri'
      line = fields.join(' ')
    }
    normalizedLines.push(line)
  }
  return normalizedLines.join('\n')
}

function parseValue(token: string, spec: FieldSpec): number | null {
  const text = token.trim().toLowerCase()
  if (!text) return null
  if (spec.names) {
    const index = spec.names.indexOf(text)
    if (index >= 0) return index + spec.min
  }
  if (!/^\d+$/.test(text)) return null
  const value = Number(text)
  if (value < spec.min || value > spec.max) return null
  return value
}

/** 单个字段 → 命中值升序数组；任何看不懂的写法返回 null。 */
function parseField(field: string, spec: FieldSpec): number[] | null {
  const hits: number[] = []
  for (const part of field.split(',')) {
    const text = part.trim().toLowerCase()
    if (!text) return null
    const chunks = text.split('/')
    if (chunks.length > 2) return null
    const [body, stepText] = chunks
    let step = 1
    if (stepText !== undefined) {
      if (!/^\d+$/.test(stepText)) return null
      step = Number(stepText)
      if (step < 1) return null
    }
    let low: number
    let high: number
    if (body === '*') {
      low = spec.min
      high = spec.max
    } else if (body.includes('-')) {
      const bounds = body.split('-')
      if (bounds.length !== 2) return null
      const start = parseValue(bounds[0], spec)
      const end = parseValue(bounds[1], spec)
      if (start === null || end === null || start > end) return null
      low = start
      high = end
    } else {
      const single = parseValue(body, spec)
      if (single === null) return null
      low = single
      // `5/10` 是「从 5 起每 10 个」，光写 `5` 就只有 5 自己。
      high = stepText === undefined ? single : spec.max
    }
    for (let value = low; value <= high; value += step) {
      if (!hits.includes(value)) hits.push(value)
    }
  }
  if (!hits.length) return null
  return hits.sort((a, b) => a - b)
}

/**
 * 接下来的 `count` 次触发。看不懂的表达式返回 **null**（≠ 空数组：空数组会被
 * 当成「解析成功但永不触发」，这两件事在界面上要说不同的话）。
 */
function previewSingleCron(
  line: string,
  needed: number,
  from: Date,
): Date[] | null {
  const normalized = normalizeCronWeekdays(line)
  const raw = normalized.trim().toLowerCase()
  if (!raw) return null
  const fields = raw.split(/\s+/)
  if (fields.length !== 5) return null

  const parsed: number[][] = []
  for (let i = 0; i < FIELDS.length; i += 1) {
    const values = parseField(fields[i], FIELDS[i])
    if (values === null) return null
    parsed.push(values)
  }
  const [minutes, hours, monthDays, months, weekDays] = parsed
  const domRestricted = fields[2] !== '*'
  const dowRestricted = fields[4] !== '*'

  const runs: Date[] = []
  const start = new Date(from.getFullYear(), from.getMonth(), from.getDate())
  const floor = from.getTime()

  for (let offset = 0; offset < MAX_SCAN_DAYS && runs.length < needed; offset += 1) {
    const day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + offset)
    if (!months.includes(day.getMonth() + 1)) continue
    if (domRestricted && !monthDays.includes(day.getDate())) continue
    if (dowRestricted && !weekDays.includes((day.getDay() + 6) % 7)) continue
    for (const hour of hours) {
      for (const minute of minutes) {
        const slot = new Date(day.getFullYear(), day.getMonth(), day.getDate(), hour, minute)
        if (slot.getTime() <= floor) continue
        runs.push(slot)
        if (runs.length >= needed) break
      }
      if (runs.length >= needed) break
    }
  }
  return runs
}

/**
 * 接下来的 `count` 次触发。支持多行或分号分隔的多个 cron。
 * 看不懂的表达式返回 **null**。
 */
export function previewCron(
  expression: string,
  options: { count?: number; from?: Date } = {},
): CronPreview | null {
  const count = Math.max(1, options.count ?? 3)
  const from = options.from ?? new Date()
  const lines = splitCronExpressions(expression)
  if (!lines.length) return null

  const needed = Math.max(count, 2)
  const allRuns: Date[] = []
  const normalizedLines: string[] = []

  for (const line of lines) {
    const singleRuns = previewSingleCron(line, needed, from)
    if (singleRuns === null) return null
    allRuns.push(...singleRuns)
    normalizedLines.push(normalizeCronWeekdays(line))
  }

  if (!allRuns.length) return null

  // 去重并按时间升序排序
  const uniqueRuns: Date[] = []
  const seen = new Set<number>()
  allRuns.sort((a, b) => a.getTime() - b.getTime())
  for (const d of allRuns) {
    const t = d.getTime()
    if (!seen.has(t)) {
      seen.add(t)
      uniqueRuns.push(d)
    }
  }

  const intervalSeconds =
    uniqueRuns.length >= 2 ? Math.round((uniqueRuns[1].getTime() - uniqueRuns[0].getTime()) / 1000) : null
  return {
    normalized: normalizedLines.join('\n'),
    runs: uniqueRuns.slice(0, count),
    intervalSeconds,
  }
}

/** 相邻两次触发的间隔秒数；算不出来返回 null。用于「间隔 < 5 分钟」就地提示。 */
export function cronIntervalSeconds(expression: string, from?: Date): number | null {
  return previewCron(expression, { count: 2, from })?.intervalSeconds ?? null
}

/** `YYYY-MM-DD HH:MM`，与后端 `preview_trading_runs` 的展示口径一致。 */
export function formatCronRun(when: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0')
  return (
    `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}` +
    ` ${pad(when.getHours())}:${pad(when.getMinutes())}`
  )
}

/** 直接给界面用的字符串列表；null 表示「无法预览」。 */
export function describeCronRuns(
  expression: string,
  options: { count?: number; from?: Date } = {},
): string[] | null {
  const preview = previewCron(expression, options)
  if (!preview) return null
  return preview.runs.map(formatCronRun)
}

/**
 * 非主租户的 cron 下限（秒）。
 *
 * **权威值在后端**：`src/ops` 的 `MIN_TENANT_CRON_INTERVAL_SECONDS`，闸门由
 * `guard_tenant_cron_floor` 用 `cron_interval_seconds()` 实算后拦（422）。
 * 这里这一份**只用于提交前的就地提示**，让人在点保存之前就知道会被拒；
 * 判不准也不影响正确性——真正说了算的仍然是后端那次 422。
 * 两处不一致时，以后端为准并回来改这一行。
 */
export const TENANT_CRON_FLOOR_SECONDS = 300

/**
 * 「快于下限」的就地提示文案 —— **只此一份**。
 *
 * JobEditorDialog 与 JobScheduleInline 此前各手抄一句近乎逐字相同的长句
 * （「这条 cron 约每 N 分钟触发一次，快于 5 分钟下限；非主账号提交会被后端拒绝（422）」），
 * 改一处漏一处。下限数字也从 TENANT_CRON_FLOOR_SECONDS 算出，不再写死在文案里。
 */
export function cronTooFrequentTitle(intervalSeconds: number | null): string {
  const minutes = Math.max(1, Math.round((intervalSeconds ?? 0) / 60))
  const floorMinutes = Math.round(TENANT_CRON_FLOOR_SECONDS / 60)
  return `约每 ${minutes} 分钟一次，快于 ${floorMinutes} 分钟下限（非主账号会被拒）`
}

/** 后端 `trading_schedule.ALLOWED_INTERVALS`，一字不差。 */
export const TRADING_INTERVALS = [5, 10, 15, 30, 60] as const

export type TradingScheduleMode = 'off' | 'once' | 'interval'

/** 与后端 `schedule_dict_from_payload` 落库的结构同形。 */
export interface TradingSchedule {
  mode: TradingScheduleMode
  run_hour: number
  run_minute: number
  interval_minutes: number
  window_start_hour: number
  window_start_minute: number
  window_end_hour: number
  window_end_minute: number
}

export function defaultTradingSchedule(): TradingSchedule {
  return {
    mode: 'once',
    run_hour: 15,
    run_minute: 30,
    interval_minutes: 10,
    window_start_hour: 9,
    window_start_minute: 30,
    window_end_hour: 14,
    window_end_minute: 50,
  }
}

/**
 * 结构化调度 → cron，逐字对齐后端 `compose_trading_cron`。
 *
 * **必须写 `mon-fri` 而不是 `1-5`**：落库的 cron 会被 APScheduler 直接吃掉，
 * 而它的 0 是周一，`1-5` 会变成周二到周六（后端只对历史写法做兼容改写，
 * 新写的不该再依赖那层兜底）。
 */
export function composeTradingCron(schedule: TradingSchedule): string {
  if (schedule.mode === 'off') return ''
  if (schedule.mode === 'once') {
    const hour = clamp(schedule.run_hour, 0, 23)
    const minute = clamp(schedule.run_minute, 0, 59)
    return `${minute} ${hour} * * mon-fri`
  }
  const interval = nearestTradingInterval(schedule.interval_minutes)
  const startHour = clamp(schedule.window_start_hour, 0, 23)
  const endHour = clamp(schedule.window_end_hour, startHour, 23)
  return `*/${interval} ${startHour}-${endHour} * * mon-fri`
}

/** 落到最接近的合法档位：后端对档位外的值直接 422，不如在这里先靠过去。 */
export function nearestTradingInterval(value: number): number {
  const wanted = Number(value) || 0
  let best = TRADING_INTERVALS[0] as number
  for (const option of TRADING_INTERVALS) {
    if (Math.abs(option - wanted) < Math.abs(best - wanted)) best = option
  }
  return best
}

function clamp(value: number, low: number, high: number): number {
  const n = Math.round(Number(value) || 0)
  return Math.min(high, Math.max(low, n))
}