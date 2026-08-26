import { ElMessage, ElMessageBox } from 'element-plus'
import type { Ref } from 'vue'

import {
  batchAiSessions,
  deleteAiSession,
  listAiSessions,
  patchAiSession,
} from '@/shared/api/ai_assistant'
import { toErrorMessage } from '@/shared/lib/errors'
import type { AiSessionDetail, AiSessionSummary } from '@/shared/types/ai_assistant'

type ClearActive = (id: string) => void

export async function refreshAiSessionLists(
  sessions: Ref<AiSessionSummary[]>,
  archivedSessions: Ref<AiSessionSummary[]>,
  options: {
    bump: () => number
    isCurrent: (version: number) => boolean
  },
): Promise<void> {
  const version = options.bump()
  const [rows, archived] = await Promise.all([
    listAiSessions(),
    listAiSessions({ archivedOnly: true }),
  ])
  if (!options.isCurrent(version)) return
  sessions.value = rows
  archivedSessions.value = archived
}

export async function confirmDeleteAiSessions(ids: string[], titles: string[]): Promise<boolean> {
  const label = titles.length === 1
    ? `确定永久删除「${titles[0] || '新对话'}」？此操作不可恢复。`
    : `确定永久删除选中的 ${ids.length} 个对话？此操作不可恢复。`
  try {
    await ElMessageBox.confirm(label, '删除对话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      confirmButtonClass: 'el-button--danger',
    })
    return true
  } catch {
    return false
  }
}

export async function deleteAiSessionsWithConfirm(opts: {
  ids: string[]
  sessions: Ref<AiSessionSummary[]>
  archivedSessions: Ref<AiSessionSummary[]>
  clearIfActive: ClearActive
  setError: (message: string) => void
  disposed: () => boolean
  reload: () => Promise<void>
}): Promise<void> {
  const titles = opts.ids.map(
    (id) => [...opts.sessions.value, ...opts.archivedSessions.value].find((item) => item.id === id)?.title || '新对话',
  )
  if (!(await confirmDeleteAiSessions(opts.ids, titles))) return
  for (const id of opts.ids) opts.clearIfActive(id)
  try {
    if (opts.ids.length === 1) {
      await deleteAiSession(opts.ids[0])
      if (opts.disposed()) return
      opts.sessions.value = opts.sessions.value.filter((session) => session.id !== opts.ids[0])
      opts.archivedSessions.value = opts.archivedSessions.value.filter((session) => session.id !== opts.ids[0])
    } else {
      const result = await batchAiSessions('delete', opts.ids)
      if (opts.disposed()) return
      await opts.reload()
      if (result.failed.length) ElMessage.warning(`完成 ${result.ok.length} 条，失败 ${result.failed.length} 条`)
      else ElMessage.success('已删除')
    }
  } catch (caught) {
    opts.setError(toErrorMessage(caught, '删除会话失败'))
  }
}

export async function archiveAiSession(opts: {
  id: string
  clearIfActive: ClearActive
  setError: (message: string) => void
  disposed: () => boolean
  reload: () => Promise<void>
}): Promise<void> {
  opts.clearIfActive(opts.id)
  try {
    await patchAiSession(opts.id, { archived: true })
    if (opts.disposed()) return
    await opts.reload()
    ElMessage.success('已归档')
  } catch (caught) {
    opts.setError(toErrorMessage(caught, '归档失败'))
  }
}

export async function restoreAiSession(opts: {
  id: string
  railTab: Ref<'active' | 'archived'>
  setError: (message: string) => void
  disposed: () => boolean
  reload: () => Promise<void>
}): Promise<void> {
  try {
    await patchAiSession(opts.id, { archived: false })
    if (opts.disposed()) return
    await opts.reload()
    opts.railTab.value = 'active'
    ElMessage.success('已恢复')
  } catch (caught) {
    opts.setError(toErrorMessage(caught, '恢复失败'))
  }
}

export async function batchAiSessionAction(opts: {
  action: 'archive' | 'unarchive' | 'delete'
  ids: string[]
  sessions: Ref<AiSessionSummary[]>
  archivedSessions: Ref<AiSessionSummary[]>
  clearIfActive: ClearActive
  setError: (message: string) => void
  disposed: () => boolean
  reload: () => Promise<void>
}): Promise<void> {
  if (!opts.ids.length) return
  if (opts.action === 'delete') {
    await deleteAiSessionsWithConfirm({
      ids: opts.ids,
      sessions: opts.sessions,
      archivedSessions: opts.archivedSessions,
      clearIfActive: opts.clearIfActive,
      setError: opts.setError,
      disposed: opts.disposed,
      reload: opts.reload,
    })
    return
  }
  try {
    const result = await batchAiSessions(opts.action, opts.ids)
    if (opts.disposed()) return
    await opts.reload()
    if (result.failed.length) ElMessage.warning(`完成 ${result.ok.length} 条，失败 ${result.failed.length} 条`)
    else ElMessage.success(opts.action === 'archive' ? '已归档' : '已恢复')
  } catch (caught) {
    opts.setError(toErrorMessage(caught, '批量操作失败'))
  }
}

export function dropActiveSessionIfMatch(
  id: string,
  active: Ref<AiSessionDetail | null>,
  messages: Ref<unknown[]>,
  agents: Ref<unknown[]>,
): void {
  if (active.value?.id !== id) return
  active.value = null
  messages.value = []
  agents.value = []
}
