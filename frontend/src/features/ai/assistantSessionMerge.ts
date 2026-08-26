import type { AiMessage } from '@/shared/types/ai_assistant'

function mergeMessageFields(server: AiMessage, prior: AiMessage): AiMessage {
  const mergedStatus = server.status ?? prior.status
  // Remote transcript 通常不带 status；勿把已有正文的远端气泡折回 streaming
  // 本地/远端已是 error 时保持 error（empty_completion 失败文案不能被 sync 伪装成 done）
  let status = mergedStatus
  if (prior.status === 'error' || server.status === 'error') {
    status = 'error'
  } else if (prior.status === 'streaming' && server.content?.trim() && mergedStatus === 'streaming') {
    status = 'done'
  }
  return {
    ...server,
    content: server.content?.trim() ? server.content : prior.content,
    thinking: server.thinking ?? prior.thinking,
    warnings: server.warnings?.length ? server.warnings : prior.warnings,
    tool_receipts: server.tool_receipts?.length ? server.tool_receipts : prior.tool_receipts,
    artifacts: server.artifacts?.length ? server.artifacts : prior.artifacts,
    images: server.images?.length ? server.images : prior.images,
    hitl: server.hitl ?? prior.hitl,
    agents: server.agents?.length ? server.agents : prior.agents,
    status,
  }
}

function lastIndexOfRole(messages: AiMessage[], role: AiMessage['role']): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === role) return index
  }
  return -1
}

function sameText(left: string | undefined, right: string | undefined): boolean {
  return String(left || '').trim() === String(right || '').trim()
}

function hasRoleAfter(messages: AiMessage[], start: number, role: AiMessage['role']): boolean {
  for (let index = start + 1; index < messages.length; index += 1) {
    if (messages[index]?.role === role) return true
  }
  return false
}

/** Index of the open turn bubble for ``role``, or -1 if the local bubble must be appended. */
function foldTargetIndex(messages: AiMessage[], prior: AiMessage, local: AiMessage[]): number {
  const role = prior.role
  if (role === 'user') {
    const lastUser = lastIndexOfRole(messages, 'user')
    if (lastUser < 0) return -1
    // Open remote turn (user without following assistant): fold id-mismatch / images.
    if (!hasRoleAfter(messages, lastUser, 'assistant')) return lastUser
    // Remote turn already complete.
    // If local already has that remote user id, this local-* is a *new* turn (e.g. same wording twice).
    const remoteUserId = messages[lastUser]?.id
    if (remoteUserId && local.some((row) => row.id === remoteUserId)) return -1
    // Same-turn remap: local only has local-* twins, remote brought server ids.
    if (sameText(messages[lastUser]?.content, prior.content)) return lastUser
    return -1
  }
  if (role === 'assistant') {
    const lastUser = lastIndexOfRole(messages, 'user')
    if (lastUser < 0) return lastIndexOfRole(messages, 'assistant')
    // Only fold onto an assistant that belongs to the latest user turn.
    for (let index = messages.length - 1; index > lastUser; index -= 1) {
      if (messages[index]?.role === 'assistant') return index
    }
    return -1
  }
  return lastIndexOfRole(messages, role)
}

/** Merge server transcript onto local turn state; keep tool/artifact when ids diverge. */
export function mergeSessionMessages(local: AiMessage[], remote: AiMessage[]): AiMessage[] {
  if (!remote.length) return local
  const localById = new Map(local.map((message) => [message.id, message]))
  const merged = remote.map((server) => {
    const prior = localById.get(server.id)
    return prior ? mergeMessageFields(server, prior) : { ...server }
  })
  for (const prior of local) {
    if (!prior.id.startsWith('local-')) continue
    if (remote.some((message) => message.id === prior.id)) continue
    const index = foldTargetIndex(merged, prior, local)
    if (index < 0) {
      // Remote already has a newer complete turn, or the latest user has no assistant yet.
      merged.push({ ...prior })
      continue
    }
    merged[index] = mergeMessageFields(merged[index], prior)
  }
  return merged
}
