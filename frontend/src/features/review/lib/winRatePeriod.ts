/** 后端周聚合使用周一日期；同时接受历史 ISO 周编号。 */
export function matchesWinRatePeriod(dateText: string, period: string): boolean {
  const text = dateText.slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false
  const day = new Date(`${text}T00:00:00Z`)
  if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0, 10) !== text) return false
  if (/^\d{4}-\d{2}$/.test(period)) return text.startsWith(period)
  if (/^\d{4}-\d{2}-\d{2}$/.test(period)) {
    const start = new Date(`${period}T00:00:00Z`).getTime()
    return Number.isFinite(start) && day.getTime() >= start && day.getTime() < start + 7 * 86400000
  }
  if (!/^\d{4}-W\d{2}$/.test(period)) return false
  day.setUTCDate(day.getUTCDate() + 4 - (day.getUTCDay() || 7))
  const year = day.getUTCFullYear()
  const week = Math.ceil(((day.getTime() - Date.UTC(year, 0, 1)) / 86400000 + 1) / 7)
  return period === `${year}-W${String(week).padStart(2, '0')}`
}
