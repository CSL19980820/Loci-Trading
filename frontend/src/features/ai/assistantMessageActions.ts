/** 对话气泡动作：复制 / 重跑 的纯逻辑。 */
import { copyText } from '@/shared/lib/clipboard'
import type { AiMessage } from '@/shared/types/ai_assistant'

/** 找某条助手消息之前最近的用户消息（用于「重新生成」）。 */
export function previousUserMessage(
  messages: AiMessage[],
  assistantId: string,
): AiMessage | null {
  const index = messages.findIndex((row) => row.id === assistantId)
  if (index < 0) return null
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const row = messages[cursor]
    if (row?.role === 'user') return row
  }
  return null
}

export function messagePlainText(message: AiMessage): string {
  return String(message.content || '').trim()
}

/** 契约不变：纯函数，只返回是否复制成功，提示由调用方（AssistantPanel）负责。 */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  return copyText(text.trim())
}
