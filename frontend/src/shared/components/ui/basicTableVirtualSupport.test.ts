import { describe, expect, it } from 'vitest'

import type { BasicTableColumn } from './basicTableTypes'
import {
  canVirtualizeBasicTable,
  distributeVirtualColumnWidths,
} from './basicTableVirtualSupport'

describe('distributeVirtualColumnWidths', () => {
  it('grows minWidth flex columns to fill leftover container space', () => {
    const columns: BasicTableColumn[] = [
      { type: 'selection', width: 48, fixed: 'left' },
      { prop: 'date', label: '日期', width: 110 },
      { prop: 'reason', label: '理由', minWidth: 260 },
      { prop: 'actions', label: '操作', width: 80, fixed: 'right' },
    ]
    const widths = distributeVirtualColumnWidths(columns, 1000)
    expect(widths).toEqual([48, 110, 762, 80])
    expect(widths.reduce((sum, width) => sum + width, 0)).toBe(1000)
  })

  it('falls back to the last non-fixed data column when no flex column exists', () => {
    const columns: BasicTableColumn[] = [
      { prop: 'name', label: '名称', width: 120 },
      { prop: 'score', label: '评分', width: 80 },
      { prop: 'actions', label: '操作', width: 80, fixed: 'right' },
    ]
    const widths = distributeVirtualColumnWidths(columns, 500)
    expect(widths).toEqual([120, 300, 80])
  })

  it('keeps base widths when the container is narrower than the sum', () => {
    const columns: BasicTableColumn[] = [
      { prop: 'name', label: '名称', minWidth: 200 },
      { prop: 'actions', label: '操作', width: 80, fixed: 'right' },
    ]
    expect(distributeVirtualColumnWidths(columns, 200)).toEqual([200, 80])
  })
})

describe('canVirtualizeBasicTable', () => {
  it('rejects filterable columns that virtual mode cannot express', () => {
    expect(
      canVirtualizeBasicTable(
        [{ prop: 'name', label: '名称', filters: [{ text: '精选', value: '精选' }] }],
        [],
        'id',
      ),
    ).toBe(false)
  })
})
