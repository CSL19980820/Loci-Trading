/** Resolve day-K dblclick to an absolute bar index (not dataZoom-filtered). */

export function resolveKlineDblclickIndex(opts: {
  dates: string[]
  /** ECharts params.name — usually the category trade date */
  name?: unknown
  dataIndex?: unknown
  /** Last axis-pointer / hover index as fallback when clicking empty grid */
  hoverIndex?: number
}): number {
  const { dates } = opts
  if (!dates.length) return -1

  const name = String(opts.name ?? '').trim().slice(0, 10)
  if (/^\d{4}-\d{2}-\d{2}$/.test(name)) {
    const byName = dates.indexOf(name)
    if (byName >= 0) return byName
  }

  const hover =
    typeof opts.hoverIndex === 'number' && Number.isFinite(opts.hoverIndex)
      ? Math.round(opts.hoverIndex)
      : -1
  if (hover >= 0 && hover < dates.length) return hover

  // Only trust dataIndex when it lands on a real absolute slot.
  // With dataZoom filterMode:'filter', dataIndex is window-relative and unsafe.
  const dataIndex =
    typeof opts.dataIndex === 'number' && Number.isFinite(opts.dataIndex)
      ? Math.round(opts.dataIndex)
      : -1
  if (dataIndex >= 0 && dataIndex < dates.length) {
    const named = dates[dataIndex]
    // If name was a valid date but missed dates[], don't fall through wrongly.
    if (name && /^\d{4}-\d{2}-\d{2}$/.test(name) && named !== name) return -1
    return dataIndex
  }
  return -1
}
