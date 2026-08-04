import type { AiMessage } from '@/shared/types/ai_assistant'

function mergeMessageFields(server: AiMessage, prior: AiMessage): AiMessage {
  return {
    ...server,
    content: server.content?.trim() ? server.content : prior.content,
    thinking: server.thinking ?? prior.thinking,
    warnings: server.warnings?.length ? server.warnings : prior.warnings,
    tool_receipts: server.tool_receipts?.length ? server.tool_receipts : prior.tool_receipts,
    artifacts: server.artifacts?.length ? server.artifacts : prior.artifacts,
    status: server.status ?? prior.status,
  }
}

function lastIndexOfRole(messages: AiMessage[], role: AiMessage['role']): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === role) return index
  }
  return -1
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
    const index = lastIndexOfRole(merged, prior.role)
    if (index < 0) continue
    merged[index] = mergeMessageFields(merged[index], prior)
  }
  return merged
}
