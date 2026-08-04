import type { VNode } from 'vue'

export type BasicTableColumn = {
  prop?: string
  label?: string
  type?: 'selection' | 'index' | 'expand'
  width?: number | string
  minWidth?: number | string
  fixed?: boolean | 'left' | 'right'
  align?: 'left' | 'center' | 'right'
  headerAlign?: 'left' | 'center' | 'right'
  hidden?: boolean
  formatter?: (row: Record<string, unknown>) => string
  render?: (
    h: typeof import('vue').h,
    ctx: { row: Record<string, unknown>; prop?: string; index: number },
  ) => VNode | string | number | null
  slotName?: string
  showOverflowTooltip?: boolean
  sortable?: boolean | 'custom'
  children?: BasicTableColumn[]
  filters?: { text: string; value: unknown }[]
  filterMultiple?: boolean
  filterPlacement?: string
  filterMethod?: (value: unknown, row: Record<string, unknown>, column: unknown) => boolean
  editRender?: {
    component?: string
    componentProps?: Record<string, unknown>
  }
}

export type BasicTablePagination = {
  pageSize?: number
  currentPage?: number
  pageSizes?: number[]
  layout?: string
  background?: boolean
  hideOnSinglePage?: boolean
  total?: number
}

export type BasicTableRequest = (
  params: Record<string, unknown> & { currentPage: number; pageSize: number },
) => Promise<{ list: Record<string, unknown>[]; total: number }>

export type BasicTableEditConfig = {
  trigger?: string
  mode?: 'row' | 'cell'
  beforeEditMethod?: (args: {
    row: Record<string, unknown>
    column: unknown
    rowIndex: number
  }) => boolean
}

export type BasicTableToolbarConfig = {
  refresh?: boolean
  zoom?: boolean
  custom?: boolean
}
