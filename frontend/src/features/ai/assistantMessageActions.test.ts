import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  copyTextToClipboard,
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

  // 线上纯 HTTP 访问时 navigator.clipboard 是 undefined（secure context 专属 API）。
  describe('copyTextToClipboard 在非安全上下文', () => {
    const realClipboard = navigator.clipboard

    afterEach(() => {
      Object.defineProperty(navigator, 'clipboard', {
        value: realClipboard,
        configurable: true,
      })
      Reflect.deleteProperty(document, 'execCommand')
      document.body.innerHTML = ''
    })

    it('navigator.clipboard 缺失时仍复制成功', async () => {
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        configurable: true,
      })
      let copied = ''
      document.execCommand = vi.fn((command: string) => {
        if (command !== 'copy') return false
        const active = document.activeElement
        copied = active instanceof HTMLTextAreaElement ? active.value : ''
        return true
      })

      await expect(copyTextToClipboard('  盈亏 +3.2%  ')).resolves.toBe(true)
      expect(copied).toBe('盈亏 +3.2%')
      expect(document.querySelector('textarea')).toBeNull()
    })
  })
})
