/**
 * BasicTable 的行内编辑态：当前编辑行 / 列，以及行主键的解析。
 *
 * 单独成文件的理由是 `resolveRowKey` —— 它是「这一行是谁」的唯一口径，
 * 编辑态、虚拟表的 row-key、清空选择都得认同一份。留在组件里时它夹在
 * 十几个事件转发函数中间，很容易被再抄一份出来（虚拟表分支就差点抄）。
 */
import { ref } from 'vue'

/** 只取 BasicTable props 里与行主键有关的一项。 */
export type BasicTableEditProps = {
  rowKey?: string | ((row: Record<string, unknown>) => string)
}

export function useBasicTableEdit(props: BasicTableEditProps) {
  const editRowKey = ref('')
  const editColumn = ref<unknown>(null)

  function resolveRowKey(row: Record<string, unknown>): string {
    if (typeof props.rowKey === 'function') return props.rowKey(row)
    if (typeof props.rowKey === 'string') return String(row[props.rowKey] ?? '')
    return String(row.id ?? '')
  }

  function isEditByRow(row: Record<string, unknown>): boolean {
    return editRowKey.value !== '' && resolveRowKey(row) === editRowKey.value
  }

  function setEditRow(row: Record<string, unknown>, column?: unknown): void {
    editRowKey.value = resolveRowKey(row)
    editColumn.value = column ?? null
  }

  function clearEdit(): void {
    editRowKey.value = ''
    editColumn.value = null
  }

  function getRowEdit(): { rowKey: string; column: unknown } {
    return { rowKey: editRowKey.value, column: editColumn.value }
  }

  return { editRowKey, editColumn, resolveRowKey, isEditByRow, setEditRow, clearEdit, getRowEdit }
}
