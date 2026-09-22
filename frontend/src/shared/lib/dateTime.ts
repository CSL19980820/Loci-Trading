/** 秒级北京时间展示；无时区的旧记录按北京时间解释。 */
export function formatDateTime(value: string | null | undefined): string {
  if (!value?.trim()) return '—'
  let text = value.trim().replace(' ', 'T')
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(text)) return '—'
  text = text.replace(/(\.\d{3})\d+(?=Z|[+-]\d{2}:?\d{2}$)/, '$1')
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)) text += '+08:00'
  const date = new Date(text)
  if (!Number.isFinite(date.getTime())) return '—'
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(date)
  const part = (name: string) => parts.find(item => item.type === name)?.value ?? ''
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}:${part('second')}`
}
