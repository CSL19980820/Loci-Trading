import type { BasicTableColumn } from './basicTableTypes'


export function createSpanMethod(
  mergeField: string[],
  rows: Record<string, unknown>[],
  _columns: BasicTableColumn[],
): ((args: {
  row: Record<string, unknown>
  column: { property?: string }
  rowIndex: number
  columnIndex: number
}) => { rowspan: number; colspan: number } | number[]) | undefined {
  if (!mergeField.length) return undefined

  const spans = new Map<string, number[]>()

  for (const rule of mergeField) {
    const fields = rule.split(',').map((s) => s.trim()).filter(Boolean)
    if (!fields.length) continue
    const keyProp = fields[0]
    const arr = Array.from({ length: rows.length }, () => 1)
    let i = 0
    while (i < rows.length) {
      const cur = rowKey(rows[i], fields)
      if (cur === '') {
        arr[i] = 1
        i += 1
        continue
      }
      let j = i + 1
      while (j < rows.length && rowKey(rows[j], fields) === cur) j += 1
      arr[i] = j - i
      for (let k = i + 1; k < j; k += 1) arr[k] = 0
      i = j
    }
    spans.set(keyProp, arr)
  }

  return ({ column, rowIndex }) => {
    const prop = column.property
    if (!prop || !spans.has(prop)) return { rowspan: 1, colspan: 1 }
    const arr = spans.get(prop)!
    const rowspan = arr[rowIndex] ?? 1
    if (rowspan === 0) return { rowspan: 0, colspan: 0 }
    return { rowspan, colspan: 1 }
  }

  function rowKey(row: Record<string, unknown>, fields: string[]): string {
    return fields.map((f) => String(row[f] ?? '')).join('\0')
  }
}
