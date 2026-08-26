/** 战法档位时间模型：与后端 skill_strategy_config 的 schedule 字段一一对应。 */
export type ScheduleMode = 'off' | 'once' | 'interval'

export interface ScheduleFields {
  mode: 'once' | 'interval'
  run_hour: number
  run_minute: number
  interval_minutes: number
  window_start_hour: number
  window_start_minute: number
  window_end_hour: number
  window_end_minute: number
}

export const HOUR_OPTS = Array.from({ length: 24 }, (_, i) => i)
export const MINUTE_OPTS = Array.from({ length: 12 }, (_, i) => i * 5)
export const INTERVAL_OPTS = [5, 10, 15, 30, 60]

export function pad(n: number): string {
  return String(n).padStart(2, '0')
}

/** 盘后选股默认：交易日 15:40 定点 */
export function screenDefaults(): ScheduleFields {
  return {
    mode: 'once',
    run_hour: 15,
    run_minute: 40,
    interval_minutes: 10,
    window_start_hour: 9,
    window_start_minute: 30,
    window_end_hour: 14,
    window_end_minute: 50,
  }
}

/** 盘中监测默认：交易时段每 10 分钟 */
export function watchDefaults(): ScheduleFields {
  return { ...screenDefaults(), mode: 'interval', run_hour: 10, run_minute: 0 }
}

/**
 * 本地预览（当日、不跳非交易日）。仅在服务端 next_runs 未回来或已被用户改动时兜底。
 * 间隔模式：展示开头若干槽 + 当天末档，避免误以为结束于整点小时。
 */
export function previewSlots(fields: ScheduleFields, limit = 5): string[] {
  const now = new Date()
  const day = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
  if (fields.mode === 'once') {
    return [`${day} ${pad(fields.run_hour)}:${pad(fields.run_minute)}`]
  }
  const start = fields.window_start_hour * 60 + fields.window_start_minute
  const end = fields.window_end_hour * 60 + fields.window_end_minute
  const step = Math.max(1, fields.interval_minutes)
  const all: string[] = []
  for (let t = start; t <= end; t += step) {
    all.push(`${day} ${pad(Math.floor(t / 60))}:${pad(t % 60)}`)
  }
  if (all.length <= limit) return all
  const head = all.slice(0, Math.max(1, limit - 1))
  const last = all[all.length - 1]
  return last && !head.includes(last) ? [...head, last] : head
}

const FIELD_KEYS = [
  'run_hour',
  'run_minute',
  'interval_minutes',
  'window_start_hour',
  'window_start_minute',
  'window_end_hour',
  'window_end_minute',
] as const

/** 从扁平配置（`screen_` / `watch_` 前缀）读出一组档位时间。 */
export function readFields(
  source: Record<string, unknown>,
  mode: ScheduleMode | null | undefined,
  fallback: ScheduleFields,
  prefix: string,
): ScheduleFields {
  const out: ScheduleFields = {
    ...fallback,
    mode: mode === 'once' || mode === 'interval' ? mode : fallback.mode,
  }
  for (const key of FIELD_KEYS) {
    const raw = source[`${prefix}${key}`]
    if (raw !== undefined && raw !== null) out[key] = Number(raw)
  }
  return out
}

/** 写回扁平配置（`screen_` / `watch_` 前缀）。 */
export function writeFields(
  fields: ScheduleFields,
  enabled: boolean,
  prefix: string,
): Record<string, unknown> {
  const out: Record<string, unknown> = {
    [`${prefix}schedule_mode`]: enabled ? fields.mode : 'off',
  }
  for (const key of FIELD_KEYS) out[`${prefix}${key}`] = fields[key]
  return out
}
