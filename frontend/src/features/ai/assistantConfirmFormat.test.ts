import { describe, expect, it } from 'vitest'

import {
  formatAskAnswers,
  missingRequiredAnswers,
} from './assistantConfirmFormat'

describe('assistantConfirmFormat', () => {
  it('formats structured multi-question answers', () => {
    const text = formatAskAnswers(
      [
        { id: 'path', prompt: '选路径？', options: ['提交'] },
        { id: 'note', prompt: '备注？', allow_free_text: true },
      ],
      { path: '提交', note: '先观望' },
    )
    expect(text).toContain('1. [path] 选路径？ → 提交')
    expect(text).toContain('2. [note] 备注？ → 先观望')
  })

  it('lists missing required answer ids', () => {
    expect(
      missingRequiredAnswers(
        [
          { id: 'path', prompt: '选路径？', options: ['提交'] },
          { id: 'note', prompt: '备注？', allow_free_text: true },
        ],
        { path: '提交', note: '  ' },
      ),
    ).toEqual(['note'])
  })
})
