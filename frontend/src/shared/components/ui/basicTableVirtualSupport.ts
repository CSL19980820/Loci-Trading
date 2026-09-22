import type { BasicTableColumn } from './basicTableTypes'

export function canVirtualizeBasicTable(
  columns: BasicTableColumn[],
  mergeField: string[],
  rowKey: string | ((row: Record<string, unknown>) => string) | undefined,
): boolean {
  if (mergeField.length || typeof rowKey === 'function') return false
  return !columns.some(
    (column) =>
      !!column.children?.length ||
      column.type === 'expand' ||
      !!column.filters?.length ||
      column.sortable === true ||
      column.sortable === 'custom',
  )
}

function columnBaseWidth(column: BasicTableColumn): number {
  const raw = column.width ?? column.minWidth
  const width = typeof raw === 'number' ? raw : Number.parseFloat(String(raw ?? ''))
  return Number.isFinite(width) && width > 0 ? width : 120
}

function isFlexColumn(column: BasicTableColumn): boolean {
  return Boolean(column.minWidth && !column.width && !column.fixed && column.type !== 'selection')
}


export function distributeVirtualColumnWidths(
  columns: BasicTableColumn[],
  containerWidth: number,
): number[] {
  const bases = columns.map((column) => columnBaseWidth(column))
  const total = bases.reduce((sum, width) => sum + width, 0)
  const leftover = Math.floor(containerWidth) - total
  if (!(leftover > 0) || !(containerWidth > 0)) return bases

  const flexIndexes = columns
    .map((column, index) => (isFlexColumn(column) ? index : -1))
    .filter((index) => index >= 0)
  if (!flexIndexes.length) {
    for (let i = columns.length - 1; i >= 0; i -= 1) {
      const column = columns[i]
      if (!column || column.fixed || column.type === 'selection') continue
      bases[i] = (bases[i] ?? 0) + leftover
      break
    }
    return bases
  }

  const share = Math.floor(leftover / flexIndexes.length)
  let rem = leftover - share * flexIndexes.length
  for (const index of flexIndexes) {
    bases[index] = (bases[index] ?? 0) + share + (rem > 0 ? 1 : 0)
    if (rem > 0) rem -= 1
  }
  return bases
}
