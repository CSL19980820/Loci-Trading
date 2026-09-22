import { parseDate, type DateValue } from '@internationalized/date'

/** Calendar values are local dates, never ISO/UTC conversions. */
export function readDate(value: unknown): DateValue | undefined {
  if (value == null || value === '') return undefined
  let text: string
  if (value instanceof Date) {
    if (Number.isNaN(value.valueOf())) return undefined
    text = `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
  } else {
    text = String(value).trim()
    if (/^\d{8}$/.test(text)) text = `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`
    else text = text.slice(0, 10).replaceAll('/', '-')
  }
  try { return parseDate(text) } catch { return undefined }
}

export function readTime(value: unknown, fallback = '00:00'): string {
  if (value instanceof Date && !Number.isNaN(value.valueOf())) return `${pad(value.getHours())}:${pad(value.getMinutes())}`
  return /[T ](\d{2}:\d{2})/.exec(String(value ?? ''))?.[1] ?? fallback
}

export function validTime(time: string): boolean { return /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time) }
export function nativeDate(date: DateValue): Date { return new Date(date.year, date.month - 1, date.day) }
const pad = (number: number) => String(number).padStart(2, '0')

export function writeDate(date: DateValue, time: string, datetime: boolean, format?: string): string | Date {
  if (datetime && !validTime(time)) throw new RangeError('Invalid time')
  const result = nativeDate(date)
  if (datetime) result.setHours(Number(time.slice(0, 2)), Number(time.slice(3, 5)), 0, 0)
  if (!format) return result
  const tokens: Record<string, string> = { YYYY: String(date.year), MM: pad(date.month), DD: pad(date.day), HH: time.slice(0, 2), mm: time.slice(3, 5), ss: '00' }
  return format.replace(/YYYY|MM|DD|HH|mm|ss/g, token => tokens[token])
}
