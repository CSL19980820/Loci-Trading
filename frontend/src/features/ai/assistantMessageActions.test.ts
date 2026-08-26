import { describe, expect, it } from 'vitest'

import {
  messagePlainText,
  previousUserMessage,
} from './assistantMessageActions'
import type { AiMessage } from '@/shared/types/ai_assistant'

function msg(partial: Partial<AiMessage> & Pick<AiMessage, 'id' | 'role'>): AiMessage {
  return {
    content: '',
    status: 'done',
    ...partial,
  } as AiMessage
}

describe('assistantMessageActions', () => {
  it('finds the nearest preceding user message for regenerate', () => {
    const messages = [
      msg({ id: 'u1', role: 'user', content: '先问' }),
      msg({ id: 'a1', role: 'assistant', content: '先答' }),
      msg({ id: 'u2', role: 'user', content: '补交割记录' }),
      msg({ id: 'a2', role: 'assistant', content: '已核对' }),
    ]
    expect(previousUserMessage(messages, 'a2')?.id).toBe('u2')
    expect(previousUserMessage(messages, 'a1')?.content).toBe('先问')
    expect(previousUserMessage(messages, 'missing')).toBeNull()
  })

  it('trims plain text for copy', () => {
    expect(messagePlainText(msg({ id: 'u', role: 'user', content: '  hello  ' }))).toBe('hello')
    expect(messagePlainText(msg({ id: 'u', role: 'user', content: '   ' }))).toBe('')
  })
})
