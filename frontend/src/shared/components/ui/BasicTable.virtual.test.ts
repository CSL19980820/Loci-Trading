import { defineComponent, h, nextTick, type PropType } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import BasicTable from './BasicTable.vue'
import type { BasicTableColumn } from './basicTableTypes'

type BasicRow = Record<string, unknown>
type RowProps = (params: { rowData: BasicRow; rowIndex: number }) => Record<string, unknown>

type TableProbeProps = {
  columns: Array<{
    fixed?: unknown
    type?: string
    cellRenderer?: (params: { rowData: BasicRow; rowIndex: number }) => unknown
    headerCellRenderer?: () => unknown
  }>
  data: BasicRow[]
  rowProps?: RowProps
}

const TableV2Probe = defineComponent({
  props: {
    columns: { type: Array as PropType<TableProbeProps['columns']>, required: true },
    data: { type: Array as PropType<TableProbeProps['data']>, required: true },
    rowProps: { type: Function as PropType<RowProps>, required: false },
  },
  setup(props: TableProbeProps, { slots }) {
    return () => {
      const firstRow = props.data[0]
      const attrs = firstRow && props.rowProps
        ? props.rowProps({ rowData: firstRow, rowIndex: 0 })
        : {}
      const selection = props.columns.find(
        (column) => column.cellRenderer && column.headerCellRenderer,
      )
      return h('div', {
        'data-testid': 'table-v2',
        'data-row-count': String(props.data.length),
        'data-first-name': String(firstRow?.name ?? ''),
        'data-fixed-columns': props.columns
          .filter((column) => column.fixed)
          .map((column) => String(column.fixed))
          .join(','),
        'data-selection-enabled': String(
          Boolean(selection?.cellRenderer && selection.headerCellRenderer),
        ),
      }, [
        firstRow
          ? h('div', { ...attrs, 'data-testid': 'virtual-row-0' }, 'first row')
          : slots.empty?.(),
      ])
    }
  },
})

const AutoResizerProbe = defineComponent({
  setup(_, { slots }) {
    return () => slots.default?.({ height: 280, width: 720 })
  },
})

const ClassicTableProbe = defineComponent({
  setup() {
    return () => h('div', { 'data-testid': 'classic-table' })
  },
})

function makeRows(count: number): BasicRow[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `row-${index}`,
    name: `候选 ${index}`,
    decision: index % 2 ? '观察' : '精选',
  }))
}

function columns(): BasicTableColumn[] {
  return [
    { type: 'selection', width: 48, fixed: 'left' },
    { prop: 'name', label: '名称', minWidth: 160 },
    { prop: 'decision', label: '裁决', width: 90 },
    { prop: 'actions', label: '操作', width: 72, fixed: 'right' },
  ]
}

function mountVirtualTable(
  dataSource: BasicRow[],
  onRowClick: ReturnType<typeof vi.fn> = vi.fn(),
) {
  return mount(BasicTable, {
    props: {
      columns: columns(),
      dataSource,
      pagination: false,
      rowKey: 'id',
      virtualized: true,
      onRowClick,
    },
    global: {
      stubs: {
        'el-auto-resizer': AutoResizerProbe,
        'el-table-v2': TableV2Probe,
        'el-table': ClassicTableProbe,
        'el-button': { template: '<button><slot /></button>' },
        'el-checkbox': { template: '<input type="checkbox" />' },
        'el-pagination': { template: '<div />' },
        'el-popover': { template: '<div><slot name="reference" /><slot /></div>' },
      },
      directives: {
        loading: () => undefined,
      },
    },
  })
}

describe('BasicTable virtualized mode', () => {
  it('keeps 1000 rows in the Element Plus virtual table with fixed and selection columns', async () => {
    const wrapper = mountVirtualTable(makeRows(1000))
    await nextTick()

    const table = wrapper.get('[data-testid="table-v2"]')
    expect(table.attributes('data-row-count')).toBe('1000')
    expect(table.attributes('data-fixed-columns')).toBe('left,right')
    expect(table.attributes('data-selection-enabled')).toBe('true')
    expect(wrapper.find('[data-testid="classic-table"]').exists()).toBe(false)
  })

  it('updates a 5000-row table after filtering and keeps live row updates visible', async () => {
    const wrapper = mountVirtualTable(makeRows(5000))
    await nextTick()
    expect(wrapper.get('[data-testid="table-v2"]').attributes('data-row-count')).toBe('5000')

    const filtered = makeRows(5000).filter((row) => String(row.decision) === '精选')
    filtered[0] = { ...filtered[0], name: '实时更新候选' }
    await wrapper.setProps({ dataSource: filtered })
    await nextTick()

    const table = wrapper.get('[data-testid="table-v2"]')
    expect(table.attributes('data-row-count')).toBe('2500')
    expect(table.attributes('data-first-name')).toBe('实时更新候选')
  })

  it('makes virtual rows keyboard-focusable and opens them with Enter', async () => {
    const onRowClick = vi.fn()
    const wrapper = mountVirtualTable(makeRows(2), onRowClick)
    await nextTick()

    const row = wrapper.get('[data-testid="virtual-row-0"]')
    expect(row.attributes('tabindex')).toBe('0')
    expect(row.attributes('aria-rowindex')).toBe('2')

    await row.trigger('keydown', { key: 'Enter' })
    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick.mock.calls[0]?.[0]).toEqual(makeRows(2)[0])
  })

  it('falls back to the classic table when a column contract is unsupported', async () => {
    const wrapper = mount(BasicTable, {
      props: {
        columns: [{ prop: 'name', label: '名称', filters: [{ text: '精选', value: '精选' }] }],
        dataSource: makeRows(3),
        pagination: false,
        rowKey: 'id',
        virtualized: true,
      },
      global: {
        stubs: {
          'el-auto-resizer': AutoResizerProbe,
          'el-table-v2': TableV2Probe,
          'el-table': ClassicTableProbe,
        },
      },
    })
    await nextTick()

    expect(wrapper.find('[data-testid="classic-table"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="table-v2"]').exists()).toBe(false)
  })

  it('keeps the virtual table mounted when empty and forwards the empty slot', async () => {
    const wrapper = mount(BasicTable, {
      props: {
        columns: columns(),
        dataSource: [],
        pagination: false,
        rowKey: 'id',
        virtualized: true,
        emptyText: '暂无候选',
        emptyReason: '当前筛选下没有记录',
      },
      slots: {
        empty: () => h('button', { 'data-testid': 'empty-action' }, '记一条候选'),
      },
      global: {
        stubs: {
          'el-auto-resizer': AutoResizerProbe,
          'el-table-v2': TableV2Probe,
          'el-table': ClassicTableProbe,
        },
        directives: {
          loading: () => undefined,
        },
      },
    })
    await nextTick()

    expect(wrapper.find('[data-testid="table-v2"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="classic-table"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="empty-action"]').text()).toBe('记一条候选')
  })
})
