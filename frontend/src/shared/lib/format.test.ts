import { describe, expect, it } from 'vitest'

import { dialogWidth } from './format'

describe('dialogWidth', () => {
  it('uses a CSS-constrained width that stays responsive after a dialog opens', () => {
    expect(dialogWidth()).toBe('min(36rem, 92vw)')
  })
})
