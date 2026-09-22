import type { CSSProperties, VNode, VNodeChild } from 'vue'
import type { BasicTableColumn } from '../basicTableTypes'
import { componentName, flattenNodes, nodeSlot } from './vnodeContent'

export type GridRecord = Record<string, unknown>
export interface GridScope { row: GridRecord; $index: number; column: GridColumn }
export interface GridColumn extends Omit<BasicTableColumn, 'children'> {
  children?: GridColumn[]
  property?: string
  cellSlot?: (scope: GridScope) => VNodeChild
  headerSlot?: (scope: { column: GridColumn; $index: number }) => VNodeChild
  selectable?: (row: GridRecord, index: number) => boolean
}
export interface GridProps {
  data?: object[]; columns?: GridColumn[]; rowKey?: string | ((row: GridRecord) => string)
  height?: string | number; maxHeight?: string | number; size?: string; stripe?: boolean; border?: boolean
  emptyText?: string; virtualized?: boolean; highlightCurrentRow?: boolean
  defaultSort?: { prop: string; order: 'ascending' | 'descending' }
  rowClassName?: string | ((scope: { row: GridRecord; rowIndex: number }) => string)
  rowStyle?: CSSProperties | ((scope: { row: GridRecord; rowIndex: number }) => CSSProperties)
  spanMethod?: (scope: { row: GridRecord; column: GridColumn; rowIndex: number; columnIndex: number }) => number[] | { rowspan: number; colspan: number } | undefined
}
export interface GridHandle {
  clearSelection: () => void
  toggleRowSelection: (row: object, selected?: boolean) => void
  getSelectionRows: () => GridRecord[]
  doLayout: () => void
  sort: (prop: string, order: string | null) => void
  clearSort: () => void
  scrollTo: (options: ScrollToOptions) => void
}
export function collectColumns(nodes: VNode[]): GridColumn[] {
  return flattenNodes(nodes).filter(node => componentName(node) === 'DataColumn').map(node => {
    const props = Object.fromEntries(Object.entries(node.props ?? {}).map(([key, value]) => [key.replace(/-([a-z])/g, (_, char: string) => char.toUpperCase()), value]))
    const column = { ...props, property: props.prop } as GridColumn
    if (props.group) column.children = collectColumns(flattenNodes(nodeSlot(node)?.()))
    else column.cellSlot = nodeSlot(node) as GridColumn['cellSlot']
    column.headerSlot = nodeSlot(node, 'header') as GridColumn['headerSlot']
    return column
  })
}
export function leafColumns(columns: GridColumn[]): GridColumn[] {
  return columns.filter(column => !column.hidden).flatMap(column => column.children?.length ? leafColumns(column.children) : [column])
}
